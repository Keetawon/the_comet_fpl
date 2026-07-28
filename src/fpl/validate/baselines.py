"""The five Stage A baselines fixed by `config/phase1_evaluation.yaml`.

Each returns a distribution over team goals for one side of one fixture, so a candidate model
is compared against them with the same proper scoring rules on the same rows. They are fixed
before any model exists precisely so the comparison cannot be chosen after seeing results.

Two of them exist to answer specific open questions rather than to be beaten:

  * `trailing_goals_attack_defence` and `trailing_xg_attack_defence` are identical apart from
    what they measure attack and defence with. Running both answers whether xG or goals is the
    better training signal -- the question the original specification left open after a quick
    test favoured goals, on data that has since been repaired.
  * `promoted_team_pooled_prior` makes the cold-start policy measurable instead of assumed.

All ratings combine **multiplicatively**. Measured on this archive, `attack x opponent
defence` correlates 0.439 with goals scored while `attack - opponent defence` manages 0.070;
subtraction also discards level information and goes negative, which inverts anything
downstream that multiplies by it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

import polars as pl

from fpl.validate.metrics import Distribution, poisson_pmf

# Shrinkage weight, in units of matches, toward the league mean. A five-match average has a
# Poisson standard error near 0.541 goals against a true between-team spread of 0.440 -- the
# noise exceeds the signal -- so ratings are pulled hard toward the mean until enough matches
# accrue.
SHRINKAGE_MATCHES = 6.0

# Measured over four seasons of promoted clubs (n = 12 team-seasons), as the mean of per-team
# ratios rather than a ratio of pooled means. The spread is large -- attack sd 0.157, range
# 0.466 to 1.015 -- so this is a starting point that observed matches should override quickly,
# not a confident estimate.
PROMOTED_ATTACK_RATIO = 0.719
PROMOTED_DEFENCE_RATIO = 1.309

# One fixture row as Polars hands it back. Values are `object` because a DataFrame row is not
# statically typed, so the accessors below check rather than cast: a silent `int(None)` or an
# accidental string season would otherwise become a wrong rate rather than an error.
type Row = dict[str, object]


def _as_int(row: Row, key: str) -> int:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} should be an integer, got {value!r}")
    return value


def _as_optional_int(row: Row, key: str) -> int | None:
    return None if row.get(key) is None else _as_int(row, key)


def _as_bool(row: Row, key: str) -> bool:
    value = row[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} should be a boolean, got {value!r}")
    return value


def _as_str(row: Row, key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} should be a string, got {value!r}")
    return value


@dataclass
class TrainingWindow:
    """Team-match rows that had kicked off before a fold's cutoff."""

    frame: pl.DataFrame

    @property
    def is_empty(self) -> bool:
        return self.frame.is_empty()


class StageABaseline(ABC):
    """Fit on a training window, then predict goals for each side of each fixture."""

    name: str

    @abstractmethod
    def fit(self, window: TrainingWindow) -> None: ...

    @abstractmethod
    def predict(self, fixtures: pl.DataFrame) -> Sequence[Distribution | None]: ...

    def rate_for(self, row: Row) -> float:
        raise NotImplementedError

    def predict_rates(self, fixtures: pl.DataFrame) -> list[float]:
        return [self.rate_for(row) for row in fixtures.iter_rows(named=True)]

    def set_prediction_season(self, season: str) -> None:
        """Optional outer-fold context for candidates with season-scoped priors."""
        del season

    def is_cold_start(self, row: Row) -> bool:
        """Whether this prediction used a declared prior instead of a team estimate."""
        del row
        return False

    def parameters(self) -> dict[str, float | int | str]:
        """Fold-local selected parameters retained in the validation report."""
        return {}


def _venue_means(frame: pl.DataFrame) -> tuple[float, float]:
    """League mean goals scored at home and away in the training window."""
    home = frame.filter(pl.col("was_home"))["goals_for"].drop_nulls()
    away = frame.filter(~pl.col("was_home"))["goals_for"].drop_nulls()
    home_mean = _series_mean(home, fallback=1.4)
    away_mean = _series_mean(away, fallback=1.2)
    return home_mean, away_mean


def _series_mean(series: pl.Series, *, fallback: float) -> float:
    """Mean of a non-empty numeric series, or `fallback` when there is nothing to average."""
    if not series.len():
        return fallback
    value = series.mean()
    if not isinstance(value, (int, float)):
        raise TypeError(f"expected a numeric mean, got {value!r}")
    return float(value)


