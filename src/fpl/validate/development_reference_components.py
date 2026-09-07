"""CURRENT component arithmetic over the explicitly retrospective minutes reference.

No CLI, forecast writer, production flag or minutes refit. The pinned cache loader
validates every retained row before exposing a fold. Only the small orchestration
nested inside the prospective job is repeated; estimators/allocators/composer are
the unchanged implementations. Synthetic tests compare their exact inputs/outputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import duckdb
import polars as pl

from fpl.config import load_phase2_evaluation, load_phase3_evaluation, load_scoring_rules
from fpl.jobs import prospective_points_v1 as prospective
from fpl.jobs.competitive_participation_pilot import file_sha256
from fpl.models.attacking_assists_baselines import AssistHistoryRow
from fpl.models.attacking_baselines import PlayerHistoryRow, TargetRowProjection
from fpl.models.attacking_baselines import poisson_pmf as goal_poisson_pmf
from fpl.models.attacking_v2 import _RosterEntry, mean_trailing_signal
from fpl.models.attacking_v3 import allocate_minutes_gated_rates
from fpl.models.bps_bonus import BpsSimConfig, fit_residual_model
from fpl.models.defensive_contribution_v1 import DcHistoryRow
from fpl.models.gk_saves_v1 import GkSavesHistoryRow
from fpl.models.points_composition import (
    DEFAULT_MAX_POINTS_FULL,
    MEASURED_CONCEDED_EXPOSURE,
    BpsExactLookup,
    ComponentDistributions,
    ComposedPlayer,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    conditional_rate,
    representative_minutes,
)
from fpl.types import Position
from fpl.validate.baselines import TrailingGoalsAttackDefence
from fpl.validate.metrics import Distribution, poisson_pmf
from fpl.validate.minutes_baselines import MinuteBins, MinutesDistribution, TargetRow
from fpl.validate.points_harness import TARGET_RULESET, default_component_suite
from fpl.validate.points_harness_v3 import (
    DEFAULT_DRAWS,
    _fixture_seed,
    _residual_prediction,
    _residual_training_rows,
)
from fpl.validate.retrospective_minutes_proxy import EVIDENCE_CLASS
from fpl.validate.retrospective_minutes_proxy import NAME as MINUTES_NAME

NAME = "retrospective_current_component_proxy_v1"
MANIFEST = "results/retrospective_minutes_proxy_cache_manifest.json"
MANIFEST_SHA256 = "5b813d58b71bad97a5c81774aaf70c0bca5f4e0e3bcd518e6f26e0acfea19bac"
CACHE_HEAD = "eea2381c8395af0b136782c515d0e34181cc462c"
EXPECTED_COUNTS = {
    "2023-24": 29725,
    "2024-25": 27283,
    "2025-26": 29747,
    "rows": 86755,
    "price_proxy_rows": 821,
}
SOURCE_FILES = (
    "src/fpl/validate/development_reference_components.py",
    "docs/development-reference-components.md",
    "config/phase2_evaluation.yaml",
    "config/phase3_evaluation.yaml",
    "config/phase3_stage_c_assists_evaluation.yaml",
    "config/scoring_2026_27.yaml",
    "src/fpl/config.py",
    "src/fpl/types.py",
    "src/fpl/jobs/prospective_points_v1.py",
    "src/fpl/models/attacking_baselines.py",
    "src/fpl/models/attacking_assists_baselines.py",
    "src/fpl/models/attacking_v1.py",
    "src/fpl/models/attacking_assists_v1.py",
    "src/fpl/models/attacking_v2.py",
    "src/fpl/models/attacking_v3.py",
    "src/fpl/models/gk_saves_v1.py",
    "src/fpl/models/defensive_contribution_v1.py",
    "src/fpl/models/bps_bonus.py",
    "src/fpl/models/points_composition.py",
    "src/fpl/models/scoring.py",
    "src/fpl/validate/baselines.py",
    "src/fpl/validate/metrics.py",
    "src/fpl/validate/points_harness.py",
    "src/fpl/validate/points_harness_v3.py",
)


def component_source_fingerprints(root: Path) -> dict[str, str]:
    """Additional transitive component pins, alongside the retained minutes manifest."""
    return {name: file_sha256(root / name) for name in SOURCE_FILES}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("reference timestamps must be timezone aware")
    return result


def _pmf(value: Sequence[float]) -> MinutesDistribution:
    if len(value) != 4 or any(isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in value):
        raise ValueError("invalid four-bin minutes PMF")
    if not math.isclose(math.fsum(value), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("minutes PMF does not sum to one")
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


@dataclass(frozen=True, slots=True)
class ReferenceMinutesRow:
    target: TargetRow
    team_code: int
    minutes: MinutesDistribution
    cold_start: bool
    price_proxy_dependent: bool
    # Retain the complete consulted-price/selector lineage immutably.
    selector_provenance_json: str


@dataclass(frozen=True, slots=True)
class ValidatedMinutesControlFold:
    season: str
    gw: int
    as_of: datetime
    rows: tuple[ReferenceMinutesRow, ...]
    database_sha256: str
    manifest_sha256: str
    fold_sha256: str
    metadata_json: str
    # Only synthetic in-memory tests omit this; real reference folds are bound to a file.
    database_path: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedMinutesControlCache:
    folds: tuple[ValidatedMinutesControlFold, ...]
    provenance_json: str


def _decode_fold(
    payload: dict[str, Any], *, database_hash: str, manifest_hash: str, fold_hash: str
) -> ValidatedMinutesControlFold:
    as_of = _time(payload["as_of"])
    maximum = payload["maximum_prior_kickoff"]
    if maximum is not None and _time(maximum) >= as_of:
        raise ValueError("reference prior event reaches target cutoff")
    if payload["same_gw_history_rows"] != 0 or payload["future_history_rows"] != 0:
        raise ValueError("reference cache reports leakage")
    rows = []
    for row in payload["rows"]:
        raw = row["target"]
        if set(raw) != set(TargetRow.__dataclass_fields__):
            raise ValueError("target must retain the exact nine-field outcome-free projection")
        target = TargetRow(
            **{
                **raw,
                "position": Position(raw["position"]),
                "kickoff_time": _time(raw["kickoff_time"]),
            }
        )
        minutes = _pmf(row["minutes_distribution"])
        _pmf(row["raw_v3_distribution"])
        lineage = row["selector_provenance"]
        selector = lineage["selector"]
        if (
            lineage["comparator"] != MINUTES_NAME
            or lineage["evidence_class"] != EVIDENCE_CLASS
            or lineage["promotion_permitted"] is not False
            or selector["historical_deadline_validity_established"] is not False
            or selector["selector_arithmetic_reproduced"] is not True
            or selector["blockers"]
            or _pmf(selector["distribution"]) != minutes
            or lineage["proxy_dependent"] is not row["price_proxy_dependent"]
            or lineage["cold_start"] is not row["cold_start"]
        ):
            raise ValueError("reference selector evidence/PMF is inconsistent")
        if row["price_proxy_dependent"] and (
            not row["cold_start"]
            or not lineage["archive_price_lineage"]
            or lineage["database_sha256"] != database_hash
        ):
            raise ValueError("price-dependent row lacks its exact source lineage")
        rows.append(
            ReferenceMinutesRow(
                target,
                row["team_code"],
                minutes,
                row["cold_start"],
                row["price_proxy_dependent"],
                _json(lineage),
            )
        )
    fold = ValidatedMinutesControlFold(
        payload["season"],
        payload["gw"],
        as_of,
        tuple(rows),
        database_hash,
        manifest_hash,
        fold_hash,
        _json({k: v for k, v in payload.items() if k != "rows"}),
    )
    _validate_rows(fold)
    if min(r.target.kickoff_time for r in rows) != as_of:
        raise ValueError("archive reference cutoff is not the first target kickoff")
    if [(r.target.fixture, r.target.code) for r in rows] != sorted(
        (r.target.fixture, r.target.code) for r in rows
    ):
        raise ValueError("archive reference roster is not in canonical fixture/code order")
    return fold


def read_minutes_control_cache(
    directory: Path, *, db: Path, root: Path
) -> ValidatedMinutesControlCache:
    """Read ALL 114 pinned fold files/86,755 rows, never fit or silently accept a subset."""
    directory, db, root = directory.resolve(), db.resolve(), root.resolve()
    manifest_path = directory / "manifest.json"
    if (
        file_sha256(manifest_path) != MANIFEST_SHA256
        or file_sha256(root / MANIFEST) != MANIFEST_SHA256
    ):
        raise ValueError("retained minutes manifest differs from pinned completed reference")
    manifest = json.loads(manifest_path.read_bytes())
    provenance = manifest["provenance"]
    if (
        manifest["completed"] is not True
        or provenance["git_head"] != CACHE_HEAD
        or provenance["comparator"] != MINUTES_NAME
        or provenance["evidence_class"] != EVIDENCE_CLASS
        or provenance["worktree_clean"] is not True
        or provenance["historical_deadline_validity"] is not False
        or provenance["new_model_candidate_scoring"] is not False
    ):
        raise ValueError("reference identity/provenance does not match the completed cache")
    if json.loads((directory / "provenance.json").read_bytes()) != provenance:
        raise ValueError("cache provenance file and completed manifest disagree")
    database_hash = provenance["database_sha256"]
    if Path(str(db) + ".wal").exists() or file_sha256(db) != database_hash:
        raise ValueError("reference database hash/WAL differs")
    for name, expected in provenance["source_sha256"].items():
        if file_sha256(root / name) != expected:
            raise ValueError(f"reference source changed: {name}")
    folds = []
    counts: Counter[str] = Counter()
    keys = set()
    for entry in manifest["folds"]:
        path = (directory / entry["file"]).resolve()
        if path.parent != directory or path.name != f"{entry['season']}-gw{entry['gw']:02d}.json":
            raise ValueError("cache fold path/identity escapes the declared directory")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError(f"cache fold hash differs: {path.name}")
        fold = _decode_fold(
            json.loads(body),
            database_hash=database_hash,
            manifest_hash=MANIFEST_SHA256,
            fold_hash=entry["sha256"],
        )
        key = fold.season, fold.gw
        if key in keys or key != (entry["season"], entry["gw"]) or len(fold.rows) != entry["rows"]:
            raise ValueError("cache fold identities/counts differ")
        keys.add(key)
        counts[fold.season] += len(fold.rows)
        counts["rows"] += len(fold.rows)
        counts["price_proxy_rows"] += sum(r.price_proxy_dependent for r in fold.rows)
        folds.append(replace(fold, database_path=str(db)))
    expected_keys = {
        (season, gw) for season in EXPECTED_COUNTS if season[:4].isdigit() for gw in range(1, 39)
    }
    if (
        keys != expected_keys
        or dict(counts) != EXPECTED_COUNTS
        or manifest["counts"] != EXPECTED_COUNTS
    ):
        raise ValueError("complete reference population/price-proxy counts differ")
    return ValidatedMinutesControlCache(tuple(folds), _json(provenance))


def _validate_rows(fold: ValidatedMinutesControlFold) -> None:
    if fold.as_of.utcoffset() is None or not fold.rows:
        raise ValueError("reference requires a nonempty timezone-aware GW batch")
    keys = set()
    clubs: dict[int, tuple[int, Position]] = {}
    sides: dict[int, set[tuple[int, int, bool, datetime]]] = defaultdict(set)
    team_map: dict[int, int] = {}
    for row in fold.rows:
        t = row.target
        if type(t) is not TargetRow or (t.season, t.gw) != (fold.season, fold.gw):
            raise ValueError("reference target is not the exact safe GW projection")
        if t.kickoff_time.utcoffset() is None or t.kickoff_time < fold.as_of:
            raise ValueError("target precedes cutoff")
        if (t.fixture, t.code) in keys:
            raise ValueError("duplicate target player-fixture")
        keys.add((t.fixture, t.code))
        club = row.team_code, t.position
        if t.code in clubs and clubs[t.code] != club:
            raise ValueError("same-GW club/position identity conflict")
        clubs[t.code] = club
        if t.team_id in team_map and team_map[t.team_id] != row.team_code:
            raise ValueError("season-qualified team map is ambiguous")
        team_map[t.team_id] = row.team_code
        sides[t.fixture].add((t.team_id, t.opponent_team_id, t.was_home, t.kickoff_time))
        _pmf(row.minutes)
        if row.price_proxy_dependent and not row.cold_start:
            raise ValueError("established player's own minutes cannot depend on price proxy")
    if len(set(team_map.values())) != len(team_map):
        raise ValueError("stable team identity is not one-to-one")
    for fixture_sides in sides.values():
        if len(fixture_sides) != 2:
            raise ValueError("joint composition requires both complete declared club rosters")
        a, b = tuple(fixture_sides)
        if a != (b[1], b[0], not b[2], b[3]) or a[0] == a[1]:
            raise ValueError("fixture sides/kickoff do not reconcile reciprocally")


@dataclass(frozen=True, slots=True)
class ReferencePlayerComponents:
    target: TargetRow
    team_code: int
    player: FixturePlayer
    cold_start: bool
    direct_price_proxy: bool
    team_price_proxy_codes: tuple[int, ...]
    fixture_price_proxy_codes: tuple[int, ...]
    selector_provenance_json: str
    # Raw signals remain nullable; the incumbent's declared cold prior is separate.
    raw_goal_signal: float | None
    raw_assist_signal: float | None
    resolved_goal_signal: float
    resolved_assist_signal: float
    unconditional_goal_rate: float | None
    unconditional_assist_rate: float | None
    stage_a_league_average: bool


@dataclass(frozen=True, slots=True)
class DevelopmentReferenceComponents:
    season: str
    gw: int
    as_of: datetime
    rows: tuple[ReferencePlayerComponents, ...]
    team_scored: tuple[tuple[int, int, Distribution], ...]
    diagnostics_json: str
    provenance_json: str
    identity: str = NAME
    evidence_class: str = EVIDENCE_CLASS
    promotion_permitted: bool = False


def build_reference_components(
    con: duckdb.DuckDBPyConnection, fold: ValidatedMinutesControlFold
) -> DevelopmentReferenceComponents:
    """Reproduce default components; preserve supplied roster order until the composer.

    Archive callers use ONLY folds from read_minutes_control_cache. Synthetic tests
    supply an explicit captured-2026 registry order to compare the unchanged live job.
    No current-target archive outcome is read. Minutes are never refitted here.
    """
    _validate_rows(fold)
    as_of, season = fold.as_of, fold.season
    files = [str(r[2]) for r in con.execute("PRAGMA database_list").fetchall() if r[2]]
    expected_files = [] if fold.database_path is None else [str(Path(fold.database_path).resolve())]
    if [str(Path(p).resolve()) for p in files] != expected_files:
        raise ValueError("component connection is not the validated reference database")
    # All reused component helpers read prior kickoff only. Reject a malformed
    # historical batch that would make an already-played target-GW row eligible.
    for table in ("mart_fact_player_fixture", "mart_fact_team_match"):
        count = con.execute(
            f"SELECT count(*) FROM {table} WHERE season=? AND gw=? AND kickoff_time < ?",
            [season, fold.gw, as_of],
        ).fetchone()
        if count is None or count[0]:
            raise ValueError("target-GW observations would enter current component helpers")
    rules = load_scoring_rules(TARGET_RULESET)
    bps = rules.bps
    if bps is None:
        raise ValueError("full-points reference requires the existing BPS rules")
    suite = default_component_suite()
    clubs = {r.target.code: r.team_code for r in fold.rows}
    team_map = {r.target.team_id: r.team_code for r in fold.rows}
    frame = (
        con.execute(
            """SELECT season,gw,fixture,strftime(kickoff_time,'%Y-%m-%dT%H:%M:%SZ') kickoff_time,
                  code,position,COALESCE(goals_scored,0) goals,COALESCE(assists,0) assists,
                  minutes,saves,goals_conceded,defensive_contribution,
                  expected_goals,expected_assists,creativity
           FROM mart_fact_player_fixture WHERE minutes IS NOT NULL AND kickoff_time < ?
           ORDER BY kickoff_time,season,fixture,code""",
            [as_of],
        )
        .pl()
        .sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)
    )
    goals_history, assists_history, saves_history, dc_history = [], [], [], []
    for r in frame.iter_rows(named=True):
        position = Position.from_archive_label(r["position"])
        goals_history.append(
            PlayerHistoryRow(
                r["season"],
                r["gw"],
                r["fixture"],
                r["kickoff_time"],
                r["code"],
                position,
                r["goals"],
                r["expected_goals"],
            )
        )
        assists_history.append(
            AssistHistoryRow(
                r["season"],
                r["gw"],
                r["fixture"],
                r["kickoff_time"],
                r["code"],
                position,
                r["assists"],
                r["minutes"],
                r["expected_assists"],
                r["creativity"],
            )
        )
        saves_history.append(
            GkSavesHistoryRow(position, r["minutes"], r["saves"], r["goals_conceded"])
        )
        if r["defensive_contribution"] is not None:
            dc_history.append(
                DcHistoryRow(r["code"], position, r["minutes"], r["defensive_contribution"])
            )
    goals_model = suite.fit_goals(goals_history)
    assists_model = suite.fit_assists(assists_history)
    saves_model = suite.fit_saves(saves_history)
    dc_model = suite.fit_dc(dc_history, rules.defensive_contribution.thresholds)
    bps_config = BpsSimConfig()
    residual_rows = _residual_training_rows(con, as_of)
    residual = fit_residual_model(
        residual_rows,
        bps,
        prior_strength=bps_config.prior_strength,
        trailing_window=bps_config.trailing_window,
        ridge_lambda=bps_config.ridge_lambda,
        sigma_floor=bps_config.sigma_floor,
        sd_floor=bps_config.sd_floor,
        minimum_position_rows=bps_config.minimum_position_rows,
    )
    schedule_rows = {}
    for row in fold.rows:
        t = row.target
        schedule_rows[(t.fixture, t.team_id)] = {
            "fixture": t.fixture,
            "gw": t.gw,
            "team_id": t.team_id,
            "opponent_team_id": t.opponent_team_id,
            "was_home": t.was_home,
        }
    stage_a = TrailingGoalsAttackDefence()
    team_scored, league_conceded = prospective.prospective_team_scored(
        con,
        season=season,
        as_of=as_of,
        team_map=team_map,
        schedule=pl.DataFrame(list(schedule_rows.values())),
        model=stage_a,
    )
    known_team_codes = stage_a.known_team_codes()
    league_pmf = poisson_pmf(max(league_conceded, 1e-6))
    covered = frozenset(load_phase3_evaluation().xg_signal_policy.xg_covered_seasons)
    goal_kind = prospective.resolve_share_signal_kind(season, covered, "auto")
    assist_kind = prospective.resolve_assist_signal_kind(season, covered, "auto")
    attack, attack_prior = prospective.appeared_attack_signals(
        con, as_of, kind=goal_kind, current_club=clubs
    )
    assists, assist_prior = prospective.appeared_assist_signals(
        con, as_of, kind=assist_kind, current_club=clubs
    )
    goal_signals = {
        code: mean_trailing_signal(rows, kind=goal_kind, window=5) for code, rows in attack.items()
    }
    assist_slot = "expected_goals" if assist_kind == "expected_assists" else "threat"
    assist_signals = {
        code: mean_trailing_signal(rows, kind=assist_slot, window=5)
        for code, rows in assists.items()
    }
    assist_rate = prospective.league_assist_rate(con, as_of)
    ict = prospective.trailing_ict(con, as_of, current_club=clubs)
    teams: dict[tuple[int, int], list[ReferenceMinutesRow]] = defaultdict(list)
    fixture_proxies: dict[int, set[int]] = defaultdict(set)
    for row in fold.rows:
        teams[(row.target.fixture, row.team_code)].append(row)
        if row.price_proxy_dependent:
            fixture_proxies[row.target.fixture].add(row.target.code)
    result = []
    for (fixture, team_code), roster in teams.items():
        own = team_scored.get((fixture, team_code))
        lambda_team = None if own is None else sum(i * p for i, p in enumerate(own))
        p_play = {r.target.code: max(0.0, min(1.0, 1 - r.minutes[0])) for r in roster}
        goal_roster, assist_roster = [], []
        for row in roster:
            code = row.target.code
            goal_signal, assist_signal = goal_signals.get(code), assist_signals.get(code)
            goal_roster.append(
                _RosterEntry(
                    code, attack_prior if goal_signal is None else goal_signal, goal_signal is None
                )
            )
            assist_roster.append(
                _RosterEntry(
                    code,
                    assist_prior if assist_signal is None else assist_signal,
                    assist_signal is None,
                )
            )
        goal_rates = (
            {}
            if lambda_team is None
            else allocate_minutes_gated_rates(goal_roster, p_play, lambda_team, minutes_gating=True)
        )
        assist_rates = (
            {}
            if lambda_team is None
            else allocate_minutes_gated_rates(
                assist_roster, p_play, lambda_team * assist_rate, minutes_gating=True
            )
        )
        team_proxies = tuple(sorted(r.target.code for r in roster if r.price_proxy_dependent))
        for row, goal_entry, assist_entry in zip(roster, goal_roster, assist_roster, strict=True):
            t = row.target
            target = TargetRowProjection(
                t.season,
                t.gw,
                t.fixture,
                t.kickoff_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                t.code,
                t.position,
                t.team_id,
                t.opponent_team_id,
                t.was_home,
            )
            goals, assist_pmf = goals_model.predict(target), assists_model.predict(target)
            g_rate, a_rate = None, None
            if lambda_team is not None:
                g_rate, a_rate = goal_rates[t.code][0], assist_rates[t.code][0]
                goals = goal_poisson_pmf(conditional_rate(g_rate, p_play[t.code], cap=lambda_team))
                assist_pmf = goal_poisson_pmf(
                    conditional_rate(a_rate, p_play[t.code], cap=lambda_team * assist_rate)
                )
            opponent_code = team_map[t.opponent_team_id]
            conceded = team_scored.get((fixture, opponent_code))
            fallback = prospective._stage_a_uses_league_average(
                team_code=team_code,
                opponent_code=opponent_code,
                known_team_codes=known_team_codes,
                opponent_conceded_unresolved=conceded is None,
            )
            if conceded is None:
                conceded = league_pmf
            influence, creativity = ict.get(t.code, (0.0, 0.0))
            player = FixturePlayer(
                t.code,
                ComponentDistributions(
                    t.position,
                    row.minutes,
                    goals,
                    assist_pmf,
                    conceded,
                    saves_model.predict(t.position, sum(i * p for i, p in enumerate(conceded))),
                    dc_model.predict(t.code, t.position),
                ),
                _residual_prediction(
                    residual,
                    code=t.code,
                    position=t.position.value,
                    influence=influence,
                    creativity=creativity,
                ),
                residual.sigma(t.position.value),
            )
            result.append(
                ReferencePlayerComponents(
                    t,
                    team_code,
                    player,
                    row.cold_start,
                    row.price_proxy_dependent,
                    team_proxies if lambda_team is not None else (),
                    tuple(sorted(fixture_proxies[fixture])),
                    row.selector_provenance_json,
                    goal_signals.get(t.code),
                    assist_signals.get(t.code),
                    goal_entry.signal,
                    assist_entry.signal,
                    g_rate,
                    a_rate,
                    fallback,
                )
            )
    by_key = {(r.target.fixture, r.target.code): r for r in result}
    ordered = tuple(by_key[(r.target.fixture, r.target.code)] for r in fold.rows)
    return DevelopmentReferenceComponents(
        season,
        fold.gw,
        as_of,
        ordered,
        tuple((fixture, team, pmf) for (fixture, team), pmf in sorted(team_scored.items())),
        _json(
            {
                "training_rows": frame.height,
                "residual_training_rows": len(residual_rows),
                "goal_signal": goal_kind,
                "assist_signal": assist_kind,
                "assist_conversion": assist_rate,
                "goal_cold_prior": attack_prior,
                "assist_cold_prior": assist_prior,
                "stage_a_parameters": stage_a.parameters(),
                "component_parameters": {
                    model.name: cast(Any, model).parameters()
                    for model in (goals_model, assists_model, saves_model, dc_model)
                },
                "bps_config": asdict(bps_config),
                "bps_position_models": {k: asdict(v) for k, v in residual.by_position.items()},
                "bps_fallback_model": asdict(residual.fallback),
                "maximum_prior_kickoff": frame["kickoff_time"].max() if frame.height else None,
                "minutes_refitted": False,
                "same_gw_history_rows": 0,
            }
        ),
        _json(
            {
                "database_sha256": fold.database_sha256,
                "minutes_manifest_sha256": fold.manifest_sha256,
                "minutes_fold_sha256": fold.fold_sha256,
                "minutes_fold_metadata": json.loads(fold.metadata_json),
                "evidence_class": EVIDENCE_CLASS,
                "historical_deadline_validity": False,
                "roster_policy": "declared_archive_population_not_historical_live_registry",
                "component_identity": NAME,
                "defaults": {
                    "attacking": "v3",
                    "assists": "coupled",
                    "appearance": "seasonal",
                    "share_signal": "auto",
                    "draws": DEFAULT_DRAWS,
                    "base_seed": prospective.BASE_SEED,
                    "max_points": DEFAULT_MAX_POINTS_FULL,
                    "conceded_exposure": MEASURED_CONCEDED_EXPOSURE,
                },
            }
        ),
    )


def compose_reference_fixture(
    reference: DevelopmentReferenceComponents, fixture: int
) -> tuple[ComposedPlayer, ...]:
    """Unchanged joint fixture composer, never a per-player independent substitute."""
    if (
        type(reference) is not DevelopmentReferenceComponents
        or reference.identity != NAME
        or reference.evidence_class != EVIDENCE_CLASS
        or reference.promotion_permitted
    ):
        raise ValueError("only the explicit development component reference is accepted")
    players = [r.player for r in reference.rows if r.target.fixture == fixture]
    if not players:
        raise ValueError("fixture absent from reference")
    rules = load_scoring_rules(TARGET_RULESET)
    if rules.bps is None:
        raise ValueError("BPS rules missing")
    minutes = representative_minutes(MinuteBins.from_config(load_phase2_evaluation()).ranges)
    return tuple(
        compose_fixture_full_points(
            players,
            PointsLookup(rules, bin_minutes=minutes),
            BpsExactLookup(
                rules.bps,
                bin_minutes=minutes,
                clean_sheet_minimum_minutes=rules.clean_sheets.minimum_minutes,
            ),
            ExtraScoring(
                rules.saves.unit,
                rules.defensive_contribution.points,
                rules.saves.positions,
                frozenset(rules.defensive_contribution.thresholds),
            ),
            fixture_seed=_fixture_seed(prospective.BASE_SEED, reference.season, fixture),
            draws=DEFAULT_DRAWS,
            max_points=DEFAULT_MAX_POINTS_FULL,
            conceded_exposure=MEASURED_CONCEDED_EXPOSURE,
        )
    )
