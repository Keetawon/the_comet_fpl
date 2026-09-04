"""Select finalized historical/live outcomes and append them to immutable ledgers.

Player outcomes remain at ``(season, code, fixture)``. Team outcomes are official fixture scores
stored as two reciprocal rows at ``(season, fixture, team_id)``; they are never reconstructed from
player goals because that would omit own goals. Historical marts and current live captures are
kept separate at ingest, then merged here with historical keys taking precedence so one real-world
outcome cannot be attached twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fpl.config import load_scoring_rules
from fpl.models.scoring import calculate_points
from fpl.storage.ledger import (
    LedgerOutcome,
    TeamLedgerOutcome,
    attach_outcome_batch,
    ensure_ledger_schema,
)
from fpl.types import PlayerMatchStats, Position

if TYPE_CHECKING:
    import duckdb


class OutcomeAttachmentError(Exception):
    """An outcome payload cannot be attached without breaking the ledger contract."""


class OutcomeSourceError(OutcomeAttachmentError):
    """The sources do not provide a valid finalized fixture outcome."""


class UnfinalizedOutcomeError(OutcomeSourceError):
    """A past player-fixture has no authoritative finalized-fixture signal."""


class NullOutcomeError(OutcomeSourceError):
    """A finalized fixture is missing a required outcome value."""


class DuplicateOutcomeSourceError(OutcomeSourceError):
    """An outcome source violates its declared fixture grain."""


class OutcomeConflictError(OutcomeAttachmentError):
    """A re-presented finalized outcome differs from its immutable attached value."""


@dataclass(frozen=True, slots=True)
class OutcomeAttachmentResult:
    """Accounting for one atomic player-and-team attachment attempt.

    The original three fields retain their player-outcome meaning for compatibility. Team counts
    are explicit additions, so old callers do not silently change interpretation.
    """

    selected: int
    attached: int
    already_attached: int
    team_selected: int = 0
    team_attached: int = 0
    team_already_attached: int = 0


def _require_aware(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _required_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OutcomeSourceError(f"{name} must be an integer, got {value!r}")
    return value


def _optional_int(value: object, *, name: str) -> int | None:
    return None if value is None else _required_int(value, name=name)


def _historical_player_rows(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime, season: str | None
) -> list[tuple[object, ...]]:
    where = ["t.kickoff_time < ?"]
    params: list[object] = [as_of]
    if season is not None:
        where.append("t.season = ?")
        params.append(season)
    return con.execute(
        f"""
        SELECT
            t.season,
            t.code,
            t.fixture,
            f.fixture AS fixture_source,
            f.finished,
            t.total_points_as_recorded,
            t.points_under_rules_2026_27
        FROM mart_target_player_fixture AS t
        LEFT JOIN stg_fixture AS f
          ON f.season = t.season
         AND f.fixture = t.fixture
        WHERE {" AND ".join(where)}
        ORDER BY t.season, t.code, t.fixture
        """,
        params,
    ).fetchall()


_LIVE_COMPONENT_COLUMNS = (
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "penalties_saved",
    "penalties_missed",
    "own_goals",
    "yellow_cards",
    "red_cards",
    "bonus",
    "defensive_contribution",
)


def _live_player_rows(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime, season: str | None
) -> list[tuple[object, ...]]:
    fixture_filter = "AND season = ?" if season is not None else ""
    player_filter = "AND season = ?" if season is not None else ""
    params: list[object] = [as_of]
    if season is not None:
        params.append(season)
    params.append(as_of)
    if season is not None:
        params.append(season)
    params.append(as_of)
    components = ",\n            ".join(f"p.{column}" for column in _LIVE_COMPONENT_COLUMNS)
    return con.execute(
        f"""
        WITH latest_fixture AS (
            SELECT * EXCLUDE (version_rank)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY season, fixture
                    ORDER BY known_at DESC, capture_id DESC
                ) AS version_rank
                FROM stg_live_fixture_version
                WHERE known_at <= ? {fixture_filter}
            )
            WHERE version_rank = 1
        ),
        latest_player AS (
            SELECT * EXCLUDE (version_rank)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY season, code, fixture
                    ORDER BY known_at DESC, capture_id DESC
                ) AS version_rank
                FROM stg_live_player_fixture_version
                WHERE known_at <= ? {player_filter}
            )
            WHERE version_rank = 1
        )
        SELECT
            p.season,
            p.code,
            p.fixture,
            f.fixture AS fixture_source,
            f.finished,
            p.total_points,
            p.position,
            {components}
        FROM latest_player AS p
        LEFT JOIN latest_fixture AS f
          ON f.season = p.season
         AND f.fixture = p.fixture
        WHERE p.kickoff_time < ?
          AND NOT EXISTS (
              SELECT 1
              FROM mart_target_player_fixture AS historic
              WHERE historic.season = p.season
                AND historic.code = p.code
                AND historic.fixture = p.fixture
          )
        ORDER BY p.season, p.code, p.fixture
        """,
        params,
    ).fetchall()


def select_finalized_outcomes(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str | None = None,
) -> list[LedgerOutcome]:
    """Select finalized historical and current-live player-fixture outcomes."""
    _require_aware(as_of, name="as_of")
    outcomes: list[LedgerOutcome] = []
    seen: set[tuple[str, int, int]] = set()

    for (
        source_season,
        source_code,
        source_fixture,
        fixture_source,
        finished,
        recorded_points,
        replayed_points,
    ) in _historical_player_rows(con, as_of=as_of, season=season):
        key = (
            str(source_season),
            _required_int(source_code, name="historical player code"),
            _required_int(source_fixture, name="historical player fixture"),
        )
        if key in seen:
            raise DuplicateOutcomeSourceError(
                f"duplicate mart outcome source row for player-fixture {key}"
            )
        seen.add(key)
        if fixture_source is None:
            raise UnfinalizedOutcomeError(
                f"player-fixture {key} has no matching stg_fixture finalization row"
            )
        if finished is not True:
            raise UnfinalizedOutcomeError(
                f"player-fixture {key} is not finalized in stg_fixture.finished"
            )
        if recorded_points is None or replayed_points is None:
            raise NullOutcomeError(
                f"player-fixture {key} has NULL outcome points; NULL must not be attached as zero"
            )
        outcomes.append(
            LedgerOutcome(
                season=key[0],
                code=key[1],
                fixture=key[2],
                total_points_as_recorded=_required_int(
                    recorded_points, name=f"player-fixture {key} recorded points"
                ),
                points_under_rules_2026_27=_required_int(
                    replayed_points, name=f"player-fixture {key} replayed points"
                ),
            )
        )

    rules = load_scoring_rules("2026_27")
    component_count = len(_LIVE_COMPONENT_COLUMNS)
    for row in _live_player_rows(con, as_of=as_of, season=season):
        (
            source_season,
            source_code,
            source_fixture,
            fixture_source,
            finished,
            recorded_points,
            position_label,
            *component_values,
        ) = row
        if len(component_values) != component_count:
            raise OutcomeSourceError("live player outcome projection has the wrong component shape")
        key = (
            str(source_season),
            _required_int(source_code, name="live player code"),
            _required_int(source_fixture, name="live player fixture"),
        )
        if key in seen:
            raise DuplicateOutcomeSourceError(
                f"duplicate live outcome source row for player-fixture {key}"
            )
        seen.add(key)
        if fixture_source is None:
            raise UnfinalizedOutcomeError(
                f"live player-fixture {key} has no fixture version known at the cutoff"
            )
        if finished is not True:
            raise UnfinalizedOutcomeError(
                f"live player-fixture {key} is not finalized in the latest fixture version"
            )
        if recorded_points is None:
            raise NullOutcomeError(
                f"live player-fixture {key} has NULL recorded points; NULL is not zero"
            )
        component_row = dict(zip(_LIVE_COMPONENT_COLUMNS, component_values, strict=True))
        try:
            stats = PlayerMatchStats.from_row(component_row)
            position = Position(str(position_label))
            replayed = calculate_points(stats, rules, position)
        except (TypeError, ValueError) as exc:
            raise NullOutcomeError(
                f"live player-fixture {key} cannot be replayed under scoring_2026_27: {exc}"
            ) from exc
        outcomes.append(
            LedgerOutcome(
                season=key[0],
                code=key[1],
                fixture=key[2],
                total_points_as_recorded=_required_int(
                    recorded_points, name=f"live player-fixture {key} recorded points"
                ),
                points_under_rules_2026_27=replayed,
            )
        )

    return sorted(outcomes, key=lambda item: (item.season, item.code, item.fixture))


def _instant_from_epoch_us(value: object, *, name: str) -> datetime:
    """Rebuild an aware UTC instant from DuckDB `epoch_us()` microseconds.

    A `datetime` is still accepted so any caller already holding one keeps working; anything
    else raises rather than being coerced, because a silently wrong kickoff moves the
    point-in-time boundary.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise OutcomeSourceError(f"{name} is not an epoch-microsecond integer: {value!r}")
    return datetime.fromtimestamp(value / 1_000_000, tz=UTC)


