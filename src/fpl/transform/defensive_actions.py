"""Source-neutral defensive-actions contract and the FPL defensive-contribution rebuild.

FPL only began recording defensive actions in 2025-26: `tackles`, `recoveries`, and
`clearances_blocks_interceptions` are 0% non-null for 2021-22..2024-25 and 100% only in
2025-26 (verified against `mart_fact_player_fixture`). Yet defensive contribution (DC) is a
2026-27 scoring element. To make a DC component backtestable earlier than 2025-26 the raw
defensive actions must come from an **external** per-match source (e.g. FBref), because FPL's
own archive cannot supply them.

Two things must hold before any external backfill is trusted:

  1. The rebuild formula must match FPL's own definition. It does, exactly. FPL's
     `defensive_contribution` COUNT (the value the scoring calculator thresholds) rebuilds
     from the raw actions as:

        DEF        -> tackles + CBI                        (CBIT)
        MID, FWD   -> tackles + CBI + recoveries           (CBITR)
        GK         -> no DC scoring threshold (gotcha 7); never awarded

     where CBI is FPL's combined `clearances_blocks_interceptions`. This reproduces FPL's
     recorded DC on 2025-26 at 9733/9733 (DEF), 13309/13309 (MID), 3278/3278 (FWD). See
     `fpl.jobs.validate_dc_overlap`.

  2. The external actions must themselves match FPL's (Opta's) definitions. That is proven
     the same way, on the one overlap season (2025-26) that carries both FPL's own DC and the
     external source's actions: rebuild DC from the external actions and require it to
     reproduce FPL's recorded DC before trusting the backfill for 2021-22..2024-25. This
     module supplies the neutral contract and the check; the overlap comparison against a real
     external source is run when a source is chosen.

This module is source-agnostic and has no I/O: it defines the shape any source adapts into,
the rebuild function, and the reconciliation check. It is deliberately free of DuckDB, SQL,
and network so it can be exercised entirely offline.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from fpl.types import Position, Season

# Positions whose DC earns points in 2026-27, and therefore the only positions whose DC
# rebuild must reconcile. GK has no DC threshold, so a keeper's DC is never scored and is not
# reconciled (its FPL value matches neither CBIT nor CBITR at 100%, which is expected and
# harmless because it is unused).
DC_SCORING_POSITIONS: frozenset[Position] = frozenset({Position.DEF, Position.MID, Position.FWD})

# Positions that add recoveries to CBI. DEF uses CBIT (no recoveries); MID and FWD use CBITR.
_RECOVERIES_COUNT_FOR: frozenset[Position] = frozenset({Position.MID, Position.FWD})


def combine_cbi(*, clearances: int, blocks: int, interceptions: int) -> int:
    """Combine the three CBI parts into FPL's single `clearances_blocks_interceptions`.

    External sources report clearances, blocks, and interceptions separately; FPL stores
    only their sum. Adapters use this so the rebuild sees exactly the field FPL records.
    """
    return clearances + blocks + interceptions


def reconstruct_defensive_contribution(
    position: Position, *, tackles: int, cbi: int, recoveries: int
) -> int:
    """Rebuild FPL's `defensive_contribution` COUNT from raw actions.

    Returns the count that the scoring calculator compares against the position threshold,
    not the awarded points. Proven exact on FPL's own 2025-26 archive for every scoring
    position (see the module docstring). GK is not a DC scoring position; the CBIT value is
    returned for completeness but the scoring layer never reads it for a keeper.
    """
    base = tackles + cbi
    if position in _RECOVERIES_COUNT_FOR:
        return base + recoveries
    return base


@dataclass(frozen=True, slots=True)
class ExternalDefensiveActions:
    """One player's defensive actions in one match, from an external per-match source.

    Source-neutral: FBref, an Understat mirror, or a vendored dump all adapt into this shape.
    It carries the identity fields needed to crosswalk to an FPL `code`/`team_code` (name +
    club + season, plus an optional Opta id anchor) and the raw counts FPL's DC is built from.
    The three CBI parts are kept separate because external sources report them separately,
    whereas FPL stores only their sum.

    Identity is resolved downstream, per season, by `fpl.transform.external_identity`; this
    record never carries a bare cross-season id.
    """

    season: Season
    external_player_id: str
    player_name: str
    team_name: str
    match_date: str
    tackles: int
    interceptions: int
    blocks: int
    clearances: int
    recoveries: int

    @property
    def cbi(self) -> int:
        """FPL's combined clearances + blocks + interceptions."""
        return combine_cbi(
            clearances=self.clearances, blocks=self.blocks, interceptions=self.interceptions
        )

    def rebuilt_dc(self, position: Position) -> int:
        """The DC count this row implies for a player of the given position."""
        return reconstruct_defensive_contribution(
            position, tackles=self.tackles, cbi=self.cbi, recoveries=self.recoveries
        )


