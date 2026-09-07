"""Synthetic arithmetic equivalence, not another historical model evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.config import load_phase2_evaluation, repo_root
from fpl.jobs import prospective_points_v1 as prospective
from fpl.models.points_composition import MEASURED_CONCEDED_EXPOSURE
from fpl.types import Position
from fpl.validate import development_reference_components as reference
from fpl.validate.minutes_baselines import MinuteBins, TargetRow
from fpl.validate.minutes_harness import player_fixture_history
from fpl.validate.points_harness import default_component_suite
from fpl.validate.prospective_incumbent_adapter import (
    V3_NAME,
    DefaultMinutesInputs,
    NullablePriceEvidence,
    RegistryEvidence,
    reproduce_default_minutes,
)
from tests import test_prospective_points_v1 as live_fixture


def _synthetic_db():
    # Real live-loader machinery; all bytes/data are explicitly synthetic 2026.
    players = [
        live_fixture._player(1, 1001, 1, 1),
        live_fixture._player(2, 1002, 2, 1),
        live_fixture._player(3, 1003, 3, 1),
        live_fixture._player(4, 1004, 4, 1),  # cold newcomer
        live_fixture._player(5, 2001, 1, 2),
        live_fixture._player(6, 2002, 2, 2),
        live_fixture._player(7, 2003, 3, 2),
        live_fixture._player(8, 2004, 4, 2),
    ]
    history = [
        (1001, "GK", 1, 2, True),
        (1002, "DEF", 1, 2, True),
        (1003, "MID", 1, 2, True),
        (2001, "GK", 2, 1, False),
        (2002, "DEF", 2, 1, False),
        (2003, "MID", 2, 1, False),
        (2004, "FWD", 2, 1, False),
    ]
    fixtures = [live_fixture._fixture(501, 1, 2), live_fixture._fixture(502, 2, 1)]
    fixtures[1]["kickoff_time"] = "2026-08-25T14:00:00Z"  # same-GW second leg
    con = live_fixture._basic_db(players, fixtures, history)
    con.execute("UPDATE mart_fact_player_fixture SET expected_goals=0.1+code%3*0.05")
    con.execute("UPDATE mart_fact_player_fixture SET defensive_contribution=code%15")
    return con


def _independent_fold(con, captured, minutes_model, forecast):
    cutoff = live_fixture.AS_OF
    bootstrap = prospective.live_bootstrap_snapshot(con, "2026-27", cutoff)
    meta = prospective.player_metadata_live(bootstrap)
    team_map = prospective.team_code_map_live(bootstrap)
    clubs = {code: team_map[m.team_id] for code, m in meta.items()}
    last = prospective.last_team_code(con, cutoff, current_club=clubs)
    prior = prospective.prior_season_appearance_rate(con, cutoff, current_club=clubs)
    recent = prospective.trailing5_minute_bins(
        con, cutoff, MinuteBins.from_config(load_phase2_evaluation()), current_club=clubs
    )
    maximum = max((r.kickoff_time for r in player_fixture_history(con, as_of=cutoff)), default=None)
    records = {(r.fixture, r.code): r for r in forecast.records}
    rows = []
    # Match production's observed registry order, not an invented SQL ordering guarantee.
    for fixture, (players, _kwargs) in captured.items():
        for player in players:
            r = records[(fixture, player.code)]
            target = TargetRow(
                r.season,
                r.gw,
                fixture,
                r.kickoff_time,
                r.code,
                Position(r.position),
                r.team_id,
                r.opponent_team_id,
                r.was_home,
            )
            selector = reproduce_default_minutes(
                DefaultMinutesInputs(
                    target,
                    cutoff,
                    minutes_model.predict(target),
                    cutoff,
                    V3_NAME,
                    clubs[r.code],
                    r.code in last,
                    recent.get(r.code),
                    prior.get(r.code, (None, 0)),
                    maximum,
                    "synthetic-prior",
                    RegistryEvidence(
                        "deadline_known", bootstrap.capture_id, bootstrap.known_at, True
                    ),
                    NullablePriceEvidence(
                        meta[r.code].now_cost, bootstrap.known_at, bootstrap.capture_id
                    ),
                    # This synthetic cold player's club has no other FWD, so no cap witness.
                    NullablePriceEvidence(None, bootstrap.known_at, bootstrap.capture_id),
                )
            )
            assert selector.blockers == ()
            assert selector.distribution == player.components.minutes
            rows.append(
                reference.ReferenceMinutesRow(
                    target,
                    clubs[r.code],
                    selector.distribution,
                    r.code not in last,
                    False,
                    json.dumps(asdict(selector)),
                )
            )
    return reference.ValidatedMinutesControlFold(
        "2026-27",
        1,
        cutoff,
        tuple(rows),
        "synthetic-db",
        "synthetic-manifest",
        "synthetic-fold",
        "{}",
    )


@pytest.fixture
def exact_reference(monkeypatch, request):
    con = _synthetic_db()
    variant = getattr(request, "param", "normal")
    if variant == "no_team_history":
        con.execute("DELETE FROM mart_fact_team_match")
    elif variant in {"null", "zero"}:
        value = "NULL" if variant == "null" else "0"
        con.execute(
            f"UPDATE mart_fact_player_fixture SET expected_goals={value},expected_assists={value}"
        )
    captured, fitted = {}, []
    original_compose = prospective.compose_fixture_full_points
    suite = default_component_suite()

    def fit_minutes(history, as_of):
        model = suite.fit_minutes(history, as_of)
        fitted.append(model)
        return model

    def capture(players, *args, **kwargs):
        # Seed identifies these two distinct synthetic fixture calls.
        fixture = 501 + len(captured)
        captured[fixture] = (tuple(players), dict(kwargs))
        return original_compose(players, *args, **kwargs)

    monkeypatch.setattr(
        prospective, "default_component_suite", lambda: replace(suite, fit_minutes=fit_minutes)
    )
    monkeypatch.setattr(prospective, "compose_fixture_full_points", capture)
    forecast = prospective.predict_prospective_points(
        con,
        as_of=live_fixture.AS_OF,
        season="2026-27",
        gw_from=1,
        gw_to=1,
        db_path=None,
        repo=None,
    )
    assert len(fitted) == 1
    fold = _independent_fold(con, captured, fitted[0], forecast)

    # Any accidental minutes refit in the adapter is a test failure.
    def no_minutes_fit(*args, **kwargs):
        raise AssertionError("reference must reuse cached final minutes")

    monkeypatch.setattr(
        reference, "default_component_suite", lambda: replace(suite, fit_minutes=no_minutes_fit)
    )
    actual = reference.build_reference_components(con, fold)
    try:
        yield con, fold, actual, captured, forecast
    finally:
        con.close()


@pytest.mark.parametrize(
    "exact_reference", ["normal", "null", "zero", "no_team_history"], indirect=True
)
def test_exact_default_components_and_full_joint_pmfs(exact_reference):
    _con, _fold, actual, captured, forecast = exact_reference
    assert actual.evidence_class == reference.EVIDENCE_CLASS
    assert actual.promotion_permitted is False
    records = {(r.fixture, r.code): r for r in forecast.records}
    for fixture, (expected_players, kwargs) in captured.items():
        actual_players = tuple(r.player for r in actual.rows if r.target.fixture == fixture)
        assert actual_players == expected_players  # Includes all PMFs + residual mean/sigma.
        assert kwargs == {
            "fixture_seed": reference._fixture_seed(202627, "2026-27", fixture),
            "draws": 2000,
            "max_points": 34,
            "conceded_exposure": MEASURED_CONCEDED_EXPOSURE,
        }
        for result in reference.compose_reference_fixture(actual, fixture):
            expected = records[(fixture, result.code)]
            assert result.distribution == expected.distribution
            assert result.expected_bonus == expected.expected_bonus
            assert len(result.distribution) == 35
            assert sum(result.distribution) == pytest.approx(1, abs=1e-14)
    assert any(r.cold_start for r in actual.rows)
    assert {r.target.fixture for r in actual.rows} == {501, 502}


def test_exact_stage_a_mirror_and_conversion_not_generic_v2(exact_reference):
    con, _fold, actual, _captured, _forecast = exact_reference
    teams = {(fixture, code): pmf for fixture, code, pmf in actual.team_scored}
    metadata = json.loads(actual.diagnostics_json)
    assert metadata["assist_conversion"] == prospective.league_assist_rate(con, actual.as_of)
    assert metadata["assist_conversion"] != 0.75
    assert metadata["minutes_refitted"] is False
    for row in actual.rows:
        other = 102 if row.team_code == 101 else 101
        assert row.player.components.team_goals_conceded == teams[(row.target.fixture, other)]


def test_future_truncation_and_target_fields_never_predictors(exact_reference):
    con, fold, before, _captured, _forecast = exact_reference
    con.execute("""INSERT INTO mart_fact_player_fixture
        (season,gw,fixture,kickoff_time,code,position,team_id,opponent_team_id,was_home,
         minutes,goals_scored,assists,expected_goals,expected_assists,influence,creativity)
        VALUES ('2026-27',1,501,'2026-08-22T14:00:00Z',1001,'GK',1,2,true,
                90,99,98,90.0,90.0,9999.0,9999.0)""")
    assert reference.build_reference_components(con, fold) == before
    con.execute("UPDATE mart_fact_player_fixture SET gw=2 WHERE season='2026-27'")
    assert reference.build_reference_components(con, fold) == before


def test_same_gw_earlier_observation_rejected(exact_reference):
    con, fold, _actual, _captured, _forecast = exact_reference
    con.execute("UPDATE mart_fact_player_fixture SET season='2026-27',gw=1 WHERE fixture=901")
    with pytest.raises(ValueError, match="target-GW observations"):
        reference.build_reference_components(con, fold)


def test_null_signals_stay_null_and_default_fallback_is_separate(exact_reference):
    con, fold, _actual, _captured, _forecast = exact_reference
    con.execute(
        "UPDATE mart_fact_player_fixture SET expected_goals=NULL,expected_assists=NULL "
        "WHERE code=1002"
    )
    actual = reference.build_reference_components(con, fold)
    selected = [r for r in actual.rows if r.target.code == 1002]
    assert all(r.raw_goal_signal is None and r.raw_assist_signal is None for r in selected)
    assert all(r.resolved_goal_signal > 0 and r.resolved_assist_signal > 0 for r in selected)
    remaining = con.execute(
        "SELECT count(*) FROM mart_fact_player_fixture WHERE code=1002 AND expected_goals IS NULL"
    ).fetchone()[0]
    assert remaining == 14


def test_proxy_propagates_through_team_allocation_and_whole_fixture_bonus(exact_reference):
    con, fold, _actual, _captured, _forecast = exact_reference
    changed = replace(
        fold,
        rows=tuple(
            replace(r, price_proxy_dependent=True) if r.target.code == 1004 else r
            for r in fold.rows
        ),
    )
    actual = reference.build_reference_components(con, changed)
    for r in actual.rows:
        assert r.direct_price_proxy == (r.target.code == 1004)
        assert r.team_price_proxy_codes == ((1004,) if r.team_code == 101 else ())
        assert r.fixture_price_proxy_codes == (1004,)


@pytest.mark.parametrize(
    "defect", ["duplicate", "side", "position", "cutoff", "pmf", "established_price"]
)
def test_typed_reference_rejects_invalid_grains(exact_reference, defect):
    _con, fold, _actual, _captured, _forecast = exact_reference
    rows = list(fold.rows)
    if defect == "duplicate":
        rows.append(rows[0])
    elif defect == "side":
        rows = [r for r in rows if r.team_code == 101]
    elif defect == "position":
        rows[-1] = replace(rows[-1], target=replace(rows[-1].target, position=Position.GK))
    elif defect == "cutoff":
        rows[0] = replace(
            rows[0], target=replace(rows[0].target, kickoff_time=fold.as_of - timedelta(seconds=1))
        )
    elif defect == "pmf":
        rows[0] = replace(rows[0], minutes=(0.2, 0.2, 0.2, 0.2))
    else:
        index = next(i for i, r in enumerate(rows) if not r.cold_start)
        rows[index] = replace(rows[index], price_proxy_dependent=True)
    with pytest.raises(
        ValueError, match=r"duplicate|rosters|identity conflict|cutoff|PMF|price proxy"
    ):
        reference._validate_rows(replace(fold, rows=tuple(rows)))


def _cache_payload(gw):
    cutoff = datetime(2023, 8, 1, tzinfo=UTC) + timedelta(days=7 * gw)
    rows = []
    for code, team, opp, home in ((10, 1, 2, True), (20, 2, 1, False)):
        target = {
            "season": "2023-24",
            "gw": gw,
            "fixture": gw,
            "kickoff_time": cutoff.isoformat(),
            "code": code,
            "position": "GK",
            "team_id": team,
            "opponent_team_id": opp,
            "was_home": home,
        }
        selector = {
            "historical_deadline_validity_established": False,
            "selector_arithmetic_reproduced": True,
            "blockers": [],
            "distribution": [0.1, 0.2, 0.3, 0.4],
        }
        lineage = {
            "comparator": reference.MINUTES_NAME,
            "evidence_class": reference.EVIDENCE_CLASS,
            "promotion_permitted": False,
            "proxy_dependent": False,
            "cold_start": False,
            "selector": selector,
            "archive_price_lineage": [],
        }
        rows.append(
            {
                "target": target,
                "team_code": 100 + team,
                "minutes_distribution": selector["distribution"],
                "raw_v3_distribution": selector["distribution"],
                "cold_start": False,
                "price_proxy_dependent": False,
                "selector_provenance": lineage,
            }
        )
    return {
        "season": "2023-24",
        "gw": gw,
        "as_of": cutoff.isoformat(),
        "maximum_prior_kickoff": None,
        "future_history_rows": 0,
        "same_gw_history_rows": 0,
        "rows": rows,
    }


@pytest.fixture
def tiny_cache(tmp_path, monkeypatch):
    directory, root = tmp_path / "cache", tmp_path / "repo"
    directory.mkdir()
    (root / "results").mkdir(parents=True)
    (root / "source.py").write_text("frozen", encoding="utf8")
    db = tmp_path / "synthetic.duckdb"
    db.write_bytes(b"synthetic identity only: no database read in cache loader")
    counts = {"2023-24": 76, "rows": 76, "price_proxy_rows": 0}
    provenance = {
        "git_head": reference.CACHE_HEAD,
        "comparator": reference.MINUTES_NAME,
        "evidence_class": reference.EVIDENCE_CLASS,
        "worktree_clean": True,
        "historical_deadline_validity": False,
        "new_model_candidate_scoring": False,
        "database_sha256": reference.file_sha256(db),
        "source_sha256": {"source.py": reference.file_sha256(root / "source.py")},
    }
    folds = []
    for gw in range(1, 39):
        name = f"2023-24-gw{gw:02d}.json"
        (directory / name).write_text(json.dumps(_cache_payload(gw)), encoding="utf8")
        folds.append(
            {
                "season": "2023-24",
                "gw": gw,
                "file": name,
                "rows": 2,
                "sha256": reference.file_sha256(directory / name),
            }
        )
    manifest = {"completed": True, "counts": counts, "provenance": provenance, "folds": folds}
    body = json.dumps(manifest).encode()
    (directory / "manifest.json").write_bytes(body)
    (root / reference.MANIFEST).write_bytes(body)
    (directory / "provenance.json").write_text(json.dumps(provenance), encoding="utf8")
    monkeypatch.setattr(reference, "MANIFEST_SHA256", hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(reference, "EXPECTED_COUNTS", counts)
    return directory, db, root


def test_cache_reads_all_hashed_rows_without_fitting(tiny_cache):
    directory, db, root = tiny_cache
    result = reference.read_minutes_control_cache(directory, db=db, root=root)
    assert len(result.folds) == 38
    assert sum(len(f.rows) for f in result.folds) == 76
    assert result.folds[-1].gw == 38


@pytest.mark.parametrize("defect", ["last_fold", "manifest", "provenance", "source", "db", "wal"])
def test_cache_fail_closed_even_if_last_fold_corrupted(tiny_cache, defect):
    directory, db, root = tiny_cache
    targets = {
        "last_fold": directory / "2023-24-gw38.json",
        "manifest": directory / "manifest.json",
        "provenance": directory / "provenance.json",
        "source": root / "source.py",
        "db": db,
        "wal": db.with_name(db.name + ".wal"),
    }
    targets[defect].write_bytes(b"{}")
    with pytest.raises(ValueError, match=r"hash|manifest|provenance|source|database"):
        reference.read_minutes_control_cache(directory, db=db, root=root)


@pytest.mark.parametrize(
    "defect",
    [
        "target_outcome",
        "selector_pmf",
        "late_prior",
        "early_target",
        "bad_evidence",
        "missing_price_lineage",
    ],
)
def test_cache_row_semantics_fail_closed(defect):
    payload = _cache_payload(1)
    row = payload["rows"][0]
    if defect == "target_outcome":
        row["target"]["minutes"] = 90
    elif defect == "selector_pmf":
        row["minutes_distribution"] = [1.0, 0.0, 0.0, 0.0]
    elif defect == "late_prior":
        payload["maximum_prior_kickoff"] = payload["as_of"]
    elif defect == "early_target":
        row["target"]["kickoff_time"] = "2020-01-01T00:00:00Z"
    elif defect == "bad_evidence":
        row["selector_provenance"]["evidence_class"] = "strict_prospective"
    else:
        row["price_proxy_dependent"] = True
        row["cold_start"] = True
        row["selector_provenance"].update(proxy_dependent=True, cold_start=True)
    with pytest.raises(ValueError, match=r"projection|inconsistent|cutoff|lineage"):
        reference._decode_fold(
            payload, database_hash="db", manifest_hash="manifest", fold_hash="fold"
        )


def test_existing_production_source_pins_are_unchanged():
    import yaml

    root = repo_root()
    config = yaml.safe_load(
        (root / "config/retrospective_current_minutes_proxy_v1.yaml").read_bytes()
    )
    for name, expected in config["unchanged_source_sha256"].items():
        assert reference.file_sha256(root / name) == expected


def test_actual_default_still_refuses_completely_empty_minutes_history():
    con = _synthetic_db()
    con.execute("DELETE FROM mart_fact_player_fixture")
    try:
        with pytest.raises(ValueError, match="requires at least one eligible prior minutes row"):
            prospective.predict_prospective_points(
                con,
                as_of=live_fixture.AS_OF,
                season="2026-27",
                gw_from=1,
                gw_to=1,
                db_path=None,
                repo=None,
            )
    finally:
        con.close()


def test_reference_provenance_cannot_be_relabelled_prospective(exact_reference):
    _con, _fold, actual, _captured, _forecast = exact_reference
    with pytest.raises(ValueError, match="explicit development"):
        reference.compose_reference_fixture(
            replace(actual, evidence_class="strict_prospective"), 501
        )


def test_reference_connection_is_bound_to_validated_file(exact_reference):
    con, fold, _actual, _captured, _forecast = exact_reference
    with pytest.raises(ValueError, match="validated reference database"):
        reference.build_reference_components(con, replace(fold, database_path="another.duckdb"))