def _historical_team_rows(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime, season: str | None
) -> list[tuple[object, ...]]:
    where = ["f.kickoff_time < ?", "f.finished IS TRUE"]
    params: list[object] = [as_of]
    if season is not None:
        where.append("f.season = ?")
        params.append(season)
    return con.execute(
        f"""
        SELECT
            f.season, f.fixture, f.gw, epoch_us(f.kickoff_time), f.team_h, f.team_a,
            f.team_h_score, f.team_a_score, home.team_code, away.team_code
        FROM stg_fixture AS f
        LEFT JOIN stg_team AS home
          ON home.season = f.season AND home.team_id = f.team_h
        LEFT JOIN stg_team AS away
          ON away.season = f.season AND away.team_id = f.team_a
        WHERE {" AND ".join(where)}
        ORDER BY f.season, f.fixture
        """,
        params,
    ).fetchall()


def _live_team_rows(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime, season: str | None
) -> list[tuple[object, ...]]:
    fixture_filter = "AND season = ?" if season is not None else ""
    team_filter = "AND season = ?" if season is not None else ""
    params: list[object] = [as_of]
    if season is not None:
        params.append(season)
    params.append(as_of)
    if season is not None:
        params.append(season)
    params.append(as_of)
    return con.execute(
        f"""
        WITH latest_fixture AS (
            SELECT * EXCLUDE (version_rank)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY season, fixture
                    ORDER BY known_at DESC, capture_id DESC
                ) AS version_rank
                FROM stg_live_fixture_version
                WHERE known_at <= ? {fixture_filter}
            )
            WHERE version_rank = 1
        ),
        latest_team AS (
            SELECT * EXCLUDE (version_rank)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY season, team_id
                    ORDER BY known_at DESC, capture_id DESC
                ) AS version_rank
                FROM stg_live_team_version
                WHERE known_at <= ? {team_filter}
            )
            WHERE version_rank = 1
        )
        SELECT
            f.season, f.fixture, f.gw, epoch_us(f.kickoff_time), f.team_h, f.team_a,
            f.team_h_score, f.team_a_score, home.team_code, away.team_code
        FROM latest_fixture AS f
        LEFT JOIN latest_team AS home
          ON home.season = f.season AND home.team_id = f.team_h
        LEFT JOIN latest_team AS away
          ON away.season = f.season AND away.team_id = f.team_a
        WHERE f.kickoff_time < ?
          AND f.finished IS TRUE
          AND NOT EXISTS (
              SELECT 1 FROM stg_fixture AS historic
              WHERE historic.season = f.season
                AND historic.fixture = f.fixture
                AND historic.finished IS TRUE
          )
        ORDER BY f.season, f.fixture
        """,
        params,
    ).fetchall()


