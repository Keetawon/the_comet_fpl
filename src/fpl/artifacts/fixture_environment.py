"""`FixtureEnvironment`: the contract between the football engine and the FPL components.

This is the interface the whole V2 architecture turns on. V1's Stage A hands downstream a
single scalar -- the team's expected goals -- and every component then has to reconstruct the
football context it needs from that one number. Goalkeeper saves is the clearest casualty:
with only `lambda_conceded` available, shots on target faced can only be
`lambda_conceded / (1 - save_rate)`, which makes it a deterministic function of goals conceded
rather than a quantity in its own right. Measured on this archive the correlation between team
shots on target allowed and goals allowed is **0.621**, so that identity throws away about 61%
of the variance in shots faced.

A `FixtureEnvironment` carries the football prediction as a bundle instead: the goal
distribution AND the shot, chance, territorial and defensive-action environment that produced
it, per side, for one fixture.

Three properties are load-bearing:

  * **Every non-goal field is `float | None`.** `None` means the engine had no signal for it,
    which is the normal case for a season the provider did not cover. A component receiving
    `None` must fall back explicitly; it must never read it as zero, which would claim a team
    faces no shots at all.
  * **`goal_distribution` is a distribution, not a mean.** Clean sheets, the goals-conceded
    penalty and the bonus simulation all need mass, not expectation.
  * **It is immutable and self-describing.** `signal_coverage` records which signals actually
    contributed, so a downstream result can always be traced to the evidence behind it.

This module is pure: no database, no SQL, no config read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

# The canonical signal names the engine may fit and the environment may carry. Declared here,
# beside the contract, so a component can ask for a signal by a name that is checked rather
# than by a string that silently misses.
SIGNAL_GOALS: Final[str] = "goals"
SIGNAL_EXPECTED_GOALS: Final[str] = "expected_goals"
SIGNAL_EXPECTED_GOALS_ON_TARGET: Final[str] = "expected_goals_on_target"
SIGNAL_SHOTS_ON_TARGET: Final[str] = "shots_on_target"
SIGNAL_SHOTS: Final[str] = "shots"
SIGNAL_BOX_TOUCHES: Final[str] = "touches_in_opposition_box"
SIGNAL_BIG_CHANCES: Final[str] = "big_chances_created"
SIGNAL_DEFENSIVE_ACTIONS: Final[str] = "defensive_actions"

# The shots-on-target-allowed measurement derived from goalkeeper saves + goals conceded. It
# is a SEPARATE signal name from `shots_on_target` because it is a different measurement with
# different failure modes, and conflating them would let a proxy silently stand in for a
# direct observation.
SIGNAL_SHOTS_ON_TARGET_FACED_PROXY: Final[str] = "shots_on_target_allowed_proxy"

KNOWN_SIGNALS: Final[frozenset[str]] = frozenset(
    {
        SIGNAL_GOALS,
        SIGNAL_EXPECTED_GOALS,
        SIGNAL_EXPECTED_GOALS_ON_TARGET,
        SIGNAL_SHOTS_ON_TARGET,
        SIGNAL_SHOTS,
        SIGNAL_BOX_TOUCHES,
        SIGNAL_BIG_CHANCES,
        SIGNAL_DEFENSIVE_ACTIONS,
        SIGNAL_SHOTS_ON_TARGET_FACED_PROXY,
    }
)


class FixtureEnvironmentError(ValueError):
    """A fixture environment was constructed inconsistently."""


@dataclass(frozen=True, slots=True)
class TeamEnvironment:
    """One club's predicted football environment for one fixture.

    `expected_goals` is the mean of `goal_distribution` by construction, not an independent
    field -- they are validated against each other so a caller can use whichever it needs
    without wondering whether they agree.

    The `*_against` fields are what this club is predicted to FACE, which is not simply the
    opponent's `*_for`: it is the opponent's attacking rate evaluated against this club's
    defence at this venue. Both are carried because a component generally needs one specific
    direction and deriving the wrong one is silent.
    """

    team_code: int
    was_home: bool
    goal_distribution: tuple[float, ...]
    expected_goals: float
    expected_goals_against: float
    expected_shots_on_target: float | None = None
    expected_shots_on_target_against: float | None = None
    expected_shots: float | None = None
    expected_shots_against: float | None = None
    expected_goals_on_target_value: float | None = None
    expected_goals_on_target_against: float | None = None
    expected_box_touches: float | None = None
    expected_box_touches_against: float | None = None
    expected_big_chances: float | None = None
    expected_big_chances_against: float | None = None
    expected_possession: float | None = None
    expected_defensive_actions: float | None = None
    cold_start: bool = False
    signal_coverage: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.goal_distribution:
            raise FixtureEnvironmentError("goal_distribution must not be empty")
        total = sum(self.goal_distribution)
        if abs(total - 1.0) > 1e-6:
            raise FixtureEnvironmentError(
                f"goal_distribution sums to {total!r}, not 1.0; a truncated or unnormalised "
                "pmf would silently misprice every downstream probability"
            )
        implied = sum(index * mass for index, mass in enumerate(self.goal_distribution))
        # Tolerance is loose because the pmf is truncated at a maximum goal count, which
        # removes a little mass from the tail; it is tight enough to catch a mismatched pair.
        if abs(implied - self.expected_goals) > 0.05:
            raise FixtureEnvironmentError(
                f"expected_goals {self.expected_goals:.4f} disagrees with the mean of "
                f"goal_distribution ({implied:.4f})"
            )

    def signal(self, name: str) -> float | None:
        """This club's predicted value of a named signal, or `None` where unavailable."""
        return {
            SIGNAL_GOALS: self.expected_goals,
            SIGNAL_EXPECTED_GOALS: self.expected_goals,
            SIGNAL_SHOTS_ON_TARGET: self.expected_shots_on_target,
            SIGNAL_SHOTS: self.expected_shots,
            SIGNAL_EXPECTED_GOALS_ON_TARGET: self.expected_goals_on_target_value,
            SIGNAL_BOX_TOUCHES: self.expected_box_touches,
            SIGNAL_BIG_CHANCES: self.expected_big_chances,
            SIGNAL_DEFENSIVE_ACTIONS: self.expected_defensive_actions,
        }.get(name)


