"""DuckDB storage and append-only ledger for prospective prediction artifacts.

The prediction ledger retains every forecast run vintage with its point-in-time
knowledge cutoff (`as_of`), input hashes, component/contract identities, and stable
player-gameweek distributions. Historical prediction vintages are immutable and never
overwritten or updated. Actual match outcomes land in a separate outcome table.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import duckdb

from fpl.artifacts.prospective_points import (
    ForecastArtifactManifest,
    ProspectivePointsArtifact,
)


class DuplicateRunError(ValueError):
    """Refused to re-ingest an existing run_id into the ledger."""


_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS ledger_forecast_run (
    run_id                     VARCHAR PRIMARY KEY,
    created_at                 TIMESTAMPTZ NOT NULL,
    as_of                      TIMESTAMPTZ NOT NULL,
    season                     VARCHAR NOT NULL,
    gw_from                    INTEGER NOT NULL,
    gw_to                      INTEGER NOT NULL,
    commit_sha                 VARCHAR NOT NULL,
    database_sha256            VARCHAR NOT NULL,
    artifact_sha256            VARCHAR NOT NULL,
    base_seed                  BIGINT NOT NULL,
    monte_carlo_draws          INTEGER NOT NULL,
    fixture_points_support_max INTEGER NOT NULL,
    row_count                  INTEGER NOT NULL,
    roster_size                INTEGER NOT NULL,
    fixture_count              INTEGER NOT NULL,
    contract_identities        JSON NOT NULL,
    bootstrap_capture_id       VARCHAR NOT NULL,
    bootstrap_payload_sha256   VARCHAR NOT NULL,
    schedule_capture_ids       JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_prediction_player_gameweek (
    run_id                                 VARCHAR NOT NULL,
    season                                 VARCHAR NOT NULL,
    gw                                     INTEGER NOT NULL,
    code                                   INTEGER NOT NULL,
    web_name                               VARCHAR,
    position                               VARCHAR NOT NULL,
    team_id                                INTEGER NOT NULL,
    team_code                              INTEGER,
    now_cost                               INTEGER,
    selected_by_percent                    DOUBLE,
    availability_status                    VARCHAR NOT NULL,
    chance_of_playing                      DOUBLE,
    availability_multiplier                DOUBLE NOT NULL,
    fixture_ids                            JSON NOT NULL,
    kickoff_times                          JSON NOT NULL,
    expected_points                        DOUBLE NOT NULL,
    availability_adjusted_expected_points DOUBLE NOT NULL,
    expected_bonus                         DOUBLE NOT NULL,
    distribution                           DOUBLE[] NOT NULL,
    cold_start_player                      BOOLEAN NOT NULL,
    stage_a_league_average_team            BOOLEAN NOT NULL,
    attacking_signal_cold_start            BOOLEAN NOT NULL,
    assist_signal_cold_start               BOOLEAN NOT NULL,
    transferred_no_rescale                 BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, season, gw, code),
    FOREIGN KEY (run_id) REFERENCES ledger_forecast_run(run_id)
);

CREATE TABLE IF NOT EXISTS ledger_outcome_player_fixture (
    season                   VARCHAR NOT NULL,
    code                     INTEGER NOT NULL,
    fixture                  INTEGER NOT NULL,
    attached_at              TIMESTAMPTZ NOT NULL,
    total_points_as_recorded INTEGER,
    points_under_rules_2026_27 INTEGER,
    PRIMARY KEY (season, code, fixture)
);
"""