def _shrunk_ratio(observed_total: float, matches: int, league_mean: float) -> float:
    """`(n*observed + k*mu) / (n + k)` expressed as a ratio to the league mean."""
    if league_mean <= 0:
        return 1.0
    numerator = observed_total + SHRINKAGE_MATCHES * league_mean
    denominator = matches + SHRINKAGE_MATCHES
    return (numerator / denominator) / league_mean


class LeagueHomeAwayGoals(StageABaseline):
    """Intercept only: every team is the league average for its venue.

    Transparent floor. On a proper scoring rule this is much harder to beat than it looks,
    because most of a single match's outcome is irreducible.
    """

    name = "league_home_away_goals"

    def __init__(self) -> None:
        self._home = 1.4
        self._away = 1.2

    def fit(self, window: TrainingWindow) -> None:
        if not window.is_empty:
            self._home, self._away = _venue_means(window.frame)

    def rate_for(self, row: Row) -> float:
        return self._home if _as_bool(row, "was_home") else self._away

    def predict(self, fixtures: pl.DataFrame) -> list[Distribution]:
        return [poisson_pmf(rate) for rate in self.predict_rates(fixtures)]


@dataclass
class _Ratings:
    """Attack and defence multipliers keyed on `team_code`, never on `team_id`.

    A rating follows a club across seasons, and `team_id` does not: it is reassigned every
    summer and it recurs, so pooling on it produces a history that looks continuous while
    actually belonging to several different clubs.
    """

    attack: dict[int, float] = field(default_factory=dict)
    defence: dict[int, float] = field(default_factory=dict)
    matches: dict[int, int] = field(default_factory=dict)


class TrailingAttackDefence(StageABaseline):
    """`lambda = mu_venue x attack_team x defence_opponent`, from a trailing window.

    `measure` selects what attack and defence are estimated from: recorded goals, or xG. The
    two subclasses below differ in nothing else, which is what makes their comparison a clean
    answer to the xG-versus-goals question.
    """

    def __init__(self, *, measure: str, name: str) -> None:
        self.name = name
        self._measure = measure
        self._ratings = _Ratings()
        self._home = 1.4
        self._away = 1.2

    def fit(self, window: TrainingWindow) -> None:
        frame = window.frame
        if frame.is_empty():
            return
        self._home, self._away = _venue_means(frame)
        league = (self._home + self._away) / 2.0

        scored = self._measure
        conceded = "goals_against" if scored == "goals_for" else "team_xgc"

        # NULLs stay NULL: 2021-22 has no xG at all and 2022-23 none before GW16. Dropping
        # them is right; coercing them to zero would invent a league of goalless teams.
        usable = frame.drop_nulls([scored, conceded])
        if usable.is_empty():
            return

        # `maintain_order` is not cosmetic: an unordered group_by partitions across threads,
        # so a float sum lands on a different last bit from run to run. Measured on this
        # archive, 16 of 20 repeat aggregations disagreed, and that reached the reported log
        # score. A pre-registered evaluation has to reproduce exactly.
        grouped = usable.group_by("team_code", maintain_order=True).agg(
            pl.col(scored).sum().alias("scored_total"),
            pl.col(conceded).sum().alias("conceded_total"),
            pl.len().alias("matches"),
        )
        ratings = _Ratings()
        for row in grouped.iter_rows(named=True):
            team = int(row["team_code"])
            matches = int(row["matches"])
            ratings.matches[team] = matches
            ratings.attack[team] = _shrunk_ratio(float(row["scored_total"]), matches, league)
            ratings.defence[team] = _shrunk_ratio(float(row["conceded_total"]), matches, league)
        self._ratings = ratings

    def rate_for(self, row: Row) -> float:
        venue_mean = self._home if _as_bool(row, "was_home") else self._away
        attack = self._ratings.attack.get(_as_int(row, "team_code"), 1.0)
        defence = self._ratings.defence.get(_as_int(row, "opponent_team_code"), 1.0)
        return max(venue_mean * attack * defence, 0.05)

    def predict(self, fixtures: pl.DataFrame) -> list[Distribution]:
        return [poisson_pmf(rate) for rate in self.predict_rates(fixtures)]


class TrailingGoalsAttackDefence(TrailingAttackDefence):
    def __init__(self) -> None:
        super().__init__(measure="goals_for", name="trailing_goals_attack_defence")


class TrailingXgAttackDefence(TrailingAttackDefence):
    def __init__(self) -> None:
        super().__init__(measure="team_xg", name="trailing_xg_attack_defence")


