"""Observe the unchanged player pipeline for the bounded GW1--3 validation audit.

This module neither reads target outcomes nor implements a predictor. The scoped
observers return the original fitted model and composed objects unchanged. Run
in a dedicated validation process: the production job's module bindings are
temporarily observed, then restored, including when an assertion fails.
"""

from __future__ import annotations

import hashlib
import pickle
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import duckdb

from fpl.artifacts.prospective_points import artifact_bytes
from fpl.features.pit import AsOf
from fpl.jobs import prospective_points_v1 as job
from fpl.models.points_composition import (
    BpsExactLookup,
    ComposedPlayer,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
)
from fpl.models.sdp_environment import canonical
from fpl.validate.minutes_baselines import HistoryRow
from fpl.validate.points_harness import MinutesPredictor, default_component_suite
from fpl.validate.points_harness_v3 import _fixture_seed
from fpl.validate.sdp_counterfactual import (
    FrozenCounterfactualInputs,
    bind_counterfactual_selector,
)

BASE_SEED = 202627
DRAWS = 2000
MAX_POINTS = 34
INVALID = "INVALIDATED_BY_IMPLEMENTATION_BUG"


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(f"{INVALID}: {detail}")


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def replay_gameweek(
    con: duckdb.DuckDBPyConnection,
    *,
    repo: Path,
    db_path: Path,
    season: str,
    gw: int,
    cutoff: datetime,
    fixture_gameweeks: Mapping[int, int],
    counterfactual_inputs: FrozenCounterfactualInputs | None = None,
) -> dict[str, Any]:
    """Return exact paired predictions and artifacts, without labels or scores.

    The existing minutes V3 fitter still performs its own historical parameter
    selection. Observing that call is not a new search or a replacement fitter.
    Real artifact creation retains the job's truthful clean-worktree requirement.
    """
    AsOf(cutoff)
    _require(season == "2026-27" and type(gw) is int and gw in (1, 2, 3), "bounded season/GW")
    _require(
        all(
            type(k) is int and k > 0 and type(v) is int and v > 0
            for k, v in fixture_gameweeks.items()
        ),
        "fixture/gameweek identity",
    )
    fixtures = {fixture for fixture, event in fixture_gameweeks.items() if event == gw}
    _require(bool(fixtures), "empty target fixture population")
    seed_map = {_fixture_seed(BASE_SEED, season, fixture): fixture for fixture in fixtures}
    _require(len(seed_map) == len(fixtures), "fixture seed collision")
    calls: Counter[int] = Counter()
    observed: dict[tuple[int, int, int], dict[str, Any]] = {}
    minute_fits: list[dict[str, Any]] = []
    suite = default_component_suite()
    original_fit = suite.fit_minutes
    original_compose = cast(
        Callable[..., list[ComposedPlayer]], vars(job)["compose_fixture_full_points"]
    )

    def fit_minutes(history: tuple[HistoryRow, ...], as_of: datetime) -> MinutesPredictor:
        _require(as_of == cutoff, "minutes fit cutoff changed")
        _require(
            all(
                r.kickoff_time < cutoff
                and not (r.season == season and (r.gw >= gw or r.fixture in fixtures))
                for r in history
            ),
            "target/future minutes entered fit history",
        )
        before = _sha([asdict(row) for row in history])
        model = original_fit(history, as_of)
        _require(before == _sha([asdict(row) for row in history]), "minutes fitter mutated history")
        parameters = getattr(model, "parameters", None)
        minute_fits.append(
            {
                "name": model.name,
                "as_of": as_of.isoformat(),
                "history_rows": len(history),
                "history_sha256": before,
                "latest_history_kickoff": max(
                    (row.kickoff_time.isoformat() for row in history), default=None
                ),
                "parameters": dict(parameters()) if callable(parameters) else None,
                "selection": "unchanged_existing_fit_minutes_v3_on_prior_history",
            }
        )
        return model

    def compose(
        players: Sequence[FixturePlayer],
        points_lookup: PointsLookup,
        bps_lookup: BpsExactLookup,
        extra: ExtraScoring,
        *,
        fixture_seed: int,
        draws: int,
        max_points: int = MAX_POINTS,
        conceded_exposure: Sequence[float] | None = None,
    ) -> list[ComposedPlayer]:
        _require(fixture_seed in seed_map, "unexpected fixture composition")
        _require(draws == DRAWS and max_points == MAX_POINTS, "composition settings changed")
        fixture = seed_map[fixture_seed]
        lane = calls[fixture]
        _require(lane in (0, 1), "extra primary/shadow composition")
        calls[fixture] += 1
        player_codes = {player.code for player in players}
        _require(len(player_codes) == len(players), "duplicate composer player")
        # Pickle is only an in-process mutation check, never an input deserializer
        # or persisted fingerprint (set iteration need not survive another process).
        inputs = (players, points_lookup, bps_lookup, extra, conceded_exposure)
        before = pickle.dumps(inputs, protocol=5)
        component_rows = {player.code: asdict(player) for player in players}
        result = original_compose(
            players,
            points_lookup,
            bps_lookup,
            extra,
            fixture_seed=fixture_seed,
            draws=draws,
            max_points=max_points,
            conceded_exposure=conceded_exposure,
        )
        _require(before == pickle.dumps(inputs, protocol=5), "composer mutated its inputs")
        _require(
            len(result) == len(players) and {row.code for row in result} == player_codes,
            "composer result player identity",
        )
        for row in result:
            observed[lane, fixture, row.code] = {
                **component_rows[row.code],
                "probability_any_bonus": row.probability_any_bonus,
                "composed_distribution": row.distribution,
                "composed_expected_bonus": row.expected_bonus,
            }
        return result

    binding = (
        bind_counterfactual_selector(
            counterfactual_inputs, cutoff=cutoff, current_fixture_gameweeks=fixture_gameweeks
        )
        if counterfactual_inputs is not None
        else nullcontext()
    )
    with binding, patch.object(job, "compose_fixture_full_points", compose):
        current = job.predict_prospective_points(
            con,
            as_of=cutoff,
            season=season,
            gw_from=gw,
            gw_to=gw,
            attacking="v3",
            appearance="seasonal",
            share_signal="auto",
            assists="coupled",
            suite=replace(suite, fit_minutes=fit_minutes),
            draws=DRAWS,
            base_seed=BASE_SEED,
            max_points=MAX_POINTS,
            db_path=db_path,
            repo=repo,
            football_environment_primary="sdp_v2",
        )
    incumbent = current.shadow_incumbent
    _require(incumbent is not None, "recursive incumbent shadow missing")
    assert incumbent is not None
    _require(dict(calls) == dict.fromkeys(fixtures, 2), "incomplete paired fixture compositions")
    _require(len(minute_fits) == 2, "expected one unchanged minutes fit per execution")
    _require(minute_fits[0] == minute_fits[1], "primary/shadow minutes fit differs")
    _require(incumbent.football_environment_provenance is None, "incumbent was not disabled")
    _require(incumbent.shadow_incumbent is None, "nested incumbent shadow")
    environment = current.football_environment_provenance
    _require(environment is not None, "primary selector provenance missing")
    assert environment is not None
    decisions = environment["decisions"]
    selectors = {int(row["fixture"]): str(row["selector"]) for row in decisions}
    _require(
        len(selectors) == len(decisions) and set(selectors) == fixtures,
        "selector fixture identity differs",
    )
    paired_fields = (
        "as_of",
        "season",
        "gw_from",
        "gw_to",
        "draws",
        "base_seed",
        "max_points",
        "roster_size",
        "fixture_count",
        "attacking_mode",
        "appearance_mode",
        "assists_mode",
        "share_signal_kind",
        "commit_sha",
        "worktree_clean",
        "config_sha256",
        "archive_sha256",
        "phase2_config_sha256",
        "phase3_config_sha256",
        "bootstrap_capture_id",
        "bootstrap_known_at",
        "bootstrap_payload_sha256",
        "schedule_capture_ids",
        "selectable_player_registry_sha256",
    )
    _require(
        all(getattr(current, key) == getattr(incumbent, key) for key in paired_fields),
        "primary/shadow population, inputs, or execution settings differ",
    )
    _require(current.players == incumbent.players, "primary/shadow player registry differs")
    _require(
        {k: v for k, v in current.component_names.items() if k != "team_clean_sheet"}
        == {k: v for k, v in incumbent.component_names.items() if k != "team_clean_sheet"},
        "player component version differs",
    )

    def lane_output(result: job.ProspectivePointsResult, lane: int) -> dict[str, Any]:
        players = {row.code: row for row in result.players}
        teams = {(row.fixture, row.team_id): row for row in result.team_records}
        _require(len(players) == len(result.players), "duplicate player metadata")
        _require(len(teams) == len(result.team_records), "duplicate team fixture metadata")
        predictions = []
        keys = set()
        for record in result.records:
            key = (record.fixture, record.code)
            _require(key not in keys, "duplicate predicted player fixture")
            keys.add(key)
            _require(
                record.season == season
                and record.gw == gw
                and record.fixture in fixtures
                and record.kickoff_time > cutoff,
                "prediction outside target fixture/cutoff population",
            )
            captured = observed.get((lane, *key))
            _require(captured is not None, "prediction lacks original component observation")
            assert captured is not None
            _require(
                record.distribution == captured["composed_distribution"]
                and record.expected_bonus == captured["composed_expected_bonus"],
                "result differs from exact composer return",
            )
            opponent = teams.get((record.fixture, record.opponent_team_id))
            own = teams.get((record.fixture, record.team_id))
            _require(
                own is not None
                and opponent is not None
                and own.team_code == record.team_code
                and opponent.opponent_team_id == record.team_id,
                "team/opponent fixture identity",
            )
            assert own is not None
            assert opponent is not None
            _require(
                record.team_code is not None and opponent.team_code is not None,
                "stable fixture team identity unavailable",
            )
            selector = selectors[record.fixture]
            predictions.append(
                {
                    **asdict(record),
                    "kickoff_time": record.kickoff_time.isoformat(),
                    "web_name": players[record.code].web_name,
                    "opponent_team_code": opponent.team_code,
                    "selector": selector,
                    "fallback_reason": None if selector == "SDP_PRIMARY" else selector,
                    "components": {
                        **captured["components"],
                        "probability_any_bonus": captured["probability_any_bonus"],
                    },
                    "residual_mean": captured["residual_mean"],
                    "residual_sigma": captured["residual_sigma"],
                    "probability_any_bonus": captured["probability_any_bonus"],
                    "team_environment": {
                        **asdict(own),
                        "kickoff_time": own.kickoff_time.isoformat(),
                    },
                    "opponent_environment": {
                        **asdict(opponent),
                        "kickoff_time": opponent.kickoff_time.isoformat(),
                    },
                }
            )
        _require(
            keys == {(fixture, code) for side, fixture, code in observed if side == lane},
            "unreported composed player fixture",
        )
        artifact = job.build_prospective_artifact(result)
        raw = artifact_bytes(artifact)
        return {
            "predictions": predictions,
            "artifact_bytes": raw,
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
            "provenance": {
                **cast(dict[str, Any], job.result_to_record(result)["provenance"]),
                "artifact_manifest": artifact.manifest.model_dump(mode="json"),
                "execution_football_environment": "sdp_v2" if lane == 0 else "disabled",
                "paired_stratification": "primary_fixture_selector_for_both_executions",
                "minutes_fit_observation": minute_fits[lane],
                "observer": "player_model_gw1_3_replay_v1",
            },
        }

    left, right = lane_output(current, 0), lane_output(incumbent, 1)
    left_rows = {(r["fixture"], r["code"]): r for r in left["predictions"]}
    right_rows = {(r["fixture"], r["code"]): r for r in right["predictions"]}
    identity_fields = (
        "season",
        "gw",
        "fixture",
        "kickoff_time",
        "code",
        "position",
        "team_id",
        "team_code",
        "opponent_team_id",
        "opponent_team_code",
        "was_home",
    )
    _require(left_rows.keys() == right_rows.keys(), "paired target identities differ")
    for key, left_row in left_rows.items():
        right_row = right_rows[key]
        _require(
            all(left_row[field] == right_row[field] for field in identity_fields),
            "paired target metadata differs",
        )
        if selectors[key[0]] != "SDP_PRIMARY":
            _require(
                canonical(left_row) == canonical(right_row), "fallback prediction/components differ"
            )
    return {
        "current": left,
        "incumbent": right,
        "pair_invariants": {
            "identical_target_identities": True,
            "identical_cutoff_fpl_registry_scoring_and_player_components": True,
            "fallback_record_and_component_bytes_identical": True,
            "unchanged_composer_inputs": True,
            "unchanged_minutes_history_and_fit": True,
            "recursive_incumbent_shadow": True,
            "target_player_fixtures": len(left_rows),
            "target_fixtures": len(fixtures),
            "fallback_player_fixtures": sum(
                selectors[key[0]] != "SDP_PRIMARY" for key in left_rows
            ),
            "target_identity_sha256": _sha(
                [
                    {field: left_rows[key][field] for field in identity_fields}
                    for key in sorted(left_rows)
                ]
            ),
        },
    }
