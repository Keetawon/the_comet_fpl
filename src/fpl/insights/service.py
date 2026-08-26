"""Verified evidence resolution, bounded generation, caching, and single-flight."""

from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from fpl.insights.contracts import (
    INSIGHT_RESPONSE_SCHEMA,
    INSIGHT_SCHEMA_VERSION,
    PROMPT_VERSION,
    InsightErrorCode,
    InsightSource,
    InsightStatus,
    InsightSummaryRequest,
    InsightSummaryResponse,
    ProviderInsightItem,
    ProviderSummaryPayload,
    ResolvedInsightEvidence,
    canonical_evidence_bytes,
)
from fpl.insights.evidence import InsightEvidenceError, resolve_insight_evidence
from fpl.insights.providers import (
    DEFAULT_ZAI_BASE_URL,
    PROVIDER_OVERALL_TIMEOUT_SECONDS,
    InsightGenerationError,
    InsightProvider,
    ZaiGlmProvider,
)

INSIGHT_CACHE_DIRNAME = "insight-cache"
DEFAULT_RATE_LIMIT = 6
DEFAULT_RATE_WINDOW_SECONDS = 60.0
MAX_CACHE_RECORD_BYTES = 16 * 1024
MAX_MEMORY_CACHE_RECORDS = 128


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Flight:
    event: threading.Event
    response: InsightSummaryResponse | None = None
    error: InsightErrorCode | None = None


