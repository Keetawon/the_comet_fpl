"""Synthetic retained-pair checkpoint tests; no network or real outcomes."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from fpl.jobs import score_sdp_checkpoint as checkpoint_job
from fpl.jobs.score_sdp_checkpoint import write_report
from fpl.validate import sdp_checkpoint
from fpl.validate.sdp_checkpoint import (
    SCORING,
    build_checkpoint,
    canonical_bytes,
    finality_witness,
    score_pair_report,
)

type Row = dict[str, Any]


def _sample(*, legs: tuple[int, ...] = (2,), final: bool | None = True) -> Row:
    pair: Row = {
        "prediction_id": "p" * 64,
        "season": "2026-27",
        "gw_from": 4,
        "gw_to": 8,
        "as_of": "2026-09-08T09:00:00+00:00",
        "created_at": "2026-09-08T09:01:00+00:00",
        "primary_run_id": "primary-run",
        "shadow_run_id": "shadow-run",
        "primary_artifact_sha256": "a" * 64,
        "shadow_artifact_sha256": "b" * 64,
    }
    contract: Row = {
        "schema_version": 1,
        "checkpoint_id": "synthetic",
        "vintage_policy": "fixed_origin",
        "gameweeks": [4],
        "model_freeze_sha": "f" * 40,
        "forecast_emitter_sha": "e" * 40,
        "selection_registered_at": "2026-09-08T09:02:00+00:00",
        "scoring": dict(SCORING),
        **{
            k: pair[k]
            for k in (
                "prediction_id",
                "season",
                "primary_artifact_sha256",
                "shadow_artifact_sha256",
            )
        },
    }
    fixtures = list(range(41, 41 + len(legs)))
    outcome = {
        "attached": True,
        "total_points_as_recorded": sum(legs),
        "points_under_rules_2026_27": sum(legs),
        "legs": [
            {
                "fixture": f,
                "attached_at": "2026-09-14T10:00:00+00:00",
                "total_points_as_recorded": y,
                "points_under_rules_2026_27": y,
            }
            for f, y in zip(fixtures, legs, strict=True)
        ],
    }
    players, teams = [], []
    for role in ("primary", "shadow"):
        target = sum(min(34, max(0, y)) for y in legs)
        pmf = [0.0] * (34 * len(legs) + 1)
        pmf[target] = 1.0
        players.append(
            {
                "role": role,
                "run_id": pair[f"{role}_run_id"],
                "artifact_sha256": pair[f"{role}_artifact_sha256"],
                "season": "2026-27",
                "gw": 4,
                "code": 11,
                "position": "DEF",
                "team_id": 1,
                "team_code": 101,
                "fixture_ids": fixtures,
                "expected_points": float(target),
                "distribution": pmf,
                "availability_adjusted_expected_points": float(target),
                "outcome": copy.deepcopy(outcome),
            }
        )
        for fixture in fixtures:
            for team, opponent, home in ((1, 2, True), (2, 1, False)):
                teams.append(
                    {
                        "role": role,
                        "run_id": pair[f"{role}_run_id"],
                        "artifact_sha256": pair[f"{role}_artifact_sha256"],
                        "season": "2026-27",
                        "gw": 4,
                        "fixture": fixture,
                        "team_id": team,
                        "team_code": 100 + team,
                        "opponent_team_id": opponent,
                        "was_home": home,
                        "kickoff_time": "2026-09-12T15:00:00+00:00",
                        "lambda_for": 0.5,
                        "lambda_against": 0.5,
                        "probability_clean_sheet": 0.5,
                        "goals_for_distribution": [0.5, 0.5],
                        "selector": "SDP_PRIMARY" if role == "primary" else None,
                        "outcome": {
                            "attached": True,
                            "attached_at": "2026-09-14T10:00:00+00:00",
                            "goals_for": 1 if home else 0,
                            "goals_against": 0 if home else 1,
                        },
                    }
                )
    return {
        "pair": pair,
        "contract": contract,
        "players": players,
        "teams": teams,
        "finality": {
            4: {
                "season": "2026-27",
                "gw": 4,
                "official_final": final,
                "source": "synthetic",
                "fixtures": [{"fixture": f, "finished": final} for f in fixtures],
            }
        },
    }


def _score(sample: Row) -> Row:
    return score_pair_report(
        sample["pair"],
        sample["players"],
        sample["teams"],
        finality=sample["finality"],
        contract=sample["contract"],
        contract_sha256="c" * 64,
    )


def test_synthetic_scores_use_stored_distributions_and_deduplicate_teams() -> None:
    report = _score(_sample())
    assert report["status"] == "COMPLETE"
    assert report["players"]["primary"]["overall"]["mean_crps"] == 0
    assert report["teams"]["primary"]["overall"]["goal_nll"] == pytest.approx(math.log(2))
    assert report["teams"]["primary"]["overall"]["clean_sheet"]["brier"] == 0.25
    assert report["operations"]["forecast_fixture_count"] == 1
    assert report["operations"]["team_pairs_scored"] == 2
    assert report["paired"]["players"]["overall"]["all_paired_losses_numerically_equal"]
    assert report["players"]["primary"]["rankings"][0]["captain_shortlists"][0][
        "selected_codes"
    ] == [11]


def test_dgw_coarsens_each_leg_but_preserves_signed_total() -> None:
    report = _score(_sample(legs=(-2, 5)))
    points = report["players"]["primary"]["overall"]
    assert points["mean_log_score"] == 0
    assert points["signed_points"]["mean_observed"] == 3
    assert points["signed_points"]["mae"] == 2
    assert points["events_on_coarsened_target"]["points_ge5"]["observed_rate"] == 1
    assert report["players"]["primary"]["rankings"][0]["top_k"][0]["hit_rate_ge5"] == 0


@pytest.mark.parametrize("final", [False, None])
def test_whole_gw_finality_blocks_both_grains_even_with_attached_legs(final: bool | None) -> None:
    report = _score(_sample(final=final))
    assert report["status"] == "PENDING"
    assert report["reason"] == "NO_OFFICIALLY_FINALIZED_GAMEWEEKS"
    assert report["players"]["primary"]["overall"]["mean_crps"] is None
    assert report["teams"]["primary"]["overall"]["goal_crps"] is None
    assert report["operations"]["player_pairs_scored"] == 0


def test_missing_dgw_leg_does_not_become_zero() -> None:
    sample = _sample(legs=(1, 2))
    for row in sample["players"]:
        row["outcome"] = {"attached": False, "reason": "one leg missing"}
    report = _score(sample)
    assert report["operations"]["player_pairs_scored"] == 0
    assert report["exclusions"]["players"][0]["reason"] == "FINALIZED_PLAYER_OUTCOME_UNAVAILABLE"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("duplicate", "duplicate"),
        ("missing_shadow", "population"),
        ("identity", "position"),
        ("cs", "opponent PMF"),
        ("outcome", "outcome mismatch"),
        ("leg", "legs differ"),
        ("pmf", "invalid retained PMF"),
        ("selector", "selector"),
    ],
)
def test_malformed_or_mismatched_evidence_fails_closed(mutation: str, match: str) -> None:
    sample = _sample()
    if mutation == "duplicate":
        sample["teams"].append(copy.deepcopy(sample["teams"][0]))
    elif mutation == "missing_shadow":
        sample["players"].pop()
    elif mutation == "identity":
        sample["players"][1]["position"] = "MID"
    elif mutation == "cs":
        sample["teams"][0]["probability_clean_sheet"] = 0.2
    elif mutation == "outcome":
        sample["players"][1]["outcome"]["total_points_as_recorded"] = 9
    elif mutation == "leg":
        for row in sample["players"]:
            row["outcome"]["legs"][0]["fixture"] = 99
    elif mutation == "pmf":
        sample["players"][0]["distribution"][0] = float("nan")
    else:
        sample["teams"][0]["selector"] = None
    with pytest.raises(ValueError, match=match):
        _score(sample)


def test_official_recorded_and_replayed_points_remain_separate() -> None:
    sample = _sample()
    for row in sample["players"]:
        row["outcome"]["points_under_rules_2026_27"] = 9
        row["outcome"]["legs"][0]["points_under_rules_2026_27"] = 9
    report = _score(sample)
    assert report["players"]["primary"]["overall"]["signed_points"]["mean_observed"] == 2
    assert report["players"]["primary"]["recorded_vs_replayed_disagreement_rows"] == 1
    assert report["players"]["primary"]["components"]["minutes"] is None


def test_deterministic_replay_permutation_and_input_immutability() -> None:
    sample = _sample(legs=(-2, 5))
    snapshot = canonical_bytes(sample)
    first = canonical_bytes(_score(sample))
    assert canonical_bytes(sample) == snapshot
    sample["players"].reverse()
    sample["teams"].reverse()
    assert canonical_bytes(_score(sample)) == first


def test_new_outcome_attachment_changes_report_identity_without_overwriting(tmp_path: Path) -> None:
    pending = _sample(final=False)
    first = _score(pending)
    path = tmp_path / "report-v1.json"
    assert write_report(path, first)
    original = path.read_bytes()
    assert not write_report(path, first)
    final = _score(_sample())
    assert final["report_version"] != first["report_version"]
    with pytest.raises(ValueError, match="different evidence"):
        write_report(path, final)
    assert path.read_bytes() == original
    assert write_report(tmp_path / "report-v2.json", final)


def test_contract_mismatch_rejected_before_outcome_access(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _sample()
    sample["contract"]["primary_artifact_sha256"] = "f" * 64
    monkeypatch.setattr(sdp_checkpoint, "load_pair", lambda con, prediction_id: sample["pair"])

    def forbidden(*args: Any) -> Any:
        pytest.fail("outcomes read before contract validation")

    monkeypatch.setattr(sdp_checkpoint, "pair_player_gameweek_rows", forbidden)
    with duckdb.connect() as con, pytest.raises(ValueError, match="artifact_sha256 mismatch"):
        build_checkpoint(con, contract=sample["contract"], contract_sha256="c" * 64)


def test_rolling_policy_cannot_pool_gameweeks() -> None:
    sample = _sample()
    sample["contract"]["vintage_policy"] = "rolling"
    assert _score(sample)["vintage_policy"] == "rolling"
    sample["contract"]["gameweeks"] = [4, 5]
    with pytest.raises(ValueError, match="one target GW"):
        _score(sample)


def test_latest_live_fixture_revision_drives_complete_whole_gw_witness() -> None:
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE stg_live_fixture_version(season VARCHAR, gw INTEGER, "
            "fixture INTEGER, finished BOOLEAN, known_at TIMESTAMPTZ, capture_id VARCHAR)"
        )
        con.execute(
            "INSERT INTO stg_live_fixture_version VALUES "
            "('2026-27',4,41,TRUE,'2026-09-14T10:00:00Z','a'),"
            "('2026-27',4,42,FALSE,'2026-09-14T10:00:00Z','a')"
        )
        before = finality_witness(con, "2026-27", 4)
        assert before["official_final"] is False
        con.execute(
            "INSERT INTO stg_live_fixture_version VALUES "
            "('2026-27',4,42,TRUE,'2026-09-15T10:00:00Z','b')"
        )
        after = finality_witness(con, "2026-27", 4)
        assert after["official_final"] is True
        assert len(after["fixtures"]) == 2
        assert before != after
        assert finality_witness(con, "2026-27", 5)["official_final"] is None


def test_archived_finality_authority_has_priority_and_null_is_not_true() -> None:
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE stg_fixture(season VARCHAR, gw INTEGER, "
            "fixture INTEGER, finished BOOLEAN)"
        )
        con.execute("INSERT INTO stg_fixture VALUES ('2026-27',4,41,NULL)")
        assert finality_witness(con, "2026-27", 4)["official_final"] is False
        assert finality_witness(con, "2026-27", 5)["official_final"] is None


def test_repaired_canonical_integer_keys_round_trip_and_collision_rejection() -> None:
    data = canonical_bytes({"fixtures": {2: [1], 10: [2]}})
    assert canonical_bytes(json.loads(data)) == data
    with pytest.raises(ValueError, match="ambiguous"):
        canonical_bytes({2: "a", "2": "b"})


def test_changed_scoring_pin_and_unregistered_horizon_are_rejected() -> None:
    sample = _sample()
    sample["contract"]["scoring"]["log_floor"] = 0.01
    with pytest.raises(ValueError, match="scoring policy"):
        _score(sample)
    sample = _sample()
    sample["contract"]["gameweeks"] = [4, 5]
    sample["finality"][5] = {"season": "2026-27", "gw": 5, "official_final": False}
    with pytest.raises(ValueError, match="no retained forecast"):
        _score(sample)


@pytest.mark.parametrize("attach", [False, True])
def test_cli_safe_optional_attachment_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attach: bool,
) -> None:
    sample = _sample(final=False)
    contract = tmp_path / "contract.yaml"
    contract.write_text(yaml.safe_dump(sample["contract"]), encoding="utf-8")
    events: list[str] = []
    sentinel = object()

    @contextmanager
    def connect(db: Path, *, read_only: bool) -> Iterator[object]:
        assert read_only
        events.append("reader_open")
        yield sentinel
        events.append("reader_closed")

    @contextmanager
    def writer(db: Path, *, backup: Path) -> Iterator[object]:
        assert backup == tmp_path / "backup.duckdb"
        events.append("backup_then_writer")
        yield sentinel
        events.append("writer_closed")

    def load(con: object, *, contract: Row, contract_sha256: str) -> Row:
        events.append("pair_loaded")
        return dict(sample["pair"])

    @dataclass
    class Result:
        attached: int = 0

    def attach_outcomes(con: object, *, as_of: datetime, season: str) -> Result:
        assert as_of.tzinfo == UTC
        assert abs((datetime.now(UTC) - as_of).total_seconds()) < 5
        assert season == "2026-27"
        events.append("authoritative_attach")
        return Result()

    def build(con: object, *, contract: Row, contract_sha256: str) -> Row:
        events.append("read_only_score")
        return _score(sample)

    monkeypatch.setattr(checkpoint_job, "connect", connect)
    monkeypatch.setattr(checkpoint_job, "writer_lock", writer)
    monkeypatch.setattr(checkpoint_job, "load_checkpoint_pair", load)
    monkeypatch.setattr(checkpoint_job, "attach_finalized_outcomes", attach_outcomes)
    monkeypatch.setattr(checkpoint_job, "build_checkpoint", build)
    args = [
        "--db",
        str(tmp_path / "db.duckdb"),
        "--contract",
        str(contract),
        "--output",
        str(tmp_path / "report.json"),
    ]
    if attach:
        args += ["--attach-outcomes", "--backup", str(tmp_path / "backup.duckdb")]
    assert checkpoint_job.main(args) == 0
    assert events == (
        [
            "reader_open",
            "pair_loaded",
            "reader_closed",
            "backup_then_writer",
            "authoritative_attach",
            "writer_closed",
            "reader_open",
            "read_only_score",
            "reader_closed",
        ]
        if attach
        else ["reader_open", "read_only_score", "reader_closed"]
    )


def test_attachment_requires_new_backup_before_database_access(tmp_path: Path) -> None:
    contract = tmp_path / "contract.yaml"
    contract.write_text(yaml.safe_dump(_sample()["contract"]), encoding="utf-8")
    args = [
        "--db",
        str(tmp_path / "missing.duckdb"),
        "--contract",
        str(contract),
        "--output",
        str(tmp_path / "report.json"),
        "--attach-outcomes",
    ]
    with pytest.raises(SystemExit):
        checkpoint_job.main(args)
    backup = tmp_path / "existing.duckdb"
    backup.write_bytes(b"immutable")
    with pytest.raises(ValueError, match="new backup"):
        checkpoint_job.main([*args, "--backup", str(backup)])
    assert backup.read_bytes() == b"immutable"


def test_real_ledger_projections_and_metadata_scored_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _sample(legs=(-2, 5))
    monkeypatch.setattr(sdp_checkpoint, "load_pair", lambda con, prediction_id: sample["pair"])
    instant = datetime(2026, 9, 14, 10, tzinfo=UTC)
    with duckdb.connect() as con:
        con.execute("SET TimeZone = 'UTC'")
        created: set[str] = set()

        def insert(table: str, row: Row) -> None:
            if table not in created:
                projections = ", ".join(f'? AS "{key}"' for key in row)
                con.execute(f"CREATE TABLE {table} AS SELECT {projections}", list(row.values()))
                created.add(table)
            else:
                columns = ", ".join(f'"{key}"' for key in row)
                con.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in row)})",
                    list(row.values()),
                )

        for role in ("primary", "shadow"):
            decisions = [{"fixture": f, "selector": "SDP_PRIMARY"} for f in (41, 42)]
            insert(
                "ledger_forecast_run",
                {
                    "run_id": sample["pair"][f"{role}_run_id"],
                    "commit_sha": sample["contract"]["forecast_emitter_sha"],
                    "worktree_clean": True,
                    "fixture_points_support_max": 34,
                    "component_modes": json.dumps(
                        {"football_environment.provenance": json.dumps({"decisions": decisions})}
                    ),
                },
            )
        for row in sample["players"]:
            insert(
                "ledger_prediction_player_gameweek",
                {
                    **{
                        key: row[key]
                        for key in (
                            "run_id",
                            "season",
                            "gw",
                            "code",
                            "position",
                            "team_id",
                            "team_code",
                            "expected_points",
                            "availability_adjusted_expected_points",
                            "distribution",
                        )
                    },
                    "fixture_ids": json.dumps(row["fixture_ids"]),
                    "web_name": "Synthetic",
                    "cold_start_player": False,
                    "transferred_no_rescale": False,
                    "availability_status": "a",
                    "availability_multiplier": 1.0,
                },
            )
        for row in sample["teams"]:
            insert(
                "ledger_prediction_team_fixture",
                {
                    **{
                        key: row[key]
                        for key in (
                            "run_id",
                            "season",
                            "gw",
                            "fixture",
                            "team_id",
                            "team_code",
                            "opponent_team_id",
                            "was_home",
                            "lambda_for",
                            "lambda_against",
                            "probability_clean_sheet",
                            "goals_for_distribution",
                        )
                    },
                    "kickoff_time": instant,
                    "stage_a_league_average_team": False,
                },
            )
            if row["role"] == "primary":
                insert(
                    "ledger_outcome_team_fixture",
                    {
                        "season": row["season"],
                        "fixture": row["fixture"],
                        "team_id": row["team_id"],
                        "attached_at": instant,
                        "goals_for": row["outcome"]["goals_for"],
                        "goals_against": row["outcome"]["goals_against"],
                    },
                )
        for fixture, actual in ((41, -2), (42, 5)):
            insert(
                "stg_fixture", {"season": "2026-27", "gw": 4, "fixture": fixture, "finished": True}
            )
            insert(
                "ledger_outcome_player_fixture",
                {
                    "season": "2026-27",
                    "fixture": fixture,
                    "code": 11,
                    "attached_at": instant,
                    "total_points_as_recorded": actual,
                    "points_under_rules_2026_27": actual,
                },
            )

        def retained_rows() -> Row:
            # Keep DuckDB timestamps as JSON text; no optional Python timezone adapter needed.
            return {
                table: con.execute(
                    f"SELECT CAST(to_json(t) AS VARCHAR) FROM {table} t ORDER BY 1"
                ).fetchall()
                for table in created
            }

        before = retained_rows()
        report = build_checkpoint(con, contract=sample["contract"], contract_sha256="c" * 64)
        assert report["status"] == "COMPLETE"
        assert report["players"]["primary"]["overall"]["signed_points"]["mae"] == 2
        assert report["players"]["primary"]["slices"]["cold_start"]["False"]["rows"] == 1
        assert before == retained_rows()


def test_five_gw_bootstrap_reuses_row_multiplicity_and_frozen_quantiles() -> None:
    rows = [
        {
            "season": "2026-27",
            "gw": gw,
            "difference": dict.fromkeys(
                ("log_score", "crps", "signed_absolute_error"), float(gw - 4)
            ),
        }
        for gw in range(4, 9)
        for _ in range(gw - 3)
    ]
    uncertainty = sdp_checkpoint._five_gw_uncertainty(
        rows, gameweeks=(4, 5, 6, 7, 8), finalized=[4, 5, 6, 7, 8], vintage_policy="fixed_origin"
    )
    assert len(uncertainty["draws"]) == 3125
    first, last = uncertainty["draws"][0], uncertainty["draws"][-1]
    assert first["sampled_gameweeks"] == [4] * 5
    assert first["rows_with_multiplicity"] == 5
    assert first["difference"]["crps"] == 0
    assert last["rows_with_multiplicity"] == 25
    assert last["difference"]["crps"] == 4
    draw = next(d for d in uncertainty["draws"] if d["sampled_gameweeks"] == [4, 4, 4, 4, 8])
    assert draw["rows_with_multiplicity"] == 9
    assert draw["difference"]["crps"] == pytest.approx(20 / 9)
    assert uncertainty["n_finalized_gameweeks"] == uncertainty["n_scored_gameweeks"] == 5
    assert all(0 < low < high < 4 for low, high in uncertainty["intervals_95"].values())


def test_uncertainty_waits_and_unimplemented_diagnostics_stay_null() -> None:
    report = _score(_sample(final=False))
    uncertainty = report["paired"]["players"]["uncertainty"]
    assert uncertainty["n_finalized_gameweeks"] == uncertainty["n_scored_gameweeks"] == 0
    assert all(value is None for value in uncertainty["intervals_95"].values())
    assert uncertainty["draws"] == []
    assert report["paired"]["players"]["overall"]["all_paired_losses_numerically_equal"] is None
    assert report["players"]["primary"]["availability_adjusted"]["metrics"] is None
    assert report["players"]["primary"]["forensic_component_attribution"]["labels"] is None
