"""Live FPL API client.

No authentication. CORS-blocked, so server-side only. Rate-limited to roughly
1 request/second by default.

The response models use `extra="ignore"`: FPL adds and removes fields between seasons
(`mng_*` appeared in 2024-25 and was gone by 2025-26), and a new field upstream must not
break a snapshot run. Fields we actually depend on are declared and validated.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fpl.config import LiveApiSource, load_sources

# Proxy/gateway statuses that mean "policy refused this host", not "the server erred".
# Retrying these is pointless and hides the real cause.
_EGRESS_BLOCKED_STATUSES: Final[frozenset[int]] = frozenset({403, 407})


class EgressBlockedError(RuntimeError):
    """The FPL API is unreachable because egress is blocked, not because it failed.

    Raised distinctly so `daily_snapshot` can exit with a diagnostic that names the cause
    instead of writing a partial snapshot or reporting a generic timeout.
    """


class ApiResponseError(RuntimeError):
    """The API responded, but not usefully."""


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def _empty_to_none(value: Any) -> Any:
    """Coerce placeholder strings to None before validation.

    FPL sends proper JSON `null`, but the archive CSVs render it as the literal `"None"`
    and some payload mirrors preserve that. Coercing here keeps a cosmetic difference in a
    single optional field from aborting a snapshot run -- R5 data is unrecoverable, so the
    client fails only on things that actually matter.
    """
    if isinstance(value, str) and value.strip() in {"", "None", "null", "NaN"}:
        return None
    return value


class BootstrapEvent(_Payload):
    id: int
    name: str
    deadline_time: datetime | None = None
    finished: bool = False
    is_current: bool = False
    is_next: bool = False


class BootstrapTeam(_Payload):
    id: int
    name: str
    short_name: str
    code: int | None = None
    pulse_id: int | None = None
    strength: int | None = None


class BootstrapElement(_Payload):
    id: int
    code: int
    web_name: str
    element_type: int
    team: int
    now_cost: int | None = None
    status: str | None = None
    chance_of_playing_next_round: int | None = None
    news: str | None = None
    news_added: datetime | None = None
    penalties_order: int | None = None
    direct_freekicks_order: int | None = None
    corners_and_indirect_freekicks_order: int | None = None
    selected_by_percent: str | None = None
    opta_code: str | None = None
    # Retained for the Phase 1 baseline: FPL's own forecast is one of the three
    # benchmarks the model must beat. Never used as a feature.
    ep_next: str | None = None
    ep_this: str | None = None

    _normalise = field_validator(
        "news_added", "status", "news", "opta_code", "selected_by_percent", mode="before"
    )(_empty_to_none)


class BootstrapStatic(_Payload):
    events: list[BootstrapEvent] = Field(default_factory=list)
    teams: list[BootstrapTeam] = Field(default_factory=list)
    elements: list[BootstrapElement] = Field(default_factory=list)
    # Kept as raw mappings. The scoring block's exact shape is FPL's to change, and
    # `verify_rules` is the single place that interprets it -- modelling it strictly here
    # would turn an upstream rename into a snapshot outage.
    game_config: dict[str, Any] = Field(default_factory=dict)
    game_settings: dict[str, Any] = Field(default_factory=dict)

    def scoring_block(self) -> dict[str, Any]:
        """`game_config.scoring`, falling back to older payload shapes."""
        scoring = self.game_config.get("scoring")
        if isinstance(scoring, dict):
            return scoring
        # Pre-2024 payloads carried the scoring constants directly on game_settings.
        return {
            key.removeprefix("scoring_"): value
            for key, value in self.game_settings.items()
            if key.startswith("scoring_")
        }

    def next_event(self) -> BootstrapEvent | None:
        for event in self.events:
            if event.is_next:
                return event
        return None

    def current_event(self) -> BootstrapEvent | None:
        for event in self.events:
            if event.is_current:
                return event
        return None


class ApiFixture(_Payload):
    id: int
    code: int | None = None
    event: int | None = None
    finished: bool = False
    kickoff_time: datetime | None = None
    team_h: int
    team_a: int
    team_h_score: int | None = None
    team_a_score: int | None = None
    team_h_difficulty: int | None = None
    team_a_difficulty: int | None = None
    pulse_id: int | None = None


class ElementHistory(_Payload):
    """One authoritative player-fixture row from element-summary.

    The live endpoint is gameweek-aggregated, so it cannot distinguish two fixtures in a
    double gameweek. Element history is the source of truth for this grain.
    """

    element: int
    fixture: int
    opponent_team: int
    total_points: int | None = None
    was_home: bool
    kickoff_time: datetime
    round: int
    minutes: int | None = None
    starts: int | None = None
    goals_scored: int | None = None
    assists: int | None = None
    clean_sheets: int | None = None
    goals_conceded: int | None = None
    saves: int | None = None
    penalties_saved: int | None = None
    penalties_missed: int | None = None
    own_goals: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    bonus: int | None = None
    bps: int | None = None
    expected_goals: float | None = None
    expected_assists: float | None = None
    expected_goals_conceded: float | None = None
    defensive_contribution: int | None = None
    tackles: int | None = None
    recoveries: int | None = None
    clearances_blocks_interceptions: int | None = None
    value: int | None = None
    selected: int | None = None
    transfers_in: int | None = None
    transfers_out: int | None = None


class ElementSummary(_Payload):
    fixtures: list[ApiFixture] = Field(default_factory=list)
    history: list[ElementHistory] = Field(default_factory=list)
    history_past: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SeasonSkew:
    """Whether the fixtures payload belongs to the same season as bootstrap-static.

    Gotcha 14: as of 2026-07-26 `/api/fixtures/` still returned the completed 2025-26
    fixtures while `bootstrap-static` had already rolled over to 2026/27 teams and
    deadlines. Team ids are reassigned every season, so joining across that boundary
    silently attributes matches to the wrong clubs.
    """

    bootstrap_first_deadline: datetime | None
    fixtures_first_kickoff: datetime | None
    fixtures_all_finished: bool
    is_consistent: bool
    detail: str


def detect_season_skew(bootstrap: BootstrapStatic, fixtures: list[ApiFixture]) -> SeasonSkew:
    """Compare the two payloads' timelines without assuming either is authoritative."""
    deadlines = [event.deadline_time for event in bootstrap.events if event.deadline_time]
    kickoffs = [fixture.kickoff_time for fixture in fixtures if fixture.kickoff_time]
    first_deadline = min(deadlines) if deadlines else None
    first_kickoff = min(kickoffs) if kickoffs else None
    all_finished = bool(fixtures) and all(fixture.finished for fixture in fixtures)

    if first_deadline is None or first_kickoff is None:
        return SeasonSkew(
            first_deadline, first_kickoff, all_finished, False, "missing deadline or kickoff data"
        )
    # A fixtures payload for the same season starts no earlier than that season's first
    # deadline (allowing a day of slack for deadline-to-kickoff ordering).
    skew_days = (first_deadline - first_kickoff).days
    if skew_days > 1:
        return SeasonSkew(
            first_deadline,
            first_kickoff,
            all_finished,
            False,
            f"fixtures payload starts {skew_days} days before the first bootstrap deadline; "
            "it is a previous season. Team ids are not comparable across seasons.",
        )
    return SeasonSkew(first_deadline, first_kickoff, all_finished, True, "consistent")


