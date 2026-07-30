"""Point-in-time data access. The enforcement mechanism behind R4.

Every feature is a function of `(entity, as_of)` and no feature may read a row with
`kickoff_time >= as_of`. Discipline does not scale, so the API is shaped to make a leaking
feature awkward to write:

  1. `AsOf` refuses a naive datetime, so "which timezone" cannot silently move the
     boundary.
  2. Features never receive a database connection. They receive a `FeatureSource`, a
     capability restricted to the component fact tables -- it cannot name a
     `mart_target_*` table, so the targets are not merely discouraged but unreachable.
  3. `observed_*` appends `kickoff_time < as_of` itself, after any caller filters.
     Callers pass values, never SQL.
  4. `schedule()` may return future rows, but its projection is restricted to columns
     knowable before kickoff. A future outcome is not filtered out, it is absent.

Layers 1-4 are runtime. `tests/test_point_in_time.py` adds two static ones: an AST scan
that fails any module in this package which reaches for a connection directly, and a
truncation-equivalence test that catches a forgotten filter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

import duckdb
import polars as pl

from fpl.storage.db import FEATURE_READABLE_TABLES, TARGET_TABLE_PREFIX, connect


class LeakageError(RuntimeError):
    """Raised when an access pattern could read post-`as_of` information."""


@dataclass(frozen=True, slots=True)
class AsOf:
    """A point-in-time cursor. Timezone-aware UTC only.

    A naive datetime is rejected rather than assumed: archive `kickoff_time` values are
    tz-aware, and comparing them against a naive boundary would silently shift the cutoff
    by the local offset -- up to a full gameweek of leakage in the worst case.
    """

    ts: datetime

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None or self.ts.utcoffset() is None:
            raise LeakageError(
                f"as_of must be timezone-aware; got naive {self.ts!r}. Use "
                "datetime(..., tzinfo=UTC)."
            )


# Only knowable after kickoff. Never available for a fixture at or after `as_of`.
OUTCOME_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "minutes",
        "starts",
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
        "bps",
        "expected_goals",
        "expected_assists",
        "expected_goals_conceded",
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
        "goals_for",
        "goals_against",
        "team_xg",
        "team_xgc",
        "team_bps",
        # Not outcomes of play, but recorded post-hoc per gameweek in the archive.
        "value",
        "selected",
        "transfers_in",
        "transfers_out",
    }
)

# Knowable before kickoff: schedule metadata only.
SCHEDULE_COLUMNS: Final[tuple[str, ...]] = (
    "season",
    "gw",
    "fixture",
    "pulse_id",
    "kickoff_time",
    "team_id",
    "opponent_team_id",
    "was_home",
    "fdr",
    "rest_days",
)

_KEY_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "season",
        "gw",
        "fixture",
        "pulse_id",
        "kickoff_time",
        "code",
        "position",
        "team_id",
        "opponent_team_id",
        "was_home",
        "fdr",
        "rest_days",
    }
)

# The versioned live player registry (the contract's `live_prospective_registry`). Identity and
# registration metadata only -- no outcome column -- so it is the point-in-time-safe way to
# select WHICH players a live/prospective run predicts, with known_at <= as_of. `pit.py` is the
# sanctioned access layer and is exempt from the static table-name guard, so naming the table
# here is permitted; the projection is still checked against OUTCOME_COLUMNS at call time.
_PLAYER_REGISTRY_TABLE: Final[str] = "stg_live_player_version"
_PLAYER_REGISTRY_COLUMNS: Final[tuple[str, ...]] = (
    "code",
    "season",
    "element",
    "web_name",
    "element_type",
    "position",
    "team_id",
    "now_cost",
    "status",
    "capture_id",
)


class FeatureSource:
    """A read-only capability over the component fact tables.

    The connection is private. There is no accessor that returns it, and no method that
    accepts caller SQL, so a feature holding a `FeatureSource` cannot reach a target
    table even deliberately.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.__con = con

    @classmethod
    def open(cls, db_path: Path | str | None = None) -> Self:
        return cls(connect(db_path, read_only=True))

    def close(self) -> None:
        self.__con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def readable_tables(self) -> frozenset[str]:
        return FEATURE_READABLE_TABLES

    def _check_table(self, table: str) -> None:
        if table.startswith(TARGET_TABLE_PREFIX):
            raise LeakageError(
                f"{table!r} is a target table. Features must never read targets -- that is "
                "label leakage, not point-in-time leakage, and it is equally fatal. Only "
                "the validation harness and the dashboard may read them."
            )
        if table not in FEATURE_READABLE_TABLES:
            raise LeakageError(
                f"{table!r} is not feature-readable. Allowed: {sorted(FEATURE_READABLE_TABLES)}"
            )

    def _columns(self, table: str) -> list[str]:
        self._check_table(table)
        return [
            str(name)
            for (name,) in self.__con.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = ? ORDER BY ordinal_position
                """,
                [table],
            ).fetchall()
        ]

    def _has_table(self, table: str) -> bool:
        self._check_table(table)
        row = self.__con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        return bool(row and row[0])

    def _select(
        self,
        table: str,
        *,
        columns: Sequence[str],
        predicates: Sequence[str],
        params: Sequence[object],
    ) -> pl.DataFrame:
        """The single place a query is issued. Identifiers are validated, values bound."""
        self._check_table(table)
        available = set(self._columns(table))
        unknown = [column for column in columns if column not in available]
        if unknown:
            raise ValueError(f"unknown column(s) for {table}: {unknown}")
        projection = ", ".join(f'"{column}"' for column in columns)
        where = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        relation = self.__con.execute(f"SELECT {projection} FROM {table} {where}", list(params))
        return pl.from_arrow(relation.to_arrow_table())  # type: ignore[return-value]

    def _select_latest_known(
        self,
        table: str,
        *,
        columns: Sequence[str],
        identity_columns: Sequence[str],
        known_at: datetime,
        predicates: Sequence[str],
        params: Sequence[object],
    ) -> pl.DataFrame:
        """Newest version per identity that existed at `known_at`."""
        self._check_table(table)
        available = set(self._columns(table))
        required = set(columns) | set(identity_columns) | {"known_at", "capture_id"}
        unknown = sorted(required - available)
        if unknown:
            raise ValueError(f"unknown column(s) for {table}: {unknown}")
        projection = ", ".join(f'"{column}"' for column in columns)
        partition = ", ".join(f'"{column}"' for column in identity_columns)
        where = f"AND {' AND '.join(predicates)}" if predicates else ""
        relation = self.__con.execute(
            f"""
            WITH ranked AS (
                SELECT *, row_number() OVER (
                    PARTITION BY {partition}
                    ORDER BY known_at DESC, capture_id DESC
                ) AS version_rank
                FROM {table}
                WHERE known_at <= ?
            )
            SELECT {projection} FROM ranked
            WHERE version_rank = 1 {where}
            """,
            [known_at, *params],
        )
        return pl.from_arrow(relation.to_arrow_table())  # type: ignore[return-value]


class PointInTimeView:
    """The only sanctioned reader of fact tables inside `features/`.

    Constructed from a `FeatureSource`, never from a connection, so the restriction
    travels with the object rather than depending on the caller.
    """

    def __init__(self, source: FeatureSource, as_of: AsOf) -> None:
        if not isinstance(as_of, AsOf):
            raise TypeError("as_of must be an AsOf, not a bare datetime")
        self._source = source
        self._as_of = as_of

    @property
    def as_of(self) -> AsOf:
        return self._as_of

    # -- observed: outcomes, hard-filtered to before as_of ------------------------------

    def observed_player_fixtures(
        self,
        *,
        codes: Sequence[int] | None = None,
        seasons: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Player component rows with `kickoff_time < as_of`."""
        return self._observed(
            "mart_fact_player_fixture",
            columns=columns,
            entity_column="code",
            entity_values=codes,
            seasons=seasons,
        )

    def observed_team_matches(
        self,
        *,
        team_ids: Sequence[int] | None = None,
        seasons: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Team match rows with `kickoff_time < as_of`."""
        return self._observed(
            "mart_fact_team_match",
            columns=columns,
            entity_column="team_id",
            entity_values=team_ids,
            seasons=seasons,
        )

    def _observed(
        self,
        table: str,
        *,
        columns: Sequence[str] | None,
        entity_column: str,
        entity_values: Sequence[int] | None,
        seasons: Sequence[str] | None,
    ) -> pl.DataFrame:
        selected = list(columns) if columns is not None else self._source._columns(table)
        predicates: list[str] = []
        params: list[object] = []

        # Caller filters first...
        if entity_values is not None:
            if entity_values:
                placeholders = ", ".join("?" for _ in entity_values)
                predicates.append(f"{entity_column} IN ({placeholders})")
                params.extend(entity_values)
            else:
                predicates.append("FALSE")
        if seasons is not None:
            if seasons:
                placeholders = ", ".join("?" for _ in seasons)
                predicates.append(f"season IN ({placeholders})")
                params.extend(seasons)
            else:
                predicates.append("FALSE")

        # ...and the point-in-time boundary last, appended here and nowhere else.
        predicates.append("kickoff_time < ?")
        params.append(self._as_of.ts)

        archive = self._source._select(
            table, columns=selected, predicates=predicates, params=params
        )
        live_table = "mart_fact_player_fixture_live"
        if table != "mart_fact_player_fixture" or not self._source._has_table(live_table):
            return archive
        live = self._source._select_latest_known(
            live_table,
            columns=selected,
            identity_columns=("season", "code", "fixture"),
            known_at=self._as_of.ts,
            predicates=predicates,
            params=params,
        )
        return pl.concat([archive, live], how="vertical_relaxed")

    # -- schedule: metadata only, future rows permitted ---------------------------------

    def schedule(
        self,
        *,
        team_ids: Sequence[int] | None = None,
        seasons: Sequence[str] | None = None,
        until: datetime | None = None,
        since: datetime | None = None,
    ) -> pl.DataFrame:
        """Fixture metadata, including fixtures at or after `as_of`.

        Safe because the projection excludes every outcome column, so there is nothing
        leakable in the result. This is how a feature learns who a team plays next
        without learning what happened.

        Time bounds are applied in SQL rather than on the returned frame. Beyond keeping
        every filter in one place, it avoids a real footgun: DuckDB hands back timestamps
        tagged `Etc/UTC` while a Python `datetime.UTC` literal is tagged `UTC`, and Polars
        treats those as different dtypes and refuses the comparison.
        """
        available = set(self._source._columns("mart_fact_team_match"))
        selected = [column for column in SCHEDULE_COLUMNS if column in available]
        predicates: list[str] = []
        params: list[object] = []
        if team_ids is not None:
            if team_ids:
                predicates.append(f"team_id IN ({', '.join('?' for _ in team_ids)})")
                params.extend(team_ids)
            else:
                predicates.append("FALSE")
        if seasons is not None:
            if seasons:
                predicates.append(f"season IN ({', '.join('?' for _ in seasons)})")
                params.extend(seasons)
            else:
                predicates.append("FALSE")
        if until is not None:
            if until.tzinfo is None:
                raise LeakageError("`until` must be timezone-aware")
            predicates.append("kickoff_time < ?")
            params.append(until)
        if since is not None:
            if since.tzinfo is None:
                raise LeakageError("`since` must be timezone-aware")
            predicates.append("kickoff_time >= ?")
            params.append(since)
        archive = self._source._select(
            "mart_fact_team_match", columns=selected, predicates=predicates, params=params
        )
        live_table = "mart_team_fixture_live"
        if not self._source._has_table(live_table):
            return archive
        live = self._source._select_latest_known(
            live_table,
            columns=selected,
            identity_columns=("season", "team_id", "fixture"),
            known_at=self._as_of.ts,
            predicates=predicates,
            params=params,
        )
        return pl.concat([archive, live], how="vertical_relaxed").unique(
            subset=["season", "fixture", "team_id"], keep="last"
        )

    def upcoming_fixtures(
        self, *, team_ids: Sequence[int] | None = None, seasons: Sequence[str] | None = None
    ) -> pl.DataFrame:
        """Schedule rows at or after `as_of` -- the fixtures being predicted."""
        return self.schedule(team_ids=team_ids, seasons=seasons, since=self._as_of.ts)

    # -- versioned player registry: the live/prospective roster-selection path ------------

    def player_registry(
        self,
        *,
        codes: Sequence[int] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Newest player registration per stable `code` whose capture existed at or before as_of.

        The registered `live_prospective_registry` path: one row per stable player `code`,
        taking the newest `stg_live_player_version` capture with ``known_at <= as_of`` and
        breaking ties on ``capture_id`` descending. It exposes identity/registration metadata
        only -- ``code``, position, club, status, cost, and the capture id -- and never an
        outcome column (guarded by :func:`assert_no_outcome_columns`). This is how a
        live/prospective Stage B run selects *which players to predict* from a versioned
        registry before the model sees entity, team, or position; the historical archive's
        unversioned roster proxy cannot be reused here without forfeiting any real-deadline
        claim.

        ``status`` is returned as registry metadata but is NOT consumed as a model feature by
        this path; a versioned-availability candidate would be a separately named, amended
        policy (see the Stage B contract's `live_availability_prospective_candidate`).
        """
        if columns is not None:
            selected = list(columns)
        else:
            available = self._source._columns(_PLAYER_REGISTRY_TABLE)
            selected = [column for column in _PLAYER_REGISTRY_COLUMNS if column in available]
        assert_no_outcome_columns(selected)
        if "code" not in selected:
            raise ValueError("player_registry projection must include the 'code' identity column")
        predicates: list[str] = []
        params: list[object] = []
        if codes is not None:
            if codes:
                placeholders = ", ".join("?" for _ in codes)
                predicates.append(f"code IN ({placeholders})")
                params.extend(codes)
            else:
                predicates.append("FALSE")
        return self._source._select_latest_known(
            _PLAYER_REGISTRY_TABLE,
            columns=selected,
            identity_columns=("code",),
            known_at=self._as_of.ts,
            predicates=predicates,
            params=params,
        )


def assert_no_outcome_columns(columns: Sequence[str]) -> None:
    """Guard for callers building their own projections. Raises on any outcome column."""
    offending = sorted(set(columns) & OUTCOME_COLUMNS)
    if offending:
        raise LeakageError(f"outcome column(s) not permitted here: {offending}")


def schedule_safe_columns(columns: Sequence[str]) -> list[str]:
    return [column for column in columns if column in _KEY_COLUMNS]
