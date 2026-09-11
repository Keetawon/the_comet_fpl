"""V2 component engine: `FixtureEnvironment` -> the composer's `ComponentDistributions`.

The join between the football half of V2 and the FPL half. It is deliberately an ADAPTER rather
than a rewrite: `models/points_composition.py` already takes exactly the right input -- minutes,
goals, assists, goals conceded, saves and a DC probability per player-fixture -- so V2 plugs in
at that boundary with **no change to the composer, the artifact contract, or the optimizer**.
That is the point of having a contract there at all, and it is why Milestone I costs nothing.

What each component draws from the environment:

| component | V1 source | V2 source |
| --- | --- | --- |
| minutes | Stage B trailing bins | **unchanged** -- SDP bears on football, not on selection |
| goals | Stage A lambda x trailing xG share | environment `expected_goals` x the same share |
| assists | Stage A lambda x trailing xA share | environment `expected_goals` x the same share |
| goals conceded | opponent's Stage A distribution | the opponent's environment distribution |
| saves | `k * lambda_conceded` (an identity) | `save_rate * expected shots on target faced` |
| DC | per-player trailing hit rate | team defensive-action environment x role share |

Two of those are the substantive V2 changes; the rest are the same quantity arriving from a
richer source. Keeping the attacking allocation unchanged is deliberate -- swapping the team
scale AND the allocation at once would make any measured difference unattributable.

Pure module: no database, SQL, Polars or config read. Scoring constants arrive as `ExtraScoring`
from the caller, as they already do for the v2 composer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from fpl.artifacts.fixture_environment import FixtureEnvironment
from fpl.models.attacking_baselines import MAX_GOALS, poisson_pmf
from fpl.models.defensive_environment_v2 import DefensiveEnvironmentV2
from fpl.models.gk_saves_v2 import GkSavesV2
from fpl.models.points_composition import ComponentDistributions, conditional_rate
from fpl.types import Position

NAME: Final[str] = "component_engine_v2"

# Representative on-pitch share per Stage B minutes bin, used to thin the DC action count.
# Measured minutes shares are 0.254 / 0.837 / 1.000 for bins 1-3 (bin 0 never plays).
#
# NOTE these are the MINUTES shares, deliberately not the measured goals-conceded exposure
# (0.344 / 0.813 / 0.999). That exposure curve is steeper than minutes because a substitute
# enters a game already going badly and late goals are more frequent -- an effect specific to
# CONCEDING. Borrowing it for defensive actions would import a constant measured for a
# different quantity, which this repository has an explicit rule against.
MINUTES_EXPOSURE_BY_BIN: Final[tuple[float, float, float, float]] = (0.0, 0.254, 0.837, 1.0)


@dataclass(frozen=True, slots=True)
class PlayerProfile:
    """One player's non-football inputs for one fixture.

    `attacking_share` and `assist_share` are UNCONDITIONAL expected shares of the team's goals
    and assists -- the same quantities the V1 minutes-gated allocation produces, so the two
    engines allocate identically and only the team scale differs.

    `minutes` is the Stage B four-bin distribution over `(0, 1-59, 60-89, 90)`.
    """

    code: int
    position: Position
    team_code: int
    minutes: tuple[float, float, float, float]
    attacking_share: float
    assist_share: float

    @property
    def probability_of_playing(self) -> float:
        return 1.0 - self.minutes[0]

    @property
    def expected_minutes_exposure(self) -> float:
        """Expected on-pitch share of the match, over the minutes distribution."""
        return sum(
            mass * exposure
            for mass, exposure in zip(self.minutes, MINUTES_EXPOSURE_BY_BIN, strict=True)
        )


def _share_normaliser(profiles: Sequence[PlayerProfile], *, assists: bool) -> float:
    """Availability-weighted total share, the denominator that conserves the team rate.

    A roster's shares are estimated over appearances, so scaling them by `p_play` and
    renormalising is what makes the allocated rates sum back to the team's expected goals.
    """
    total = sum(
        (profile.assist_share if assists else profile.attacking_share)
        * profile.probability_of_playing
        for profile in profiles
    )
    return total


def _allocated_rate(
    profile: PlayerProfile, team_rate: float, normaliser: float, *, assists: bool
) -> float:
    """Unconditional expected events for one player: `team_rate * share_i` conserved."""
    if normaliser <= 0.0:
        return 0.0
    share = profile.assist_share if assists else profile.attacking_share
    return team_rate * share * profile.probability_of_playing / normaliser


def build_component_distributions(
    environment: FixtureEnvironment,
    profiles: Sequence[PlayerProfile],
    *,
    team_code: int,
    saves_model: GkSavesV2 | None = None,
    dc_model: DefensiveEnvironmentV2 | None = None,
    dc_thresholds: Mapping[Position, int] | None = None,
    assist_conversion: float = 0.75,
    max_goals: int = MAX_GOALS,
) -> dict[int, ComponentDistributions]:
    """One `ComponentDistributions` per player of one club in one fixture.

    `assist_conversion` is the share of a team's goals that carry a recorded assist. It scales
    the team's goal rate into an assist rate; it is a caller-supplied constant rather than a
    modelled quantity, and is stated here so it is not mistaken for one.

    **Rates handed to the composer are CONDITIONAL ON APPEARANCE.** The composer draws the
    minutes bin first and scores a bin-0 draw as zero, so passing an unconditional rate would
    apply the appearance gate twice -- a defect that was measured to destroy 11.11% of all goal
    and assist mass before it was found. `conditional_rate` divides `p_play` back out, capped
    at the team rate because no player can be expected to outscore their own club.
    """
    side = environment.for_team(team_code)
    conceded = environment.goals_conceded_distribution(team_code)
    team_goals = side.expected_goals
    team_assists = team_goals * assist_conversion

    goal_normaliser = _share_normaliser(profiles, assists=False)
    assist_normaliser = _share_normaliser(profiles, assists=True)

    built: dict[int, ComponentDistributions] = {}
    for profile in profiles:
        p_play = profile.probability_of_playing
        goal_rate = conditional_rate(
            _allocated_rate(profile, team_goals, goal_normaliser, assists=False),
            p_play,
            cap=max(team_goals, 1e-9),
        )
        assist_rate = conditional_rate(
            _allocated_rate(profile, team_assists, assist_normaliser, assists=True),
            p_play,
            cap=max(team_assists, 1e-9),
        )

        saves = None
        if saves_model is not None:
            saves = saves_model.predict(
                profile.position,
                side.expected_goals_against,
                expected_shots_on_target_faced=side.expected_shots_on_target_against,
            )

        dc_probability = 0.0
        if dc_model is not None and dc_thresholds is not None:
            dc_probability = dc_model.predict(
                code=profile.code,
                position=profile.position,
                threshold=dc_thresholds.get(profile.position),
                team_defensive_actions=side.expected_defensive_actions,
                minutes_exposure=profile.expected_minutes_exposure,
            )

        built[profile.code] = ComponentDistributions(
            position=profile.position,
            minutes=profile.minutes,
            goals=poisson_pmf(goal_rate, max_goals=max_goals),
            assists=poisson_pmf(assist_rate, max_goals=max_goals),
            team_goals_conceded=conceded,
            saves=saves,
            dc_hit_probability=dc_probability,
        )
    return built


def conserved_team_goals(
    components: Mapping[int, ComponentDistributions],
    profiles: Sequence[PlayerProfile],
) -> float:
    """Expected team goals realised by the roster, for the conservation check.

    Each player's realised contribution is `p_play * conditional_rate`, because the composer
    scores a non-appearance as zero. Summed over the roster this must return the team's
    expected goals -- if it does not, the allocation is leaking mass, which is exactly the
    defect this repository has already paid for once.
    """
    total = 0.0
    for profile in profiles:
        distribution = components.get(profile.code)
        if distribution is None:
            continue
        conditional = sum(index * mass for index, mass in enumerate(distribution.goals))
        total += profile.probability_of_playing * conditional
    return total
