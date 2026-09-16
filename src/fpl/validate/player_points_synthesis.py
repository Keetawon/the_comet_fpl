"""Development-only conditional GK-save substitution into the unchanged composer.

The formal runner owns immutable component acceptance receipts and complete roster
hashes. This pure boundary neither selects a model nor reads a target outcome. A
nonempty substitution must cover EVERY declared GK, including a predicted DNP;
the existing composer alone draws and gates minutes. No other replacement is
licensed here, and the supplied CURRENT reference is never mutated or relabelled.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from fpl.config import load_phase2_evaluation, load_scoring_rules
from fpl.jobs import prospective_points_v1 as prospective
from fpl.models.points_composition import (
    DEFAULT_MAX_POINTS_FULL,
    MAX_COUNT,
    MEASURED_CONCEDED_EXPOSURE,
    BpsExactLookup,
    ComponentDistributions,
    ComposedPlayer,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    representative_minutes,
)
from fpl.types import Position
from fpl.validate.development_reference_components import NAME as REFERENCE_NAME
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    ReferenceMinutesRow,
    ReferencePlayerComponents,
    ValidatedMinutesControlFold,
    _validate_rows,
)
from fpl.validate.metrics import Distribution
from fpl.validate.minutes_baselines import MinuteBins, TargetRow
from fpl.validate.points_harness import TARGET_RULESET
from fpl.validate.points_harness_v3 import DEFAULT_DRAWS, _fixture_seed
from fpl.validate.retrospective_minutes_proxy import EVIDENCE_CLASS as REFERENCE_EVIDENCE_CLASS

NAME = "retrospective_player_points_synthesis_v1"
EVIDENCE_CLASS = "retrospective_backfill_development"


@dataclass(frozen=True, slots=True)
class ComposerContext:
    """Prebuilt fixed lookup tables; no draw, rule, seed or exposure override."""

    points: PointsLookup
    bps: BpsExactLookup
    extra: ExtraScoring


def build_composer_context() -> ComposerContext:
    """Build the exact CURRENT lookup tables once, not once per fixture."""
    rules = load_scoring_rules(TARGET_RULESET)
    if rules.bps is None:
        raise ValueError("BPS rules missing")
    minutes = representative_minutes(MinuteBins.from_config(load_phase2_evaluation()).ranges)
    return ComposerContext(
        PointsLookup(rules, bin_minutes=minutes),
        BpsExactLookup(
            rules.bps,
            bin_minutes=minutes,
            clean_sheet_minimum_minutes=rules.clean_sheets.minimum_minutes,
        ),
        ExtraScoring(
            rules.saves.unit,
            rules.defensive_contribution.points,
            rules.saves.positions,
            frozenset(rules.defensive_contribution.thresholds),
        ),
    )


def _validate_count_pmf(pmf: Distribution, label: str) -> None:
    if (
        type(pmf) is not tuple
        or len(pmf) != MAX_COUNT + 1
        or any(type(p) not in (int, float) or not math.isfinite(p) or p < 0 for p in pmf)
        or not math.isclose(math.fsum(pmf), 1, rel_tol=0, abs_tol=1e-12)
    ):
        raise ValueError(f"{label} requires a finite unit-mass 0..10 count PMF")


def compose_synthesis_fixture(
    reference: DevelopmentReferenceComponents,
    fixture: int,
    context: ComposerContext,
    *,
    saves_replacements: Mapping[int, Distribution] | None = None,
) -> tuple[ComposedPlayer, ...]:
    """Compose one complete fixture with only appearance-conditional GK saves.

    None/empty map uses the incumbent unchanged. Active maps must contain exactly
    the fixture's GK codes, not only observed starters or appeared keepers. The
    caller authenticates the complete reference roster and accepted H provenance;
    a PMF by itself cannot prove historical conditionality or source lineage.
    """
    if (
        type(reference) is not DevelopmentReferenceComponents
        or reference.identity != REFERENCE_NAME
        or reference.evidence_class != REFERENCE_EVIDENCE_CLASS
        or reference.promotion_permitted is not False
    ):
        raise ValueError("only the explicit development CURRENT reference is accepted")
    if type(context) is not ComposerContext:
        raise ValueError("build the fixed development composer context first")
    if type(fixture) is not int or fixture <= 0:
        raise ValueError("fixture requires an exact positive integer identity")
    if type(reference.rows) is not tuple or any(
        type(r) is not ReferencePlayerComponents
        or type(r.target) is not TargetRow
        or type(r.player) is not FixturePlayer
        or type(r.player.components) is not ComponentDistributions
        for r in reference.rows
    ):
        raise ValueError("exact outcome-free reference predictor types required")
    rows = tuple(r for r in reference.rows if r.target.fixture == fixture)
    if not rows:
        raise ValueError("fixture absent from reference")
    _validate_rows(
        ValidatedMinutesControlFold(
            reference.season,
            reference.gw,
            reference.as_of,
            tuple(
                ReferenceMinutesRow(
                    r.target,
                    r.team_code,
                    r.player.components.minutes,
                    r.cold_start,
                    r.direct_price_proxy,
                    r.selector_provenance_json,
                )
                for r in reference.rows
            ),
            "",
            "",
            "",
            "{}",
        )
    )
    for row in rows:
        player, target = row.player, row.target
        c = player.components
        if (
            type(c.position) is not Position
            or type(target.position) is not Position
            or any(
                type(value) is not int or value <= 0
                for value in (
                    player.code,
                    target.code,
                    target.team_id,
                    target.opponent_team_id,
                    row.team_code,
                )
            )
            or type(target.was_home) is not bool
            or player.code != target.code
            or c.position != target.position
        ):
            raise ValueError("fixture player identity/position differs from reference roster")
        for label, pmf in (
            ("goals", c.goals),
            ("assists", c.assists),
            ("conceded", c.team_goals_conceded),
        ):
            _validate_count_pmf(pmf, label)
        if c.saves is None:
            raise ValueError("CURRENT saves PMF must exist to preserve the random stream")
        _validate_count_pmf(c.saves, "incumbent saves")
        if c.position is not Position.GK and c.saves != (1.0,) + (0.0,) * MAX_COUNT:
            raise ValueError("CURRENT non-GK saves must retain point-mass-zero support")
        if c.disciplinary is not None:
            raise ValueError("disciplinary replacement is not licensed by this synthesis")
        if (
            any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in (c.dc_hit_probability, player.residual_mean, player.residual_sigma)
            )
            or not 0 <= c.dc_hit_probability <= 1
            or (c.position is Position.GK and c.dc_hit_probability != 0)
            or player.residual_sigma < 0
        ):
            raise ValueError("invalid incumbent DC or unchanged BPS residual")
    if saves_replacements is not None and not isinstance(saves_replacements, Mapping):
        raise ValueError("saves replacements must be a mapping of exact GK codes")
    replacements = {} if saves_replacements is None else dict(saves_replacements)
    if replacements:
        expected = {r.player.code for r in rows if r.player.components.position == Position.GK}
        if any(type(code) is not int for code in replacements) or set(replacements) != expected:
            raise ValueError("saves replacements must cover exactly every fixture GK code")
        for pmf in replacements.values():
            _validate_count_pmf(pmf, "conditional saves replacement")
    players = [
        replace(
            r.player, components=replace(r.player.components, saves=replacements[r.player.code])
        )
        if r.player.code in replacements
        else r.player
        for r in rows
    ]
    # No new RNG or draws: saves, DC, minutes, goals and the joint bonus world stay
    # coupled exactly as in CURRENT. The neutral return type carries no CURRENT label.
    return tuple(
        compose_fixture_full_points(
            players,
            context.points,
            context.bps,
            context.extra,
            fixture_seed=_fixture_seed(prospective.BASE_SEED, reference.season, fixture),
            draws=DEFAULT_DRAWS,
            max_points=DEFAULT_MAX_POINTS_FULL,
            conceded_exposure=MEASURED_CONCEDED_EXPOSURE,
        )
    )
