"""Append-only prediction ledger.

Every pre-deadline forecast is recorded here as an immutable vintage. This is the one thing that
can lift the repository's structural "development-only" caveat: the historical evaluations use
unversioned, outcome-derived proxies for the target roster and the knowledge-time cutoff, which no
further archive work can remove -- only a forecast committed *before* a real deadline, with its
knowledge time and inputs pinned, can. Daily snapshots protect the inputs; this ledger protects the
commitment.

The ledger consumes the frozen prospective-points artifact (``fpl.artifacts.prospective_points``)
and nothing else -- it never reaches around that boundary into the models or the database to
re-derive a prediction, because the artifact boundary is what makes a recorded run auditable.

Three tables, all prefixed ``ledger_``:

* ``ledger_forecast_run`` -- one immutable row per recorded run. ``run_id`` is deterministic (a hash
  of the run's identity, so re-ingesting byte-identical input is recognised, never duplicated) and
  ``as_of`` is the knowledge time, the most important column in the schema.
* ``ledger_prediction_player_gameweek`` -- one row per ``(run_id, season, gw, code)``, the full
  artifact row including the distribution and all degradation flags. ``NULL`` stays ``NULL``.
* ``ledger_outcome_player_fixture`` -- a SEPARATE table at ``(season, code, fixture)`` grain, joined
  to predictions only at read time and only after a fixture is final. Recorded points and points
  replayed under ``scoring_2026_27`` are separately named columns and never conflated.

There is no update or delete path for a recorded prediction. A later run for the same
``(season, gw, code)`` creates a new vintage under a new ``run_id``; it never modifies an earlier
row.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fpl.artifacts.prospective_points import (
    ForecastArtifactManifest,
    ProspectivePointsArtifact,
    artifact_bytes,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import duckdb


class LedgerError(Exception):
    """The ledger was asked to do something that would break its append-only guarantee."""


class DuplicateRunError(LedgerError):
    """A run with this deterministic ``run_id`` is already recorded.

    Refused rather than silently overwritten: an operator re-running a job on an already recorded
    artifact must find out, and a recorded vintage is immutable by contract.
    """


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_forecast_run (
    run_id                      VARCHAR PRIMARY KEY,
    created_at                  TIMESTAMPTZ NOT NULL,
    as_of                       TIMESTAMPTZ NOT NULL,
    season                      VARCHAR NOT NULL,
    gw_from                     INTEGER NOT NULL,
    gw_to                       INTEGER NOT NULL,
    artifact_schema             VARCHAR NOT NULL,
    schema_version              INTEGER NOT NULL,
    status                      VARCHAR NOT NULL,
    commit_sha                  VARCHAR NOT NULL,
    database_sha256             VARCHAR NOT NULL,
    artifact_sha256             VARCHAR NOT NULL,
    base_seed                   BIGINT NOT NULL,
    monte_carlo_draws           INTEGER NOT NULL,
    fixture_points_support_max  INTEGER NOT NULL,
    freshness_cold_start        BOOLEAN NOT NULL,
    worktree_clean              BOOLEAN NOT NULL,
    row_count                   INTEGER NOT NULL,
    roster_size                 INTEGER NOT NULL,
    fixture_count               INTEGER NOT NULL,
    contract_identities         VARCHAR NOT NULL,
    component_modes             VARCHAR NOT NULL,
    bootstrap_capture_id        VARCHAR NOT NULL,
    bootstrap_known_at          TIMESTAMPTZ NOT NULL,
    bootstrap_payload_sha256    VARCHAR NOT NULL,
    schedule_capture_ids        VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_prediction_player_gameweek (
    run_id                                VARCHAR NOT NULL,
    season                                VARCHAR NOT NULL,
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
    fixture_ids                            VARCHAR NOT NULL,
    kickoff_times                          VARCHAR NOT NULL,
    expected_points                        DOUBLE NOT NULL,
    availability_adjusted_expected_points  DOUBLE NOT NULL,
    expected_bonus                         DOUBLE NOT NULL,
    distribution                           DOUBLE[] NOT NULL,
    cold_start_player                      BOOLEAN NOT NULL,
    stage_a_league_average_team            BOOLEAN NOT NULL,
    attacking_signal_cold_start            BOOLEAN NOT NULL,
    assist_signal_cold_start               BOOLEAN NOT NULL,
    transferred_no_rescale                 BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, season, gw, code)
);

CREATE TABLE IF NOT EXISTS ledger_outcome_player_fixture (
    season                     VARCHAR NOT NULL,
    code                       INTEGER NOT NULL,
    fixture                    INTEGER NOT NULL,
    attached_at                TIMESTAMPTZ NOT NULL,
    total_points_as_recorded   INTEGER,
    points_under_rules_2026_27 INTEGER,
    PRIMARY KEY (season, code, fixture)
);
"""


