"""Descriptive current-player usage; never a forecast, model feature or optimizer input.

The fixed arithmetic is reused from the frozen development study. This separate
contract accepts genuine current captures and has no target fixture or target GW.
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

from fpl.features.attacking_role_premium_v1 import (
    POSITIONS,
    RECENT_WINDOW_MINUTES,
    UsageObservation,
    _percentile,
    _rates,
    _totals,
)
from fpl.features.pit import AsOf


@dataclass(frozen=True, slots=True)
class RegisteredUsagePlayer:
    season: str
    player_code: int
    web_name: str
    fpl_position: str
    team_code: int
    source_known_at: datetime
    available_at: datetime
    capture_id: str


@dataclass(frozen=True, slots=True)
class PlayerAttackingUsageSnapshot:
    season: str
    player_code: int
    web_name: str
    fpl_position: str
    team_code: int
    as_of: datetime
    long_xg90: float | None
    long_xa90: float | None
    long_xgi90: float | None
    recent_xg90: float | None
    recent_xa90: float | None
    recent_xgi90: float | None
    long_usage_percentile: float | None
    recent_usage_percentile: float | None
    long_xg_percentile: float | None
    long_xa_percentile: float | None
    recent_xg_percentile: float | None
    recent_xa_percentile: float | None
    delta_xg90: float | None
    delta_xa90: float | None
    delta_xgi90: float | None
    delta_usage_percentile: float | None
    historical_minutes: float | None
    measured_minutes: float
    historical_starts: int | None
    historical_appearances: int | None
    historical_meaningful_appearances: int | None
    recent_window_minutes: float | None
    recent_measured_minutes: float | None
    long_usage_bucket: str
    recent_usage_bucket: str
    exposure_bucket: str
    long_peer_count: int
    recent_peer_count: int
    long_profile_status: str
    recent_profile_status: str
    source_known_at: datetime
    available_at: datetime
    registry_capture_id: str
    history_sha256: str
    population_history_sha256: str
    source_versions: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class _Profile:
    totals: tuple[float, float, float]
    status: str
    witnessed_minutes: float | None


def _instant(value: datetime) -> datetime:
    return AsOf(value).ts.astimezone(UTC)


def _positive_int(value: int) -> bool:
    return type(value) is int and value > 0


def usage_bucket(percentile: float | None) -> str:
    if percentile is None:
        return "UNKNOWN"
    if not math.isfinite(percentile) or not 0 <= percentile <= 1:
        raise ValueError("usage percentile must be finite and within zero to one")
    return (
        "NORMAL"
        if percentile < 0.75
        else "ELEVATED"
        if percentile < 0.9
        else "HIGH"
        if percentile < 0.975
        else "EXTREME"
    )


def exposure_bucket(minutes: float | None) -> str:
    if minutes is None:
        return "UNKNOWN"
    if not math.isfinite(minutes) or minutes < 0:
        raise ValueError("exposure minutes must be finite and nonnegative")
    return (
        "VERY_LOW"
        if minutes < 180
        else "LOW"
        if minutes < 450
        else "MODERATE"
        if minutes < 900
        else "ESTABLISHED"
    )


def _validate_observation(row: UsageObservation) -> None:
    if (
        not _positive_int(row.fixture_id)
        or not _positive_int(row.gameweek)
        or not _positive_int(row.player_code)
        or row.fpl_position not in POSITIONS
        or not row.source_snapshot_id
        or re.fullmatch(r"[0-9a-f]{64}", row.source_sha256) is None
    ):
        raise ValueError("invalid current observation identity/provenance")
    if row.minutes is not None and (type(row.minutes) is not int or not 0 <= row.minutes <= 120):
        raise ValueError("invalid observed minutes")
    if row.starts is not None and (type(row.starts) is not int or row.starts not in (0, 1)):
        raise ValueError("invalid observed starts")
    for value in (row.xg, row.xa):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("invalid observed opportunity")
    if _instant(row.source_known_at) <= _instant(row.kickoff_time):
        raise ValueError("observed match must precede current source knowledge")
    if _instant(row.available_at) < _instant(row.source_known_at):
        raise ValueError("observation availability precedes source knowledge")


def _history(
    history: Sequence[UsageObservation],
    registry: dict[int, RegisteredUsagePlayer],
    cutoff: datetime,
) -> dict[int, list[UsageObservation]]:
    versions: dict[tuple[int, int, str], UsageObservation] = {}
    for row in history:
        registered = registry.get(row.player_code)
        if registered is None or row.season != registered.season:
            continue
        if row.evidence_class != "CURRENT_PROSPECTIVE":
            continue
        if _instant(row.source_known_at) > cutoff or _instant(row.available_at) > cutoff:
            continue
        version = (row.player_code, row.fixture_id, row.source_snapshot_id)
        if version in versions and versions[version] != row:
            raise ValueError("contradictory duplicate current source version")
        versions[version] = row
    latest: dict[tuple[int, int], UsageObservation] = {}
    for row in versions.values():
        key = (row.player_code, row.fixture_id)
        old = latest.get(key)
        if old is None or (_instant(row.source_known_at), row.source_snapshot_id) > (
            _instant(old.source_known_at),
            old.source_snapshot_id,
        ):
            latest[key] = row
    selected: dict[int, list[UsageObservation]] = defaultdict(list)
    for _, row in sorted(latest.items()):
        if _instant(row.kickoff_time) >= cutoff:
            continue
        _validate_observation(row)
        if row.fpl_position != registry[row.player_code].fpl_position:
            raise ValueError("same-season historical position contradicts registered position")
        selected[row.player_code].append(row)
    return selected


def _profile(rows: Sequence[UsageObservation], *, recent: bool) -> _Profile:
    limit = RECENT_WINDOW_MINUTES if recent else math.inf
    witnessed: list[float] = []
    incomplete = False
    for row in sorted(rows, key=lambda r: (_instant(r.kickoff_time), r.fixture_id), reverse=True):
        if limit <= 0:
            break
        if row.minutes is None:
            # An unknown gap cannot be crossed to assemble a recent time window.
            return _Profile(_totals(rows), "UNKNOWN_MINUTES", None)
        if row.minutes <= 0:
            continue
        used = min(float(row.minutes), limit)
        witnessed.append(used)
        limit -= used
        if row.xg is None or row.xa is None:
            incomplete = True
    totals = _totals(rows, RECENT_WINDOW_MINUTES if recent else None)
    status = (
        "INCOMPLETE_OPPORTUNITY"
        if incomplete
        else "NO_MEASURED_EXPOSURE"
        if totals[0] == 0
        else "AVAILABLE"
    )
    return _Profile(totals, status, math.fsum(witnessed))


def _difference(recent: float | None, long: float | None) -> float | None:
    return None if recent is None or long is None else recent - long


def _digest(rows: Sequence[UsageObservation]) -> str:
    payload = []
    for row in rows:
        record = asdict(row)
        for key, value in record.items():
            if isinstance(value, datetime):
                record[key] = _instant(value).isoformat()
        payload.append(record)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def build_player_attacking_usage(
    history: Sequence[UsageObservation],
    players: Sequence[RegisteredUsagePlayer],
    as_of: datetime,
) -> tuple[PlayerAttackingUsageSnapshot, ...]:
    """Describe latest eligible current observations independently of a future fixture."""
    cutoff = _instant(as_of)
    registry: dict[int, RegisteredUsagePlayer] = {}
    for player in players:
        if _instant(player.source_known_at) > cutoff or _instant(player.available_at) > cutoff:
            continue
        if (
            not _positive_int(player.player_code)
            or not _positive_int(player.team_code)
            or player.fpl_position not in POSITIONS
            or not player.capture_id
            or not player.season
            or not player.web_name
            or _instant(player.available_at) < _instant(player.source_known_at)
        ):
            raise ValueError("invalid current player registry identity/availability")
        if player.player_code in registry:
            raise ValueError("duplicate registered stable player identity")
        registry[player.player_code] = player
    if len({p.season for p in registry.values()}) > 1:
        raise ValueError("one current season required; positions must not cross seasons")
    selected = _history(history, registry, cutoff)
    position_rows: dict[str, list[UsageObservation]] = defaultdict(list)
    for code, rows in selected.items():
        position_rows[registry[code].fpl_position].extend(rows)
    priors = {}
    for position, rows in position_rows.items():
        minutes, xg, xa = _totals(rows)
        if minutes > 0:
            priors[position] = (90.0 * xg / minutes, 90.0 * xa / minutes)
    profiles = {
        code: (
            _profile(selected.get(code, []), recent=False),
            _profile(selected.get(code, []), recent=True),
        )
        for code in registry
    }
    rates: dict[tuple[int, int], tuple[float, float]] = {}
    peers: dict[tuple[str, int], list[tuple[float, float]]] = defaultdict(list)
    for code in sorted(registry):
        for index, profile in enumerate(profiles[code]):
            if profile.status == "AVAILABLE":
                position = registry[code].fpl_position
                rate = _rates(profile.totals, priors[position])
                rates[code, index] = rate
                peers[position, index].append(rate)
    population_digest = _digest(
        [row for selected_code in sorted(selected) for row in selected[selected_code]]
    )
    population_source_known_at = max(
        [_instant(p.source_known_at) for p in registry.values()]
        + [_instant(row.source_known_at) for rows in selected.values() for row in rows],
        default=cutoff,
    )
    population_available_at = max(
        [_instant(p.available_at) for p in registry.values()]
        + [_instant(row.available_at) for rows in selected.values() for row in rows],
        default=cutoff,
    )
    result = []
    for code in sorted(registry):
        player, rows = registry[code], selected.get(code, [])
        long, recent = profiles[code]
        rate_values: list[tuple[float | None, float | None, float | None]] = []
        percentiles: list[tuple[float | None, float | None, float | None]] = []
        for index in (0, 1):
            profile_rate = rates.get((code, index))
            if profile_rate is None:
                rate_values.append((None, None, None))
                percentiles.append((None, None, None))
            else:
                own_peers = peers[player.fpl_position, index]
                pg = _percentile(profile_rate[0], [r[0] for r in own_peers])
                pa = _percentile(profile_rate[1], [r[1] for r in own_peers])
                rate_values.append((profile_rate[0], profile_rate[1], sum(profile_rate)))
                percentiles.append((pg, pa, (pg + pa) / 2.0))
        lg, la, lgi = rate_values[0]
        rg, ra, rgi = rate_values[1]
        lpg, lpa, lp = percentiles[0]
        rpg, rpa, rp = percentiles[1]
        starts = (
            None
            if any(r.starts is None for r in rows)
            else sum(r.starts for r in rows if r.starts is not None)
        )
        known_minutes = all(r.minutes is not None for r in rows)
        appearances = (
            sum(r.minutes > 0 for r in rows if r.minutes is not None) if known_minutes else None
        )
        meaningful = (
            sum(r.minutes >= 45 for r in rows if r.minutes is not None) if known_minutes else None
        )
        result.append(
            PlayerAttackingUsageSnapshot(
                season=player.season,
                player_code=code,
                web_name=player.web_name,
                fpl_position=player.fpl_position,
                team_code=player.team_code,
                as_of=cutoff,
                long_xg90=lg,
                long_xa90=la,
                long_xgi90=lgi,
                recent_xg90=rg,
                recent_xa90=ra,
                recent_xgi90=rgi,
                long_usage_percentile=lp,
                recent_usage_percentile=rp,
                long_xg_percentile=lpg,
                long_xa_percentile=lpa,
                recent_xg_percentile=rpg,
                recent_xa_percentile=rpa,
                delta_xg90=_difference(rg, lg),
                delta_xa90=_difference(ra, la),
                delta_xgi90=_difference(rgi, lgi),
                delta_usage_percentile=_difference(rp, lp),
                historical_minutes=long.witnessed_minutes,
                measured_minutes=long.totals[0],
                historical_starts=starts,
                historical_appearances=appearances,
                historical_meaningful_appearances=meaningful,
                recent_window_minutes=recent.witnessed_minutes,
                recent_measured_minutes=None
                if recent.witnessed_minutes is None
                else recent.totals[0],
                long_usage_bucket=usage_bucket(lp),
                recent_usage_bucket=usage_bucket(rp),
                exposure_bucket=exposure_bucket(long.witnessed_minutes),
                long_peer_count=len(peers[player.fpl_position, 0]),
                recent_peer_count=len(peers[player.fpl_position, 1]),
                long_profile_status=long.status,
                recent_profile_status=recent.status,
                source_known_at=population_source_known_at,
                available_at=population_available_at,
                registry_capture_id=player.capture_id,
                history_sha256=_digest(rows),
                population_history_sha256=population_digest,
                source_versions=tuple(
                    sorted(
                        {
                            (
                                r.source_snapshot_id,
                                _instant(r.source_known_at).isoformat(),
                                r.source_sha256,
                            )
                            for r in rows
                        }
                    )
                ),
            )
        )
    return tuple(result)
