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

The tables are all prefixed ``ledger_``:

* ``ledger_forecast_run`` -- one immutable row per recorded run. ``run_id`` is deterministic (a hash
  of the run's identity, so re-ingesting byte-identical input is recognised, never duplicated) and
  ``as_of`` is the knowledge time, the most important column in the schema.
* ``ledger_prediction_player_gameweek`` -- one row per ``(run_id, season, gw, code)``, the full
  artifact row including the distribution and all degradation flags. ``NULL`` stays ``NULL``.
* ``ledger_outcome_player_fixture`` -- a SEPARATE table at ``(season, code, fixture)`` grain, joined
  to predictions only at read time and only after a fixture is final. Recorded points and points
  replayed under ``scoring_2026_27`` are separately named columns and never conflated.
* ``ledger_outcome_team_fixture`` -- two reciprocal, immutable rows per finalized fixture, one
  from each club's perspective. Scores come directly from the official fixture payload, so own
  goals are represented and are never reconstructed from player events.

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


class InvalidTeamOutcomeError(LedgerError):
    """Team outcomes are not a complete, reciprocal two-sided fixture result."""


class OutcomeValueConflictError(LedgerError):
    """A finalized team outcome differs from its already-attached immutable value."""


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

CREATE TABLE IF NOT EXISTS ledger_prediction_player_fixture (
    run_id                      VARCHAR NOT NULL,
    season                      VARCHAR NOT NULL,
    gw                          INTEGER NOT NULL,
    fixture                     INTEGER NOT NULL,
    code                        INTEGER NOT NULL,
    kickoff_time                TIMESTAMPTZ NOT NULL,
    position                    VARCHAR NOT NULL,
    team_id                     INTEGER NOT NULL,
    team_code                   INTEGER,
    opponent_team_id            INTEGER NOT NULL,
    was_home                    BOOLEAN NOT NULL,
    expected_points             DOUBLE NOT NULL,
    expected_bonus              DOUBLE NOT NULL,
    distribution                DOUBLE[] NOT NULL,
    stage_a_league_average_team BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, season, fixture, code)
);

CREATE TABLE IF NOT EXISTS ledger_prediction_team_fixture (
    run_id                      VARCHAR NOT NULL,
    season                      VARCHAR NOT NULL,
    gw                          INTEGER NOT NULL,
    fixture                     INTEGER NOT NULL,
    kickoff_time                TIMESTAMPTZ NOT NULL,
    team_id                     INTEGER NOT NULL,
    team_code                   INTEGER,
    opponent_team_id            INTEGER NOT NULL,
    was_home                    BOOLEAN NOT NULL,
    lambda_for                  DOUBLE NOT NULL,
    lambda_against              DOUBLE NOT NULL,
    probability_clean_sheet     DOUBLE NOT NULL,
    goals_for_distribution      DOUBLE[] NOT NULL,
    stage_a_league_average_team BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, season, fixture, team_id)
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