def select_finalized_team_outcomes(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str | None = None,
) -> list[TeamLedgerOutcome]:
    """Select official finalized fixture scores as reciprocal team rows."""
    _require_aware(as_of, name="as_of")
    outcomes: list[TeamLedgerOutcome] = []
    seen: set[tuple[str, int]] = set()
    rows = _historical_team_rows(con, as_of=as_of, season=season)
    rows.extend(_live_team_rows(con, as_of=as_of, season=season))
    for (
        source_season,
        source_fixture,
        gw,
        kickoff_time,
        team_h,
        team_a,
        team_h_score,
        team_a_score,
        team_h_code,
        team_a_code,
    ) in rows:
        fixture_key = (
            str(source_season),
            _required_int(source_fixture, name="team fixture"),
        )
        if fixture_key in seen:
            raise DuplicateOutcomeSourceError(
                f"duplicate team fixture outcome source row for {fixture_key}"
            )
        seen.add(fixture_key)
        if gw is None or kickoff_time is None:
            raise NullOutcomeError(f"finalized fixture {fixture_key} has NULL gw or kickoff_time")
        if team_h_score is None or team_a_score is None:
            raise NullOutcomeError(
                f"finalized fixture {fixture_key} has NULL official score; NULL is not zero"
            )
        home_id = _required_int(team_h, name=f"fixture {fixture_key} home team")
        away_id = _required_int(team_a, name=f"fixture {fixture_key} away team")
        if home_id == away_id:
            raise OutcomeSourceError(f"finalized fixture {fixture_key} has the same team twice")
        # Both selectors project `epoch_us(kickoff_time)` rather than the TIMESTAMPTZ itself.
        # DuckDB converts a TIMESTAMPTZ fetched through `fetchall()` into a Python datetime via
        # `pytz`, which this project does not declare as a dependency -- it pins `tzdata` for
        # `zoneinfo` -- so a clean install raised ModuleNotFoundError here. Exact microseconds
        # carry no timezone name, so no IANA lookup happens at all. Same fix, and same reason,
        # as the one already applied to the BI exporter's provenance reads.
        kickoff = _instant_from_epoch_us(
            kickoff_time, name=f"finalized fixture {fixture_key} kickoff_time"
        )
        _require_aware(kickoff, name=f"fixture {fixture_key} kickoff_time")
        home_score = _required_int(team_h_score, name=f"fixture {fixture_key} home score")
        away_score = _required_int(team_a_score, name=f"fixture {fixture_key} away score")
        if home_score < 0 or away_score < 0:
            raise OutcomeSourceError(f"finalized fixture {fixture_key} has a negative score")
        outcomes.extend(
            (
                TeamLedgerOutcome(
                    season=fixture_key[0],
                    fixture=fixture_key[1],
                    team_id=home_id,
                    team_code=_optional_int(
                        team_h_code, name=f"fixture {fixture_key} home team_code"
                    ),
                    opponent_team_id=away_id,
                    gw=_required_int(gw, name=f"fixture {fixture_key} gw"),
                    kickoff_time=kickoff,
                    was_home=True,
                    goals_for=home_score,
                    goals_against=away_score,
                ),
                TeamLedgerOutcome(
                    season=fixture_key[0],
                    fixture=fixture_key[1],
                    team_id=away_id,
                    team_code=_optional_int(
                        team_a_code, name=f"fixture {fixture_key} away team_code"
                    ),
                    opponent_team_id=home_id,
                    gw=_required_int(gw, name=f"fixture {fixture_key} gw"),
                    kickoff_time=kickoff,
                    was_home=False,
                    goals_for=away_score,
                    goals_against=home_score,
                ),
            )
        )
    return sorted(outcomes, key=lambda item: (item.season, item.fixture, not item.was_home))


