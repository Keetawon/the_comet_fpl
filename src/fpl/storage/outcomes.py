"""Finalized player-fixture outcome selection and append-only attachment.

This module is deliberately the boundary between outcome-bearing marts and the prediction ledger.
It reads exactly one source grain, ``(season, code, fixture)``, and never touches predictions.
``stg_fixture.finished`` is the repository's authoritative official-fixtures finalization flag;
``mart_target_player_fixture`` supplies the two separately named outcome measures.

An existing outcome whose two measures match is an idempotent no-op.  An existing outcome whose
measures differ is an error rather than an update: final outcomes are append-only facts and must not
silently change after attachment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from fpl.storage.ledger import LedgerOutcome, attach_outcomes, ensure_ledger_schema

if TYPE_CHECKING:
    import duckdb


class OutcomeAttachmentError(Exception):
    """An outcome payload cannot be attached without breaking the ledger contract."""


class OutcomeSourceError(OutcomeAttachmentError):
    """The marts do not provide a valid finalized player-fixture outcome."""


class UnfinalizedOutcomeError(OutcomeSourceError):
    """A past player-fixture has no authoritative finalized-fixture signal."""


class NullOutcomeError(OutcomeSourceError):
    """A finalized player-fixture is missing one of its required outcome measures."""


class DuplicateOutcomeSourceError(OutcomeSourceError):
    """The source violates its player-fixture grain."""


class OutcomeConflictError(OutcomeAttachmentError):
    """A re-presented finalized outcome differs from the immutable attached value."""


@dataclass(frozen=True, slots=True)
class OutcomeAttachmentResult:
    """Accounting for one source-to-ledger attachment attempt."""

    selected: int
    attached: int
    already_attached: int


def _require_aware(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def select_finalized_outcomes(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str | None = None,
) -> list[LedgerOutcome]:
    """Select valid realized outcomes from the marts at player-fixture grain.

    Only rows whose player-fixture kickoff is strictly before ``as_of`` are considered.  Every
    considered row must have a matching ``stg_fixture`` row with ``finished = TRUE`` and both point
    measures present.  Source duplicates are rejected rather than deduplicated: two fixtures in a
    double gameweek have different fixture ids and remain distinct, while duplicate source rows at
    the same player-fixture key are invalid.
    """
    _require_aware(as_of, name="as_of")
    where = ["t.kickoff_time < ?"]
    params: list[object] = [as_of]
    if season is not None:
        where.append("t.season = ?")
        params.append(season)

    rows = con.execute(
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
    ) in rows:
        key = (str(source_season), int(source_code), int(source_fixture))
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
                total_points_as_recorded=int(recorded_points),
                points_under_rules_2026_27=int(replayed_points),
            )
        )
    return outcomes


def _new_outcomes_only(
    con: duckdb.DuckDBPyConnection, outcomes: list[LedgerOutcome]
) -> tuple[list[LedgerOutcome], int]:
    """Split a valid payload into new rows and exact immutable repeats.

    Exact repeats are deliberately a no-op.  A changed value for an existing key is rejected before
    the write transaction starts, so a batch cannot partly append new facts before it discovers that
    a previously finalized fixture would need to be mutated.
    """
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


def attach_finalized_outcomes(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str | None = None,
    attached_at: datetime | None = None,
) -> OutcomeAttachmentResult:
    """Attach finalized mart outcomes without weakening the ledger's append-only guarantee.

    Same final payload: exact existing values are skipped (idempotent no-op).  New fixture keys are
    appended in the ledger's one transaction.  An already-attached key with different values fails
    closed, because finalization is not permission to revise a realized fact in place.
    """
    if attached_at is not None:
        _require_aware(attached_at, name="attached_at")
    selected = select_finalized_outcomes(con, as_of=as_of, season=season)
    new_outcomes, already_attached = _new_outcomes_only(con, selected)
    attached = attach_outcomes(con, new_outcomes, attached_at=attached_at) if new_outcomes else 0
    return OutcomeAttachmentResult(
        selected=len(selected), attached=attached, already_attached=already_attached
    )
