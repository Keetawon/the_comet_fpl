"""Development-only form summaries and regenerated OOS style inputs. No production hook."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any, Literal

from fpl.features.pit import AsOf
from fpl.validate import tactical_matchup as style
from fpl.validate.tactical_state import (
    StateEstimate,
    TacticalObservation,
    _vector,
    current_state,
)

Arm = Literal["C0", "C1", "A", "B", "C", "D"]
ARMS: tuple[Arm, ...] = ("C0", "C1", "A", "B", "C", "D")
WEIGHTS = (0.40, 0.30, 0.20, 0.07, 0.03)


def weighted_summary(
    rows: Sequence[TacticalObservation], dimension: int, *, median: bool = False
) -> tuple[float | None, int]:
    measured = [
        (float(v), w)
        for r, w in zip(rows, WEIGHTS, strict=False)
        if (v := r.values[dimension]) is not None
    ]
    if not measured:
        return None, 0
    total = math.fsum(w for _, w in measured)
    if not median:
        return math.fsum(v * w for v, w in measured) / total, len(measured)
    measured.sort()
    cumulative = 0.0
    for i, (v, w) in enumerate(measured):
        cumulative = math.fsum((cumulative, w))
        if math.isclose(cumulative, total / 2, abs_tol=1e-12, rel_tol=0):
            return (v + measured[i + 1][0]) / 2, len(measured)
        if cumulative > total / 2:
            return v, len(measured)
    raise AssertionError("positive finite weights must cross their midpoint")


def form_state(
    history: Sequence[TacticalObservation],
    team_code: int,
    season: str,
    cutoff: datetime,
    gw: int,
    was_home: bool,
    arm: Arm,
) -> tuple[StateEstimate, dict[str, Any]]:
    AsOf(cutoff)
    if arm not in ARMS:
        raise ValueError("unregistered arm")
    base = current_state(history, team_code, season, cutoff, gw)
    visible = sorted(
        (r for r in history if r.kickoff < cutoff and (r.season, r.gw) != (season, gw)),
        key=lambda r: (r.kickoff, r.season, r.fixture, r.team_code),
    )
    own = sorted(
        (r for r in visible if r.team_code == team_code and r.season == season),
        key=lambda r: (r.kickoff, r.fixture),
        reverse=True,
    )
    overall, venue = own[:5], [r for r in own if r.was_home == was_home][:5]
    raw_overall, raw_venue, priors, counts, estimates = [], [], [], [], []
    for d in range(5):
        a, na = weighted_summary(overall, d)
        v, nv = weighted_summary(venue, d, median=arm == "D")
        venue_measured = [
            r.values[d] for r in visible if r.was_home == was_home and r.values[d] is not None
        ]
        vp = (
            math.fsum(x for x in venue_measured if x is not None) / len(venue_measured)
            if venue_measured
            else base.prior[d]
        )
        p = base.prior[d]
        # A changes only recency; preserve the production overall n/(n+2) prior.
        a_pooled = na / (na + 2) * a + 2 / (na + 2) * p if a is not None and p is not None else p
        anchor = vp if arm == "B" else a_pooled
        estimate = (
            nv / (nv + 3) * v + 3 / (nv + 3) * anchor
            if v is not None and anchor is not None
            else anchor
        )
        estimates.append(a_pooled if arm == "A" else estimate)
        raw_overall.append(a)
        raw_venue.append(v)
        priors.append(vp)
        counts.append(nv)
    oldest = min((r.kickoff for r in venue), default=None)
    details = {
        "target_venue": "home" if was_home else "away",
        "overall_keys": [r.key for r in overall],
        "venue_keys": [r.key for r in venue],
        "overall_raw": raw_overall,
        "venue_raw": raw_venue,
        "venue_valid_counts": counts,
        "venue_prior": priors,
        "venue_matches": len(venue),
        "venue_oldest_kickoff": oldest.isoformat() if oldest else None,
        "venue_age_days": (cutoff - oldest).total_seconds() / 86400 if oldest else None,
    }
    if arm in ("C0", "C1"):
        return base, details
    state_counts = base.counts if arm == "A" else tuple(counts)
    return StateEstimate(
        values=_vector(estimates),
        recent_raw=_vector(raw_overall if arm == "A" else raw_venue),
        counts=(
            state_counts[0],
            state_counts[1],
            state_counts[2],
            state_counts[3],
            state_counts[4],
        ),
        prior=base.prior,
        source_keys=base.source_keys,
    ), details


def interpreted_observations(
    raw: Sequence[TacticalObservation],
    interpreted: Sequence[dict[str, Any]],
    targets: Sequence[dict[str, Any]],
) -> list[TacticalObservation]:
    """Exact identity join; only precision changes, raw observations remain immutable."""
    keyed = {(r["season"], r["fixture"], r["team_code"]): r for r in interpreted}
    shot_rows = {(r["season"], r["fixture"], r["team_code"]): r for r in targets}
    if len(keyed) != len(interpreted) or len(shot_rows) != len(targets):
        raise ValueError("duplicate interpretation identity")
    if set(keyed) != {r.key for r in raw} or set(shot_rows) != set(keyed):
        raise ValueError("interpretation population changed")
    result = []
    for r in raw:
        value, t = keyed[r.key], shot_rows[r.key]
        for field in (
            "opponent_team_code",
            "was_home",
            "capture_id",
            "payload_sha256",
            "source_known_at",
            "sdp_match_id",
        ):
            if value[field] != getattr(r, field) or value[field] != t[field]:
                raise ValueError(f"interpretation identity differs: {r.key}: {field}")
        sot, shots = value["shots_on_target_corroborated"], t["shots"]
        raw_sot = value["shots_on_target"]
        if sot != raw_sot and (
            raw_sot is not None
            or sot != 0
            or value["sot_interpretation"]
            not in {"independent_report_zero", "shot_accounting_and_fpl_proxy_zero"}
        ):
            raise ValueError("uncorroborated SOT interpretation")
        precision = sot / shots if sot is not None and shots is not None and shots > 0 else None
        result.append(replace(r, values=_vector((precision, *r.values[1:]))))
    return result


def style_walk_forward(
    observations: list[TacticalObservation],
    arm: Arm,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Only the production style stage, refitted chronologically for each arm.

    Reuses the exact frozen ridge fit/prediction functions; no obsolete tactical
    goal-offset grid. A (club, venue) key handles mixed-venue double gameweeks.
    """
    if len({r.key for r in observations}) != len(observations):
        raise ValueError("duplicate observation")
    batches: dict[tuple[str, int], list[TacticalObservation]] = defaultdict(list)
    for r in observations:
        batches[r.season, r.gw].append(r)
    history: list[style._Record] = []
    folds = []
    for season, gw in sorted(batches, key=lambda k: (min(r.kickoff for r in batches[k]), *k)):
        batch = sorted(batches[season, gw], key=lambda r: (r.kickoff, r.fixture, r.team_code))
        cutoff = min(r.kickoff for r in batch)
        prior = [r for r in history if r.observation.kickoff < cutoff]
        visible = [
            r for r in observations if r.kickoff < cutoff and (r.season, r.gw) != (season, gw)
        ]
        models, fits = style._style_fits(prior)
        if style._stacking_violations(prior) or style._fit_time_violations(
            list(fits.values()), cutoff
        ):
            raise ValueError("OOS style training leakage")
        states = {
            (r.team_code, r.was_home): form_state(
                observations, r.team_code, season, cutoff, gw, r.was_home, arm
            )
            for r in batch
        }
        pending = []
        keyed_batch = {r.key: r for r in batch}
        for r in batch:
            other = keyed_batch[r.season, r.fixture, r.opponent_team_code]
            if other.was_home == r.was_home or other.opponent_team_code != r.team_code:
                raise ValueError("nonreciprocal target sides")
            own, details = states[r.team_code, r.was_home]
            opponent, opponent_details = states[other.team_code, other.was_home]
            if set(own.source_keys) & set(keyed_batch):
                raise ValueError("target GW in state history")
            x, prediction, _, _ = style._prediction(own, opponent, r.was_home, models)
            row = {
                **asdict(r),
                "key": style.observation_key(r),
                "kickoff_time": r.kickoff.isoformat(),
                "as_of": cutoff.isoformat(),
                "observed_goals": r.goals,
                "source_capture_id": r.capture_id,
                "source_known_at": r.source_known_at.isoformat() if r.source_known_at else None,
                "current_state": own.values,
                "opponent_state": opponent.values,
                "predicted_state": prediction,
                "style_predictors": x,
                "recent_counts": own.counts,
                "opponent_counts": opponent.counts,
                "form": details,
                "opponent_form": opponent_details,
                "state_source_keys_sha256": style._hash(
                    [f"{s}:{f}:{t}" for s, f, t in own.source_keys]
                ),
                "state_source_rows": len(own.source_keys),
                "maximum_state_source_event": max((r.kickoff for r in visible), default=None),
                "maximum_style_training_event": max(
                    (
                        f["maximum_training_event"]
                        for f in fits.values()
                        if f["maximum_training_event"]
                    ),
                    default=None,
                ),
            }
            if row["maximum_state_source_event"] is not None:
                row["maximum_state_source_event"] = row["maximum_state_source_event"].isoformat()
            pending.append(style._Record(r, row, x, None, None, None, {}, ()))
        predictions = {r.observation.key: r.row["predicted_state"] for r in pending}
        for record in pending:
            r = record.observation
            record.row["predicted_opponent_state"] = predictions[
                r.season, r.fixture, r.opponent_team_code
            ]
        history.extend(pending)
        folds.append({"season": season, "gw": gw, "as_of": cutoff.isoformat(), "style_fits": fits})
        if progress is not None:
            progress(f"{arm} style {season} GW{gw}: {len(prior)} prior rows")
    return {"rows": [r.row for r in history], "folds": folds}