@dataclass(frozen=True, slots=True)
class LedgerOutcome:
    """A realised outcome for one player-fixture, attached only after the fixture is final.

    ``total_points_as_recorded`` and ``points_under_rules_2026_27`` are kept separate on purpose:
    the recorded FPL points and the points replayed under this repository's scoring config are
    different quantities (R1) and must never be conflated.
    """

    season: str
    code: int
    fixture: int
    total_points_as_recorded: int | None
    points_under_rules_2026_27: int | None


def ensure_ledger_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the ledger tables if absent. Idempotent -- every statement is CREATE IF NOT EXISTS."""
    con.execute(_SCHEMA)


def derive_run_id(manifest: ForecastArtifactManifest, artifact_sha256: str) -> str:
    """A deterministic, stable id for a forecast run.

    Built from the run's identity fields, with ``artifact_sha256`` (the canonical hash of the whole
    manifest and every row) included so that any change to any field or row yields a different id,
    while byte-identical input yields the same id. It never depends on wall-clock time, so
    re-generating the same forecast and re-ingesting it is recognised as the same run.
    """
    identity = {
        "artifact_sha256": artifact_sha256,
        "as_of": manifest.as_of.isoformat(),
        "season": manifest.season,
        "gw_from": manifest.gw_from,
        "gw_to": manifest.gw_to,
        "commit_sha": manifest.commit_sha,
        "database_sha256": manifest.database_sha256,
        "base_seed": manifest.base_seed,
        "schema_version": manifest.schema_version,
    }
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_exists(con: duckdb.DuckDBPyConnection, run_id: str) -> bool:
    row = con.execute("SELECT 1 FROM ledger_forecast_run WHERE run_id = ?", [run_id]).fetchone()
    return row is not None


def _insert_run(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    manifest: ForecastArtifactManifest,
    artifact_sha256: str,
    created_at: datetime,
) -> None:
    contract_identities = json.dumps(
        {
            name: {"name": c.name, "version": c.version, "sha256": c.sha256}
            for name, c in sorted(manifest.contracts.items())
        },
        sort_keys=True,
    )
    con.execute(
        """
        INSERT INTO ledger_forecast_run (
            run_id, created_at, as_of, season, gw_from, gw_to, artifact_schema, schema_version,
            status, commit_sha, database_sha256, artifact_sha256, base_seed, monte_carlo_draws,
            fixture_points_support_max, freshness_cold_start, worktree_clean, row_count,
            roster_size, fixture_count, contract_identities, component_modes, bootstrap_capture_id,
            bootstrap_known_at, bootstrap_payload_sha256, schedule_capture_ids
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            created_at,
            manifest.as_of,
            manifest.season,
            manifest.gw_from,
            manifest.gw_to,
            manifest.artifact_schema,
            manifest.schema_version,
            manifest.status,
            manifest.commit_sha,
            manifest.database_sha256,
            artifact_sha256,
            manifest.base_seed,
            manifest.monte_carlo_draws,
            manifest.fixture_points_support_max,
            manifest.freshness_cold_start,
            manifest.worktree_clean,
            manifest.row_count,
            manifest.roster_size,
            manifest.fixture_count,
            contract_identities,
            json.dumps(manifest.component_modes, sort_keys=True),
            manifest.live_inputs.bootstrap_capture_id,
            manifest.live_inputs.bootstrap_known_at,
            manifest.live_inputs.bootstrap_payload_sha256,
            json.dumps(list(manifest.live_inputs.schedule_capture_ids)),
        ],
    )