def _new_outcomes_only(
    con: duckdb.DuckDBPyConnection, outcomes: list[LedgerOutcome]
) -> tuple[list[LedgerOutcome], int]:
    ensure_ledger_schema(con)
    new_outcomes: list[LedgerOutcome] = []
    already_attached = 0
    for outcome in outcomes:
        existing = con.execute(
            """
            SELECT total_points_as_recorded, points_under_rules_2026_27
            FROM ledger_outcome_player_fixture
            WHERE season = ? AND code = ? AND fixture = ?
            """,
            [outcome.season, outcome.code, outcome.fixture],
        ).fetchone()
        if existing is None:
            new_outcomes.append(outcome)
            continue
        existing_values = (existing[0], existing[1])
        candidate_values = (
            outcome.total_points_as_recorded,
            outcome.points_under_rules_2026_27,
        )
        if existing_values != candidate_values:
            key = (outcome.season, outcome.code, outcome.fixture)
            raise OutcomeConflictError(
                f"finalized outcome for {key} differs from its attached immutable values: "
                f"existing={existing_values}, candidate={candidate_values}"
            )
        already_attached += 1
    return new_outcomes, already_attached


def _team_values(outcome: TeamLedgerOutcome) -> tuple[object, ...]:
    """The immutable values a re-attachment must match, with kickoff as epoch microseconds.

    Matches the comparison query below, which projects `epoch_us(kickoff_time)`: DuckDB
    converts a fetched TIMESTAMPTZ through `pytz`, an undeclared dependency here. Comparing
    integers is also stricter than comparing datetimes, which can differ in tzinfo
    representation while denoting the same instant.
    """
    return (
        outcome.team_code,
        outcome.opponent_team_id,
        outcome.gw,
        round(outcome.kickoff_time.timestamp() * 1_000_000),
        outcome.was_home,
        outcome.goals_for,
        outcome.goals_against,
    )


