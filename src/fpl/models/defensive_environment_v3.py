"""Development-only predicted CBIRT environment and prequential Gamma-Poisson DC.

No database, target-row exposure, provider imputation, or production entry point.
The opportunity ratio is NOT a conserved share: DEF DC omits recoveries, whereas
the common team CBIRT opportunity denominator includes them for every position.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from fpl.models.attacking_baselines import poisson_pmf
from fpl.types import Position

NAME = "retrospective_predicted_environment_gamma_poisson_dc_v1"
EVIDENCE_CLASS = "retrospective_archive_price_proxy_development"
WINDOW = 5
PRIOR_MATCHES = 5.0
DISPERSION_MINIMUM_ROWS = 200
DISPERSION_PRIOR_ROWS = 100.0
MAXIMUM_COUNT = 60
COMPLETION_MARGIN = timedelta(hours=6)


def _aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("timezone-aware event/cutoff required")


def _nonnegative(value: float, label: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError(f"finite nonnegative {label} required")


def _count(value: int | None, label: str) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"nullable nonnegative integer {label} required")


def _minutes(value: Sequence[float]) -> None:
    if len(value) != 4:
        raise ValueError("exact four-bin minutes PMF required")
    for mass in value:
        _nonnegative(mass, "minutes probability")
    if not math.isclose(math.fsum(value), 1.0, abs_tol=1e-12, rel_tol=0):
        raise ValueError("minutes PMF mass differs from one")


def _identity(season: str, gw: int, fixture: int, team_code: int, kickoff: datetime) -> None:
    _aware(kickoff)
    if not season or any(type(v) is not int or v <= 0 for v in (gw, fixture, team_code)):
        raise ValueError("season-qualified stable fixture/team identity required")


@dataclass(frozen=True, slots=True)
class DcPlayerObservation:
    season: str
    gw: int
    fixture: int
    kickoff: datetime
    code: int
    team_code: int
    position: Position
    minutes: int | None
    defensive_contribution: int | None

    def __post_init__(self) -> None:
        _identity(self.season, self.gw, self.fixture, self.team_code, self.kickoff)
        if type(self.code) is not int or self.code <= 0 or not isinstance(self.position, Position):
            raise ValueError("stable player identity and position required")
        _count(self.minutes, "minutes")
        _count(self.defensive_contribution, "DC")
        if self.minutes is not None and self.minutes > 120:
            raise ValueError("playing minutes exceed supported observation range")


@dataclass(frozen=True, slots=True)
class DcTeamObservation:
    season: str
    gw: int
    fixture: int
    kickoff: datetime
    team_code: int
    defensive_actions: int | None

    def __post_init__(self) -> None:
        _identity(self.season, self.gw, self.fixture, self.team_code, self.kickoff)
        _count(self.defensive_actions, "team CBIRT")


@dataclass(frozen=True, slots=True)
class DcTarget:
    season: str
    gw: int
    fixture: int
    kickoff: datetime
    code: int
    team_code: int
    position: Position
    minutes_pmf: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        _identity(self.season, self.gw, self.fixture, self.team_code, self.kickoff)
        if type(self.code) is not int or self.code <= 0 or not isinstance(self.position, Position):
            raise ValueError("stable player identity and position required")
        _minutes(self.minutes_pmf)


@dataclass(frozen=True, slots=True)
class DcMeanPrediction:
    target: DcTarget
    as_of: datetime
    maximum_source_kickoff: datetime | None
    history_sha256: str
    team_environment: float | None
    intensity_ratio: float | None
    full_match_mean: float | None
    means_by_minutes_bin: tuple[float, float, float, float] | None
    exposure_minutes_by_bin: tuple[float, float, float, float]
    team_history_matches: int
    player_history_appearances: int
    past_witnessed_transfer: bool
    evidence_class: str = EVIDENCE_CLASS

    def __post_init__(self) -> None:
        _aware(self.as_of)
        if self.target.kickoff < self.as_of or self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("invalid pre-fixture retrospective mean provenance")
        if len(self.history_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.history_sha256
        ):
            raise ValueError("mean prediction requires an immutable prior-history fingerprint")
        for value in (self.team_environment, self.intensity_ratio, self.full_match_mean):
            if value is not None:
                _nonnegative(value, "decomposition value")
        if self.maximum_source_kickoff is not None:
            _aware(self.maximum_source_kickoff)
            if self.maximum_source_kickoff + COMPLETION_MARGIN >= self.as_of:
                raise ValueError("mean source event reaches cutoff/completion margin")
        if self.means_by_minutes_bin is not None:
            if len(self.means_by_minutes_bin) != 4 or self.means_by_minutes_bin[0] != 0:
                raise ValueError(
                    "four conditional count means with exact zero nonappearance required"
                )
            for value in self.means_by_minutes_bin:
                _nonnegative(value, "conditional mean")


class PredictedDefensiveEnvironment:
    """Fixed recent opportunity state, fitted only before one complete target GW."""

    def __init__(self) -> None:
        self.as_of: datetime | None = None
        self.excluded_target_gw: tuple[str, int] | None = None
        self.maximum_source_kickoff: datetime | None = None
        self.history_sha256 = ""
        self.league_environment: float | None = None
        self.team_history: dict[int, list[float]] = {}
        self.player_history: dict[tuple[int, Position], list[tuple[int, float]]] = {}
        self.position_ratios: dict[Position, float] = {}
        self.club_witnesses: dict[tuple[str, int], set[int]] = {}
        self.exposure_minutes_by_bin = (0.0, 59.0, 89.0, 90.0)

    def fit(
        self,
        players: Sequence[DcPlayerObservation],
        teams: Sequence[DcTeamObservation],
        *,
        as_of: datetime,
        excluded_target_gw: tuple[str, int],
    ) -> PredictedDefensiveEnvironment:
        self.as_of = None
        _aware(as_of)
        if not excluded_target_gw[0] or type(excluded_target_gw[1]) is not int:
            raise ValueError("explicit whole target-GW exclusion required")
        prior_players = sorted(
            (
                r
                for r in players
                if r.kickoff + COMPLETION_MARGIN < as_of and (r.season, r.gw) != excluded_target_gw
            ),
            key=lambda r: (r.kickoff, r.season, r.fixture, r.code),
        )
        prior_teams = sorted(
            (
                r
                for r in teams
                if r.kickoff + COMPLETION_MARGIN < as_of and (r.season, r.gw) != excluded_target_gw
            ),
            key=lambda r: (r.kickoff, r.season, r.fixture, r.team_code),
        )
        pkeys = [(r.season, r.fixture, r.code) for r in prior_players]
        tkeys = [(r.season, r.fixture, r.team_code) for r in prior_teams]
        if len(pkeys) != len(set(pkeys)) or len(tkeys) != len(set(tkeys)):
            raise ValueError("duplicate prior player/team fixture")
        team_map = {(r.season, r.fixture, r.team_code): r for r in prior_teams}
        measured = [r.defensive_actions for r in prior_teams if r.defensive_actions is not None]
        self.league_environment = math.fsum(measured) / len(measured) if measured else None
        self.team_history = defaultdict(list)
        self.player_history = defaultdict(list)
        self.club_witnesses = defaultdict(set)
        totals: dict[Position, list[float]] = defaultdict(lambda: [0.0, 0.0])
        exposures: dict[int, list[int]] = defaultdict(list)
        for team_row in prior_teams:
            if team_row.defensive_actions is not None:
                self.team_history[team_row.team_code].append(float(team_row.defensive_actions))
        for row in prior_players:
            self.club_witnesses[row.season, row.code].add(row.team_code)
            if (
                row.position is Position.GK
                or row.minutes is None
                or row.minutes <= 0
                or row.defensive_contribution is None
            ):
                continue
            bin_index = 1 if row.minutes < 60 else 2 if row.minutes < 90 else 3
            exposures[bin_index].append(row.minutes)
            team = team_map.get((row.season, row.fixture, row.team_code))
            if team is None:
                continue
            if team.kickoff != row.kickoff or team.gw != row.gw:
                raise ValueError("player and team fixture metadata contradict")
            if (
                team.defensive_actions is not None
                and row.defensive_contribution > team.defensive_actions
            ):
                raise ValueError("player DC exceeds the complete team's CBIRT opportunity count")
            if team.defensive_actions is None or team.defensive_actions <= 0:
                continue
            opportunity = team.defensive_actions * row.minutes / 90
            self.player_history[row.code, row.position].append(
                (row.defensive_contribution, opportunity)
            )
            totals[row.position][0] += row.defensive_contribution
            totals[row.position][1] += opportunity
        self.position_ratios = {
            position: ys / exposure for position, (ys, exposure) in totals.items()
        }
        values = tuple(
            math.fsum(exposures[b]) / len(exposures[b]) if exposures[b] else fallback
            for b, fallback in enumerate((0.0, 59.0, 89.0, 90.0))
        )
        self.exposure_minutes_by_bin = values[0], values[1], values[2], values[3]
        self.maximum_source_kickoff = max(
            [r.kickoff for r in prior_players] + [r.kickoff for r in prior_teams], default=None
        )
        self.history_sha256 = hashlib.sha256(
            json.dumps(
                [[asdict(r) for r in prior_players], [asdict(r) for r in prior_teams]],
                sort_keys=True,
                separators=(",", ":"),
                default=lambda v: v.isoformat(),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        self.excluded_target_gw = excluded_target_gw
        self.as_of = as_of
        return self

    def predict_mean(self, target: DcTarget) -> DcMeanPrediction:
        if self.as_of is None:
            raise ValueError("fit a prior-only target-GW state first")
        if (target.season, target.gw) != self.excluded_target_gw or target.kickoff < self.as_of:
            raise ValueError("prediction must belong to the fitted whole target GW")
        team_recent = self.team_history.get(target.team_code, [])[-WINDOW:]
        player_recent = self.player_history.get((target.code, target.position), [])[-WINDOW:]
        position_prior = self.position_ratios.get(target.position)
        environment = ratio = full_mean = None
        means = None
        if self.league_environment is not None:
            environment = (math.fsum(team_recent) + PRIOR_MATCHES * self.league_environment) / (
                len(team_recent) + PRIOR_MATCHES
            )
            if position_prior is not None and self.league_environment > 0:
                prior_opportunity = PRIOR_MATCHES * self.league_environment
                ratio = (
                    math.fsum(y for y, _ in player_recent) + prior_opportunity * position_prior
                ) / (math.fsum(e for _, e in player_recent) + prior_opportunity)
                full_mean = environment * ratio
                values = tuple(full_mean * m / 90 for m in self.exposure_minutes_by_bin)
                means = values[0], values[1], values[2], values[3]
        return DcMeanPrediction(
            target,
            self.as_of,
            self.maximum_source_kickoff,
            self.history_sha256,
            environment,
            ratio,
            full_mean,
            means,
            self.exposure_minutes_by_bin,
            len(team_recent),
            len(player_recent),
            any(
                team != target.team_code
                for team in self.club_witnesses.get((target.season, target.code), set())
            ),
        )


@dataclass(frozen=True, slots=True)
class DcOosObservation:
    prediction: DcMeanPrediction
    observed_count: int | None
    observed_minutes: int | None

    def __post_init__(self) -> None:
        _count(self.observed_count, "observed DC target")
        _count(self.observed_minutes, "observed minutes target")
        if self.observed_minutes is not None and self.observed_minutes > 120:
            raise ValueError("observed OOS minutes exceed supported range")


@dataclass(frozen=True, slots=True)
class DispersionEstimate:
    alpha: float
    rows: int
    residual_excess_sum: float
    conditional_squared_mean_sum: float
    shrinkage: float
    maximum_oos_kickoff: datetime | None
    used_dispersion: bool
    as_of: datetime
    excluded_target_gw: tuple[str, int]

    def __post_init__(self) -> None:
        _aware(self.as_of)
        _nonnegative(self.alpha, "dispersion")
        if self.maximum_oos_kickoff is not None:
            _aware(self.maximum_oos_kickoff)
            if self.maximum_oos_kickoff + COMPLETION_MARGIN >= self.as_of:
                raise ValueError("dispersion source reaches target cutoff")


def fit_dispersion(
    observations: Sequence[DcOosObservation],
    *,
    as_of: datetime,
    excluded_target_gw: tuple[str, int],
) -> DispersionEstimate:
    """NB2 residual moment estimate from earlier frozen OOS means, not in-sample fits.

    Subtract both Poisson variance and the forecast minutes-bin mixture variance.
    Observed minutes only identify the predeclared appeared label cohort; they never
    choose a bin or alter a forecast mean. No full-season variance constant is used.
    """
    _aware(as_of)
    excess, squared_means = [], []
    maximum = None
    seen = set()
    for row in sorted(
        observations,
        key=lambda r: (
            r.prediction.target.kickoff,
            r.prediction.target.season,
            r.prediction.target.fixture,
            r.prediction.target.code,
        ),
    ):
        prediction = row.prediction
        target = prediction.target
        if (
            target.kickoff + COMPLETION_MARGIN >= as_of
            or (target.season, target.gw) == excluded_target_gw
        ):
            continue
        key = target.season, target.fixture, target.code
        if key in seen:
            raise ValueError("duplicate OOS player-fixture forecast")
        seen.add(key)
        if (
            row.observed_minutes is None
            or row.observed_minutes <= 0
            or row.observed_count is None
            or prediction.means_by_minutes_bin is None
        ):
            continue
        played = math.fsum(target.minutes_pmf[1:])
        if played <= 0:
            continue
        weights = [p / played for p in target.minutes_pmf]
        weights[0] = 0.0
        means = prediction.means_by_minutes_bin
        mean = math.fsum(w * m for w, m in zip(weights, means, strict=True))
        second = math.fsum(w * m * m for w, m in zip(weights, means, strict=True))
        mixture_variance = max(0.0, second - mean * mean)
        excess.append((row.observed_count - mean) ** 2 - mean - mixture_variance)
        squared_means.append(second)
        maximum = target.kickoff
    n = len(excess)
    numerator, denominator = math.fsum(excess), math.fsum(squared_means)
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        raise ValueError("nonfinite prequential dispersion moments")
    used = n >= DISPERSION_MINIMUM_ROWS and denominator > 0
    shrinkage = n / (n + DISPERSION_PRIOR_ROWS) if used else 0.0
    alpha = max(0.0, numerator / denominator) * shrinkage if used else 0.0
    _nonnegative(alpha, "dispersion")
    return DispersionEstimate(
        alpha, n, numerator, denominator, shrinkage, maximum, used, as_of, excluded_target_gw
    )


def gamma_poisson_pmf(mean: float, alpha: float, maximum: int = MAXIMUM_COUNT) -> tuple[float, ...]:
    """NB2; support 0..maximum-1 plus >=maximum. Alpha=0 is exact existing Poisson.

    Stable log-CDF gives the overflow mass even when P(0) rounds to one under a
    very large finite dispersion. Nonrepresentable arithmetic fails, not clipped
    to an arbitrary fitted dispersion or count-mean ceiling.
    """
    _nonnegative(mean, "mean")
    _nonnegative(alpha, "dispersion")
    if type(maximum) is not int or maximum < 1:
        raise ValueError("positive count support required")
    if mean == 0 or alpha == 0:
        return poisson_pmf(mean, max_goals=maximum)
    product = mean * alpha
    if not math.isfinite(product):
        raise ValueError("Gamma-Poisson mean/dispersion arithmetic overflow")
    log_denominator = math.log1p(product)
    log_probability = -mean * (log_denominator / product if product else 1.0)
    logs = [log_probability]
    for k in range(1, maximum):
        factor = (k - 1) * alpha
        log_factor = (
            math.log1p(factor) if math.isfinite(factor) else math.log(k - 1) + math.log(alpha)
        )
        log_probability += math.log(mean) + log_factor - math.log(k) - log_denominator
        logs.append(log_probability)
    largest = max(logs)
    log_cdf = largest + math.log(math.fsum(math.exp(p - largest) for p in logs))
    masses = [math.exp(p) for p in logs]
    masses.append(-math.expm1(min(0.0, log_cdf)))
    total = math.fsum(masses)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("invalid Gamma-Poisson probability mass")
    return tuple(p / total for p in masses)


@dataclass(frozen=True, slots=True)
class DcThresholdForecast:
    conditional_hit_probability: float
    marginal_hit_probability: float
    conditional_count_pmf: tuple[float, ...] | None
    marginal_count_pmf: tuple[float, ...] | None
    dispersion: float
    fallback: str | None


def predict_threshold(
    prediction: DcMeanPrediction,
    dispersion: DispersionEstimate,
    threshold: int,
    incumbent_conditional_probability: float,
) -> DcThresholdForecast:
    _nonnegative(incumbent_conditional_probability, "incumbent probability")
    if (
        incumbent_conditional_probability > 1
        or type(threshold) is not int
        or not 1 <= threshold <= MAXIMUM_COUNT
    ):
        raise ValueError("invalid incumbent probability or threshold")
    _nonnegative(dispersion.alpha, "dispersion")
    if dispersion.as_of != prediction.as_of or dispersion.excluded_target_gw != (
        prediction.target.season,
        prediction.target.gw,
    ):
        raise ValueError("dispersion and mean must be fitted for the same pre-GW cutoff")
    played = math.fsum(prediction.target.minutes_pmf[1:])
    if prediction.means_by_minutes_bin is None or played <= 0:
        return DcThresholdForecast(
            incumbent_conditional_probability,
            played * incumbent_conditional_probability,
            None,
            None,
            dispersion.alpha,
            "no_predicted_appearance" if played <= 0 else "unavailable_prior_opportunity",
        )
    distributions = [
        gamma_poisson_pmf(mean, dispersion.alpha) for mean in prediction.means_by_minutes_bin
    ]
    weights = prediction.target.minutes_pmf
    marginal = tuple(
        math.fsum(weights[b] * distributions[b][k] for b in range(4))
        for k in range(MAXIMUM_COUNT + 1)
    )
    conditional = tuple(
        math.fsum(weights[b] * distributions[b][k] for b in range(1, 4)) / played
        for k in range(MAXIMUM_COUNT + 1)
    )
    conditional_hit = math.fsum(conditional[threshold:])
    return DcThresholdForecast(
        conditional_hit, played * conditional_hit, conditional, marginal, dispersion.alpha, None
    )