CREATE TABLE IF NOT EXISTS ledger_outcome_team_fixture (
    season             VARCHAR NOT NULL,
    fixture            INTEGER NOT NULL,
    team_id            INTEGER NOT NULL,
    team_code          INTEGER,
    opponent_team_id   INTEGER NOT NULL,
    gw                  INTEGER NOT NULL,
    kickoff_time        TIMESTAMPTZ NOT NULL,
    was_home            BOOLEAN NOT NULL,
    goals_for           INTEGER NOT NULL,
    goals_against       INTEGER NOT NULL,
    attached_at         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (season, fixture, team_id)
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


@dataclass(frozen=True, slots=True)
class TeamLedgerOutcome:
    """One club's view of an official finalized fixture score.

    Rows are attached only as a reciprocal pair. ``team_code`` may be unknown because the
    season-scoped team id still identifies and validates both sides; NULL is preserved rather than
    fabricated.
    """

    season: str
    fixture: int
    team_id: int
    team_code: int | None
    opponent_team_id: int
    gw: int
    kickoff_time: datetime
    was_home: bool
    goals_for: int
    goals_against: int


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
    _insert_fixture_predictions(con, run_id, artifact)


def _insert_fixture_predictions(
    con: duckdb.DuckDBPyConnection, run_id: str, artifact: ProspectivePointsArtifact
) -> None:
    """Record the schema-version-2 fixture-grain rows, if the artifact carries them.

    A version-1 artifact has none, so this is a no-op and the vintage is still complete for its
    own schema version. Both tables share the run's transaction, so a vintage can never be half
    recorded at one grain and whole at another.
    """
    if artifact.player_fixture_rows:
        con.executemany(
            """
            INSERT INTO ledger_prediction_player_fixture (
                run_id, season, gw, fixture, code, kickoff_time, position, team_id, team_code,
                opponent_team_id, was_home, expected_points, expected_bonus, distribution,
                stage_a_league_average_team
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    run_id,
                    row.season,
                    row.gw,
                    row.fixture,
                    row.code,
                    row.kickoff_time,
                    row.position,
                    row.team_id,
                    row.team_code,
                    row.opponent_team_id,
                    row.was_home,
                    row.expected_points,
                    row.expected_bonus,
                    list(row.distribution),
                    row.stage_a_league_average_team,
                ]
                for row in artifact.player_fixture_rows
            ],
        )
    if artifact.team_fixture_rows:
        con.executemany(
            """
            INSERT INTO ledger_prediction_team_fixture (
                run_id, season, gw, fixture, kickoff_time, team_id, team_code, opponent_team_id,
                was_home, lambda_for, lambda_against, probability_clean_sheet,
                goals_for_distribution, stage_a_league_average_team
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    run_id,
                    row.season,
                    row.gw,
                    row.fixture,
                    row.kickoff_time,
                    row.team_id,
                    row.team_code,
                    row.opponent_team_id,
                    row.was_home,
                    row.lambda_for,
                    row.lambda_against,
                    row.probability_clean_sheet,
                    list(row.goals_for_distribution),
                    row.stage_a_league_average_team,
                ]
                for row in artifact.team_fixture_rows
            ],
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


def _validate_team_outcome_batch(outcomes: Sequence[TeamLedgerOutcome]) -> None:
    """Require exactly two reciprocal rows for every represented fixture."""
    fixtures: dict[tuple[str, int], list[TeamLedgerOutcome]] = {}
    seen: set[tuple[str, int, int]] = set()
    for outcome in outcomes:
        key = (outcome.season, outcome.fixture, outcome.team_id)
        if key in seen:
            raise InvalidTeamOutcomeError(f"duplicate team outcome row for {key}")
        seen.add(key)
        integer_values = {
            "fixture": outcome.fixture,
            "team_id": outcome.team_id,
            "opponent_team_id": outcome.opponent_team_id,
            "gw": outcome.gw,
            "goals_for": outcome.goals_for,
            "goals_against": outcome.goals_against,
        }
        for name, value in integer_values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidTeamOutcomeError(
                    f"team outcome {key} has non-integer {name}: {value!r}"
                )
        if outcome.team_code is not None and (
            isinstance(outcome.team_code, bool) or not isinstance(outcome.team_code, int)
        ):
            raise InvalidTeamOutcomeError(
                f"team outcome {key} has non-integer team_code: {outcome.team_code!r}"
            )
        if not isinstance(outcome.kickoff_time, datetime):
            raise InvalidTeamOutcomeError(f"team outcome {key} has invalid kickoff_time")
        if outcome.kickoff_time.tzinfo is None or outcome.kickoff_time.utcoffset() is None:
            raise InvalidTeamOutcomeError(f"team outcome {key} has a naive kickoff_time")
        if type(outcome.was_home) is not bool:  # bool is semantically load-bearing here
            raise InvalidTeamOutcomeError(f"team outcome {key} has invalid was_home")
        if outcome.team_id == outcome.opponent_team_id:
            raise InvalidTeamOutcomeError(f"team outcome {key} names itself as opponent")
        if outcome.goals_for < 0 or outcome.goals_against < 0:
            raise InvalidTeamOutcomeError(f"team outcome {key} has a negative score")
        fixtures.setdefault((outcome.season, outcome.fixture), []).append(outcome)

    for fixture_key, pair in fixtures.items():
        if len(pair) != 2:
            raise InvalidTeamOutcomeError(
                f"fixture {fixture_key} must have exactly two reciprocal team outcomes"
            )
        first, second = pair
        reciprocal = (
            first.team_id == second.opponent_team_id
            and second.team_id == first.opponent_team_id
            and first.was_home is not second.was_home
            and first.gw == second.gw
            and first.kickoff_time == second.kickoff_time
            and first.goals_for == second.goals_against
            and first.goals_against == second.goals_for
        )
        if not reciprocal:
            raise InvalidTeamOutcomeError(f"fixture {fixture_key} team outcomes are not reciprocal")


def _insert_player_outcomes(
    con: duckdb.DuckDBPyConnection,
    outcomes: Sequence[LedgerOutcome],
    stamp: datetime,
) -> None:
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


def _insert_team_outcomes(
    con: duckdb.DuckDBPyConnection,
    outcomes: Sequence[TeamLedgerOutcome],
    stamp: datetime,
) -> None:
    for outcome in outcomes:
        existing = con.execute(
            """
            SELECT 1 FROM ledger_outcome_team_fixture
            WHERE season = ? AND fixture = ? AND team_id = ?
            """,
            [outcome.season, outcome.fixture, outcome.team_id],
        ).fetchone()
        if existing is not None:
            key = (outcome.season, outcome.fixture, outcome.team_id)
            raise DuplicateRunError(f"team outcome for {key} already attached")
        con.execute(
            """
            INSERT INTO ledger_outcome_team_fixture (
                season, fixture, team_id, team_code, opponent_team_id, gw, kickoff_time,
                was_home, goals_for, goals_against, attached_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                outcome.season,
                outcome.fixture,
                outcome.team_id,
                outcome.team_code,
                outcome.opponent_team_id,
                outcome.gw,
                outcome.kickoff_time,
                outcome.was_home,
                outcome.goals_for,
                outcome.goals_against,
                stamp,
            ],
        )


def attach_outcome_batch(
    con: duckdb.DuckDBPyConnection,
    player_outcomes: Sequence[LedgerOutcome],
    team_outcomes: Sequence[TeamLedgerOutcome],
    *,
    attached_at: datetime | None = None,
) -> tuple[int, int]:
    """Atomically append new player rows and complete reciprocal team fixture pairs."""
    ensure_ledger_schema(con)
    _validate_team_outcome_batch(team_outcomes)
    stamp = attached_at or datetime.now(UTC)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("attached_at must be timezone-aware")
    con.execute("BEGIN TRANSACTION")
    try:
        _insert_player_outcomes(con, player_outcomes, stamp)
        _insert_team_outcomes(con, team_outcomes, stamp)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(player_outcomes), len(team_outcomes)


def attach_outcomes(
    con: duckdb.DuckDBPyConnection,
    outcomes: Sequence[LedgerOutcome],
    *,
    attached_at: datetime | None = None,
) -> int:
    """Attach new player-fixture outcomes; a duplicate key remains a strict refusal."""
    attached, _ = attach_outcome_batch(con, outcomes, (), attached_at=attached_at)
    return attached


def _team_outcome_values(outcome: TeamLedgerOutcome) -> tuple[object, ...]:
    """The immutable values a re-attachment must match exactly.

    `kickoff_time` is rendered as epoch microseconds to match the comparison query, which
    projects `epoch_us(kickoff_time)` rather than the TIMESTAMPTZ itself. DuckDB converts a
    fetched TIMESTAMPTZ into a Python datetime through `pytz`, which this project does not
    declare as a dependency (it pins `tzdata` for `zoneinfo`), so a clean install raised
    ModuleNotFoundError here. Microseconds carry no timezone name, so no IANA lookup happens --
    and comparing two integers is a stricter equality test than comparing two datetimes that
    could differ only in tzinfo representation.
    """
    return (
        outcome.team_code,
        outcome.opponent_team_id,
        outcome.gw,
        _epoch_microseconds(outcome.kickoff_time),
        outcome.was_home,
        outcome.goals_for,
        outcome.goals_against,
    )


def _epoch_microseconds(value: datetime) -> int:
    """An aware instant as exact epoch microseconds, matching DuckDB's `epoch_us()`."""
    return round(value.timestamp() * 1_000_000)


def attach_team_outcomes(
    con: duckdb.DuckDBPyConnection,
    outcomes: Sequence[TeamLedgerOutcome],
    *,
    attached_at: datetime | None = None,
) -> int:
    """Idempotently attach complete team results; changed repeats fail closed.

    A fixture is either wholly new or wholly present with exact values. A one-sided pre-existing
    fixture is treated as corruption and is not silently repaired.
    """
    ensure_ledger_schema(con)
    _validate_team_outcome_batch(outcomes)
    new_outcomes: list[TeamLedgerOutcome] = []
    grouped: dict[tuple[str, int], list[TeamLedgerOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault((outcome.season, outcome.fixture), []).append(outcome)
    for fixture_key, pair in grouped.items():
        existing_count = 0
        for outcome in pair:
            existing = con.execute(
                """
                SELECT team_code, opponent_team_id, gw, epoch_us(kickoff_time), was_home,
                       goals_for, goals_against
                FROM ledger_outcome_team_fixture
                WHERE season = ? AND fixture = ? AND team_id = ?
                """,
                [outcome.season, outcome.fixture, outcome.team_id],
            ).fetchone()
            if existing is None:
                continue
            existing_count += 1
            if tuple(existing) != _team_outcome_values(outcome):
                key = (outcome.season, outcome.fixture, outcome.team_id)
                raise OutcomeValueConflictError(
                    f"finalized team outcome for {key} differs from its attached immutable values"
                )
        if existing_count == 0:
            new_outcomes.extend(pair)
        elif existing_count != 2:
            raise OutcomeValueConflictError(
                f"finalized team outcome fixture {fixture_key} is only partly attached"
            )
    _, attached = attach_outcome_batch(con, (), new_outcomes, attached_at=attached_at)
    return attached
