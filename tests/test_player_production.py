"""Frozen adoption, duration DC, and immutable whole-gameweek G+A publication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import duckdb
import polars as pl
import pytest

from fpl.artifacts.prospective_points import ArtifactError, artifact_bytes, read_artifact_bytes
from fpl.config import config_dir, repo_root
from fpl.jobs.prospective_points_v1 import build_prospective_artifact, predict_prospective_points
from fpl.models.goal_involvement import gameweek_probability
from fpl.models.player_components_production import FrozenPlayerAdapter, load_component_config
from fpl.models.points_composition import compose_fixture_full_points
from fpl.publish.contract import SEMANTIC_CONTRACT_V6, SEMANTIC_CONTRACT_V7
from fpl.publish.dashboard_json import (
    DashboardJsonError,
    _build_goal_involvement,
    _validate_goal_involvement_player,
)
from fpl.storage import ledger, sdp_evidence
from fpl.types import Position
from tests.test_points_composition_v3 import BPS_LOOKUP, EXTRA, LOOKUP, _deterministic_player
from tests.test_prospective_points_artifact import _artifact as legacy_artifact
from tests.test_prospective_points_v1 import AS_OF, _basic_db, _fixture, _player


@pytest.fixture(scope="module")
def adopted_artifact():
    con = _basic_db(
        players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
        fixtures=[_fixture(501, 1, 2), _fixture(502, 2, 1), _fixture(503, 1, 2, event=3)],
        history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    try:
        result = predict_prospective_points(
            con,
            as_of=AS_OF,
            season="2026-27",
            gw_from=1,
            gw_to=5,
            draws=100,
            player_components="trained",
            football_environment_primary="disabled",
            db_path=None,
            repo=repo_root(),
        )
    finally:
        con.close()
    # Explicitly synthetic provenance; no operational artifact is emitted by this test.
    result = replace(result, archive_sha256="a" * 64, commit_sha="deadbeef", worktree_clean=True)
    return build_prospective_artifact(result)


def test_frozen_coefficients_cannot_be_used_before_training_cutoff():
    config, _ = load_component_config(config_dir())
    with pytest.raises(ValueError, match="training cutoff"):
        FrozenPlayerAdapter(
            [],
            cutoff=config.training_cutoff,
            season="2025-26",
            gw=38,
            frontier_season="2025-26",
            config=config,
        )


@pytest.mark.parametrize("minutes_bin", [0, 1, 2, 3])
def test_duration_dc_scores_only_its_actual_minutes_bin(minutes_bin):
    player = _deterministic_player(1, Position.MID, 0, 0, 1, minutes_bin=minutes_bin)
    scalar = replace(player, components=replace(player.components, dc_hit_probability=0.25))
    matching = replace(
        scalar, components=replace(scalar.components, dc_by_minutes=(0, 0.25, 0.25, 0.25))
    )
    kwargs = {"fixture_seed": 17, "draws": 100, "max_points": 34}
    assert compose_fixture_full_points([scalar], LOOKUP, BPS_LOOKUP, EXTRA, **kwargs) == (
        compose_fixture_full_points([matching], LOOKUP, BPS_LOOKUP, EXTRA, **kwargs)
    )
    one = replace(scalar, components=replace(scalar.components, dc_by_minutes=(0, 0, 0, 1)))
    zero = replace(scalar, components=replace(scalar.components, dc_by_minutes=(0, 0, 0, 0)))
    yes = compose_fixture_full_points([one], LOOKUP, BPS_LOOKUP, EXTRA, **kwargs)[0]
    no = compose_fixture_full_points([zero], LOOKUP, BPS_LOOKUP, EXTRA, **kwargs)[0]

    def mean(row):
        return sum(i * p for i, p in enumerate(row.distribution))

    assert mean(yes) - mean(no) == pytest.approx(2 if minutes_bin == 3 else 0)


def test_new_artifact_roundtrip_dgw_blank_and_config_binding(adopted_artifact):
    artifact = read_artifact_bytes(artifact_bytes(adopted_artifact))
    assert artifact.manifest.schema_version == 3
    assert artifact.manifest.component_modes["goal_involvement.serving"] == "component_baseline"
    raw = artifact.manifest.component_modes["goal_involvement.parameters"]
    assert (
        hashlib.sha256(raw.encode()).hexdigest()
        == artifact.manifest.contracts["goal_involvement"].sha256
    )
    for row in artifact.rows:
        event = row.goal_involvement
        assert event is not None
        legs = [
            f.goal_involvement
            for f in artifact.player_fixture_rows
            if (f.gw, f.code) == (row.gw, row.code)
        ]
        assert all(leg is not None for leg in legs)
        expected = gameweek_probability(
            [(leg.probability_zero, leg.probability_one) for leg in legs]
        )
        assert event.probability_ge_2 == expected == event.component_probability_ge_2
        if row.gw in (2, 4, 5):
            assert event.probability_ge_2 == event.shadow_probability_ge_2 == 0
        elif row.gw == 1:
            assert len(legs) == 2


def test_existing_pair_vintage_cannot_omit_or_change_event_rows(adopted_artifact):
    with duckdb.connect() as con:
        run_id = ledger.record_forecast(con, adopted_artifact)
        sha = hashlib.sha256(artifact_bytes(adopted_artifact)).hexdigest()
        sdp_evidence._ensure_vintage(con, adopted_artifact, sha, run_id, datetime.now(UTC))
        con.execute("DELETE FROM ledger_prediction_goal_involvement_gameweek")
        with pytest.raises(sdp_evidence.PairVerificationError, match="G\\+A ledger"):
            sdp_evidence._ensure_vintage(con, adopted_artifact, sha, run_id, datetime.now(UTC))


def test_legacy_artifact_keeps_old_canonical_bytes():
    payload = artifact_bytes(legacy_artifact())
    assert b'"goal_involvement"' not in payload
    assert artifact_bytes(read_artifact_bytes(payload)) == payload


@pytest.mark.parametrize("defect", ["missing", "changed", "hash", "cutoff", "mode"])
def test_new_artifact_rejects_incomplete_or_inconsistent_event_data(adopted_artifact, defect):
    artifact = adopted_artifact
    if defect in ("missing", "changed"):
        row = artifact.rows[0]
        event = (
            None
            if defect == "missing"
            else row.goal_involvement.model_copy(update={"probability_ge_2": 1.0})
        )
        artifact = replace(
            artifact, rows=(row.model_copy(update={"goal_involvement": event}), *artifact.rows[1:])
        )
    else:
        modes = dict(artifact.manifest.component_modes)
        if defect == "mode":
            modes["goal_involvement.serving"] = "trained_event"
        else:
            modes["goal_involvement.parameters"] += " "
        manifest = artifact.manifest.model_copy(update={"component_modes": modes})
        if defect == "cutoff":
            raw = json.loads(artifact.manifest.component_modes["goal_involvement.parameters"])
            raw["training_cutoff"] = (AS_OF + timedelta(days=1)).isoformat()
            modes["goal_involvement.parameters"] = json.dumps(raw)
            contracts = dict(manifest.contracts)
            contracts["goal_involvement"] = contracts["goal_involvement"].model_copy(
                update={
                    "sha256": hashlib.sha256(
                        modes["goal_involvement.parameters"].encode()
                    ).hexdigest(),
                }
            )
            manifest = manifest.model_copy(
                update={"contracts": contracts, "component_modes": modes}
            )
        artifact = replace(artifact, manifest=manifest)
    with pytest.raises(ArtifactError):
        artifact_bytes(artifact)


def test_event_ledger_is_append_only_and_transactional(adopted_artifact, monkeypatch):
    with duckdb.connect() as con:
        run_id = ledger.record_forecast(con, adopted_artifact)
        rows = con.execute(
            "SELECT probability_ga_ge_2 FROM ledger_prediction_goal_involvement_gameweek "
            "WHERE run_id=? ORDER BY gw,code",
            [run_id],
        ).fetchall()
        assert rows == [(row.goal_involvement.probability_ge_2,) for row in adopted_artifact.rows]
        with pytest.raises(ledger.DuplicateRunError):
            ledger.record_forecast(con, adopted_artifact)
        insert = ledger._insert_predictions

        def fail_after_insert(*args):
            insert(*args)
            raise RuntimeError("synthetic failure after event insert")

        monkeypatch.setattr(ledger, "_insert_predictions", fail_after_insert)
        other = replace(
            adopted_artifact,
            manifest=adopted_artifact.manifest.model_copy(update={"base_seed": 123}),
        )
        with pytest.raises(RuntimeError, match="synthetic failure"):
            ledger.record_forecast(con, other)
        assert con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()[0] == 1
        assert con.execute(
            "SELECT count(*) FROM ledger_prediction_goal_involvement_gameweek"
        ).fetchone()[0] == len(rows)


def _public_inputs():
    run = {
        "run_id": "new",
        "season": "2026-27",
        "gw_from": 7,
        "gw_to": 12,
        "component_modes": {"goal_involvement.serving": "component_baseline"},
        "goal_involvement_model": "component_baseline",
    }
    rows = [
        {
            "run_id": "new",
            "season": "2026-27",
            "gw": gw,
            "code": 1,
            "probability_ga_ge_2": p,
            "component_probability_ga_ge_2": p,
            "shadow_probability_ga_ge_2": p / 2,
        }
        for gw, p in zip(range(7, 13), [0.2, 0, 0.3, 0.1, 0.4, 0.5], strict=True)
    ]
    runs = pl.DataFrame([{**run, "component_modes": json.dumps(run["component_modes"])}])
    return run, rows, runs


def test_public_mean_includes_blank_gw_and_never_shortens_window():
    run, rows, runs = _public_inputs()
    block = _build_goal_involvement(pl.DataFrame(rows), runs)["new", "2026-27", 1]
    assert [r["mean_next_5"] for r in block["gameweeks"]] == [0.2, 0.26, None, None, None, None]
    _validate_goal_involvement_player({"goal_involvement": block}, run)
    block["gameweeks"][0]["mean_next_5"] = 0.25  # Wrongly excluding the blank.
    with pytest.raises(DashboardJsonError, match="exactly five"):
        _validate_goal_involvement_player({"goal_involvement": block}, run)


@pytest.mark.parametrize("defect", ["missing", "duplicate", "null", "nonfinite", "wrong_serving"])
def test_publication_refuses_incomplete_or_invalid_new_event_rows(defect):
    _, rows, runs = _public_inputs()
    if defect == "missing":
        rows.pop()
    if defect == "duplicate":
        rows.append(dict(rows[0]))
    if defect == "null":
        rows[0]["probability_ga_ge_2"] = None
    if defect == "nonfinite":
        rows[0]["probability_ga_ge_2"] = float("nan")
    if defect == "wrong_serving":
        rows[0]["probability_ga_ge_2"] = 0.7
    with pytest.raises(DashboardJsonError):
        _build_goal_involvement(pl.DataFrame(rows), runs)


def test_legacy_publication_is_unavailable_and_v6_contract_is_frozen():
    _, rows, runs = _public_inputs()
    runs = runs.with_columns(pl.lit("{}").alias("component_modes"))
    rows = [{k: v for k, v in row.items() if "probability" not in k} for row in rows]
    assert _build_goal_involvement(pl.DataFrame(rows), runs) == {}
    _validate_goal_involvement_player({}, {"component_modes": {}})
    assert SEMANTIC_CONTRACT_V6.version == 6
    old = {c.name for c in SEMANTIC_CONTRACT_V6.table("fact_forecast_player_gameweek").columns}
    new = {c.name for c in SEMANTIC_CONTRACT_V7.table("fact_forecast_player_gameweek").columns}
    assert new - old == {
        "probability_ga_ge_2",
        "component_probability_ga_ge_2",
        "shadow_probability_ga_ge_2",
    }


def test_stored_event_survives_semantic_and_dashboard_exports(tmp_path):
    from fpl.artifacts.prospective_points import (
        ContractIdentity,
        GoalInvolvementFixture,
        GoalInvolvementForecast,
    )
    from fpl.jobs.build_sdp_dashboard import retain_validated_generation
    from fpl.models.player_components_production import load_event_config
    from fpl.publish.dashboard_json import export_dashboard_json, validate_dashboard_json
    from fpl.publish.export import export_bi
    from fpl.publish.public_dashboard import _assert_public_safe
    from tests.test_bi_export import _seed_database

    db = tmp_path / "synthetic.duckdb"
    old, old_id = _seed_database(db, record=True)
    config, sha = load_event_config(config_dir())
    modes = {
        **old.manifest.component_modes,
        "goal_involvement.serving": config.serving,
        "goal_involvement.parameters": (
            config_dir() / "goal_involvement_production.json"
        ).read_text(),
    }
    contracts = {
        **old.manifest.contracts,
        "goal_involvement": ContractIdentity(
            name=config.name,
            version=str(config.version),
            sha256=sha,
        ),
    }
    # Synthetic events exercise transport only; they are not new fitted model evidence.
    leg = GoalInvolvementFixture(
        probability_zero=0.8, probability_one=0.15, probability_appears=0.9
    )
    baseline = gameweek_probability([(0.8, 0.15)])
    rows = []
    for row in old.rows:
        served, shadow = config.probabilities(row.position, baseline, structural_zero=False)
        rows.append(
            row.model_copy(
                update={
                    "goal_involvement": GoalInvolvementForecast(
                        probability_ge_2=served,
                        component_probability_ge_2=baseline,
                        shadow_probability_ge_2=shadow,
                    )
                }
            )
        )
    new = replace(
        old,
        manifest=old.manifest.model_copy(
            update={
                "schema_version": 3,
                "component_modes": modes,
                "contracts": contracts,
            }
        ),
        rows=tuple(rows),
        player_fixture_rows=tuple(
            row.model_copy(update={"goal_involvement": leg}) for row in old.player_fixture_rows
        ),
    )
    with duckdb.connect(str(db)) as con:
        # The BI-only seed has one partial descriptive window; this test has no form history.
        con.execute("DELETE FROM mart_fact_player_form")
        con.execute("DELETE FROM mart_fact_team_form")
        new_id = ledger.record_forecast(con, new)
    retain_validated_generation(export_bi, db, tmp_path / "bi-endpoint", tmp_path / "bi")
    retain_validated_generation(
        export_dashboard_json, tmp_path / "bi", tmp_path / "json-endpoint", tmp_path / "json"
    )
    validate_dashboard_json(tmp_path / "json")
    players = json.loads((tmp_path / "json" / "players.json").read_bytes())["players"]
    _assert_public_safe(players)
    for player in players:
        if player["run_id"] == old_id:
            assert player.get("goal_involvement") is None
        else:
            assert player["run_id"] == new_id
            assert player["goal_involvement"]["gameweeks"] == [
                {
                    "gw": 1,
                    "probability_ge_2": baseline,
                    "mean_next_5": None,
                }
            ]