class InsightService:
    """Provider-neutral renderer with server-owned evidence and no optimizer lock."""

    def __init__(
        self,
        *,
        provider: InsightProvider | None,
        cache_dir: Path,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = _utc_now,
        overall_timeout_seconds: float = PROVIDER_OVERALL_TIMEOUT_SECONDS,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        rate_window_seconds: float = DEFAULT_RATE_WINDOW_SECONDS,
        evidence_resolver: Callable[
            [Path, InsightSummaryRequest], ResolvedInsightEvidence
        ] = resolve_insight_evidence,
    ) -> None:
        if overall_timeout_seconds <= 0:
            raise ValueError("insight overall timeout must be positive")
        if rate_limit <= 0 or rate_window_seconds <= 0:
            raise ValueError("insight rate-limit settings must be positive")
        if provider is not None:
            InsightStatus(
                enabled=True,
                provider=provider.provider_id,
                model=provider.model,
                prompt_version=PROMPT_VERSION,
            )
        self._provider = provider
        self._cache_dir = cache_dir
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._overall_timeout_seconds = overall_timeout_seconds
        self._rate_limit = rate_limit
        self._rate_window_seconds = rate_window_seconds
        self._evidence_resolver = evidence_resolver
        self._rate_lock = threading.Lock()
        self._generation_times: deque[float] = deque()
        self._flight_lock = threading.Lock()
        self._flights: dict[str, _Flight] = {}
        self._memory_cache: OrderedDict[str, InsightSummaryResponse] = OrderedDict()

    def status(self) -> InsightStatus:
        provider = self._provider
        return InsightStatus(
            enabled=provider is not None,
            provider=None if provider is None else provider.provider_id,
            model=None if provider is None else provider.model,
            prompt_version=PROMPT_VERSION,
        )

    def _cache_key(self, evidence: ResolvedInsightEvidence) -> str:
        provider = self._provider
        if provider is None:
            raise InsightGenerationError(InsightErrorCode.INSIGHTS_DISABLED)
        digest = hashlib.sha256()
        for component in (
            canonical_evidence_bytes(evidence),
            provider.provider_id.encode(),
            provider.model.encode(),
            PROMPT_VERSION.encode(),
        ):
            digest.update(len(component).to_bytes(8, "big"))
            digest.update(component)
        return digest.hexdigest()

    def _cache_path(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.json"

    @staticmethod
    def _as_cache(response: InsightSummaryResponse) -> InsightSummaryResponse:
        payload = response.model_dump(mode="json", by_alias=True)
        payload["source"] = InsightSource.CACHE.value
        return InsightSummaryResponse.model_validate(payload)

    @staticmethod
    def _cache_entry_valid(
        response: InsightSummaryResponse, evidence: ResolvedInsightEvidence
    ) -> bool:
        """Re-prove that cached output could only have come from the canonical renderer.

        Cache files are deliberately response-only, so they do not retain provider selections or
        resolved evidence.  Citation membership alone is insufficient: an edited record could
        otherwise attach fabricated text to a real fact id.  Reconstruct every text form that the
        renderer can emit from the current verified evidence and reject anything else.
        """

        page = evidence.request.page.value.replace("_", " ").title()
        allowed_headlines = {
            f"{prefix}: {page}"
            for prefix in (
                "Published evidence",
                "Published leaders",
                "Published comparison",
                "Published coverage",
            )
        }
        if response.headline not in allowed_headlines:
            return False

        by_id = {fact.id: fact.statement for fact in evidence.facts}
        for item in response.items:
            try:
                statements = [by_id[citation] for citation in item.citations]
            except KeyError:
                return False
            joined = " ".join(statements)
            allowed_text = {joined, f"Published context: {joined}"}
            if len(statements) > 1:
                allowed_text.add(f"Compared published facts: {joined}")
            if item.text not in allowed_text:
                return False
        return True

    def _memory_get(
        self, cache_key: str, evidence: ResolvedInsightEvidence
    ) -> InsightSummaryResponse | None:
        with self._flight_lock:
            response = self._memory_cache.get(cache_key)
            if response is None or not self._cache_entry_valid(response, evidence):
                if response is not None:
                    self._memory_cache.pop(cache_key, None)
                return None
            self._memory_cache.move_to_end(cache_key)
            return self._as_cache(response)

    def _memory_put(self, cache_key: str, response: InsightSummaryResponse) -> None:
        with self._flight_lock:
            self._memory_cache[cache_key] = response
            self._memory_cache.move_to_end(cache_key)
            while len(self._memory_cache) > MAX_MEMORY_CACHE_RECORDS:
                self._memory_cache.popitem(last=False)

    def _read_cache(
        self, cache_key: str, evidence: ResolvedInsightEvidence
    ) -> InsightSummaryResponse | None:
        provider = self._provider
        if provider is None:
            return None
        try:
            with self._cache_path(cache_key).open("rb") as handle:
                payload = handle.read(MAX_CACHE_RECORD_BYTES + 1)
            if len(payload) > MAX_CACHE_RECORD_BYTES:
                return None
            response = InsightSummaryResponse.model_validate_json(payload)
        except (OSError, ValidationError, ValueError):
            return None
        if (
            response.source is not InsightSource.PROVIDER
            or response.cache_key != cache_key
            or response.provider != provider.provider_id
            or response.model != provider.model
            or response.prompt_version != PROMPT_VERSION
            or not self._cache_entry_valid(response, evidence)
        ):
            return None
        self._memory_put(cache_key, response)
        return self._as_cache(response)

    def _write_cache(self, response: InsightSummaryResponse) -> None:
        payload = response.model_dump_json(by_alias=True).encode()
        if len(payload) > MAX_CACHE_RECORD_BYTES:
            return
        temporary: Path | None = None
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = self._cache_dir / f".{response.cache_key}.{uuid.uuid4().hex}.tmp"
            temporary.write_bytes(payload)
            temporary.replace(self._cache_path(response.cache_key))
        except OSError:
            return
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def _reserve_generation(self) -> None:
        now = self._monotonic()
        cutoff = now - self._rate_window_seconds
        with self._rate_lock:
            while self._generation_times and self._generation_times[0] <= cutoff:
                self._generation_times.popleft()
            if len(self._generation_times) >= self._rate_limit:
                raise InsightGenerationError(InsightErrorCode.RATE_LIMITED)
            self._generation_times.append(now)

    @staticmethod
    def _validate_selection(
        evidence: ResolvedInsightEvidence, payload: ProviderSummaryPayload
    ) -> None:
        allowed = {fact.id for fact in evidence.facts}
        selections = [frozenset(item.fact_ids) for item in payload.items]
        if len(set(selections)) != len(selections) or any(set(ids) - allowed for ids in selections):
            raise InsightGenerationError(InsightErrorCode.MALFORMED_PROVIDER_RESPONSE)

    @staticmethod
    def _render_selection(
        evidence: ResolvedInsightEvidence, payload: ProviderSummaryPayload
    ) -> tuple[str, tuple[ProviderInsightItem, ...]]:
        by_id = {fact.id: fact for fact in evidence.facts}
        page = evidence.request.page.value.replace("_", " ").title()
        prefix = {
            "overview": "Published evidence",
            "leaders": "Published leaders",
            "comparison": "Published comparison",
            "coverage": "Published coverage",
        }[payload.headline]
        items: list[ProviderInsightItem] = []
        for selection in payload.items:
            statements = [by_id[item].statement for item in selection.fact_ids]
            if selection.relation.value == "compare" and len(statements) > 1:
                text = "Compared published facts: " + " ".join(statements)
            elif selection.relation.value == "context":
                text = "Published context: " + " ".join(statements)
            else:
                text = " ".join(statements)
            if len(text) > 360:
                raise InsightGenerationError(InsightErrorCode.MALFORMED_PROVIDER_RESPONSE)
            items.append(ProviderInsightItem(text=text, citations=selection.fact_ids))
        return f"{prefix}: {page}", tuple(items)

    def _join_flight(self, cache_key: str) -> tuple[_Flight, bool]:
        with self._flight_lock:
            existing = self._flights.get(cache_key)
            if existing is not None:
                return existing, False
            flight = _Flight(event=threading.Event())
            self._flights[cache_key] = flight
            return flight, True

    def _finish_flight(
        self,
        cache_key: str,
        flight: _Flight,
        response: InsightSummaryResponse | None,
        error: InsightErrorCode | None,
    ) -> None:
        with self._flight_lock:
            flight.response = response
            flight.error = error
            if self._flights.get(cache_key) is flight:
                del self._flights[cache_key]
            flight.event.set()

    def generate(
        self, request: InsightSummaryRequest, *, dashboard_data_dir: Path
    ) -> InsightSummaryResponse:
        provider = self._provider
        if provider is None:
            raise InsightGenerationError(InsightErrorCode.INSIGHTS_DISABLED)
        try:
            evidence = self._evidence_resolver(Path(dashboard_data_dir), request)
        except (InsightEvidenceError, ValidationError, ValueError, OSError):
            raise InsightGenerationError(InsightErrorCode.INVALID_REQUEST) from None
        cache_key = self._cache_key(evidence)
        cached = self._memory_get(cache_key, evidence) or self._read_cache(cache_key, evidence)
        if cached is not None:
            return cached

        flight, owner = self._join_flight(cache_key)
        if not owner:
            if not flight.event.wait(timeout=self._overall_timeout_seconds):
                raise InsightGenerationError(InsightErrorCode.PROVIDER_TIMEOUT)
            if flight.response is not None:
                return self._as_cache(flight.response)
            raise InsightGenerationError(flight.error or InsightErrorCode.PROVIDER_UNAVAILABLE)

        response: InsightSummaryResponse | None = None
        error: InsightErrorCode | None = None
        try:
            cached = self._memory_get(cache_key, evidence) or self._read_cache(cache_key, evidence)
            if cached is not None:
                response = cached
                return cached
            self._reserve_generation()
            deadline = self._monotonic() + self._overall_timeout_seconds
            try:
                raw = provider.generate(evidence, deadline_monotonic=deadline)
                payload = ProviderSummaryPayload.model_validate(raw)
            except InsightGenerationError:
                raise
            except (ValidationError, ValueError, TypeError):
                raise InsightGenerationError(InsightErrorCode.MALFORMED_PROVIDER_RESPONSE) from None
            except Exception:
                raise InsightGenerationError(InsightErrorCode.PROVIDER_UNAVAILABLE) from None
            if self._monotonic() > deadline:
                raise InsightGenerationError(InsightErrorCode.PROVIDER_TIMEOUT)
            self._validate_selection(evidence, payload)
            headline, items = self._render_selection(evidence, payload)
            generated_at = self._utc_now()
            if generated_at.tzinfo is None or generated_at.utcoffset() is None:
                raise RuntimeError("insight UTC clock returned a naive timestamp")
            response = InsightSummaryResponse.model_validate(
                {
                    "schema": INSIGHT_RESPONSE_SCHEMA,
                    "schema_version": INSIGHT_SCHEMA_VERSION,
                    "source": InsightSource.PROVIDER.value,
                    "provider": provider.provider_id,
                    "model": provider.model,
                    "prompt_version": PROMPT_VERSION,
                    "cache_key": cache_key,
                    "generated_at": generated_at,
                    "headline": headline,
                    "items": [item.model_dump(mode="json") for item in items],
                }
            )
            self._memory_put(cache_key, response)
            self._write_cache(response)
            return response
        except InsightGenerationError as exc:
            error = exc.code
            raise
        finally:
            self._finish_flight(cache_key, flight, response, error)


def build_insight_service(
    cache_dir: Path,
    *,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> InsightService:
    """Build the optional server-only provider; invalid config stays disabled."""
    values = os.environ if environ is None else environ
    provider_name = values.get("FPL_INSIGHTS_PROVIDER", "").strip()
    api_key = values.get("FPL_INSIGHTS_API_KEY", "")
    model = values.get("FPL_INSIGHTS_MODEL", "").strip()
    base_url = values.get("FPL_INSIGHTS_BASE_URL", DEFAULT_ZAI_BASE_URL).strip()
    provider: InsightProvider | None = None
    if provider_name == "zai_glm" and api_key and model:
        try:
            provider = ZaiGlmProvider(
                api_key=api_key,
                model=model,
                base_url=base_url,
                client=client,
                monotonic=monotonic,
                sleep=sleep,
            )
            InsightStatus(
                enabled=True,
                provider=provider.provider_id,
                model=provider.model,
                prompt_version=PROMPT_VERSION,
            )
        except (ValueError, ValidationError):
            provider = None
    return InsightService(provider=provider, cache_dir=cache_dir, monotonic=monotonic)