@dataclass(frozen=True, slots=True)
class FixtureEnvironment:
    """Both sides of one fixture, plus the joint dependence the bonus simulation needs."""

    season: str
    fixture: int
    gw: int | None
    kickoff_time: datetime | None
    home: TeamEnvironment
    away: TeamEnvironment
    rho: float = 0.0
    engine: str = ""

    def __post_init__(self) -> None:
        if not self.home.was_home or self.away.was_home:
            raise FixtureEnvironmentError(
                f"{self.season} fixture {self.fixture}: home/away sides are mislabelled"
            )
        if self.home.team_code == self.away.team_code:
            raise FixtureEnvironmentError(
                f"{self.season} fixture {self.fixture}: both sides carry team_code "
                f"{self.home.team_code}"
            )

    def for_team(self, team_code: int) -> TeamEnvironment:
        if self.home.team_code == team_code:
            return self.home
        if self.away.team_code == team_code:
            return self.away
        raise KeyError(
            f"team_code {team_code} does not play in {self.season} fixture {self.fixture}"
        )

    def opponent_of(self, team_code: int) -> TeamEnvironment:
        return self.away if self.home.team_code == team_code else self.home

    def goals_conceded_distribution(self, team_code: int) -> tuple[float, ...]:
        """What this club concedes: literally the opponent's scored-goals distribution.

        Reading it off the opponent's own distribution rather than rebuilding one from a
        `lambda_against` scalar is deliberate. The two cannot then disagree, and a distribution
        regenerated from a mean discards whatever shape the engine actually predicted.
        """
        return self.opponent_of(team_code).goal_distribution

    def clean_sheet_probability(self, team_code: int) -> float:
        """P(opponent scores zero). The zero mass of the opponent's distribution, exactly."""
        return self.goals_conceded_distribution(team_code)[0]


def summarise_coverage(
    environments: Sequence[FixtureEnvironment],
) -> dict[str, dict[str, int]]:
    """Per signal: how many team-sides carried it. The honest denominator for any V2 claim."""
    counts: dict[str, dict[str, int]] = {}
    for environment in environments:
        for side in (environment.home, environment.away):
            for name, present in side.signal_coverage.items():
                block = counts.setdefault(name, {"present": 0, "absent": 0})
                block["present" if present else "absent"] += 1
    return counts
