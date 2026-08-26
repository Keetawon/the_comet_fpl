"""Adversarial tests for selector-only, server-resolved dashboard insights."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from fpl.insights.contracts import (
    INSIGHT_REQUEST_SCHEMA,
    INSIGHT_SCHEMA_VERSION,
    MAX_INSIGHT_BODY_BYTES,
    InsightErrorCode,
    InsightPage,
    InsightSource,
    InsightSummaryRequest,
    ProviderSummaryPayload,
    ResolvedInsightEvidence,
    parse_insight_request_bytes,
)
from fpl.insights.evidence import InsightEvidenceError, resolve_insight_evidence
from fpl.insights.providers import (
    MAX_PROVIDER_RESPONSE_BYTES,
    InsightGenerationError,
    ZaiGlmProvider,
)
from fpl.insights.service import InsightService, build_insight_service
from fpl.publish.dashboard_json import (
    DASHBOARD_JSON_SCHEMA,
    DASHBOARD_JSON_SCHEMA_VERSION,
    _file_row_count,
    _manifest_content_sha256,
    build_dashboard_read_models,
    render_read_model_files,
)
from fpl.publish.export import _canonical_json_bytes
from tests.test_dashboard_json import AS_OF, DATABASE_SHA, RUN_ID, SEASON, _build_source_export

API_KEY = "server-only-zai-key"
MODEL = "glm-4.7"


def _generation(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = _build_source_export(tmp_path)
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    models = build_dashboard_read_models(source)
    payloads = render_read_model_files(models)
    output = tmp_path / "dashboard-data"
    output.mkdir()
    files: dict[str, dict[str, object]] = {}
    for filename, payload in payloads.items():
        (output / filename).write_bytes(payload)
        document = json.loads(payload)
        files[filename] = {
            "row_count": _file_row_count(document, filename),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest: dict[str, Any] = {
        "schema": DASHBOARD_JSON_SCHEMA,
        "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
        "generated_at": "2026-08-26T08:00:00+00:00",
        "source": {
            "export_schema": source_manifest["schema"],
            "export_schema_version": source_manifest["schema_version"],
            "semantic_contract_version": source_manifest["semantic_contract_version"],
            "export_content_sha256": source_manifest["content_sha256"],
            "export_created_at": source_manifest["created_at"],
            "database_sha256": DATABASE_SHA,
        },
        "runs": [dict(record) for record in models.runs],
        "run_ids": [record["run_id"] for record in models.runs],
        "ease_index_formula_version": models.ease_index_formula_version,
        "files": files,
    }
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    (output / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))
    return output, manifest


def _request_dict(manifest_sha: str = "a" * 64, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": INSIGHT_REQUEST_SCHEMA,
        "schema_version": INSIGHT_SCHEMA_VERSION,
        "page": "player_analytics",
        "manifest_sha256": manifest_sha,
        "run_id": RUN_ID,
        "season": SEASON,
        "as_of": AS_OF.isoformat(),
        "scope": {
            "gw_from": 1,
            "gw_to": 2,
            "position": "MID",
            "view": "upside_downside",
            "threshold": 6,
        },
    }
    payload.update(overrides)
    return payload


def _request(manifest: dict[str, Any], **overrides: object) -> InsightSummaryRequest:
    return InsightSummaryRequest.model_validate(
        _request_dict(str(manifest["content_sha256"]), **overrides)
    )


def _page_request(page: InsightPage, manifest: dict[str, Any]) -> InsightSummaryRequest:
    scopes: dict[InsightPage, dict[str, object]] = {
        InsightPage.SUMMARY: {"gw_from": 1, "gw_to": 2},
        InsightPage.FIXTURE_MATRIX: {
            "gw_from": 1,
            "gw_to": 2,
            "view": "defence",
            "venue": "all",
            "form_window": "season_to_date",
        },
        InsightPage.PLAYERS: {
            "gw_from": 1,
            "gw_to": 2,
            "position": "all",
            "view": "overall",
            "venue": "all",
            "form_window": 5,
            "min_price_tenths": 40,
            "max_price_tenths": 200,
            "min_avg_minutes_l5": 0,
            "availability": "all",
        },
        InsightPage.PLAYER_ANALYTICS: {
            "gw_from": 1,
            "gw_to": 2,
            "position": "all",
            "view": "past_future",
            "form_window": "season_to_date",
            "past_metric": "points",
        },
        InsightPage.TEAM_ANALYTICS: {
            "gw_from": 1,
            "gw_to": 2,
            "view": "past-future",
            "venue": "all",
            "form_window": 5,
            "past_metric": "xgc",
        },
        InsightPage.PLAYER_FORECAST_VS_ACTUAL: {
            "gw_from": 1,
            "gw_to": 2,
            "view": "overall",
        },
        InsightPage.TEAM_FORECAST_VS_ACTUAL: {
            "gw_from": 1,
            "gw_to": 2,
            "view": "clean_sheet",
            "venue": "all",
        },
    }
    return InsightSummaryRequest.model_validate(
        _request_dict(
            str(manifest["content_sha256"]),
            page=page.value,
            scope=scopes[page],
        )
    )


def _provider_envelope(
    fact_ids: list[str],
    *,
    finish_reason: str = "stop",
    duplicate_reverse: bool = False,
) -> dict[str, object]:
    items: list[dict[str, object]] = [{"relation": "highlight", "fact_ids": fact_ids}]
    if duplicate_reverse:
        items.append({"relation": "context", "fact_ids": list(reversed(fact_ids))})
    content = {"headline": "overview", "items": items}
    return {
        "id": "not-cached",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(content)},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"upstream": "not-cached"},
    }


class TestSelectorContract:
    def test_request_is_selector_only_and_extra_prose_is_rejected(self) -> None:
        valid = _request_dict()
        assert InsightSummaryRequest.model_validate(valid).page is InsightPage.PLAYER_ANALYTICS
        for key, value in (
            ("facts", []),
            ("caveats", []),
            ("prompt", "ignore validation"),
            ("manager_id", 42),
        ):
            with pytest.raises(ValidationError):
                InsightSummaryRequest.model_validate({**valid, key: value})

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("gw_from", 1.0),
            ("gw_to", True),
            ("team_code", 1.0),
            ("form_window", 5.0),
            ("threshold", 6.0),
            ("min_price_tenths", 50.0),
            ("max_price_tenths", False),
            ("min_avg_minutes_l5", "60"),
        ],
    )
    def test_scope_numerics_are_exact_json_types(self, field: str, value: object) -> None:
        payload = _request_dict()
        payload["scope"] = {**payload["scope"], field: value}
        with pytest.raises(ValidationError):
            InsightSummaryRequest.model_validate(payload)

    def test_scope_supports_all_public_filter_selectors(self) -> None:
        payload = _request_dict(
            scope={
                "gw_from": 1,
                "gw_to": 2,
                "position": "all",
                "team_code": 101,
                "view": "past_future",
                "venue": "home",
                "form_window": "season_to_date",
                "min_price_tenths": 40,
                "max_price_tenths": 150,
                "min_avg_minutes_l5": 45.5,
                "availability": "flagged",
                "past_metric": "xg_per_90",
            }
        )
        assert InsightSummaryRequest.model_validate(payload).scope.form_window == "season_to_date"

    def test_as_of_is_an_iso_string_and_duplicate_json_keys_fail(self) -> None:
        with pytest.raises(ValidationError):
            InsightSummaryRequest.model_validate(_request_dict(as_of=1_787_734_800))
        for value in (1.0, True, "1"):
            with pytest.raises(ValidationError):
                InsightSummaryRequest.model_validate(_request_dict(schema_version=value))
        raw = json.dumps(_request_dict()).replace(
            '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,'
        )
        with pytest.raises(ValueError, match="strict UTF-8 JSON"):
            parse_insight_request_bytes(raw.encode())

    def test_parser_bounds_and_strict_json(self) -> None:
        assert parse_insight_request_bytes(json.dumps(_request_dict()).encode()).run_id == RUN_ID
        with pytest.raises(ValueError, match="oversized"):
            parse_insight_request_bytes(b" " * (MAX_INSIGHT_BODY_BYTES + 1))
        with pytest.raises(ValueError, match="strict UTF-8 JSON"):
            parse_insight_request_bytes(b'{"x":NaN}')


class TestEvidenceResolution:
    @pytest.mark.parametrize("page", list(InsightPage))
    def test_all_public_pages_build_bounded_server_owned_evidence(
        self, tmp_path: Path, page: InsightPage
    ) -> None:
        data, manifest = _generation(tmp_path)
        evidence = resolve_insight_evidence(data, _page_request(page, manifest))
        assert evidence.request.page is page
        assert 1 <= len(evidence.facts) <= 24
        assert all(fact.statement and len(fact.statement) <= 240 for fact in evidence.facts)
        assert all("manager" not in fact.statement.lower() for fact in evidence.facts)

    def test_fixture_defence_uses_published_clean_sheet_probability(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        resolved = resolve_insight_evidence(
            data, _page_request(InsightPage.FIXTURE_MATRIX, manifest)
        )
        rank = next(fact for fact in resolved.facts if fact.id == "fixture.rank.1")
        assert "0.4" in rank.statement
        assert "120" not in rank.statement

    def test_explanatory_views_never_claim_a_frontier(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        for page in (InsightPage.PLAYER_ANALYTICS, InsightPage.TEAM_ANALYTICS):
            resolved = resolve_insight_evidence(data, _page_request(page, manifest))
            assert all(fact.kind.value != "frontier" for fact in resolved.facts)
            assert any("no frontier" in fact.statement for fact in resolved.facts)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda request: request.model_copy(update={"manifest_sha256": "b" * 64}),
            lambda request: request.model_copy(update={"run_id": "missing-run"}),
            lambda request: request.model_copy(update={"season": "2025-26"}),
            lambda request: request.model_copy(update={"as_of": request.as_of.replace(year=2025)}),
        ],
    )
    def test_bad_generation_identity_never_reaches_provider_or_cache(
        self, tmp_path: Path, mutate: Any
    ) -> None:
        data, manifest = _generation(tmp_path)
        provider = _FakeProvider()
        service = InsightService(provider=provider, cache_dir=tmp_path / "cache")
        with pytest.raises(InsightGenerationError) as excinfo:
            service.generate(mutate(_request(manifest)), dashboard_data_dir=data)
        assert excinfo.value.code is InsightErrorCode.INVALID_REQUEST
        assert provider.calls == 0
        assert not (tmp_path / "cache").exists()

    def test_bad_scope_never_reaches_provider(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        provider = _FakeProvider()
        service = InsightService(provider=provider, cache_dir=tmp_path / "cache")
        request = _request(
            manifest,
            scope={"gw_from": 1, "gw_to": 2, "view": "value", "threshold": 6},
        )
        with pytest.raises(InsightGenerationError) as excinfo:
            service.generate(request, dashboard_data_dir=data)
        assert excinfo.value.code is InsightErrorCode.INVALID_REQUEST
        assert provider.calls == 0

    def test_tampered_file_manifest_and_schema_fail_before_provider(self, tmp_path: Path) -> None:
        for mode in ("file", "manifest", "schema"):
            case = tmp_path / mode
            data, manifest = _generation(case)
            if mode == "file":
                path = data / "players.json"
                path.write_bytes(path.read_bytes() + b" ")
            elif mode == "manifest":
                path = data / "manifest.json"
                payload = json.loads(path.read_text())
                payload["content_sha256"] = "0" * 64
                path.write_bytes(_canonical_json_bytes(payload, indent=2))
            else:
                path = data / "players.json"
                payload = json.loads(path.read_text())
                payload["schema"] = "tampered"
                rendered = _canonical_json_bytes(payload, indent=2)
                path.write_bytes(rendered)
                manifest["files"]["players.json"]["sha256"] = hashlib.sha256(rendered).hexdigest()
                manifest["content_sha256"] = _manifest_content_sha256(manifest)
                (data / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))
            provider = _FakeProvider()
            service = InsightService(provider=provider, cache_dir=case / "cache")
            with pytest.raises(InsightGenerationError) as excinfo:
                service.generate(_request(manifest), dashboard_data_dir=data)
            assert excinfo.value.code is InsightErrorCode.INVALID_REQUEST
            assert provider.calls == 0

    def test_generation_swap_is_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data, manifest = _generation(tmp_path)
        original = Path.read_bytes
        calls = 0

        def swapping_read(path: Path) -> bytes:
            nonlocal calls
            payload = original(path)
            if path == data / "manifest.json":
                calls += 1
                if calls == 2:
                    return payload + b" "
            return payload

        monkeypatch.setattr(Path, "read_bytes", swapping_read)
        with pytest.raises(InsightEvidenceError, match="changed"):
            resolve_insight_evidence(data, _request(manifest))


@dataclass
class _FakeProvider:
    provider_id: str = "fake"
    model: str = "fake-model-v1"
    calls: int = 0
    started: threading.Event | None = None
    release: threading.Event | None = None
    failure: InsightErrorCode | None = None
    unknown_citation: bool = False
    duplicate_reverse: bool = False
    seen_evidence: list[ResolvedInsightEvidence] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def generate(
        self, evidence: ResolvedInsightEvidence, *, deadline_monotonic: float
    ) -> ProviderSummaryPayload:
        del deadline_monotonic
        with self.lock:
            self.calls += 1
            self.seen_evidence.append(evidence)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=5)
        if self.failure is not None:
            raise InsightGenerationError(self.failure)
        ids = ["unknown.fact"] if self.unknown_citation else [evidence.facts[0].id]
        items: list[dict[str, object]] = [{"relation": "highlight", "fact_ids": ids}]
        if self.duplicate_reverse:
            first_two = [fact.id for fact in evidence.facts[:2]]
            items = [
                {"relation": "highlight", "fact_ids": first_two},
                {"relation": "context", "fact_ids": list(reversed(first_two))},
            ]
        return ProviderSummaryPayload.model_validate({"headline": "overview", "items": items})


class TestServiceAndProvider:
    def test_disabled_partial_and_invalid_config_are_safe(self, tmp_path: Path) -> None:
        disabled = build_insight_service(tmp_path / "disabled", environ={})
        partial = build_insight_service(
            tmp_path / "partial",
            environ={"FPL_INSIGHTS_PROVIDER": "zai_glm", "FPL_INSIGHTS_MODEL": MODEL},
        )
        invalid = build_insight_service(
            tmp_path / "invalid",
            environ={
                "FPL_INSIGHTS_PROVIDER": "zai_glm",
                "FPL_INSIGHTS_API_KEY": API_KEY,
                "FPL_INSIGHTS_MODEL": MODEL,
                "FPL_INSIGHTS_BASE_URL": "http://api.z.ai/",
            },
        )
        assert not disabled.status().enabled
        assert not partial.status().enabled
        assert not invalid.status().enabled
        with pytest.raises(InsightGenerationError) as excinfo:
            disabled.generate(
                InsightSummaryRequest.model_validate(_request_dict()),
                dashboard_data_dir=tmp_path,
            )
        assert excinfo.value.code is InsightErrorCode.INSIGHTS_DISABLED

    def test_configured_status_never_exposes_key_or_base_url(self, tmp_path: Path) -> None:
        service = build_insight_service(
            tmp_path,
            environ={
                "FPL_INSIGHTS_PROVIDER": "zai_glm",
                "FPL_INSIGHTS_API_KEY": API_KEY,
                "FPL_INSIGHTS_MODEL": MODEL,
                "FPL_INSIGHTS_BASE_URL": "https://example.test/v4/",
            },
        )
        payload = service.status().model_dump(mode="json")
        assert payload == {
            "enabled": True,
            "provider": "zai_glm",
            "model": MODEL,
            "prompt_version": "evidence-renderer-v1",
        }
        assert API_KEY not in json.dumps(payload)
        assert "example.test" not in json.dumps(payload)

    @pytest.mark.parametrize("first_status", [429, 502, 503, 504])
    def test_retryable_provider_status_retries_exactly_once(
        self, tmp_path: Path, first_status: int
    ) -> None:
        data, manifest = _generation(tmp_path)
        evidence = resolve_insight_evidence(data, _request(manifest))
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(first_status)
            return httpx.Response(200, json=_provider_envelope([evidence.facts[0].id]))

        provider = ZaiGlmProvider(
            api_key=API_KEY,
            model=MODEL,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep=lambda seconds: None,
        )
        assert provider.generate(evidence, deadline_monotonic=time.monotonic() + 5).items
        assert calls == 2

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, InsightErrorCode.PROVIDER_AUTH),
            (403, InsightErrorCode.PROVIDER_AUTH),
            (302, InsightErrorCode.PROVIDER_UNAVAILABLE),
            (400, InsightErrorCode.PROVIDER_UNAVAILABLE),
        ],
    )
    def test_auth_redirect_and_bad_request_never_retry(
        self, tmp_path: Path, status: int, expected: InsightErrorCode
    ) -> None:
        data, manifest = _generation(tmp_path)
        evidence = resolve_insight_evidence(data, _request(manifest))
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status, headers={"Location": "https://evil.example"})

        provider = ZaiGlmProvider(
            api_key=API_KEY,
            model=MODEL,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(InsightGenerationError) as excinfo:
            provider.generate(evidence, deadline_monotonic=time.monotonic() + 5)
        assert excinfo.value.code is expected
        assert calls == 1

    def test_transport_timeout_retries_once_and_returns_safe_error(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        evidence = resolve_insight_evidence(data, _request(manifest))
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("credential-like upstream detail", request=request)

        provider = ZaiGlmProvider(
            api_key=API_KEY,
            model=MODEL,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(InsightGenerationError) as excinfo:
            provider.generate(evidence, deadline_monotonic=time.monotonic() + 5)
        assert excinfo.value.code is InsightErrorCode.PROVIDER_TIMEOUT
        assert "credential" not in str(excinfo.value)
        assert calls == 2

    def test_provider_receives_only_server_resolved_facts(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        seen: dict[str, Any] = {}
        resolved = resolve_insight_evidence(data, _request(manifest))

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json=_provider_envelope([resolved.facts[0].id]),
                headers={"Content-Encoding": "identity"},
            )

        provider = ZaiGlmProvider(
            api_key=API_KEY,
            model=MODEL,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        service = InsightService(provider=provider, cache_dir=tmp_path / "cache")
        response = service.generate(_request(manifest), dashboard_data_dir=data)
        body = seen["body"]
        packet = json.loads(body["messages"][1]["content"])
        assert packet["facts"] == [
            {
                "id": fact.id,
                "kind": fact.kind.value,
                "statement": fact.statement,
                "sources": [source.value for source in fact.source_read_models],
            }
            for fact in resolved.facts
        ]
        assert body["thinking"] == {"type": "disabled"}
        assert seen["headers"]["accept-encoding"] == "identity"
        assert response.items[0].text == resolved.facts[0].statement
        assert response.items[0].citations == (resolved.facts[0].id,)

    @pytest.mark.parametrize("finish_reason", ["length", "tool_calls", None])
    def test_non_stop_or_inexact_provider_envelope_fails(
        self, tmp_path: Path, finish_reason: object
    ) -> None:
        data, manifest = _generation(tmp_path)
        resolved = resolve_insight_evidence(data, _request(manifest))
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=_provider_envelope([resolved.facts[0].id], finish_reason=finish_reason),
                )
            )
        )
        service = InsightService(
            provider=ZaiGlmProvider(api_key=API_KEY, model=MODEL, client=client),
            cache_dir=tmp_path / "cache",
        )
        with pytest.raises(InsightGenerationError) as excinfo:
            service.generate(_request(manifest), dashboard_data_dir=data)
        assert excinfo.value.code is InsightErrorCode.MALFORMED_PROVIDER_RESPONSE

    def test_response_cap_checks_length_encoding_and_stream_growth(self) -> None:
        evidence = ResolvedInsightEvidence.model_validate(
            {
                "request": _request_dict(),
                "facts": [
                    {
                        "id": "coverage.one",
                        "kind": "coverage",
                        "statement": "One row is published.",
                        "source_read_models": ["players.json"],
                    }
                ],
                "caveats": [],
            }
        )
        for response in (
            httpx.Response(
                200,
                content=b"x",
                headers={"Content-Length": str(MAX_PROVIDER_RESPONSE_BYTES + 1)},
            ),
            httpx.Response(200, content=b"x", headers={"Content-Encoding": "gzip"}),
            httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)),
        ):
            provider = ZaiGlmProvider(
                api_key=API_KEY,
                model=MODEL,
                client=httpx.Client(
                    transport=httpx.MockTransport(lambda request, value=response: value)
                ),
            )
            with pytest.raises(InsightGenerationError) as excinfo:
                provider.generate(evidence, deadline_monotonic=time.monotonic() + 5)
            assert excinfo.value.code in {
                InsightErrorCode.PROVIDER_RESPONSE_TOO_LARGE,
                InsightErrorCode.MALFORMED_PROVIDER_RESPONSE,
            }

    def test_order_insensitive_duplicate_selection_is_rejected(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        provider = _FakeProvider(duplicate_reverse=True)
        service = InsightService(provider=provider, cache_dir=tmp_path / "cache")
        with pytest.raises(InsightGenerationError) as excinfo:
            service.generate(_request(manifest), dashboard_data_dir=data)
        assert excinfo.value.code is InsightErrorCode.MALFORMED_PROVIDER_RESPONSE

    def test_invalid_disk_cache_citation_is_ignored(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        first_provider = _FakeProvider()
        cache = tmp_path / "cache"
        first = InsightService(provider=first_provider, cache_dir=cache).generate(
            _request(manifest), dashboard_data_dir=data
        )
        path = cache / f"{first.cache_key}.json"
        payload = json.loads(path.read_text())
        payload["items"][0]["citations"] = ["unknown.fact"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        second_provider = _FakeProvider()
        second = InsightService(provider=second_provider, cache_dir=cache).generate(
            _request(manifest), dashboard_data_dir=data
        )
        assert second.source is InsightSource.PROVIDER
        assert second_provider.calls == 1

    def test_disk_cache_cannot_attach_fabricated_text_to_valid_citation(
        self, tmp_path: Path
    ) -> None:
        data, manifest = _generation(tmp_path)
        cache = tmp_path / "cache"
        first = InsightService(provider=_FakeProvider(), cache_dir=cache).generate(
            _request(manifest), dashboard_data_dir=data
        )
        path = cache / f"{first.cache_key}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["items"][0]["citations"] == list(first.items[0].citations)
        payload["items"][0]["text"] = "A fabricated number is 99.99."
        path.write_text(json.dumps(payload), encoding="utf-8")

        second_provider = _FakeProvider()
        second = InsightService(provider=second_provider, cache_dir=cache).generate(
            _request(manifest), dashboard_data_dir=data
        )

        assert second.source is InsightSource.PROVIDER
        assert second.items[0].text == first.items[0].text
        assert second_provider.calls == 1

    def test_memory_cache_cannot_attach_fabricated_text_to_valid_citation(
        self, tmp_path: Path
    ) -> None:
        data, manifest = _generation(tmp_path)
        unwritable_cache = tmp_path / "not-a-directory"
        unwritable_cache.write_text("occupied", encoding="utf-8")
        provider = _FakeProvider()
        service = InsightService(provider=provider, cache_dir=unwritable_cache)
        first = service.generate(_request(manifest), dashboard_data_dir=data)
        poisoned_item = first.items[0].model_copy(update={"text": "A fabricated number is 99.99."})
        service._memory_cache[first.cache_key] = first.model_copy(
            update={"items": (poisoned_item,)}
        )

        second = service.generate(_request(manifest), dashboard_data_dir=data)

        assert second.source is InsightSource.PROVIDER
        assert second.items[0].text == first.items[0].text
        assert provider.calls == 2

    def test_cache_is_response_only_and_rate_limit_counts_generations(self, tmp_path: Path) -> None:
        data, manifest = _generation(tmp_path)
        provider = _FakeProvider()
        cache = tmp_path / "cache"
        service = InsightService(
            provider=provider,
            cache_dir=cache,
            rate_limit=2,
            rate_window_seconds=60,
        )
        base = _request_dict(str(manifest["content_sha256"]))
        requests = [
            InsightSummaryRequest.model_validate(
                {
                    **base,
                    "scope": {
                        **base["scope"],
                        "position": position,
                    },
                }
            )
            for position in ("all", "MID", "GK")
        ]
        first = service.generate(requests[0], dashboard_data_dir=data)
        assert service.generate(requests[0], dashboard_data_dir=data).source is InsightSource.CACHE
        service.generate(requests[1], dashboard_data_dir=data)
        with pytest.raises(InsightGenerationError) as excinfo:
            service.generate(requests[2], dashboard_data_dir=data)
        assert excinfo.value.code is InsightErrorCode.RATE_LIMITED
        cache_text = (cache / f"{first.cache_key}.json").read_text()
        assert API_KEY not in cache_text
        assert "upstream" not in cache_text
        cache_payload = json.loads(cache_text)
        assert not {"request", "facts", "caveats", "scope"} & set(cache_payload)

    @pytest.mark.parametrize("failure", [None, InsightErrorCode.PROVIDER_UNAVAILABLE])
    def test_in_memory_single_flight_shares_success_and_failure_when_disk_unwritable(
        self, tmp_path: Path, failure: InsightErrorCode | None
    ) -> None:
        data, manifest = _generation(tmp_path)
        cache_file = tmp_path / "not-a-directory"
        cache_file.write_text("occupied", encoding="utf-8")
        started = threading.Event()
        release = threading.Event()
        provider = _FakeProvider(
            started=started,
            release=release,
            failure=failure,
        )
        service = InsightService(provider=provider, cache_dir=cache_file)
        responses: list[InsightSource] = []
        errors: list[InsightErrorCode] = []

        def call() -> None:
            try:
                responses.append(
                    service.generate(_request(manifest), dashboard_data_dir=data).source
                )
            except InsightGenerationError as exc:
                errors.append(exc.code)

        threads = [threading.Thread(target=call) for _ in range(6)]
        for thread in threads:
            thread.start()
        assert started.wait(timeout=5)
        time.sleep(0.05)
        release.set()
        for thread in threads:
            thread.join(timeout=5)
        assert provider.calls == 1
        if failure is None:
            assert responses.count(InsightSource.PROVIDER) == 1
            assert responses.count(InsightSource.CACHE) == 5
            assert not errors
        else:
            assert errors == [failure] * 6
            assert not responses


def _rewrite_insight_read_model(
    data: Path,
    manifest: dict[str, Any],
    filename: str,
    mutate: Any,
) -> None:
    """Rewrite one still-contract-valid document and repin the atomic manifest for a regression."""
    path = data / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    rendered = _canonical_json_bytes(document, indent=2)
    path.write_bytes(rendered)
    manifest["files"][filename]["sha256"] = hashlib.sha256(rendered).hexdigest()
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    (data / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))


def test_insight_venue_filter_does_not_classify_null_as_away(tmp_path: Path) -> None:
    data, manifest = _generation(tmp_path)

    def make_one_venue_unknown(document: dict[str, Any]) -> None:
        alpha = next(team for team in document["teams"] if team["team_code"] == 101)
        fixture = next(item for item in alpha["fixtures"] if item["fixture"] == 102)
        assert fixture["was_home"] is False
        fixture["was_home"] = None

    _rewrite_insight_read_model(data, manifest, "fixture_matrix.json", make_one_venue_unknown)

    def selected_count(venue: str) -> str:
        request = InsightSummaryRequest.model_validate(
            _request_dict(
                str(manifest["content_sha256"]),
                page="fixture_matrix",
                scope={
                    "gw_from": 1,
                    "gw_to": 2,
                    "view": "overall",
                    "venue": venue,
                    "form_window": 5,
                },
            )
        )
        evidence = resolve_insight_evidence(data, request)
        return next(fact.statement for fact in evidence.facts if fact.id == "fixture.coverage")

    assert "6 published forecast fixture sides" in selected_count("all")
    assert "3 published forecast fixture sides" in selected_count("home")
    assert "2 published forecast fixture sides" in selected_count("away")


@pytest.mark.parametrize(
    ("missing_key", "view"),
    [
        ("lambda_for", "environment"),
        ("lambda_against", "environment"),
        ("probability_clean_sheet", "attack-floor"),
    ],
)
def test_team_analytics_null_axis_omits_club_like_frontend(
    tmp_path: Path, missing_key: str, view: str
) -> None:
    data, manifest = _generation(tmp_path)

    def remove_one_required_leg(document: dict[str, Any]) -> None:
        alpha = next(team for team in document["teams"] if team["team_code"] == 101)
        fixture = next(item for item in alpha["fixtures"] if item["fixture"] == 100)
        assert fixture[missing_key] is not None
        fixture[missing_key] = None

    _rewrite_insight_read_model(data, manifest, "fixture_matrix.json", remove_one_required_leg)
    request = InsightSummaryRequest.model_validate(
        _request_dict(
            str(manifest["content_sha256"]),
            page="team_analytics",
            scope={
                "gw_from": 1,
                "gw_to": 2,
                "view": view,
                "venue": "all",
                "form_window": 5,
            },
        )
    )

    evidence = resolve_insight_evidence(data, request)
    frontier = next(
        fact.statement for fact in evidence.facts if fact.id == "team.analytics.frontier"
    )
    leader = next(fact.statement for fact in evidence.facts if fact.id == "team.analytics.leader")
    assert "ALP" not in frontier
    assert "ALP" not in leader
    assert leader.startswith("BET")


def test_player_analytics_leader_is_axis_complete_and_plotted(tmp_path: Path) -> None:
    data, manifest = _generation(tmp_path)

    def remove_leading_players_price(document: dict[str, Any]) -> None:
        vicario = next(player for player in document["players"] if player["code"] == 1)
        assert vicario["now_cost"] == 55
        vicario["now_cost"] = None

    _rewrite_insight_read_model(data, manifest, "players.json", remove_leading_players_price)
    request = InsightSummaryRequest.model_validate(
        _request_dict(
            str(manifest["content_sha256"]),
            page="player_analytics",
            scope={
                "gw_from": 1,
                "gw_to": 2,
                "position": "all",
                "view": "value",
                "form_window": 5,
                "availability": "all",
            },
        )
    )

    evidence = resolve_insight_evidence(data, request)
    leader = next(
        fact.statement for fact in evidence.facts if fact.id == "player.analytics.xp.leader"
    )
    assert leader.startswith("Maddison")
    assert "5.00" in leader
    assert "Vicario" not in leader
