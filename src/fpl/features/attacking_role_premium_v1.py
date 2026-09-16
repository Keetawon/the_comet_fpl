"""Fixed development-only xG/xA usage persistence features over archived-as-of history.

This pure capability accepts historical observations and outcome-free targets. It is
not wired into production FeatureSource, player models, or the optimizer. The recent
window's fractional oldest appearance prorates aggregate xG/xA; it cannot recover
when opportunities occurred within that appearance.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final

from fpl.features.pit import AsOf

SHRINKAGE_MINUTES: Final = 450.0
RECENT_WINDOW_MINUTES: Final = 360.0
POSITIONS: Final = ("DEF", "MID", "FWD")


@dataclass(frozen=True, slots=True)
class UsageObservation:
    season: str
    gameweek: int
    fixture_id: int
    kickoff_time: datetime
    player_code: int
    fpl_position: str
    minutes: int | None
    starts: int | None
    xg: float | None
    xa: float | None
    source_known_at: datetime
    available_at: datetime
    evidence_class: str
    source_snapshot_id: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class UsageTarget:
    season: str
    gameweek: int
    fixture_id: int
    kickoff_time: datetime
    player_code: int
    fpl_position: str
    team_code: int
    opponent_team_code: int
    venue: str


@dataclass(frozen=True, slots=True)
class UsagePrediction:
    target: UsageTarget
    as_of: datetime
    control_xg90: float
    control_xa90: float
    control_xgi90: float
    candidate_xg90: float
    candidate_xa90: float
    candidate_xgi90: float
    attacking_role_premium_v1: float
    xg_premium_percentile: float
    xa_premium_percentile: float
    recent_shift_xg90: float
    recent_shift_xa90: float
    recent_shift_xgi90: float
    historical_minutes: float
    recent_window_minutes: float
    historical_starts: int | None
    historical_appearances: int | None
    historical_meaningful_appearances: int | None
    history_rows: int
    paired_history_rows: int
    unavailable_paired_rows: int
    zero_minute_history_rows: int
    peer_count: int
    positional_prior_xg90: float
    positional_prior_xa90: float
    history_sha256: str
    player_history_sha256: str
    source_versions: tuple[tuple[str, str, str], ...]


def _instant(value: datetime) -> datetime:
    return AsOf(value).ts.astimezone(UTC)


def _identity(value: int) -> bool:
    return type(value) is int and value > 0


def _validate_observation(row: UsageObservation) -> None:
    if (
        row.fpl_position not in POSITIONS
        or not _identity(row.player_code)
        or not _identity(row.fixture_id)
        or not _identity(row.gameweek)
    ):
        raise ValueError("invalid observed identity or registered position")
    if row.minutes is not None and (type(row.minutes) is not int or not 0 <= row.minutes <= 120):
        raise ValueError("invalid observed minutes")
    if row.starts is not None and (type(row.starts) is not int or row.starts not in (0, 1)):
        raise ValueError("invalid observed starts")
    for value in (row.xg, row.xa):
        if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0):
            raise ValueError("invalid observed opportunity")
    if not re.fullmatch(r"[0-9a-f]{40}", row.source_snapshot_id) or not re.fullmatch(
        r"[0-9a-f]{64}", row.source_sha256
    ):
        raise ValueError("full source snapshot and content identities required")
    if _instant(row.kickoff_time) >= _instant(row.source_known_at):
        raise ValueError("observed match must precede source knowledge")
    if _instant(row.available_at) < _instant(row.source_known_at):
        raise ValueError("availability cannot precede source knowledge")


def _selected_history(
    history: Sequence[UsageObservation],
    *,
    season: str,
    gameweek: int,
    fixtures: set[int],
    as_of: datetime,
) -> tuple[UsageObservation, ...]:
    versions: dict[tuple[int, int, str], UsageObservation] = {}
    for row in history:
        if row.season != season or row.gameweek == gameweek or row.fixture_id in fixtures:
            continue
        if row.evidence_class != "ARCHIVED_AS_OF":
            continue
        if (
            _instant(row.kickoff_time) >= as_of
            or _instant(row.source_known_at) > as_of
            or _instant(row.available_at) > as_of
        ):
            continue
        _validate_observation(row)
        version = (row.fixture_id, row.player_code, row.source_snapshot_id)
        if version in versions and versions[version] != row:
            raise ValueError("contradictory observation source version")
        versions[version] = row
    selected: dict[tuple[int, int], UsageObservation] = {}
    positions: dict[int, str] = {}
    for row in sorted(
        versions.values(), key=lambda r: (_instant(r.source_known_at), r.source_snapshot_id)
    ):
        if positions.get(row.player_code, row.fpl_position) != row.fpl_position:
            raise ValueError("contradictory historical registered position")
        positions[row.player_code] = row.fpl_position
        selected.setdefault((row.fixture_id, row.player_code), row)
    return tuple(
        sorted(
            selected.values(), key=lambda r: (r.player_code, _instant(r.kickoff_time), r.fixture_id)
        )
    )


def _paired(row: UsageObservation) -> bool:
    return row.minutes is not None and row.minutes > 0 and row.xg is not None and row.xa is not None


def _totals(
    rows: Sequence[UsageObservation], limit: float | None = None
) -> tuple[float, float, float]:
    used: list[tuple[float, float, float]] = []
    remaining = math.inf if limit is None else limit
    for row in sorted(rows, key=lambda r: (_instant(r.kickoff_time), r.fixture_id), reverse=True):
        if remaining <= 0:
            break
        if limit is not None and row.minutes is None:
            raise ValueError("unknown minutes inside recent window; window unavailable")
        if row.minutes is None or row.minutes <= 0:
            continue
        minutes = min(float(row.minutes), remaining)
        # Measured minutes consume the window even when opportunity is unavailable.
        remaining -= minutes
        if row.xg is None or row.xa is None:
            continue
        fraction = minutes / row.minutes
        used.append((minutes, fraction * row.xg, fraction * row.xa))
    return (
        math.fsum(values[0] for values in used),
        math.fsum(values[1] for values in used),
        math.fsum(values[2] for values in used),
    )


def _rates(totals: tuple[float, float, float], prior: tuple[float, float]) -> tuple[float, float]:
    minutes, xg, xa = totals
    if minutes == 0:
        return prior
    denominator = minutes + SHRINKAGE_MINUTES
    return (
        (90.0 * xg + SHRINKAGE_MINUTES * prior[0]) / denominator,
        (90.0 * xa + SHRINKAGE_MINUTES * prior[1]) / denominator,
    )


def _percentile(value: float, peers: Sequence[float]) -> float:
    return (
        sum(other < value for other in peers) + 0.5 * sum(other == value for other in peers)
    ) / len(peers)


def _history_hash(rows: Sequence[UsageObservation]) -> str:
    canonical: list[dict[str, object]] = []
    for row in rows:
        record = asdict(row)
        for key, value in record.items():
            if isinstance(value, datetime):
                record[key] = _instant(value).isoformat()
        canonical.append(record)
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def predict_batch(
    history: Sequence[UsageObservation],
    targets: Sequence[UsageTarget],
    *,
    as_of: datetime,
) -> tuple[UsagePrediction, ...]:
    """Freeze one whole GW from prior class-B evidence using the preregistered constants."""
    cutoff = _instant(as_of)
    if not targets:
        return ()
    season, gameweek = targets[0].season, targets[0].gameweek
    identities: set[tuple[int, int]] = set()
    target_positions: dict[int, str] = {}
    for target in targets:
        if (target.season, target.gameweek) != (season, gameweek):
            raise ValueError("one complete season/gameweek batch required")
        if (
            target.fpl_position not in POSITIONS
            or target.venue not in {"HOME", "AWAY"}
            or not all(
                _identity(value)
                for value in (
                    target.player_code,
                    target.fixture_id,
                    target.gameweek,
                    target.team_code,
                    target.opponent_team_code,
                )
            )
            or target.team_code == target.opponent_team_code
        ):
            raise ValueError("invalid target identity")
        if _instant(target.kickoff_time) <= cutoff:
            raise ValueError("all target fixtures must remain future at cutoff")
        key = (target.fixture_id, target.player_code)
        if key in identities:
            raise ValueError("duplicate target fixture/player")
        identities.add(key)
        if target_positions.get(target.player_code, target.fpl_position) != target.fpl_position:
            raise ValueError("contradictory target position")
        target_positions[target.player_code] = target.fpl_position
    selected = _selected_history(
        history,
        season=season,
        gameweek=gameweek,
        fixtures={target.fixture_id for target in targets},
        as_of=cutoff,
    )
    players: dict[int, list[UsageObservation]] = defaultdict(list)
    position_rows: dict[str, list[UsageObservation]] = defaultdict(list)
    for row in selected:
        if target_positions.get(row.player_code, row.fpl_position) != row.fpl_position:
            raise ValueError("target position contradicts prior registered position")
        players[row.player_code].append(row)
        position_rows[row.fpl_position].append(row)
    priors: dict[str, tuple[float, float]] = {}
    for position, rows in position_rows.items():
        minutes, xg, xa = _totals(rows)
        if minutes > 0:
            priors[position] = (90.0 * xg / minutes, 90.0 * xa / minutes)
    peers: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for code in sorted(players):
        rows = players[code]
        position = rows[0].fpl_position
        if any(_paired(row) for row in rows):
            peers[position].append(_rates(_totals(rows, RECENT_WINDOW_MINUTES), priors[position]))
    digest = _history_hash(selected)
    sources = tuple(
        sorted(
            {
                (
                    row.source_snapshot_id,
                    _instant(row.source_known_at).isoformat(),
                    row.source_sha256,
                )
                for row in selected
            }
        )
    )
    result: list[UsagePrediction] = []
    for target in sorted(targets, key=lambda t: (t.fixture_id, t.player_code)):
        if target.fpl_position not in priors:
            raise ValueError("no measured positional prior; prediction unavailable")
        rows = players.get(target.player_code, [])
        prior = priors[target.fpl_position]
        long_totals, recent_totals = _totals(rows), _totals(rows, RECENT_WINDOW_MINUTES)
        control, candidate = _rates(long_totals, prior), _rates(recent_totals, prior)
        peer_rates = peers[target.fpl_position]
        xg_percentile = _percentile(candidate[0], [rate[0] for rate in peer_rates])
        xa_percentile = _percentile(candidate[1], [rate[1] for rate in peer_rates])
        starts = (
            None
            if any(row.starts is None for row in rows)
            else sum(row.starts for row in rows if row.starts is not None)
        )
        appearances = (
            None
            if any(row.minutes is None for row in rows)
            else sum(row.minutes > 0 for row in rows if row.minutes is not None)
        )
        meaningful = (
            None
            if any(row.minutes is None for row in rows)
            else sum(row.minutes >= 45 for row in rows if row.minutes is not None)
        )
        result.append(
            UsagePrediction(
                target=target,
                as_of=cutoff,
                control_xg90=control[0],
                control_xa90=control[1],
                control_xgi90=control[0] + control[1],
                candidate_xg90=candidate[0],
                candidate_xa90=candidate[1],
                candidate_xgi90=candidate[0] + candidate[1],
                attacking_role_premium_v1=(xg_percentile + xa_percentile) / 2.0,
                xg_premium_percentile=xg_percentile,
                xa_premium_percentile=xa_percentile,
                recent_shift_xg90=candidate[0] - control[0],
                recent_shift_xa90=candidate[1] - control[1],
                recent_shift_xgi90=(candidate[0] + candidate[1]) - (control[0] + control[1]),
                historical_minutes=long_totals[0],
                recent_window_minutes=recent_totals[0],
                historical_starts=starts,
                historical_appearances=appearances,
                historical_meaningful_appearances=meaningful,
                history_rows=len(rows),
                paired_history_rows=sum(_paired(row) for row in rows),
                unavailable_paired_rows=sum(
                    row.minutes is None or row.xg is None or row.xa is None for row in rows
                ),
                zero_minute_history_rows=sum(row.minutes == 0 for row in rows),
                peer_count=len(peer_rates),
                positional_prior_xg90=prior[0],
                positional_prior_xa90=prior[1],
                history_sha256=digest,
                player_history_sha256=_history_hash(rows),
                source_versions=sources,
            )
        )
    return tuple(result)
