"""Local-CSV reader for externally-sourced per-match defensive actions.

The defensive-contribution (DC) backfill needs per-match tackles / interceptions / blocks /
clearances / recoveries for 2021-22..2024-25, which FPL never recorded (0% non-null before
2025-26). fbref.com is blocked in the build environment, so the reader consumes a CSV the
operator pulls locally (B-path: see `docs/phase3-stage-c-fbref-recipe.md`) rather than
fetching over HTTP. It produces `ExternalDefensiveActions` rows that the source-neutral
machinery -- `fpl.transform.defensive_actions` and `fpl.transform.external_identity` --
consumes unchanged.

Canonical CSV columns (exact set, order-independent)::

    season, external_player_id, player_name, team_name, match_date,
    tackles, interceptions, blocks, clearances, recoveries

`season` is the FPL "YYYY-YY" label and `match_date` is ISO (YYYY-MM-DD). The five count
columns are non-negative integers; a blank cell means **unmeasured** and is preserved as
`None`, never coerced to zero -- the same NULL semantics as `mart_fact_player_fixture`
(gotcha 5: a zero there would understate every defender's DC rate).

NULL handling: the rebuild (`reconstruct_defensive_contribution`) and the overlap gate both
need all five counts, so a row with any blank count cannot truthfully become a complete
`ExternalDefensiveActions`. Such rows are skipped here (never zeroed), exactly as
`fpl.jobs.validate_dc_overlap` skips FPL rows that are NULL in any of the four inputs.
`read_defensive_actions_csv` returns only complete rows; the count of skipped NULL-count
rows is returned alongside so the drop is never silent.

Pure: no network, no DuckDB. This is a typed ingest boundary (AGENTS rule 3), so a
missing/extra column, a bad type, or a negative count raises a single clear error naming
the offence, rather than failing row-by-row deep in the pipeline.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from fpl.transform.defensive_actions import ExternalDefensiveActions

CANONICAL_COLUMNS: Final[tuple[str, ...]] = (
    "season",
    "external_player_id",
    "player_name",
    "team_name",
    "match_date",
    "tackles",
    "interceptions",
    "blocks",
    "clearances",
    "recoveries",
)
_COUNT_COLUMNS: Final[tuple[str, ...]] = (
    "tackles",
    "interceptions",
    "blocks",
    "clearances",
    "recoveries",
)


class DefensiveActionsCsvError(ValueError):
    """Raised when a defensive-actions CSV does not match the canonical contract."""


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class _DefensiveActionsRow(BaseModel):
    """One validated CSV row. Blank counts parse to None; negatives are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season: str
    external_player_id: str
    player_name: str
    team_name: str
    match_date: str
    tackles: int | None
    interceptions: int | None
    blocks: int | None
    clearances: int | None
    recoveries: int | None

    _blank = field_validator(*_COUNT_COLUMNS, mode="before")(_blank_to_none)

    @field_validator("season")
    @classmethod
    def _season_shape(cls, value: str) -> str:
        if len(value) != 7 or value[4] != "-" or not value.replace("-", "").isdigit():
            raise ValueError(f"season {value!r} is not the FPL 'YYYY-YY' shape")
        return value

    @field_validator("match_date")
    @classmethod
    def _match_date_iso(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"match_date {value!r} is not ISO (YYYY-MM-DD)") from exc
        return value

    @field_validator(*_COUNT_COLUMNS)
    @classmethod
    def _non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("count is negative")
        return value

    @property
    def is_complete(self) -> bool:
        """All five counts are measured (non-None); i.e. the row can rebuild a DC."""
        return all(getattr(self, col) is not None for col in _COUNT_COLUMNS)


def _check_header(path: Path, header: Sequence[str]) -> None:
    actual = set(header)
    canonical = set(CANONICAL_COLUMNS)
    missing = canonical - actual
    extra = actual - canonical
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"missing columns {sorted(missing)}")
        if extra:
            parts.append(f"unexpected columns {sorted(extra)}")
        raise DefensiveActionsCsvError(
            f"{path}: header does not match the canonical contract; " + "; ".join(parts)
        )


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in exc.errors()
    )


def _row_id(raw: dict[str, str]) -> str:
    return raw.get("external_player_id") or raw.get("player_name") or "?"


def _to_external(row: _DefensiveActionsRow) -> ExternalDefensiveActions:
    # `is_complete` is checked by the caller; these asserts narrow the locals for mypy so a
    # None count can never reach the int fields.
    tackles = row.tackles
    interceptions = row.interceptions
    blocks = row.blocks
    clearances = row.clearances
    recoveries = row.recoveries
    assert tackles is not None
    assert interceptions is not None
    assert blocks is not None
    assert clearances is not None
    assert recoveries is not None
    return ExternalDefensiveActions(
        season=row.season,
        external_player_id=row.external_player_id,
        player_name=row.player_name,
        team_name=row.team_name,
        match_date=row.match_date,
        tackles=tackles,
        interceptions=interceptions,
        blocks=blocks,
        clearances=clearances,
        recoveries=recoveries,
    )


def read_defensive_actions_csv(path: str | Path) -> list[ExternalDefensiveActions]:
    """Read a defensive-actions CSV into complete, source-neutral rows.

    The header must be exactly the canonical column set (clear error on any missing/extra
    column); each row is validated against the typed contract (clear error on a bad type or
    negative count). Blank count cells stay None. Rows with any blank count are skipped
    rather than zeroed, mirroring the FPL-side NULL-skip in `validate_dc_overlap`; the count
    of such rows is available via `count_null_count_rows`. No network, no DuckDB.
    """
    resolved = Path(path)
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        if header is None:
            raise DefensiveActionsCsvError(f"{resolved}: empty CSV (no header row)")
        _check_header(resolved, header)
        rows: list[ExternalDefensiveActions] = []
        for line_no, raw in enumerate(reader, start=2):
            record = {col: (raw.get(col) or "") for col in CANONICAL_COLUMNS}
            try:
                parsed = _DefensiveActionsRow.model_validate(record)
            except ValidationError as exc:
                raise DefensiveActionsCsvError(
                    f"{resolved}:{line_no}: invalid defensive-actions row "
                    f"{_row_id(raw)!r}: {_format_validation_error(exc)}"
                ) from exc
            if parsed.is_complete:
                rows.append(_to_external(parsed))
    return rows


def count_null_count_rows(path: str | Path) -> int:
    """Count rows skipped by `read_defensive_actions_csv` for having any blank count.

    Separate from the reader so the skip is reportable without changing the reader's return
    type. A non-zero count means the dump is partially unmeasured; investigate before
    trusting a backfill that depends on it.
    """
    resolved = Path(path)
    skipped = 0
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return 0
        for raw in reader:
            if any((raw.get(col) or "").strip() == "" for col in _COUNT_COLUMNS):
                skipped += 1
    return skipped
