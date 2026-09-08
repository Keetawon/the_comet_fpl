"""Read-only prospective checkpoint adapter over immutable paired ledger vintages.

No inference, fitting, outcome attachment or retrospective forecast reconstruction occurs.
The small metric primitives are reused from the frozen scorecard; its GW1-3 runner is not.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from itertools import product
from pathlib import Path
from types import ModuleType
from typing import Any

import duckdb

from fpl.storage.db import table_exists
from fpl.storage.sdp_evidence import (
    _official_gameweek_final,
    load_pair,
    pair_player_gameweek_rows,
    pair_team_fixture_rows,
)
from fpl.validate import audit_json, metrics, player_model_gw1_3_metrics
from fpl.validate.metrics import PROBABILITY_FLOOR, crps, log_score
from fpl.validate.player_model_gw1_3_metrics import (
    PAIRED_LOSSES,
    _calibration,
    _continuous,
    _paired_summary,
    _point_slices,
    _quantile,
    _rankings,
    _with_losses,
)

type Row = dict[str, Any]
SCHEMA = "fpl.sdp-prospective-checkpoint/v1"
ROLES = ("primary", "shadow")
SCORING = {
    "signed_target": "total_points_as_recorded",
    "proper_target": "sum_individually_coarsened_fixture_targets",
    "fixture_support_max": 34,
    "log_floor": PROBABILITY_FLOOR,
}


def canonical_bytes(value: Any) -> bytes:
    """Reuse the repaired, integer-key-safe canonical audit transport."""
    return audit_json.canonical(value)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _hash(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def validate_contract(pair: Row, contract: Row, contract_sha256: str) -> tuple[int, ...]:
    """Bind selection and metric policy before any outcome projection is read."""
    _require(_hash(contract_sha256), "invalid contract hash")
    _require(
        type(contract.get("schema_version")) is int and contract["schema_version"] == 1,
        "unsupported checkpoint contract",
    )
    for field in (
        "checkpoint_id",
        "model_freeze_sha",
        "forecast_emitter_sha",
        "selection_registered_at",
    ):
        _require(isinstance(contract.get(field), str) and bool(contract[field]), f"missing {field}")
    for field in ("prediction_id", "season", "primary_artifact_sha256", "shadow_artifact_sha256"):
        _require(contract.get(field) == pair.get(field), f"checkpoint pair {field} mismatch")
    _require(contract["season"] == "2026-27", "checkpoint is bounded to 2026-27")
    for field in ("primary_artifact_sha256", "shadow_artifact_sha256"):
        _require(_hash(contract[field]), f"invalid {field}")
    gameweeks = contract.get("gameweeks")
    _require(
        isinstance(gameweeks, list)
        and bool(gameweeks)
        and all(type(gw) is int and 4 <= gw <= 8 for gw in gameweeks)
        and gameweeks == sorted(set(gameweeks)),
        "checkpoint gameweeks must be unique ordered GW4-8",
    )
    assert isinstance(gameweeks, list)
    policy = contract.get("vintage_policy")
    _require(policy in ("fixed_origin", "rolling"), "unrecognized vintage policy")
    _require(policy != "rolling" or len(gameweeks) == 1, "rolling contract selects one target GW")
    _require(
        all(pair["gw_from"] <= gw <= pair["gw_to"] for gw in gameweeks),
        "checkpoint gameweek outside retained pair horizon",
    )
    _require(contract.get("scoring") == SCORING, "checkpoint scoring policy mismatch")
    return tuple(gameweeks)


def finality_witness(con: duckdb.DuckDBPyConnection, season: str, gw: int) -> Row:
    """Retain the exact fixture flags behind the existing whole-GW finality authority."""
    archived = False
    if table_exists(con, "stg_fixture"):
        found = con.execute(
            "SELECT count(*) FROM stg_fixture WHERE season = ?", [season]
        ).fetchone()
        archived = found is not None and int(found[0]) > 0
    if archived:
        source = "stg_fixture"
        rows = con.execute(
            "SELECT fixture, finished FROM stg_fixture "
            "WHERE season = ? AND gw = ? ORDER BY fixture",
            [season, gw],
        ).fetchall()
        witnesses = [{"fixture": int(r[0]), "finished": r[1]} for r in rows]
    elif table_exists(con, "stg_live_fixture_version"):
        source = "stg_live_fixture_version"
        rows = con.execute(
            """
            SELECT fixture, finished, epoch_us(known_at), capture_id FROM (
                SELECT fixture, gw, finished, known_at, capture_id
                FROM stg_live_fixture_version WHERE season = ?
                QUALIFY row_number() OVER (
                    PARTITION BY fixture ORDER BY known_at DESC, capture_id DESC
                ) = 1
            ) WHERE gw = ? ORDER BY fixture
            """,
            [season, gw],
        ).fetchall()
        witnesses = [
            {
                "fixture": int(r[0]),
                "finished": r[1],
                "known_at_epoch_us": int(r[2]),
                "capture_id": r[3],
            }
            for r in rows
        ]
    else:
        source, witnesses = None, []
    final = _official_gameweek_final(con, season, gw)
    _require(
        final == (all(r["finished"] is True for r in witnesses) if witnesses else None),
        "finality witness disagrees with ledger authority",
    )
    return {
        "season": season,
        "gw": gw,
        "official_final": final,
        "source": source,
        "fixtures": witnesses,
    }


def _pmf(value: Any) -> tuple[float, ...]:
    _require(isinstance(value, (list, tuple)) and bool(value), "missing retained PMF")
    _require(
        all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in value)
        and math.isclose(math.fsum(value), 1, rel_tol=0, abs_tol=1e-8),
        "invalid retained PMF",
    )
    return tuple(float(p) for p in value)


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _index(
    rows: Sequence[Row], fields: tuple[str, ...], gameweeks: tuple[int, ...]
) -> dict[str, dict[tuple[Any, ...], Row]]:
    indexed: dict[str, dict[tuple[Any, ...], Row]] = {role: {} for role in ROLES}
    for row in rows:
        _require(row.get("role") in ROLES, "unknown pair role")
        if row["gw"] not in gameweeks:
            continue
        key = tuple(row[field] for field in fields)
        target = indexed[row["role"]]
        _require(key not in target, "duplicate paired prediction")
        target[key] = row
    _require(indexed["primary"].keys() == indexed["shadow"].keys(), "pair population mismatch")
    return indexed


def _paired(rows: Sequence[Row], *, team: bool = False) -> Row:
    losses = (
        ("log_score", "crps", "cs_brier")
        if team
        else ("log_score", "crps", "signed_absolute_error")
    )
    if not team:
        summary = _paired_summary(rows)
    else:
        summary = {
            "rows": len(rows),
            "metrics": {
                loss: {
                    "current_mean": _mean([r["current"][loss] for r in rows]),
                    "incumbent_mean": _mean([r["incumbent"][loss] for r in rows]),
                    "difference_current_minus_incumbent": _mean(
                        [r["difference"][loss] for r in rows]
                    ),
                }
                for loss in losses
            },
        }
    summary["all_paired_losses_numerically_equal"] = (
        all(r["difference"][loss] == 0 for r in rows for loss in losses) if rows else None
    )
    return summary


def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _metric_source_hashes() -> dict[str, str]:
    modules: tuple[ModuleType, ...] = (audit_json, metrics, player_model_gw1_3_metrics)
    paths = [Path(__file__)]
    for module in modules:
        assert module.__file__ is not None
        paths.append(Path(module.__file__))
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _pair_losses(primary: Row, shadow: Row, *, team: bool = False) -> Row:
    losses = (
        ("log_score", "crps", "cs_brier")
        if team
        else ("log_score", "crps", "signed_absolute_error")
    )
    return {
        "season": primary["season"],
        "gw": primary["gw"],
        "selector": primary["selector"],
        "current": {loss: primary[loss] for loss in losses},
        "incumbent": {loss: shadow[loss] for loss in losses},
        "difference": {loss: primary[loss] - shadow[loss] for loss in losses},
    }


def _paired_slices(rows: Sequence[Row], *, team: bool = False) -> Row:
    return {
        "overall": _paired(rows, team=team),
        "by_gameweek": {
            str(gw): _paired([r for r in rows if r["gw"] == gw], team=team)
            for gw in sorted({r["gw"] for r in rows})
        },
        "by_primary_selector": {
            str(s): _paired([r for r in rows if r["selector"] == s], team=team)
            for s in sorted({r["selector"] for r in rows})
        },
    }


def _five_gw_uncertainty(
    rows: Sequence[Row],
    *,
    gameweeks: tuple[int, ...],
    finalized: Sequence[int],
    vintage_policy: str,
    team: bool = False,
) -> Row:
    """The frozen exhaustive GW-block bootstrap, restricted to the five-GW checkpoint.

    Repeated blocks retain their row multiplicities. This is the existing paired-loss
    arithmetic generalized from three blocks to exactly five, never a model/gate change.
    """
    losses = ("log_score", "crps", "cs_brier") if team else PAIRED_LOSSES
    groups: defaultdict[tuple[str, int], list[Row]] = defaultdict(list)
    for row in rows:
        groups[row["season"], row["gw"]].append(row)
    labels = sorted(groups)
    base: Row = {
        "n_finalized_gameweeks": len(set(finalized)),
        "n_scored_gameweeks": len(labels),
        "gameweeks": [list(key) for key in labels],
        "limitation": "Only five temporal blocks; descriptive intervals, no promotion evidence.",
    }
    if (
        vintage_policy != "fixed_origin"
        or gameweeks != (4, 5, 6, 7, 8)
        or sorted(set(finalized)) != list(gameweeks)
        or len({season for season, _ in labels}) != 1
        or [gw for _, gw in labels] != list(gameweeks)
    ):
        return {
            **base,
            "status": "UNAVAILABLE_REQUIRES_ALL_FIVE_FINALIZED_SCORED_GAMEWEEKS",
            "reason": "Wait for complete fixed-origin GW4-8; rolling vintages stay separate.",
            "draws": [],
            "intervals_95": dict.fromkeys(losses),
        }
    totals = {
        label: {
            metric: math.fsum(r["difference"][metric] for r in groups[label]) for metric in losses
        }
        for label in labels
    }
    draws: list[Row] = []
    for sampled in product(labels, repeat=5):
        size = sum(len(groups[label]) for label in sampled)
        draws.append(
            {
                "sampled_gameweeks": [gw for _, gw in sampled],
                "rows_with_multiplicity": size,
                "difference": {
                    metric: math.fsum(totals[label][metric] for label in sampled) / size
                    for metric in losses
                },
            }
        )
    return {
        **base,
        "status": "DESCRIPTIVE_ONLY_FIVE_GAMEWEEK_BLOCKS",
        "draws": draws,
        "intervals_95": {
            metric: [_quantile([r["difference"][metric] for r in draws], p) for p in (0.025, 0.975)]
            for metric in losses
        },
    }


def _team_summary(rows: Sequence[Row]) -> Row:
    return {
        "rows": len(rows),
        "goal_nll": _mean([r["log_score"] for r in rows]),
        "goal_crps": _mean([r["crps"] for r in rows]),
        "clean_sheet": _calibration(
            [(r["probability_clean_sheet"], int(r["actual_against"] == 0)) for r in rows]
        ),
        "goals_calibration": _continuous(
            [(r["expected_goals"], float(r["actual_goals"])) for r in rows], len(rows)
        ),
        "goal_log_floor_hit_count": sum(
            r["distribution"][r["scored_target"]] < PROBABILITY_FLOOR for r in rows
        ),
        "goal_targets_above_support": sum(
            r["actual_goals"] >= len(r["distribution"]) for r in rows
        ),
    }


def score_pair_report(
    pair: Row,
    player_gameweek_rows: Sequence[Row],
    team_fixture_rows: Sequence[Row],
    *,
    finality: Mapping[int, Row],
    contract: Row,
    contract_sha256: str,
) -> Row:
    """Score one contract-selected vintage on common finalized identities only."""
    gameweeks = validate_contract(pair, contract, contract_sha256)
    _require(set(finality) == set(gameweeks), "incomplete finality witness population")
    for gw in gameweeks:
        _require(
            finality[gw]["season"] == pair["season"] and finality[gw]["gw"] == gw,
            "finality identity mismatch",
        )
    teams = _index(team_fixture_rows, ("season", "gw", "fixture", "team_id"), gameweeks)
    players = _index(player_gameweek_rows, ("season", "gw", "code"), gameweeks)
    _require(
        all(any(key[1] == gw for key in players["primary"]) for gw in gameweeks)
        and all(any(key[1] == gw for key in teams["primary"]) for gw in gameweeks),
        "selected gameweek has no retained forecast population",
    )
    selectors: dict[int, str] = {}
    team_scored: dict[str, list[Row]] = {role: [] for role in ROLES}
    player_scored: dict[str, list[Row]] = {role: [] for role in ROLES}
    team_exclusions: list[Row] = []
    player_exclusions: list[Row] = []
    team_paired, player_paired = [], []
    for key, primary in sorted(teams["primary"].items()):
        shadow = teams["shadow"][key]
        for field in ("team_code", "opponent_team_id", "was_home", "kickoff_time"):
            _require(primary[field] == shadow[field], f"paired team {field} mismatch")
        selector = primary.get("selector")
        _require(isinstance(selector, str) and bool(selector), "missing primary selector")
        assert isinstance(selector, str)
        fixture = primary["fixture"]
        _require(
            fixture not in selectors or selectors[fixture] == selector,
            "contradictory fixture selectors",
        )
        selectors[fixture] = selector
        evaluated: dict[str, Row] = {}
        for role in ROLES:
            row = teams[role][key]
            pmf = _pmf(row["goals_for_distribution"])
            opposite = teams[role].get((*key[:3], row["opponent_team_id"]))
            _require(opposite is not None, "missing reciprocal team prediction")
            assert opposite is not None
            _require(
                opposite["opponent_team_id"] == row["team_id"]
                and opposite["was_home"] != row["was_home"],
                "team reciprocal identity mismatch",
            )
            opponent_pmf = _pmf(opposite["goals_for_distribution"])
            _require(
                row["probability_clean_sheet"] == opponent_pmf[0],
                "clean sheet differs from opponent PMF zero mass",
            )
            _require(
                row["season"] == pair["season"]
                and row["run_id"] == pair[f"{role}_run_id"]
                and row["artifact_sha256"] == pair[f"{role}_artifact_sha256"],
                "team vintage binding mismatch",
            )
            outcome = row.get("outcome")
            _require(outcome == shadow.get("outcome"), "paired team outcome mismatch")
            if (
                finality[row["gw"]]["official_final"] is not True
                or not outcome
                or outcome.get("attached") is not True
            ):
                continue
            _require(
                all(
                    type(outcome.get(k)) is int and outcome[k] >= 0
                    for k in ("goals_for", "goals_against")
                ),
                "invalid official team scores",
            )
            opposite_outcome = opposite.get("outcome")
            _require(
                opposite_outcome is not None and opposite_outcome.get("attached") is True,
                "missing reciprocal team outcome",
            )
            assert opposite_outcome is not None
            _require(
                outcome["goals_for"] == opposite_outcome["goals_against"]
                and outcome["goals_against"] == opposite_outcome["goals_for"],
                "official score reciprocity mismatch",
            )
            target = min(outcome["goals_for"], len(pmf) - 1)
            evaluated[role] = {
                "season": row["season"],
                "gw": row["gw"],
                "fixture": fixture,
                "team_id": row["team_id"],
                "selector": selector,
                "venue": "home" if row["was_home"] else "away",
                "distribution": pmf,
                "actual_goals": outcome["goals_for"],
                "actual_against": outcome["goals_against"],
                "scored_target": target,
                "expected_goals": math.fsum(i * p for i, p in enumerate(pmf)),
                "probability_clean_sheet": row["probability_clean_sheet"],
                "log_score": log_score(pmf, target),
                "crps": crps(pmf, target),
                "cs_brier": (row["probability_clean_sheet"] - int(outcome["goals_against"] == 0))
                ** 2,
            }
        if len(evaluated) == 2:
            for role in ROLES:
                team_scored[role].append(evaluated[role])
            team_paired.append(_pair_losses(evaluated["primary"], evaluated["shadow"], team=True))
        else:
            team_exclusions.append(
                {
                    "identity": list(key),
                    "reason": "OFFICIAL_GW_NOT_FINAL"
                    if finality[primary["gw"]]["official_final"] is not True
                    else "FINALIZED_TEAM_OUTCOME_UNAVAILABLE",
                }
            )
    for key, primary in sorted(players["primary"].items()):
        shadow = players["shadow"][key]
        for field in ("position", "team_id", "team_code", "fixture_ids"):
            _require(primary[field] == shadow[field], f"paired player {field} mismatch")
        _require(primary.get("outcome") == shadow.get("outcome"), "paired player outcome mismatch")
        fixtures = primary["fixture_ids"]
        _require(len(fixtures) == len(set(fixtures)), "duplicate player fixture leg")
        _require(
            primary["position"] in ("GK", "GKP", "DEF", "MID", "FWD"),
            "invalid registered player position",
        )
        for role in ROLES:
            row = players[role][key]
            _require(
                row["season"] == pair["season"]
                and row["run_id"] == pair[f"{role}_run_id"]
                and row["artifact_sha256"] == pair[f"{role}_artifact_sha256"],
                "player vintage binding mismatch",
            )
            pmf = _pmf(row["distribution"])
            _require(
                len(pmf) == 34 * len(fixtures) + 1,
                "player PMF support differs from stored fixture convolution",
            )
            _require(_finite(row["expected_points"]), "invalid retained xP")
        outcome = primary.get("outcome")
        reason = (
            "BLANK_GAMEWEEK"
            if not fixtures
            else "OFFICIAL_GW_NOT_FINAL"
            if finality[primary["gw"]]["official_final"] is not True
            else "FINALIZED_PLAYER_OUTCOME_UNAVAILABLE"
            if not outcome or outcome.get("attached") is not True
            else None
        )
        if reason is not None:
            player_exclusions.append(
                {
                    "identity": list(key),
                    "reason": reason,
                    "detail": outcome.get("reason") if outcome else None,
                }
            )
            continue
        assert outcome is not None
        legs = outcome.get("legs")
        _require(
            isinstance(legs, list)
            and len(legs) == len(fixtures)
            and sorted(r["fixture"] for r in legs) == sorted(fixtures),
            "finalized player legs differ from forecast",
        )
        _require(
            all(
                type(leg.get(field)) is int
                for leg in legs
                for field in ("total_points_as_recorded", "points_under_rules_2026_27")
            ),
            "incomplete finalized points",
        )
        signed = sum(leg["total_points_as_recorded"] for leg in legs)
        replayed = sum(leg["points_under_rules_2026_27"] for leg in legs)
        _require(
            outcome.get("total_points_as_recorded") == signed
            and outcome.get("points_under_rules_2026_27") == replayed,
            "finalized aggregate points mismatch",
        )
        proper_target = sum(min(34, max(0, leg["total_points_as_recorded"])) for leg in legs)
        _require(
            all(fixture in selectors for fixture in fixtures), "missing player fixture selector"
        )
        reasons = sorted({selectors[fixture] for fixture in fixtures})
        selector = (
            reasons[0]
            if len(reasons) == 1
            else "MIXED_SDP_PRIMARY_FALLBACK"
            if "SDP_PRIMARY" in reasons
            else "MULTIPLE_FALLBACK_REASONS"
        )
        evaluated = {}
        for role in ROLES:
            row = players[role][key]
            scored = _with_losses(
                {
                    **row,
                    "signed_target": signed,
                    "scored_target": proper_target,
                    "points_under_rules_2026_27": replayed,
                    "coarsened_fixture_leg_count": sum(
                        not 0 <= leg["total_points_as_recorded"] <= 34 for leg in legs
                    ),
                    "selector": selector,
                    "selector_reasons": reasons,
                    "cold_start_player": row.get("cold_start_player"),
                    "transferred_no_rescale": row.get("transferred_no_rescale"),
                    "promoted_team": None,
                    "venue": None,
                }
            )
            player_scored[role].append(scored)
            evaluated[role] = scored
        player_paired.append(_pair_losses(evaluated["primary"], evaluated["shadow"]))
    witness = [finality[gw] for gw in gameweeks]
    selected_players = [r for r in player_gameweek_rows if r["gw"] in gameweeks]
    selected_teams = [r for r in team_fixture_rows if r["gw"] in gameweeks]
    outcome_rows = [
        {"grain": grain, "identity": [r[f] for f in fields], "outcome": r.get("outcome")}
        for grain, rows, fields in (
            ("player_gameweek", players["primary"].values(), ("season", "gw", "code")),
            ("team_fixture", teams["primary"].values(), ("season", "gw", "fixture", "team_id")),
        )
        for r in rows
    ]
    finalized = [gw for gw in gameweeks if finality[gw]["official_final"] is True]
    report: Row = {
        "schema": SCHEMA,
        "status": "PENDING"
        if not finalized
        else "COMPLETE"
        if len(finalized) == len(gameweeks)
        and not team_exclusions
        and not any(r["reason"] != "BLANK_GAMEWEEK" for r in player_exclusions)
        else "PARTIAL_FINALIZED_EVIDENCE",
        "reason": "NO_OFFICIALLY_FINALIZED_GAMEWEEKS" if not finalized else None,
        "checkpoint_id": contract["checkpoint_id"],
        "vintage_policy": contract["vintage_policy"],
        "gameweeks": list(gameweeks),
        "finalized_gameweeks": finalized,
        "pair": pair,
        "scoring": SCORING,
        "provenance": {
            "contract_sha256": contract_sha256,
            "contract": contract,
            "pair_sha256": content_hash(pair),
            "finality_sha256": content_hash(witness),
            "outcomes_sha256": content_hash(sorted(outcome_rows, key=canonical_bytes)),
            "player_projection_sha256": content_hash(sorted(selected_players, key=canonical_bytes)),
            "team_projection_sha256": content_hash(sorted(selected_teams, key=canonical_bytes)),
            "metric_source_sha256": _metric_source_hashes(),
        },
        "finality": witness,
        "players": {
            role: {
                **_point_slices(player_scored[role]),
                "rankings": _rankings(player_scored[role]),
                "expected_points_scope": "raw_unadjusted",
                "availability_adjusted": {
                    "status": "NOT_SCORED",
                    "metrics": None,
                    "reason": "Adjusted scoring is not implemented; raw xP/PMFs are scored.",
                },
                "forensic_component_attribution": {
                    "status": "UNAVAILABLE",
                    "labels": None,
                    "reason": "No retained component sidecars; residual categories unavailable.",
                },
                "recorded_vs_replayed_disagreement_rows": sum(
                    r["signed_target"] != r["points_under_rules_2026_27"]
                    for r in player_scored[role]
                ),
                "coarsened_fixture_leg_count": sum(
                    r["coarsened_fixture_leg_count"] for r in player_scored[role]
                ),
                "components": {
                    "status": "UNAVAILABLE",
                    "reason": "Retained pairs have no component PMF sidecars; "
                    "no inference reconstructed.",
                    "minutes": None,
                    "goals": None,
                    "assists": None,
                    "player_clean_sheet": None,
                    "saves": None,
                    "defensive_contribution": None,
                    "bonus": None,
                },
            }
            for role in ROLES
        },
        "teams": {
            role: {
                "overall": _team_summary(team_scored[role]),
                "by_gameweek": {
                    str(gw): _team_summary([r for r in team_scored[role] if r["gw"] == gw])
                    for gw in gameweeks
                },
                "by_primary_selector": {
                    s: _team_summary([r for r in team_scored[role] if r["selector"] == s])
                    for s in sorted(set(selectors.values()))
                },
                "by_venue": {
                    v: _team_summary([r for r in team_scored[role] if r["venue"] == v])
                    for v in ("home", "away")
                },
            }
            for role in ROLES
        },
        "paired": {
            "players": {
                **_paired_slices(player_paired),
                "uncertainty": _five_gw_uncertainty(
                    player_paired,
                    gameweeks=gameweeks,
                    finalized=finalized,
                    vintage_policy=contract["vintage_policy"],
                ),
            },
            "teams": {
                **_paired_slices(team_paired, team=True),
                "uncertainty": _five_gw_uncertainty(
                    team_paired,
                    gameweeks=gameweeks,
                    finalized=finalized,
                    vintage_policy=contract["vintage_policy"],
                    team=True,
                ),
            },
        },
        "operations": {
            "forecast_fixture_count": len(selectors),
            "selector_reason_counts_fixtures": dict(sorted(Counter(selectors.values()).items())),
            "sdp_primary_fixtures": sum(s == "SDP_PRIMARY" for s in selectors.values()),
            "fallback_fixtures": sum(s != "SDP_PRIMARY" for s in selectors.values()),
            "player_pairs_expected": len(players["primary"]),
            "player_pairs_scored": len(player_paired),
            "team_pairs_expected": len(teams["primary"]),
            "team_pairs_scored": len(team_paired),
            "n_finalized_gameweeks": len(finalized),
            "n_scored_player_gameweeks": len({r["gw"] for r in player_paired}),
            "n_scored_team_gameweeks": len({r["gw"] for r in team_paired}),
        },
        "exclusions": {"players": player_exclusions, "teams": team_exclusions},
        "limitations": [
            "One explicitly selected vintage per report; fixed-origin and rolling stay separate.",
            "Proper target sums per-leg 0..34-coarsened official points. "
            "Signed errors and ranks use uncoarsened official totals.",
            "The unchanged 1e-12 log floor, zero support and coarsening remain visible.",
            "Rankings use common finalized scored rows; missing outcomes reduce their population.",
            "No promotion gate, model change, outcome correction or causal attribution.",
            "Corrections rejected by the immutable ledger are blocked, never substituted here.",
        ],
    }
    report["report_version"] = content_hash(report)
    return report


def load_checkpoint_pair(
    con: duckdb.DuckDBPyConnection, *, contract: Row, contract_sha256: str
) -> Row:
    """Validate the selected prediction vintage without reading any outcome."""
    pair = load_pair(con, str(contract.get("prediction_id", "")))
    _require(pair is not None, "checkpoint pair not registered")
    assert pair is not None
    validate_contract(pair, contract, contract_sha256)
    for role in ROLES:
        manifest = con.execute(
            "SELECT commit_sha, worktree_clean, fixture_points_support_max "
            "FROM ledger_forecast_run WHERE run_id = ?",
            [pair[f"{role}_run_id"]],
        ).fetchone()
        _require(
            manifest is not None
            and manifest[0] == contract["forecast_emitter_sha"]
            and manifest[1] is True
            and manifest[2] == SCORING["fixture_support_max"],
            "retained forecast emitter, clean-state or scoring support mismatch",
        )
    return pair


def build_checkpoint(con: duckdb.DuckDBPyConnection, *, contract: Row, contract_sha256: str) -> Row:
    """Read an already registered pair and existing authoritative finalized outcomes only."""
    pair = load_checkpoint_pair(con, contract=contract, contract_sha256=contract_sha256)
    gameweeks = tuple(contract["gameweeks"])
    finality = {gw: finality_witness(con, pair["season"], gw) for gw in gameweeks}
    players = pair_player_gameweek_rows(con, pair)
    metadata: dict[tuple[str, str, int, int], Row] = {}
    for role in ROLES:
        rows = con.execute(
            "SELECT season, gw, code, web_name, cold_start_player, transferred_no_rescale, "
            "availability_status, availability_multiplier "
            "FROM ledger_prediction_player_gameweek WHERE run_id = ?",
            [pair[f"{role}_run_id"]],
        ).fetchall()
        for row in rows:
            metadata[role, str(row[0]), int(row[1]), int(row[2])] = {
                "web_name": row[3],
                "cold_start_player": row[4],
                "transferred_no_rescale": row[5],
                "availability_status": row[6],
                "availability_multiplier": row[7],
            }
    for prediction in players:
        prediction.update(
            metadata[prediction["role"], prediction["season"], prediction["gw"], prediction["code"]]
        )
    return score_pair_report(
        pair,
        players,
        pair_team_fixture_rows(con, pair),
        finality=finality,
        contract=contract,
        contract_sha256=contract_sha256,
    )