def _insert_predictions(
    con: duckdb.DuckDBPyConnection, run_id: str, artifact: ProspectivePointsArtifact
) -> None:
    params = [
        [
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
            json.dumps([kickoff.isoformat() for kickoff in row.kickoff_times]),
            row.expected_points,
            row.availability_adjusted_expected_points,
            row.expected_bonus,
            list(row.distribution),
            row.cold_start_player,
            row.stage_a_league_average_team,
            row.attacking_signal_cold_start,
            row.assist_signal_cold_start,
            row.transferred_no_rescale,
        ]
        for row in artifact.rows
    ]
    con.executemany(
        """
        INSERT INTO ledger_prediction_player_gameweek (
            run_id, season, gw, code, web_name, position, team_id, team_code, now_cost,
            selected_by_percent, availability_status, chance_of_playing, availability_multiplier,
            fixture_ids, kickoff_times, expected_points, availability_adjusted_expected_points,
            expected_bonus, distribution, cold_start_player, stage_a_league_average_team,
            attacking_signal_cold_start, assist_signal_cold_start, transferred_no_rescale
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        params,
    )


def record_forecast(
    con: duckdb.DuckDBPyConnection,
    artifact: ProspectivePointsArtifact,
    *,
    created_at: datetime | None = None,
) -> str:
    """Record a forecast as a new immutable vintage and return its ``run_id``.

    Refuses to overwrite an existing ``run_id`` (raises :class:`DuplicateRunError`). Fails closed:
    the run row and every prediction row are written inside one transaction, so a mid-ingest error
    rolls the whole thing back and leaves the ledger unchanged.
    """
    ensure_ledger_schema(con)
    artifact_sha256 = hashlib.sha256(artifact_bytes(artifact)).hexdigest()
    run_id = derive_run_id(artifact.manifest, artifact_sha256)
    if run_exists(con, run_id):
        raise DuplicateRunError(f"run {run_id} is already recorded; the ledger is append-only")

    stamp = created_at or datetime.now(UTC)
    con.execute("BEGIN TRANSACTION")
    try:
        _insert_run(con, run_id, artifact.manifest, artifact_sha256, stamp)
        _insert_predictions(con, run_id, artifact)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return run_id


def attach_outcomes(
    con: duckdb.DuckDBPyConnection,
    outcomes: Sequence[LedgerOutcome],
    *,
    attached_at: datetime | None = None,
) -> int:
    """Attach realised outcomes at ``(season, code, fixture)`` grain, after fixtures are final.

    Predictions are never touched: outcomes live in their own table and are joined to predictions
    only at read time. Attaching an outcome that already exists is refused, preserving the same
    append-only discipline as the prediction rows. Returns the number of rows inserted.
    """
    ensure_ledger_schema(con)
    stamp = attached_at or datetime.now(UTC)
    con.execute("BEGIN TRANSACTION")
    try:
        for outcome in outcomes:
            existing = con.execute(
                """
                SELECT 1 FROM ledger_outcome_player_fixture
                WHERE season = ? AND code = ? AND fixture = ?
                """,
                [outcome.season, outcome.code, outcome.fixture],
            ).fetchone()
            if existing is not None:
                key = (outcome.season, outcome.code, outcome.fixture)
                raise DuplicateRunError(f"outcome for {key} already attached")
            con.execute(
                """
                INSERT INTO ledger_outcome_player_fixture (
                    season, code, fixture, attached_at, total_points_as_recorded,
                    points_under_rules_2026_27
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    outcome.season,
                    outcome.code,
                    outcome.fixture,
                    stamp,
                    outcome.total_points_as_recorded,
                    outcome.points_under_rules_2026_27,
                ],
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(outcomes)