class NaiveFdr(StageABaseline):
    """FPL's own fixture-difficulty rating, mapped to goals by the training data.

    The product-facing baseline: this is roughly what a manager reading the official ticker
    already believes, so beating it is the minimum bar for showing our own colours instead.
    """

    name = "naive_fdr"

    def __init__(self) -> None:
        self._cells: dict[tuple[int, bool], float] = {}
        self._fallback_home = 1.4
        self._fallback_away = 1.2

    def fit(self, window: TrainingWindow) -> None:
        frame = window.frame
        if frame.is_empty():
            return
        self._fallback_home, self._fallback_away = _venue_means(frame)
        usable = frame.drop_nulls(["fdr", "goals_for"])
        if usable.is_empty():
            return
        grouped = usable.group_by(["fdr", "was_home"], maintain_order=True).agg(
            pl.col("goals_for").mean().alias("rate")
        )
        self._cells = {
            (int(row["fdr"]), bool(row["was_home"])): float(row["rate"])
            for row in grouped.iter_rows(named=True)
        }

    def rate_for(self, row: Row) -> float:
        was_home = _as_bool(row, "was_home")
        fallback = self._fallback_home if was_home else self._fallback_away
        fdr = _as_optional_int(row, "fdr")
        if fdr is None:
            return fallback
        return self._cells.get((fdr, was_home), fallback)

    def predict(self, fixtures: pl.DataFrame) -> list[Distribution]:
        return [poisson_pmf(rate) for rate in self.predict_rates(fixtures)]


class PromotedTeamPooledPrior(StageABaseline):
    """League baseline, except clubs newly promoted into the league get the pooled prior.

    Three clubs enter every season -- 15% of the league -- and treating them as league-average
    is the most predictable error a team model can make in August.

    "Promoted" means the club was not in the league last season, resolved through
    `team_code`. It emphatically does not mean "has few matches so far this season": at
    gameweek 1 every team has none, so that reading applies the prior to all twenty clubs and
    the attack and defence adjustments largely cancel into noise. That was the first
    implementation here and it scored indistinguishably from the plain league baseline, which
    is what exposed it.

    Which clubs came up is known before a ball is kicked, so using it at gameweek 1 is not
    leakage.
    """

    name = "promoted_team_pooled_prior"

    def __init__(
        self,
        minimum_team_matches: int = 6,
        promoted: dict[str, frozenset[int]] | None = None,
    ) -> None:
        self._minimum = minimum_team_matches
        self._home = 1.4
        self._away = 1.2
        self._promoted = promoted or {}
        self._matches: dict[tuple[str, int], int] = {}

    def set_promoted(self, promoted: dict[str, frozenset[int]]) -> None:
        """Season -> `team_code` of clubs newly promoted into the league that season."""
        self._promoted = promoted

    def fit(self, window: TrainingWindow) -> None:
        frame = window.frame
        if frame.is_empty():
            return
        self._home, self._away = _venue_means(frame)
        grouped = frame.group_by(["season", "team_code"], maintain_order=True).agg(
            pl.len().alias("matches")
        )
        self._matches = {
            (str(row["season"]), int(row["team_code"])): int(row["matches"])
            for row in grouped.iter_rows(named=True)
        }

    def _is_cold_start(self, season: str, team_code: int) -> bool:
        """Newly promoted, and not yet enough matches to speak for itself."""
        if team_code not in self._promoted.get(season, frozenset()):
            return False
        return self._matches.get((season, team_code), 0) < self._minimum

    def rate_for(self, row: Row) -> float:
        season = _as_str(row, "season")
        rate = self._home if _as_bool(row, "was_home") else self._away
        if self._is_cold_start(season, _as_int(row, "team_code")):
            rate *= PROMOTED_ATTACK_RATIO
        if self._is_cold_start(season, _as_int(row, "opponent_team_code")):
            rate *= PROMOTED_DEFENCE_RATIO
        return max(rate, 0.05)

    def predict(self, fixtures: pl.DataFrame) -> list[Distribution]:
        return [poisson_pmf(rate) for rate in self.predict_rates(fixtures)]

    def is_cold_start(self, row: Row) -> bool:
        season = _as_str(row, "season")
        return self._is_cold_start(season, _as_int(row, "team_code")) or self._is_cold_start(
            season, _as_int(row, "opponent_team_code")
        )


def build_baselines(minimum_team_matches: int = 6) -> list[StageABaseline]:
    """Every baseline the contract requires, in a fixed order."""
    return [
        LeagueHomeAwayGoals(),
        TrailingGoalsAttackDefence(),
        TrailingXgAttackDefence(),
        NaiveFdr(),
        PromotedTeamPooledPrior(minimum_team_matches),
    ]


def baseline_names() -> frozenset[str]:
    return frozenset(baseline.name for baseline in build_baselines())
