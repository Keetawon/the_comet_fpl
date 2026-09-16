"""Pure, retrospective broad starting-role forecasts; never a prospective capability.

The labels are provider broad positions conditional on starting, not tactical roles.
No database, outcome-table reads, FPL position feature, optimizer or model scoring.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, cast

Role = Literal["GK", "DEF", "MID", "FWD"]
RoleDistribution = tuple[float, float, float, float]
ROLES: Final = ("GK", "DEF", "MID", "FWD")
RAW_ROLES: Final = {
    "Goalkeeper": "GK",
    "Defender": "DEF",
    "Midfielder": "MID",
    "Forward": "FWD",
}
NAME: Final = "retrospective_broad_starting_role_transition_v1"
EVIDENCE_CLASS: Final = "retrospective_competitive_role_development"
WEIGHTS: Final = (1.0, 0.707, 0.5, 0.354, 0.25)
PRIOR_STRENGTH: Final = 2.0
COMPETITIONS: Final = frozenset({8, 1, 2, 5, 6, 1125})
COMPLETION_MARGIN_HOURS: Final = 6


def _aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("role timestamps must be timezone aware")


def _positive(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("role identities must be positive integer stable codes/IDs")


def observed_starting_role(raw_position: str | None, started: bool | None) -> Role | None:
    """Bench, unassigned and unknown broad labels are NOT categorical role targets."""
    if started is not None and type(started) is not bool:
        raise ValueError("starting membership must be explicitly boolean or unknown")
    if raw_position is not None and not isinstance(raw_position, str):
        raise ValueError("raw provider position must be a string or NULL")
    return cast(Role | None, RAW_ROLES.get(raw_position or "")) if started is True else None


@dataclass(frozen=True, slots=True)
class RoleHistoryRow:
    season: str
    competition_id: int
    match_id: int
    gw: int | None
    code: int
    team_code: int
    kickoff: datetime
    completed: bool | None
    started: bool | None
    raw_position: str | None
    provider_player_id: int
    fpl_opta_anchor: str
    identity_source: str
    capture_id: str
    payload_sha256: str
    known_at: datetime
    interpretation_known_at: datetime
    max_event_at: datetime | None = None
    verified_end_at: datetime | None = None

    def __post_init__(self) -> None:
        for value in (
            self.competition_id,
            self.match_id,
            self.code,
            self.team_code,
            self.provider_player_id,
        ):
            _positive(value)
        if self.gw is not None:
            _positive(self.gw)
        for timestamp in (self.kickoff, self.known_at, self.interpretation_known_at):
            _aware(timestamp)
        for optional_timestamp in (self.max_event_at, self.verified_end_at):
            if optional_timestamp is not None:
                _aware(optional_timestamp)
                if optional_timestamp < self.kickoff:
                    raise ValueError("role event/end timestamp cannot precede kickoff")
        if (
            self.max_event_at is not None
            and self.verified_end_at is not None
            and self.max_event_at > self.verified_end_at
        ):
            raise ValueError("retained role event cannot follow verified match end")
        if self.completed is not None and type(self.completed) is not bool:
            raise ValueError("match completion must be explicit boolean or unknown")
        if self.competition_id not in COMPETITIONS:
            raise ValueError("only six explicitly licensed competitive competitions")
        if (self.competition_id == 8) != (self.gw is not None):
            raise ValueError("PL role rows require verified FPL GW; cup rows have no invented GW")
        if (
            not self.season
            or not self.identity_source
            or not self.capture_id
            or self.fpl_opta_anchor != f"p{self.provider_player_id}"
            or len(self.payload_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.payload_sha256)
        ):
            raise ValueError("exact crosswalk and original source provenance are required")
        observed_starting_role(self.raw_position, self.started)

    @property
    def role(self) -> Role | None:
        return observed_starting_role(self.raw_position, self.started)

    @property
    def completion_time_proxy(self) -> bool:
        return self.verified_end_at is None


@dataclass(frozen=True, slots=True)
class RoleTarget:
    """Outcome-free PL roster/schedule proxy; NOT the target starting eleven."""

    season: str
    gw: int
    fixture: int
    code: int
    team_code: int
    kickoff: datetime
    as_of: datetime
    identity_source: str

    def __post_init__(self) -> None:
        for value in (self.gw, self.fixture, self.code, self.team_code):
            _positive(value)
        _aware(self.kickoff)
        _aware(self.as_of)
        if self.kickoff < self.as_of or not self.season or not self.identity_source:
            raise ValueError("role target requires future schedule and declared roster evidence")


@dataclass(frozen=True, slots=True)
class RolePrediction:
    target: RoleTarget
    probabilities: RoleDistribution
    pooled_prior_baseline: RoleDistribution
    smoothed_last_role_baseline: RoleDistribution
    recent_distribution: RoleDistribution | None
    recent_measured_starts: int
    recent_weight: float
    latest_observed_role: Role | None
    witnessed_current_club_spell: bool
    recent_sources: tuple[RoleHistoryRow, ...]
    maximum_prior_event: datetime | None
    maximum_source_known_at: datetime | None
    maximum_interpretation_known_at: datetime | None
    recent_state_persistence_baseline: RoleDistribution
    maximum_retained_event: datetime | None = None
    completion_time_proxy: bool = False
    evidence_class: str = EVIDENCE_CLASS
    conditionality: str = "role_given_hypothetical_start_not_start_probability"
    membership_limitation: str = "observed_club_spell_only_unobserved_transfers_unresolved"
    promotion_permitted: bool = False


@dataclass(frozen=True, slots=True)
class RoleBatchForecast:
    season: str
    gw: int
    as_of: datetime
    predictions: tuple[RolePrediction, ...]
    global_prior: RoleDistribution
    role_counts: tuple[int, ...]
    transition_counts: tuple[tuple[int, ...], ...]
    transition_matrix: tuple[RoleDistribution, ...]
    prior_membership_rows: int
    prior_role_targets: int
    late_capture_rows: int
    source_rows_sha256: str
    source_versions: tuple[tuple[str, str, str, str], ...]
    completion_time_proxy_rows: int = 0
    name: str = NAME
    evidence_class: str = EVIDENCE_CLASS


def _distribution(values: Sequence[float]) -> RoleDistribution:
    if len(values) != 4 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("four finite nonnegative role probabilities required")
    if not math.isclose(math.fsum(values), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("role probability mass must be one")
    return cast(RoleDistribution, tuple(values))


def _ordered(history: Sequence[RoleHistoryRow]) -> tuple[RoleHistoryRow, ...]:
    keys: set[tuple[str, int, int, int]] = set()
    player_times: set[tuple[int, datetime]] = set()
    for row in history:
        if type(row) is not RoleHistoryRow:
            raise ValueError("only the explicit retrospective role-history interface is accepted")
        key = (row.season, row.competition_id, row.match_id, row.code)
        if key in keys or (row.code, row.kickoff) in player_times:
            raise ValueError("duplicate role revision or ambiguous simultaneous player fixture")
        keys.add(key)
        player_times.add((row.code, row.kickoff))
    return tuple(
        sorted(history, key=lambda r: (r.kickoff, r.season, r.competition_id, r.match_id, r.code))
    )


def _completed_before(row: RoleHistoryRow, cutoff: datetime) -> bool:
    """A six-hour exclusion margin is not a recorded whistle or a provider SLA."""
    end_bound = row.verified_end_at or row.kickoff + timedelta(hours=COMPLETION_MARGIN_HOURS)
    return (
        row.completed is True
        and row.kickoff < cutoff
        and end_bound < cutoff
        and (row.max_event_at is None or row.max_event_at < cutoff)
    )


def forecast_role_batch(
    history: Sequence[RoleHistoryRow], targets: Sequence[RoleTarget]
) -> RoleBatchForecast:
    """Fit count summaries on prior events, then predict the COMPLETE GW without updates."""
    if not targets or any(type(target) is not RoleTarget for target in targets):
        raise ValueError("nonempty outcome-free role target batch required")
    season, gw, cutoff = targets[0].season, targets[0].gw, targets[0].as_of
    if any((t.season, t.gw, t.as_of) != (season, gw, cutoff) for t in targets):
        raise ValueError("one entire season/GW must share one cutoff")
    if min(t.kickoff for t in targets) != cutoff:
        raise ValueError("cutoff must equal the declared complete GW's first kickoff proxy")
    if len({(t.fixture, t.code) for t in targets}) != len(targets):
        raise ValueError("duplicate target player-fixture")
    clubs: dict[int, int] = {}
    kickoffs: dict[int, datetime] = {}
    for target in targets:
        if target.code in clubs and clubs[target.code] != target.team_code:
            raise ValueError("same-GW roster club ambiguity")
        clubs[target.code] = target.team_code
        if target.fixture in kickoffs and kickoffs[target.fixture] != target.kickoff:
            raise ValueError("one target fixture cannot have contradictory kickoffs")
        kickoffs[target.fixture] = target.kickoff
    prior = tuple(
        row
        for row in _ordered(history)
        if _completed_before(row, cutoff)
        and not (row.competition_id == 8 and (row.season, row.gw) == (season, gw))
    )
    by_code: defaultdict[int, list[RoleHistoryRow]] = defaultdict(list)
    role_counts = [0] * 4
    transitions = [[0] * 4 for _ in ROLES]
    previous: dict[int, tuple[int, Role | None]] = {}
    for row in prior:
        by_code[row.code].append(row)
        old_club, old_role = previous.get(row.code, (row.team_code, None))
        if old_club != row.team_code:
            old_role = None
        role = row.role
        if role is not None:
            role_counts[ROLES.index(role)] += 1
            if old_role is not None:
                transitions[ROLES.index(old_role)][ROLES.index(role)] += 1
            old_role = role
        elif row.started is not False:
            # An unknown/intervening unlabelled start cannot prove a next-start transition.
            old_role = None
        previous[row.code] = (row.team_code, old_role)
    n_roles = sum(role_counts)
    global_prior = _distribution([n / n_roles for n in role_counts] if n_roles else [0.25] * 4)
    transition_matrix = tuple(
        _distribution(
            [
                (count + PRIOR_STRENGTH * p) / (sum(row) + PRIOR_STRENGTH)
                for count, p in zip(row, global_prior, strict=True)
            ]
        )
        for row in transitions
    )
    maximum_prior = max((row.kickoff for row in prior), default=None)
    maximum_known = max((row.known_at for row in prior), default=None)
    maximum_interpretation = max((row.interpretation_known_at for row in prior), default=None)
    maximum_event = max(
        (row.max_event_at for row in prior if row.max_event_at is not None), default=None
    )
    proxy_rows = sum(row.completion_time_proxy for row in prior)
    predictions = []
    for target in sorted(targets, key=lambda t: (t.fixture, t.code)):
        spell: list[RoleHistoryRow] = []
        witnessed = False
        for row in reversed(by_code[target.code]):
            if row.team_code != target.team_code:
                break
            witnessed = True
            if row.role is not None:
                spell.append(row)
                if len(spell) == len(WEIGHTS):
                    break
        n = len(spell)
        alpha = n / (n + PRIOR_STRENGTH)
        recent = None
        last = None
        smoothed = global_prior
        persistence = global_prior
        predicted = global_prior
        if spell:
            last = spell[0].role
            total_weight = math.fsum(WEIGHTS[:n])
            recent = _distribution(
                [
                    math.fsum(
                        w for row, w in zip(spell, WEIGHTS[:n], strict=True) if row.role == role
                    )
                    / total_weight
                    for role in ROLES
                ]
            )
            predicted = _distribution(
                [
                    alpha * math.fsum(recent[a] * transition_matrix[a][b] for a in range(4))
                    + (1 - alpha) * global_prior[b]
                    for b in range(4)
                ]
            )
            persistence = _distribution(
                [alpha * recent[b] + (1 - alpha) * global_prior[b] for b in range(4)]
            )
            smoothed = _distribution(
                [
                    (float(last == role) + PRIOR_STRENGTH * p) / (1 + PRIOR_STRENGTH)
                    for role, p in zip(ROLES, global_prior, strict=True)
                ]
            )
        predictions.append(
            RolePrediction(
                target,
                predicted,
                global_prior,
                smoothed,
                recent,
                n,
                alpha,
                last,
                witnessed,
                tuple(spell),
                maximum_prior,
                maximum_known,
                maximum_interpretation,
                persistence,
                maximum_retained_event=maximum_event,
                completion_time_proxy=proxy_rows > 0,
            )
        )

    def encode(value: object) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        raise TypeError(f"unexpected role source type {type(value).__name__}")

    source_bytes = json.dumps(
        [asdict(row) for row in prior],
        default=encode,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    versions = tuple(
        sorted(
            {
                (
                    r.capture_id,
                    r.payload_sha256,
                    r.known_at.isoformat(),
                    r.interpretation_known_at.isoformat(),
                )
                for r in prior
            }
        )
    )
    return RoleBatchForecast(
        season,
        gw,
        cutoff,
        tuple(predictions),
        global_prior,
        tuple(role_counts),
        tuple(tuple(row) for row in transitions),
        transition_matrix,
        len(prior),
        n_roles,
        sum(row.known_at > cutoff or row.interpretation_known_at > cutoff for row in prior),
        hashlib.sha256(source_bytes).hexdigest(),
        versions,
        completion_time_proxy_rows=proxy_rows,
    )


def walk_forward_role_forecasts(
    history: Sequence[RoleHistoryRow], targets: Sequence[RoleTarget]
) -> tuple[RoleBatchForecast, ...]:
    """Sequential out-of-event-time forecasts for all declared roster rows; no scoring."""
    grouped: defaultdict[tuple[str, int], list[RoleTarget]] = defaultdict(list)
    for target in targets:
        grouped[(target.season, target.gw)].append(target)
    keys = sorted(grouped, key=lambda key: (grouped[key][0].as_of, key))
    return tuple(forecast_role_batch(history, grouped[key]) for key in keys)