def assert_same_season(bootstrap: BootstrapStatic, fixtures: list[ApiFixture]) -> None:
    """Raise unless the two payloads describe the same season.

    Call before any join between fixture team ids and bootstrap team ids.
    """
    skew = detect_season_skew(bootstrap, fixtures)
    if not skew.is_consistent:
        raise ApiResponseError(f"season skew between bootstrap-static and fixtures: {skew.detail}")


class FplApiClient:
    """Polite, retrying client. `base_url` is overridable so tests and `--dry-run` can
    point at a local stub without touching the network."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        config: LiveApiSource | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config or load_sources().live_api
        self._base_url = (base_url or self._config.base_url).rstrip("/")
        self._client = client or httpx.Client(
            timeout=self._config.timeout_seconds, follow_redirects=True
        )
        self._owns_client = client is None
        self._last_request_at: float | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _throttle(self) -> None:
        interval = self._config.min_request_interval_seconds
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < interval:
                time.sleep(interval - elapsed)
        self._last_request_at = time.monotonic()

    def get_json(self, path: str) -> Any:
        """GET with throttling and exponential backoff. Raises on a policy block."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(url)
            except httpx.ProxyError as error:
                raise EgressBlockedError(
                    f"egress blocked reaching {url}: {error}. The host is not permitted by "
                    "this environment's network policy."
                ) from error
            except httpx.HTTPError as error:
                last_error = error
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except json.JSONDecodeError as error:
                        raise ApiResponseError(f"{url} returned invalid JSON: {error}") from error
                if response.status_code in _EGRESS_BLOCKED_STATUSES:
                    raise EgressBlockedError(
                        f"egress blocked reaching {url}: HTTP {response.status_code} from the "
                        "proxy or gateway. This is a policy denial, not a server error -- "
                        "retrying will not help."
                    )
                if response.status_code < 500:
                    raise ApiResponseError(f"{url} returned HTTP {response.status_code}")
                last_error = ApiResponseError(f"{url} returned HTTP {response.status_code}")

            if attempt < self._config.max_retries:
                time.sleep(self._config.retry_backoff_base_seconds * (2**attempt))
        raise ApiResponseError(
            f"{url} failed after {self._config.max_retries} retries: {last_error}"
        ) from last_error

    def bootstrap_static(self) -> BootstrapStatic:
        return BootstrapStatic.model_validate(
            self.get_json(self._config.endpoints["bootstrap_static"])
        )

    def fixtures(self) -> list[ApiFixture]:
        payload = self.get_json(self._config.endpoints["fixtures"])
        if not isinstance(payload, list):
            raise ApiResponseError("fixtures endpoint did not return a list")
        return [ApiFixture.model_validate(item) for item in payload]

    def raw_bootstrap_static(self) -> Any:
        """The undecoded payload, for snapshotting. R5 stores what arrived, not a parse."""
        return self.get_json(self._config.endpoints["bootstrap_static"])

    def raw_fixtures(self) -> Any:
        return self.get_json(self._config.endpoints["fixtures"])

    def raw_event_live(self, gw: int) -> Any:
        path = self._config.endpoints["event_live"].format(gw=gw)
        return self.get_json(path)

    def raw_element_summary(self, element_id: int) -> Any:
        path = self._config.endpoints["element_summary"].format(element_id=element_id)
        return self.get_json(path)

    def element_summary(self, element_id: int) -> ElementSummary:
        return ElementSummary.model_validate(self.raw_element_summary(element_id))
