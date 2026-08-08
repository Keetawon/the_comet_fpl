"""The append-only prediction ledger.

Deterministic and network-free: a small synthetic artifact is built from the frozen contract types
and recorded into an in-memory DuckDB. The tests pin the append-only guarantees -- exact round-trip,
duplicate refusal, independent vintages, separate outcome attachment, NULL preservation, failure
atomicity, and deterministic run ids.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    write_artifact_atomic,
)
from fpl.jobs.record_forecast import main as record_forecast_cli
from fpl.storage import ledger
from fpl.storage.db import connect
from fpl.storage.ledger import (
    DuplicateRunError,
    LedgerOutcome,
    attach_outcomes,
    record_forecast,
)

HASH = "a" * 64
AS_OF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def _row(
    *,
    code: int,
    gw: int = 1,
    mean: float = 0.8,
    web_name: str | None = "Player",
    team_code: int | None = 100,
    now_cost: int | None = 50,
) -> ForecastArtifactRow:
    distribution = (1.0 - mean, mean)  # E = mean over {0, 1}
    return ForecastArtifactRow(
        season="2026-27",
        gw=gw,
        code=code,
        web_name=web_name,
        position="MID",
        team_id=7,
        team_code=team_code,
        now_cost=now_cost,
        selected_by_percent=None,
        availability_status="a",
        chance_of_playing=None,
        availability_multiplier=1.0,
        fixture_ids=(1000 + code,),
        kickoff_times=(datetime(2026, 8, 22, 14, tzinfo=UTC),),
        expected_points=mean,
        availability_adjusted_expected_points=mean,
        expected_bonus=0.0,
        distribution=distribution,
        cold_start_player=False,
        stage_a_league_average_team=False,
        attacking_signal_cold_start=False,
        assist_signal_cold_start=False,
        transferred_no_rescale=False,
    )


def _artifact(
    rows: tuple[ForecastArtifactRow, ...],
    *,
    base_seed: int = 1,
    as_of: datetime = AS_OF,
) -> ProspectivePointsArtifact:
    roster = len({row.code for row in rows})
    horizon = len({row.gw for row in rows})
    manifest = ForecastArtifactManifest(
        as_of=as_of,
        season="2026-27",
        gw_from=1,
        gw_to=horizon,
        row_count=len(rows),
        roster_size=roster,
        fixture_count=len(rows),
        monte_carlo_draws=100,
        base_seed=base_seed,
        fixture_points_support_max=40,
        freshness_cold_start=True,
        commit_sha="deadbeef",
        database_sha256=HASH,
        contracts={"synthetic": ContractIdentity(name="synthetic", version="1", sha256=HASH)},
        component_modes={"minutes": "shrunk"},
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="cap-1",
            bootstrap_known_at=datetime(2026, 8, 20, tzinfo=UTC),
            bootstrap_payload_sha256=HASH,
            schedule_capture_ids=("cap-1",),
        ),
    )
    return ProspectivePointsArtifact(manifest=manifest, rows=rows)


def test_a_recorded_run_round_trips_exactly() -> None:
    con = connect(":memory:")
    artifact = _artifact((_row(code=11, mean=0.8), _row(code=12, mean=0.4)))
    run_id = record_forecast(con, artifact)

    (run_count,) = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    assert run_count == 1
    # as_of is the knowledge time; assert it is stored verbatim via a SQL predicate (reading a
    # TIMESTAMPTZ back into Python would require pytz, which the environment does not carry).
    (matched, season) = con.execute(
        "SELECT (as_of = ?), season FROM ledger_forecast_run WHERE run_id = ?",
        [AS_OF, run_id],
    ).fetchone()
    assert matched is True
    assert season == "2026-27"

    for source in artifact.rows:
        gw, code, dist, exp, mult = con.execute(
            """
            SELECT gw, code, distribution, expected_points, availability_multiplier
            FROM ledger_prediction_player_gameweek
            WHERE run_id = ? AND season = ? AND gw = ? AND code = ?
            """,
            [run_id, source.season, source.gw, source.code],
        ).fetchone()
        assert (gw, code) == (source.gw, source.code)
        assert tuple(dist) == source.distribution  # distribution round-trips exactly
        assert exp == pytest.approx(source.expected_points)
        assert mult == source.availability_multiplier
    con.close()


def test_reingesting_an_existing_run_is_refused() -> None:
    con = connect(":memory:")
    artifact = _artifact((_row(code=11),))
    record_forecast(con, artifact)
    with pytest.raises(DuplicateRunError):
        record_forecast(con, artifact)
    (run_count,) = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    (pred_count,) = con.execute("SELECT count(*) FROM ledger_prediction_player_gameweek").fetchone()
    assert run_count == 1  # the refusal wrote nothing
    assert pred_count == 1
    con.close()


def test_a_second_vintage_does_not_touch_the_first() -> None:
    con = connect(":memory:")
    first = _artifact((_row(code=11, mean=0.8),), base_seed=1)
    second = _artifact((_row(code=11, mean=0.3),), base_seed=2)  # same (season, gw, code), new run
    run_a = record_forecast(con, first)
    run_b = record_forecast(con, second)
    assert run_a != run_b

    (run_count,) = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    assert run_count == 2
    # The earlier vintage's prediction is unchanged by the later one.
    (dist_a,) = con.execute(
        """
        SELECT distribution FROM ledger_prediction_player_gameweek
        WHERE run_id = ? AND code = 11 AND gw = 1
        """,
        [run_a],
    ).fetchone()
    assert tuple(dist_a) == (1.0 - 0.8, 0.8)
    con.close()


def test_outcomes_attach_separately_and_recorded_vs_replayed_stay_named() -> None:
    con = connect(":memory:")
    artifact = _artifact((_row(code=11),))
    run_id = record_forecast(con, artifact)

    attached = attach_outcomes(
        con,
        [
            LedgerOutcome(
                season="2026-27",
                code=11,
                fixture=1011,
                total_points_as_recorded=6,
                points_under_rules_2026_27=7,
            )
        ],
    )
    assert attached == 1
    recorded, replayed = con.execute(
        """
        SELECT total_points_as_recorded, points_under_rules_2026_27
        FROM ledger_outcome_player_fixture WHERE season = ? AND code = 11 AND fixture = 1011
        """,
        ["2026-27"],
    ).fetchone()
    assert (recorded, replayed) == (6, 7)  # kept as separate, differently named quantities

    # Predictions are untouched by attaching an outcome.
    (pred_count,) = con.execute(
        "SELECT count(*) FROM ledger_prediction_player_gameweek WHERE run_id = ?", [run_id]
    ).fetchone()
    assert pred_count == 1

    # A second attach for the same player-fixture is refused (append-only).
    with pytest.raises(DuplicateRunError):
        attach_outcomes(
            con,
            [
                LedgerOutcome(
                    season="2026-27",
                    code=11,
                    fixture=1011,
                    total_points_as_recorded=2,
                    points_under_rules_2026_27=2,
                )
            ],
        )
    con.close()


def test_nulls_survive_as_nulls() -> None:
    con = connect(":memory:")
    artifact = _artifact((_row(code=11, web_name=None, team_code=None, now_cost=None),))
    run_id = record_forecast(con, artifact)
    web_name, team_code, now_cost, selected = con.execute(
        """
        SELECT web_name, team_code, now_cost, selected_by_percent
        FROM ledger_prediction_player_gameweek WHERE run_id = ? AND code = 11
        """,
        [run_id],
    ).fetchone()
    assert web_name is None and team_code is None and now_cost is None and selected is None
    con.close()


def test_a_mid_ingest_failure_leaves_the_ledger_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    con = connect(":memory:")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure after the run row was written")

    monkeypatch.setattr(ledger, "_insert_predictions", boom)
    artifact = _artifact((_row(code=11), _row(code=12)))
    with pytest.raises(RuntimeError, match="simulated failure"):
        record_forecast(con, artifact)

    (run_count,) = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    (pred_count,) = con.execute("SELECT count(*) FROM ledger_prediction_player_gameweek").fetchone()
    assert run_count == 0  # the run row was rolled back with the predictions
    assert pred_count == 0
    con.close()


def test_run_id_is_stable_across_byte_identical_input_and_differs_on_any_change() -> None:
    rows = (_row(code=11, mean=0.8),)
    first = _artifact(rows, base_seed=1, as_of=AS_OF)
    identical = _artifact((_row(code=11, mean=0.8),), base_seed=1, as_of=AS_OF)
    changed_seed = _artifact(rows, base_seed=2, as_of=AS_OF)
    changed_as_of = _artifact(rows, base_seed=1, as_of=datetime(2026, 8, 21, 17, 31, tzinfo=UTC))
    changed_row = _artifact((_row(code=11, mean=0.9),), base_seed=1, as_of=AS_OF)

    def _id(artifact: ProspectivePointsArtifact) -> str:
        import hashlib

        from fpl.artifacts.prospective_points import artifact_bytes

        return ledger.derive_run_id(
            artifact.manifest, hashlib.sha256(artifact_bytes(artifact)).hexdigest()
        )

    base = _id(first)
    assert _id(identical) == base  # byte-identical input -> same id
    assert _id(changed_seed) != base
    assert _id(changed_as_of) != base
    assert _id(changed_row) != base  # a changed distribution flips the artifact hash


def test_cli_records_and_is_idempotent(tmp_path: Path) -> None:
    artifact = _artifact((_row(code=11), _row(code=12)))
    path = tmp_path / "forecast.jsonl"
    write_artifact_atomic(path, artifact)
    db = tmp_path / "ledger.duckdb"

    assert record_forecast_cli([str(path), "--db", str(db)]) == 0
    assert record_forecast_cli([str(path), "--db", str(db)]) == 0  # idempotent no-op

    con = connect(db)
    (run_count,) = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    (pred_count,) = con.execute("SELECT count(*) FROM ledger_prediction_player_gameweek").fetchone()
    assert run_count == 1  # the second run did not duplicate the vintage
    assert pred_count == 2
    # The stored contract identities round-trip as JSON.
    (contracts_json,) = con.execute(
        "SELECT contract_identities FROM ledger_forecast_run"
    ).fetchone()
    assert json.loads(contracts_json)["synthetic"]["version"] == "1"
    con.close()
