"""Exact, evidence-bound contracts for optional dashboard language rendering."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INSIGHT_REQUEST_SCHEMA = "fpl.insight-summary-request"
INSIGHT_RESPONSE_SCHEMA = "fpl.insight-summary-response"
INSIGHT_ERROR_SCHEMA = "fpl.insight-summary-error"
INSIGHT_SCHEMA_VERSION = 1
PROMPT_VERSION: Final = "evidence-renderer-v1"
MAX_INSIGHT_BODY_BYTES = 16 * 1024

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SAFE_PROVIDER_ID = re.compile(r"[a-z][a-z0-9_.-]{0,47}\Z")
_SAFE_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}\Z")
_SEASON = re.compile(r"(\d{4})-(\d{2})\Z")
_WINDOWS_PATH = re.compile(r"(?:\A|\s)[A-Za-z]:[\\/]")
_PRIVATE_OR_DECISION = re.compile(
    r"\b(?:manager(?:[_ -]?id)?|capture(?:[_ -]?id)?|squad|captain|vice(?:-captain)?|"
    r"transfer|bank|purchase(?: price)?|selling(?: value| price)?|authorization|api(?:[_ -]?key)?|"
    r"password|secret|bearer|access(?:[_ -]?token)?|filesystem|file(?:[_ -]?path)?|plan builder|"
    r"squad draft|optimizer audit|locked players?|excluded players?|bench rule|recommend(?:ation)?|"
    r"should (?:buy|sell|pick)|lineup)\b",
    re.IGNORECASE,
)
_PROMPT_INJECTION = re.compile(
    r"\b(?:ignore (?:all |any )?(?:previous|prior) instructions?|system prompt|developer message|"
    r"assistant message|act as|role\s*:|jailbreak)\b",
    re.IGNORECASE,
)
_HTML = re.compile(r"</?[A-Za-z][^>]*>")
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_NEGATED_RECOMMENDATION = re.compile(
    r"\bnot (?:an? )?(?:(?:validated|optimal) )?"
    r"(?:(?:squad|transfer|captaincy|lineup)(?: or (?:squad|transfer|captaincy|lineup))* )?"
    r"recommendation\b",
    re.IGNORECASE,
)


class _ExactModel(BaseModel):
    # Wire contracts accept aliases only.  In particular, ``schema_name`` is an internal
    # Python spelling for the reserved JSON key ``schema`` and must not become a second,
    # undocumented request key through Pydantic's population-by-name convenience.
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=False)


class InsightPage(StrEnum):
    SUMMARY = "summary"
    FIXTURE_MATRIX = "fixture_matrix"
    PLAYERS = "players"
    PLAYER_ANALYTICS = "player_analytics"
    TEAM_ANALYTICS = "team_analytics"
    PLAYER_FORECAST_VS_ACTUAL = "player_forecast_vs_actual"
    TEAM_FORECAST_VS_ACTUAL = "team_forecast_vs_actual"


class InsightFactKind(StrEnum):
    PUBLISHED_SCALAR = "published_scalar"
    ALLOWED_SUM = "allowed_sum"
    RANK = "rank"
    FRONTIER = "frontier"
    COVERAGE = "coverage"
    COMPARISON = "comparison"


class InsightReadModel(StrEnum):
    MANIFEST = "manifest.json"
    SUMMARY = "summary.json"
    FIXTURE_MATRIX = "fixture_matrix.json"
    PLAYERS = "players.json"
    PLAYER_HORIZONS = "player_horizons.json"
    PLAYER_FORECAST_VS_ACTUAL = "player_forecast_vs_actual.json"
    TEAM_FORECAST_VS_ACTUAL = "team_forecast_vs_actual.json"


class InsightPosition(StrEnum):
    ALL = "all"
    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class InsightView(StrEnum):
    OVERALL = "overall"
    ATTACK = "attack"
    DEFENCE = "defence"
    CLEAN_SHEET = "clean_sheet"
    VALUE = "value"
    UPSIDE_DOWNSIDE = "upside_downside"
    DIFFERENTIAL = "differential"
    PAST_FUTURE = "past_future"
    ENVIRONMENT = "environment"
    ATTACK_FLOOR = "attack-floor"
    PAST_FUTURE_HYPHEN = "past-future"


class InsightVenue(StrEnum):
    ALL = "all"
    HOME = "home"
    AWAY = "away"


class InsightAvailability(StrEnum):
    ALL = "all"
    AVAILABLE = "available"
    FLAGGED = "flagged"


class InsightPastMetric(StrEnum):
    POINTS = "points"
    XG_PER_90 = "xg_per_90"
    XA_PER_90 = "xa_per_90"
    TEAM_XG = "xg-for"
    TEAM_GOALS = "goals-for"
    TEAM_XGC = "xgc"
    TEAM_GOALS_AGAINST = "goals-against"


class InsightSource(StrEnum):
    PROVIDER = "provider"
    CACHE = "cache"


class InsightErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INSIGHTS_DISABLED = "insights_disabled"
    RATE_LIMITED = "rate_limited"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_AUTH = "provider_authentication_failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_RESPONSE_TOO_LARGE = "provider_response_too_large"
    MALFORMED_PROVIDER_RESPONSE = "malformed_provider_response"


_PAGE_READ_MODELS: dict[InsightPage, frozenset[InsightReadModel]] = {
    InsightPage.SUMMARY: frozenset({InsightReadModel.MANIFEST, InsightReadModel.SUMMARY}),
    InsightPage.FIXTURE_MATRIX: frozenset(
        {InsightReadModel.MANIFEST, InsightReadModel.FIXTURE_MATRIX}
    ),
    InsightPage.PLAYERS: frozenset(
        {
            InsightReadModel.MANIFEST,
            InsightReadModel.PLAYERS,
            InsightReadModel.PLAYER_HORIZONS,
        }
    ),
    InsightPage.PLAYER_ANALYTICS: frozenset(
        {
            InsightReadModel.MANIFEST,
            InsightReadModel.PLAYERS,
            InsightReadModel.PLAYER_HORIZONS,
        }
    ),
    InsightPage.TEAM_ANALYTICS: frozenset(
        {InsightReadModel.MANIFEST, InsightReadModel.FIXTURE_MATRIX}
    ),
    InsightPage.PLAYER_FORECAST_VS_ACTUAL: frozenset(
        {InsightReadModel.MANIFEST, InsightReadModel.PLAYER_FORECAST_VS_ACTUAL}
    ),
    InsightPage.TEAM_FORECAST_VS_ACTUAL: frozenset(
        {InsightReadModel.MANIFEST, InsightReadModel.TEAM_FORECAST_VS_ACTUAL}
    ),
}


def _contains_control(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)


def _validate_untrusted_text(value: str, *, name: str) -> str:
    if _contains_control(value):
        raise ValueError(f"{name} contains control characters")
    # The mandatory model-state caveat commonly says that a development forecast is "not a
    # validated recommendation".  Preserve that explicit negation while still rejecting an
    # affirmative recommendation or other decision/private material.
    decision_scan = _NEGATED_RECOMMENDATION.sub("", value)
    if _PRIVATE_OR_DECISION.search(decision_scan):
        raise ValueError(f"{name} contains private or decision material")
    if _PROMPT_INJECTION.search(value):
        raise ValueError(f"{name} contains prompt-like instructions")
    if _WINDOWS_PATH.search(value) or value.startswith(("/", "\\\\", "file://")):
        raise ValueError(f"{name} contains a filesystem path")
    return value


def _validate_plain_output(value: str, *, name: str) -> str:
    if _contains_control(value):
        raise ValueError(f"{name} contains control characters")
    if _HTML.search(value) or _MARKDOWN_LINK.search(value) or "```" in value:
        raise ValueError(f"{name} must be plain text")
    return _validate_untrusted_text(value, name=name)


class InsightDisplayScope(_ExactModel):
    gw_from: Annotated[int, Field(strict=True, ge=1, le=38)] | None = None
    gw_to: Annotated[int, Field(strict=True, ge=1, le=38)] | None = None
    position: InsightPosition | None = None
    team_code: Annotated[int, Field(strict=True, gt=0, le=1_000_000)] | None = None
    view: InsightView | None = None
    venue: InsightVenue | None = None
    form_window: Literal[3, 5, 10, "season_to_date"] | None = None
    threshold: Literal[2, 4, 6, 10, 15] | None = None
    min_price_tenths: Annotated[int, Field(strict=True, ge=0, le=2000)] | None = None
    max_price_tenths: Annotated[int, Field(strict=True, ge=0, le=2000)] | None = None
    min_avg_minutes_l5: float | None = Field(default=None, ge=0.0, le=90.0)
    availability: InsightAvailability | None = None
    past_metric: InsightPastMetric | None = None

    @field_validator("form_window", "threshold", mode="before")
    @classmethod
    def reject_non_exact_literal_numbers(cls, value: object) -> object:
        if isinstance(value, (bool, float)):
            raise ValueError("scope numeric selectors must be exact integers")
        return value

    @field_validator("min_avg_minutes_l5", mode="before")
    @classmethod
    def validate_min_avg_minutes(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("scope.min_avg_minutes_l5 must be a JSON number")
        if not math.isfinite(float(value)):
            raise ValueError("scope.min_avg_minutes_l5 must be finite")
        return float(value)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.gw_from is not None and self.gw_to is not None and self.gw_from > self.gw_to:
            raise ValueError("scope.gw_from must not exceed scope.gw_to")
        if (
            self.min_price_tenths is not None
            and self.max_price_tenths is not None
            and self.min_price_tenths > self.max_price_tenths
        ):
            raise ValueError("scope.min_price_tenths must not exceed scope.max_price_tenths")
        return self


class InsightFact(_ExactModel):
    id: str = Field(min_length=1, max_length=64)
    kind: InsightFactKind
    statement: str = Field(min_length=1, max_length=240)
    source_read_models: tuple[InsightReadModel, ...] = Field(min_length=1, max_length=4)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if _SAFE_ID.fullmatch(value) is None:
            raise ValueError("fact id is not a safe stable id")
        return value

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        return _validate_untrusted_text(value, name="fact statement")

    @field_validator("source_read_models")
    @classmethod
    def unique_sources(cls, value: tuple[InsightReadModel, ...]) -> tuple[InsightReadModel, ...]:
        if len(set(value)) != len(value):
            raise ValueError("fact source_read_models must be unique")
        return value


class InsightSummaryRequest(_ExactModel):
    schema_name: Literal["fpl.insight-summary-request"] = Field(alias="schema")
    schema_version: Literal[1]
    page: InsightPage
    manifest_sha256: str
    run_id: str = Field(min_length=1, max_length=128)
    season: str
    as_of: datetime
    scope: InsightDisplayScope

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_raw_schema_version(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("schema_version must be an exact JSON integer")
        return value

    @field_validator("manifest_sha256")
    @classmethod
    def validate_manifest_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("manifest_sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if _SAFE_RUN_ID.fullmatch(value) is None:
            raise ValueError("run_id is not a safe identifier")
        return value

    @field_validator("season")
    @classmethod
    def validate_season(cls, value: str) -> str:
        matched = _SEASON.fullmatch(value)
        if matched is None:
            raise ValueError("season must use YYYY-YY form")
        start = int(matched.group(1))
        if int(matched.group(2)) != (start + 1) % 100:
            raise ValueError("season end year must immediately follow its start year")
        return value

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_raw_as_of(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("as_of must be an ISO 8601 string")
        return value

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value


class ResolvedInsightEvidence(_ExactModel):
    """Server-owned evidence packet; never populated from browser-authored prose."""

    request: InsightSummaryRequest
    facts: tuple[InsightFact, ...] = Field(min_length=1, max_length=24)
    caveats: tuple[str, ...] = Field(max_length=8)

    @field_validator("caveats")
    @classmethod
    def validate_caveats(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("caveats must be unique")
        for caveat in value:
            if not 1 <= len(caveat) <= 240:
                raise ValueError("each caveat must contain 1..240 characters")
            _validate_untrusted_text(caveat, name="caveat")
        return value

    @model_validator(mode="after")
    def validate_fact_set(self) -> Self:
        fact_ids = [fact.id for fact in self.facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("fact ids must be unique")
        allowed_sources = _PAGE_READ_MODELS[self.request.page]
        for fact in self.facts:
            if set(fact.source_read_models) - allowed_sources:
                raise ValueError("resolved fact cites a read model unavailable to its page")
        return self


class ProviderRelation(StrEnum):
    HIGHLIGHT = "highlight"
    COMPARE = "compare"
    CONTEXT = "context"


class ProviderInsightSelection(_ExactModel):
    relation: ProviderRelation
    fact_ids: tuple[str, ...] = Field(min_length=1, max_length=3)

    @field_validator("fact_ids")
    @classmethod
    def validate_fact_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("provider fact ids must be unique")
        if any(_SAFE_ID.fullmatch(item) is None for item in value):
            raise ValueError("provider fact id is not safe")
        return value


class ProviderSummaryPayload(_ExactModel):
    headline: Literal["overview", "leaders", "comparison", "coverage"]
    items: tuple[ProviderInsightSelection, ...] = Field(min_length=1, max_length=4)


class ProviderInsightItem(_ExactModel):
    """Public server-rendered item. Providers never author either field."""

    text: str = Field(min_length=1, max_length=360)
    citations: tuple[str, ...] = Field(min_length=1, max_length=3)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_plain_output(value, name="insight text")

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("insight citations must be unique")
        if any(_SAFE_ID.fullmatch(item) is None for item in value):
            raise ValueError("insight citation is not a safe fact id")
        return value


class InsightSummaryResponse(_ExactModel):
    schema_name: Literal["fpl.insight-summary-response"] = Field(alias="schema")
    schema_version: Literal[1]
    source: InsightSource
    provider: str
    model: str
    prompt_version: Literal["evidence-renderer-v1"]
    cache_key: str
    generated_at: datetime
    headline: str = Field(min_length=1, max_length=160)
    items: tuple[ProviderInsightItem, ...] = Field(min_length=1, max_length=4)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if _SAFE_PROVIDER_ID.fullmatch(value) is None:
            raise ValueError("provider is not a safe identifier")
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if _SAFE_MODEL_ID.fullmatch(value) is None:
            raise ValueError("model is not a safe identifier")
        return value

    @field_validator("cache_key")
    @classmethod
    def validate_cache_key(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("cache_key must be a lowercase SHA-256 digest")
        return value

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value

    @field_validator("headline")
    @classmethod
    def validate_headline(cls, value: str) -> str:
        return _validate_plain_output(value, name="headline")


class InsightStatus(_ExactModel):
    enabled: bool
    provider: str | None
    model: str | None
    prompt_version: Literal["evidence-renderer-v1"]

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_PROVIDER_ID.fullmatch(value) is None:
            raise ValueError("provider is not a safe identifier")
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_MODEL_ID.fullmatch(value) is None:
            raise ValueError("model is not a safe identifier")
        return value

    @model_validator(mode="after")
    def validate_enabled_identity(self) -> Self:
        if self.enabled != (self.provider is not None and self.model is not None):
            raise ValueError("enabled insight status requires a complete provider identity")
        return self


class InsightErrorResponse(_ExactModel):
    schema_name: Literal["fpl.insight-summary-error"] = Field(alias="schema")
    schema_version: Literal[1]
    code: InsightErrorCode
    message: str = Field(min_length=1, max_length=160)


def parse_insight_request_bytes(payload: bytes) -> InsightSummaryRequest:
    """Parse one exact request while preserving the raw 16 KiB transport limit."""
    if not payload or len(payload) > MAX_INSIGHT_BODY_BYTES:
        raise ValueError("insight request body is missing or oversized")

    def reject_constant(value: str) -> Any:
        raise ValueError(f"strict JSON does not permit {value}")

    try:
        decoded = payload.decode("utf-8")

        def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = item
            return result

        value = json.loads(
            decoded,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("insight request body must be strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("insight request body must be a JSON object")
    return InsightSummaryRequest.model_validate(value)


def canonical_evidence_bytes(evidence: ResolvedInsightEvidence) -> bytes:
    """Canonical server-resolved bytes used only transiently to derive a cache key."""
    payload = evidence.model_dump(mode="json", by_alias=True)
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