@dataclass(frozen=True, slots=True)
class DcObservation:
    """One row for the reconciliation check: raw actions plus FPL's recorded DC count.

    `recorded_dc` is FPL's own `defensive_contribution` value; the check asks whether the
    rebuild from `tackles`/`cbi`/`recoveries` reproduces it.
    """

    position: Position
    tackles: int
    cbi: int
    recoveries: int
    recorded_dc: int


@dataclass(frozen=True, slots=True)
class DcReconstructionReport:
    """Per-position reconciliation of rebuilt DC against FPL's recorded DC.

    Only the scoring positions (DEF/MID/FWD) are reconciled; GK rows are counted but never
    contribute a mismatch because a keeper's DC is unused.
    """

    total_rows: int
    scoring_rows: int
    exact_matches: int
    mismatches: int
    max_abs_error: int
    by_position: dict[Position, tuple[int, int]]
    mismatch_examples: tuple[tuple[Position, int, int], ...] = field(default_factory=tuple)

    @property
    def agreement_rate(self) -> float:
        """Fraction of scoring rows whose rebuild matched exactly (1.0 if there are none)."""
        if self.scoring_rows == 0:
            return 1.0
        return self.exact_matches / self.scoring_rows

    @property
    def reconciles(self) -> bool:
        """True when every scoring row rebuilt exactly."""
        return self.mismatches == 0


def check_dc_reconstruction(rows: Iterable[DcObservation]) -> DcReconstructionReport:
    """Reconcile rebuilt DC against recorded DC across the scoring positions.

    This is the definition-match test. Fed FPL's own raw inputs it proves the rebuild
    formula; fed an external source's actions on the 2025-26 overlap season it proves the
    external definitions match FPL's before any earlier-season backfill is trusted.
    """
    total_rows = 0
    scoring_rows = 0
    exact_matches = 0
    mismatches = 0
    max_abs_error = 0
    by_position: dict[Position, tuple[int, int]] = {}
    examples: list[tuple[Position, int, int]] = []

    for obs in rows:
        total_rows += 1
        if obs.position not in DC_SCORING_POSITIONS:
            continue
        scoring_rows += 1
        rebuilt = reconstruct_defensive_contribution(
            obs.position, tackles=obs.tackles, cbi=obs.cbi, recoveries=obs.recoveries
        )
        seen, matched = by_position.get(obs.position, (0, 0))
        if rebuilt == obs.recorded_dc:
            exact_matches += 1
            by_position[obs.position] = (seen + 1, matched + 1)
        else:
            mismatches += 1
            by_position[obs.position] = (seen + 1, matched)
            max_abs_error = max(max_abs_error, abs(rebuilt - obs.recorded_dc))
            if len(examples) < 10:
                examples.append((obs.position, rebuilt, obs.recorded_dc))

    return DcReconstructionReport(
        total_rows=total_rows,
        scoring_rows=scoring_rows,
        exact_matches=exact_matches,
        mismatches=mismatches,
        max_abs_error=max_abs_error,
        by_position=by_position,
        mismatch_examples=tuple(examples),
    )