def ensure_ledger_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create ledger tables if they do not already exist. Idempotent DDL."""
    con.execute(_LEDGER_DDL)


def compute_run_id(manifest: ForecastArtifactManifest) -> str:
    """Derive a stable, deterministic run ID by hashing manifest identity fields.

    Re-ingesting an identical artifact produces the same run_id. Any change in
    knowledge time (as_of), Git commit, database state, seeds, contracts, or inputs
    yields a distinct run_id.
    """
    contracts_dict = {
        k: {"name": v.name, "version": v.version, "sha256": v.sha256}
        for k, v in sorted(manifest.contracts.items())
    }
    identity_payload = {
        "as_of": manifest.as_of.isoformat(),
        "season": manifest.season,
        "gw_from": manifest.gw_from,
        "gw_to": manifest.gw_to,
        "commit_sha": manifest.commit_sha,
        "database_sha256": manifest.database_sha256,
        "base_seed": manifest.base_seed,
        "monte_carlo_draws": manifest.monte_carlo_draws,
        "fixture_points_support_max": manifest.fixture_points_support_max,
        "row_count": manifest.row_count,
        "roster_size": manifest.roster_size,
        "fixture_count": manifest.fixture_count,
        "freshness_cold_start": manifest.freshness_cold_start,
        "worktree_clean": manifest.worktree_clean,
        "contracts": contracts_dict,
        "component_modes": dict(sorted(manifest.component_modes.items())),
        "bootstrap_capture_id": manifest.live_inputs.bootstrap_capture_id,
        "bootstrap_payload_sha256": manifest.live_inputs.bootstrap_payload_sha256,
        "schedule_capture_ids": list(manifest.live_inputs.schedule_capture_ids),
    }
    canonical_json = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def record_forecast_artifact(
    con: duckdb.DuckDBPyConnection,
    artifact: ProspectivePointsArtifact,
    artifact_sha256: str,
    *,
    created_at: datetime | None = None,
) -> str:
    """Record a prospective forecast artifact into the prediction ledger.

    Re-ingesting an existing run_id raises DuplicateRunError to strictly prevent
    accidental duplication or silent mutation of committed historical forecasts.

    Transaction atomicity is enforced: any failure mid-ingest rolls back the
    transaction, leaving the ledger unmodified.
    """
    ensure_ledger_tables(con)
    manifest = artifact.manifest
    run_id = compute_run_id(manifest)

    # Check for existing run_id before opening transaction
    existing = con.execute(
        "SELECT count(*) FROM ledger_forecast_run WHERE run_id = ?", [run_id]
    ).fetchone()
    if existing and existing[0] > 0:
        raise DuplicateRunError(f"Run ID {run_id} already exists in the ledger. Re-ingest refused.")

    ingest_time = created_at if created_at is not None else datetime.now(UTC)

    contracts_json = json.dumps(
        {k: v.model_dump(mode="json") for k, v in sorted(manifest.contracts.items())},
        sort_keys=True,
    )
    schedule_ids_json = json.dumps(list(manifest.live_inputs.schedule_capture_ids))

    run_row = (
        run_id,
        ingest_time,
        manifest.as_of,
        manifest.season,
        manifest.gw_from,
        manifest.gw_to,
        manifest.commit_sha,
        manifest.database_sha256,
        artifact_sha256,
        manifest.base_seed,
        manifest.monte_carlo_draws,
        manifest.fixture_points_support_max,
        manifest.row_count,
        manifest.roster_size,
        manifest.fixture_count,
        contracts_json,
        manifest.live_inputs.bootstrap_capture_id,
        manifest.live_inputs.bootstrap_payload_sha256,
        schedule_ids_json,
    )

    pred_rows: list[tuple[Any, ...]] = []
    for row in artifact.rows:
        pred_rows.append(
            (
                run_id,
                row.season,
                row.gw,
                row.code,
                row.web_name,
                row.position,
                row.team_id,
                row.team_code,
                row.now_cost,
                row.selected_by_percent,
                row.availability_status,
                row.chance_of_playing,
                row.availability_multiplier,
                json.dumps(list(row.fixture_ids)),
                json.dumps([t.isoformat() for t in row.kickoff_times]),
                row.expected_points,
                row.availability_adjusted_expected_points,
                row.expected_bonus,
                list(row.distribution),
                row.cold_start_player,
                row.stage_a_league_average_team,
                row.attacking_signal_cold_start,
                row.assist_signal_cold_start,
                row.transferred_no_rescale,
            )
        )

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            """
            INSERT INTO ledger_forecast_run (
                run_id, created_at, as_of, season, gw_from, gw_to,
                commit_sha, database_sha256, artifact_sha256, base_seed,
                monte_carlo_draws, fixture_points_support_max, row_count,
                roster_size, fixture_count, contract_identities,
                bootstrap_capture_id, bootstrap_payload_sha256, schedule_capture_ids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            run_row,
        )

        con.executemany(
            """
            INSERT INTO ledger_prediction_player_gameweek (
                run_id, season, gw, code, web_name, position, team_id, team_code,
                now_cost, selected_by_percent, availability_status, chance_of_playing,
                availability_multiplier, fixture_ids, kickoff_times, expected_points,
                availability_adjusted_expected_points, expected_bonus, distribution,
                cold_start_player, stage_a_league_average_team,
                attacking_signal_cold_start, assist_signal_cold_start,
                transferred_no_rescale
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            pred_rows,
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    return run_id


def attach_fixture_outcomes(
    con: duckdb.DuckDBPyConnection,
    season: str,
    outcomes: list[dict[str, Any]],
    *,
    attached_at: datetime | None = None,
) -> int:
    """Attach finalized fixture outcomes into ledger_outcome_player_fixture.

    Outcomes land in a separate table and are joined at read time. They never mutate
    or overwrite existing prediction rows. Points under contemporaneous rules and
    replayed 2026/27 rules remain separately named.
    """
    ensure_ledger_tables(con)
    attach_time = attached_at if attached_at is not None else datetime.now(UTC)

    rows_to_insert: list[tuple[Any, ...]] = []
    for item in outcomes:
        rows_to_insert.append(
            (
                season,
                item["code"],
                item["fixture"],
                attach_time,
                item.get("total_points_as_recorded"),
                item.get("points_under_rules_2026_27"),
            )
        )

    if not rows_to_insert:
        return 0

    con.execute("BEGIN TRANSACTION")
    try:
        con.executemany(
            """
            INSERT INTO ledger_outcome_player_fixture (
                season, code, fixture, attached_at,
                total_points_as_recorded, points_under_rules_2026_27
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (season, code, fixture) DO UPDATE SET
                attached_at = EXCLUDED.attached_at,
                total_points_as_recorded = EXCLUDED.total_points_as_recorded,
                points_under_rules_2026_27 = EXCLUDED.points_under_rules_2026_27
            """,
            rows_to_insert,
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    return len(rows_to_insert)