def _new_team_outcomes_only(
    con: duckdb.DuckDBPyConnection, outcomes: list[TeamLedgerOutcome]
) -> tuple[list[TeamLedgerOutcome], int]:
    ensure_ledger_schema(con)
    grouped: dict[tuple[str, int], list[TeamLedgerOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault((outcome.season, outcome.fixture), []).append(outcome)
    new_outcomes: list[TeamLedgerOutcome] = []
    already_attached = 0
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
            candidate = _team_values(outcome)
            if tuple(existing) != candidate:
                key = (outcome.season, outcome.fixture, outcome.team_id)
                raise OutcomeConflictError(
                    f"finalized team outcome for {key} differs from its attached immutable "
                    f"values: existing={tuple(existing)}, candidate={candidate}"
                )
        if existing_count == 0:
            new_outcomes.extend(pair)
        elif existing_count == len(pair):
            already_attached += existing_count
        else:
            raise OutcomeConflictError(
                f"finalized team fixture {fixture_key} is only partly attached"
            )
    return new_outcomes, already_attached


def attach_finalized_outcomes(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str | None = None,
    attached_at: datetime | None = None,
) -> OutcomeAttachmentResult:
    """Validate and atomically append all eligible player and team outcomes."""
    if attached_at is not None:
        _require_aware(attached_at, name="attached_at")
    selected = select_finalized_outcomes(con, as_of=as_of, season=season)
    selected_teams = select_finalized_team_outcomes(con, as_of=as_of, season=season)
    new_outcomes, already_attached = _new_outcomes_only(con, selected)
    new_teams, team_already_attached = _new_team_outcomes_only(con, selected_teams)
    attached, team_attached = attach_outcome_batch(
        con,
        new_outcomes,
        new_teams,
        attached_at=attached_at,
    )
    return OutcomeAttachmentResult(
        selected=len(selected),
        attached=attached,
        already_attached=already_attached,
        team_selected=len(selected_teams),
        team_attached=team_attached,
        team_already_attached=team_already_attached,
    )
