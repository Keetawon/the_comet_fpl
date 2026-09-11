"""V2 defensive contribution: a team environment, allocated by role, not a personal rate.

FPL's 2026/27 rules award +2 when a player's `defensive_contribution` count reaches a position
threshold (DEF 10, MID 12, FWD 12; goalkeepers never earn it -- measured max 0).

V1 (`models/defensive_contribution_v1.py`, kept and unchanged) estimates
`P(DC >= threshold)` as a shrunk trailing hit rate over the player's own DC-measured
appearances. That is wrong in one specific, measured way, and the repository already knows it:

    "Defensive contribution is a property of the team system rather than the player (measured
     team hit rates range from 0.333 to 0.146), so a transferred player's DC expectation must
     be rescaled to the destination club, never carried over."

A personal hit rate does exactly what that rule forbids. A midfielder leaving a low-block side
for a dominant one keeps a hit rate earned in a system that gave him twice the defending to do.

V2 separates the two factors the way the minutes/rate split already separates playing time from
event rate:

    expected player DC  =  team defensive-action environment
                           x  player's ROLE SHARE of it
                           x  minutes exposure

and converts the resulting expected count to a threshold probability. The team environment
comes from the football engine, so it is a property of THIS fixture at THIS club -- a
transferred player is automatically rescaled, because he is allocated a share of his new club's
environment. The share is the part that travels with the player; the scale is the part that
does not.

Coverage governs everything. `defensive_contribution` and its raw inputs exist in exactly one
archived season (2025-26); every earlier row is NULL, which is unmeasured and never zero. With
no measured DC in a fold's training window this model returns 0.0 -- contributing nothing --
exactly as V1 does.

Pure module: no database, SQL, Polars or config read. Thresholds are passed in.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from fpl.types import Position

NAME: Final[str] = "team_environment_share_dc_threshold_v2"

# Shrinkage strength, in appearances, of a player's role share toward his position's mean
# share. A share estimated from three appearances is mostly noise; the same choice of 5.0 the
# other trailing components use, and a development choice rather than a pre-registered value.
DEFAULT_ALPHA: Final[float] = 5.0
DEFAULT_WINDOW: Final[int] = 5

# Goalkeepers cannot earn the award (measured maximum DC count: 0), so they are excluded from
# every denominator rather than being allocated a share of zero -- including them would deflate
# every outfield share by the goalkeeper rows.
DC_POSITIONS: Final[frozenset[Position]] = frozenset({Position.DEF, Position.MID, Position.FWD})


@dataclass(frozen=True, slots=True)
class DcEnvironmentHistoryRow:
    """One prior player-fixture row, as far as this component reads it.

    `defensive_contribution` and `team_defensive_actions` are `None` where unmeasured. A row
    missing either carries no share information and is skipped, never zero-filled.
    """

    code: int
    team_code: int
    position: Position
    minutes: int
    defensive_contribution: int | None
    team_defensive_actions: int | None


@dataclass(frozen=True, slots=True)
class DcPrediction:
    """A threshold probability plus the pieces it was built from.

    The decomposition is retained because it is the claim being made: if a transferred player's
    probability moves, it must be traceable to the environment changing rather than to his
    share changing, and only a decomposed prediction can show that.
    """

    hit_probability: float
    expected_count: float | None
    role_share: float | None
    team_environment: float | None
    used_environment: bool


def _threshold_probability(expected: float, threshold: int) -> float:
    """P(count >= threshold) for a Poisson of the given mean.

    A Poisson is the right shape here for the same reason it is elsewhere in this repository:
    DC is a count of independent-ish discrete actions over a match. It is an approximation --
    real defensive actions cluster -- and clustering would make the true distribution wider,
    so this understates the probability for a player well below the threshold and overstates
    it for one well above. That is recorded rather than corrected, because correcting it needs
    a measured over-dispersion parameter and DC exists in one season.
    """
    if expected <= 0.0 or threshold <= 0:
        return 0.0
    # 1 - P(count <= threshold - 1), summed forward to avoid cancelling large terms.
    cumulative = 0.0
    term = math.exp(-expected)
    for count in range(threshold):
        if count:
            term *= expected / count
        cumulative += term
    return max(0.0, min(1.0, 1.0 - cumulative))


class DefensiveEnvironmentV2:
    """Fold-local role-share estimator over a predicted team defensive-action environment."""

    name: str = NAME

    def __init__(self, *, alpha: float = DEFAULT_ALPHA, window: int = DEFAULT_WINDOW) -> None:
        self._alpha = alpha
        self._window = window
        self._player_shares: dict[int, tuple[float, int]] = {}
        self._position_shares: dict[Position, float] = {}
        self._position_counts: dict[Position, float] = {}
        self._has_measured_dc = False

    def fit(self, history: Sequence[DcEnvironmentHistoryRow]) -> None:
        """Estimate each player's share of his club's defensive actions, and position means.

        The share is `player DC / team defensive actions` on the same fixture, so it is
        dimensionless and comparable between clubs -- which is the whole point. Rows without
        both measurements are skipped; a fold with none leaves the model contributing nothing.
        """
        by_player: dict[int, list[float]] = {}
        by_position: dict[Position, list[float]] = {}
        for row in history:
            if row.position not in DC_POSITIONS or row.minutes <= 0:
                continue
            if row.defensive_contribution is None or row.team_defensive_actions is None:
                continue
            if row.team_defensive_actions <= 0:
                continue
            share = row.defensive_contribution / row.team_defensive_actions
            by_player.setdefault(row.code, []).append(share)
            by_position.setdefault(row.position, []).append(share)

        self._has_measured_dc = bool(by_position)
        self._position_shares = {
            position: sum(values) / len(values) for position, values in by_position.items()
        }
        self._position_counts = {
            position: float(len(values)) for position, values in by_position.items()
        }
        self._player_shares = {}
        for code, shares in by_player.items():
            recent = shares[-self._window :]
            self._player_shares[code] = (sum(recent) / len(recent), len(recent))

    @property
    def has_measured_dc(self) -> bool:
        return self._has_measured_dc

    def role_share(self, code: int, position: Position) -> float | None:
        """Shrunk share of the club's defensive actions this player is expected to make.

        Shrinkage is toward the POSITION mean, not the overall mean: a defender and a forward
        make very different shares of the same team's defending, and a pooled target would pull
        both toward a number that describes neither.
        """
        if position not in DC_POSITIONS or not self._has_measured_dc:
            return None
        prior = self._position_shares.get(position)
        if prior is None:
            return None
        observed, appearances = self._player_shares.get(code, (0.0, 0))
        if appearances == 0:
            return prior
        return (observed * appearances + prior * self._alpha) / (appearances + self._alpha)

    def predict_detail(
        self,
        *,
        code: int,
        position: Position,
        threshold: int | None,
        team_defensive_actions: float | None,
        minutes_exposure: float = 1.0,
    ) -> DcPrediction:
        """Threshold probability for one player-fixture.

        `team_defensive_actions` is the football engine's prediction for THIS club in THIS
        fixture, so a transferred player is rescaled by construction. `None` means the engine
        had no defensive-action signal -- a coverage fact, and the model then contributes
        nothing rather than inventing an environment.

        `minutes_exposure` is the share of the match the player is expected to be on the pitch
        for. It is a linear thinning of an action count, which is the right first-order
        treatment and is deliberately NOT the exposure curve measured for goals conceded: that
        curve is steep because a substitute enters a game already going badly, an effect
        specific to conceding rather than to defending generally, and importing it here would
        be borrowing a constant measured for a different quantity.
        """
        if position not in DC_POSITIONS or threshold is None or threshold <= 0:
            return DcPrediction(0.0, None, None, None, False)
        share = self.role_share(code, position)
        if share is None or team_defensive_actions is None or team_defensive_actions <= 0:
            return DcPrediction(0.0, None, share, team_defensive_actions, False)
        expected = team_defensive_actions * share * max(minutes_exposure, 0.0)
        return DcPrediction(
            hit_probability=_threshold_probability(expected, threshold),
            expected_count=expected,
            role_share=share,
            team_environment=team_defensive_actions,
            used_environment=True,
        )

    def predict(
        self,
        *,
        code: int,
        position: Position,
        threshold: int | None,
        team_defensive_actions: float | None,
        minutes_exposure: float = 1.0,
    ) -> float:
        """The threshold probability alone, matching `DefensiveContributionV1.predict`."""
        return self.predict_detail(
            code=code,
            position=position,
            threshold=threshold,
            team_defensive_actions=team_defensive_actions,
            minutes_exposure=minutes_exposure,
        ).hit_probability

    def parameters(self) -> Mapping[str, float]:
        return {
            "alpha": self._alpha,
            "window": float(self._window),
            "players_with_share": float(len(self._player_shares)),
            "positions_with_prior": float(len(self._position_shares)),
            **{
                f"position_share_{position.value.lower()}": value
                for position, value in self._position_shares.items()
            },
        }
