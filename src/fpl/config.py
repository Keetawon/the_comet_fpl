"""Configuration loading and validation.

R2: scoring rules are configuration, not code. Every scoring constant lives in
`config/scoring_<ruleset>.yaml` and reaches the calculator only through `ScoringRules`.
`extra="forbid"` throughout, so a typo or an upstream rule change surfaces as a
validation error rather than a silently ignored key.
"""

from __future__ import annotations

import functools
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fpl.types import Position, RulesetId, Season


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------------------
# Scoring rules
# --------------------------------------------------------------------------------------


class AppearanceRules(_Frozen):
    short_play_points: int
    long_play_points: int
    long_play_minutes: int


class CleanSheetRules(_Frozen):
    minimum_minutes: int
    points: dict[Position, int]


class UnitRule(_Frozen):
    """A "N points per K events, for these positions only" rule.

    Covers goals conceded (-1 per 2, GK and DEF) and saves (+1 per 3, GK only).
    """

    points_per_unit: int
    unit: int
    positions: frozenset[Position]

    @field_validator("unit")
    @classmethod
    def _unit_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("unit must be >= 1")
        return value


class DefensiveContributionRules(_Frozen):
    """Threshold counts, not points.

    A position absent from `thresholds` can never earn DC. GK is deliberately absent
    (gotcha 7: goalkeeper defensive_contribution is always 0, measured max 0).
    """

    points: int
    thresholds: dict[Position, int]

    @field_validator("thresholds")
    @classmethod
    def _gk_never_earns_dc(cls, value: dict[Position, int]) -> dict[Position, int]:
        if Position.GK in value:
            raise ValueError(
                "goalkeepers never earn defensive contribution (gotcha 7); "
                "omit GK from thresholds rather than setting it to 0"
            )
        return value


class BonusRules(_Frozen):
    """Bonus is a rank within the match, never a per-player regression target.

    Phase 0 passes the recorded value through. `bps_rank` is the Stage D mode.
    """

    mode: Literal["passthrough", "bps_rank"]
    ranked_points: tuple[int, int, int]


class AuthoritativeRuleSource(_Frozen):
    """One captured official source that confirms named scoring fields."""

    source_id: str
    title: str
    url: str
    published_on: date | None = None
    captured_at: datetime
    sha256: str
    confirmed: frozenset[str]
    notes: str | None = None

    @field_validator("url")
    @classmethod
    def _official_https_source(cls, value: str) -> str:
        parsed = urlparse(value)
        official_hosts = {"fantasy.premierleague.com", "www.premierleague.com"}
        if parsed.scheme != "https" or parsed.hostname not in official_hosts:
            raise ValueError("authoritative rule source must be an official Premier League URL")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("authoritative rule source sha256 must be 64 lowercase hex characters")
        return value


class VerificationBlock(_Frozen):
    """Provenance for a ruleset. Three independent notions of trust.

    `payload_confirmed` -- the value matches the live `game_config.scoring`.
    `authoritative_sources` -- the value appears in an official published rule source.
    `replay_exercised`  -- the rule actually fired against recorded data.

    They are not the same and a value can have one without the others.
    `goals_scored.GK` is precisely that case: a payload confirms the number FPL
    publishes, but no goalkeeper scored in the validation data, so no replay can
    exercise it.
    """

    payload_captured_at: datetime | None = None
    payload_sha256: str | None = None
    payload_confirmed: list[str] = Field(default_factory=list)
    authoritative_sources: list[AuthoritativeRuleSource] = Field(default_factory=list)
    replay_exercised: list[str] = Field(default_factory=list)
    unverified: dict[str, str] = Field(default_factory=dict)

    def authoritatively_confirmed(self) -> frozenset[str]:
        return frozenset(path for source in self.authoritative_sources for path in source.confirmed)

    def is_confirmed(self, dotted_path: str) -> bool:
        observed = (
            dotted_path in self.payload_confirmed or dotted_path in self.authoritatively_confirmed()
        )
        return observed and dotted_path not in self.unverified


class ScoringRules(_Frozen):
    """One season's scoring function, as data."""

    ruleset_id: RulesetId
    season: Season
    appearance: AppearanceRules
    goals_scored: dict[Position, int]
    assists: int
    clean_sheets: CleanSheetRules
    goals_conceded: UnitRule
    saves: UnitRule
    penalties_saved: int
    penalties_missed: int
    own_goals: int
    yellow_cards: int
    red_cards: int
    defensive_contribution: DefensiveContributionRules
    bonus: BonusRules
    verification: VerificationBlock = Field(default_factory=VerificationBlock)

    @field_validator("goals_scored")
    @classmethod
    def _all_positions_priced(cls, value: dict[Position, int]) -> dict[Position, int]:
        missing = set(Position) - set(value)
        if missing:
            raise ValueError(f"goals_scored missing positions: {sorted(missing)}")
        return value


# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------


class ArchiveSource(_Frozen):
    base_url: str
    seasons: list[Season]
    files: dict[str, str]

    def url(self, season: Season, file_key: str) -> str:
        return f"{self.base_url}/{season}/{self.files[file_key]}"


class LiveApiSource(_Frozen):
    base_url: str
    endpoints: dict[str, str]
    min_request_interval_seconds: float
    timeout_seconds: float
    max_retries: int
    retry_backoff_base_seconds: float


class CurrentSeason(_Frozen):
    season: Season
    ruleset_id: RulesetId
    gw1_deadline: datetime


class Paths(_Frozen):
    database: str
    archive_cache: str
    snapshots: str


class SourcesConfig(_Frozen):
    archive: ArchiveSource
    live_api: LiveApiSource
    current_season: CurrentSeason
    paths: Paths


# --------------------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------------------


class NullifyExpectation(_Frozen):
    null_through_gw: int
    not_null_from_gw: int


class NullifyRule(_Frozen):
    """A declared repair of present-but-not-measured values.

    Only ever widens NULL coverage; it never writes a value.
    """

    id: str
    season: Season
    columns: list[str]
    reason: str
    gw_max: int | None = None
    gw_min: int | None = None
    expect: NullifyExpectation | None = None


class RangeRule(_Frozen):
    min: float
    max: float


class ConsistencyRule(_Frozen):
    id: str
    description: str
    predicate: str


class ExpectedAnomaly(_Frozen):
    id: str
    description: str
    season: Season | None = None


class DataQualityConfig(_Frozen):
    nullify: list[NullifyRule] = Field(default_factory=list)
    ranges: dict[str, RangeRule] = Field(default_factory=dict)
    consistency: list[ConsistencyRule] = Field(default_factory=list)
    expected_anomalies: list[ExpectedAnomaly] = Field(default_factory=list)

    def nullify_for(self, season: Season) -> list[NullifyRule]:
        return [rule for rule in self.nullify if rule.season == season]


# --------------------------------------------------------------------------------------
# Phase 1 evaluation contract
# --------------------------------------------------------------------------------------


class Phase1TargetPolicy(_Frozen):
    entity: Literal["team"]
    grain: Literal["season_team_fixture"]
    outcome: Literal["goals_distribution"]
    downstream_points_ruleset: RulesetId
    completeness_table: Literal["mart_target_completeness"]
    incomplete_target_policy: Literal["exclude_and_report"]


class Phase1CutoffPolicy(_Frozen):
    split_unit: Literal["observed_gameweek"]
    prediction_time: Literal["archive_first_kickoff_proxy_for_gameweek_deadline"]
    observed_results: Literal["kickoff_time < as_of"]
    snapshot_versions: Literal["known_at <= as_of"]


class Phase1TrainingPolicy(_Frozen):
    window: Literal["expanding"]
    minimum_observed_gameweeks: int = Field(ge=1)
    minimum_team_matches: int = Field(ge=1)
    fit_transforms_within_fold: Literal[True]
    preserve_nulls: Literal[True]
    seed: int = Field(ge=0)


class Phase1StageACandidatePolicy(_Frozen):
    """Pre-registered Candidate V2 search space and numerical fit policy."""

    name: Literal["dixon_coles_team_goals_v2"]
    inner_holdout_observed_gameweeks: int = Field(ge=1)
    minimum_inner_training_observed_gameweeks: int = Field(ge=1)
    half_life_days: tuple[float, ...] = Field(min_length=1)
    include_no_decay: Literal[True]
    prior_matches: tuple[float, ...] = Field(min_length=1)
    fallback_half_life_days: float | None
    fallback_prior_matches: float = Field(gt=0.0)
    promoted_attack_prior: float = Field(gt=0.0)
    promoted_defence_prior: float = Field(gt=0.0)
    xg_policy: Literal["use_when_measured_scaled_to_goals"]
    rate_floor: float = Field(gt=0.0)
    maximum_fit_sweeps: int = Field(ge=1)
    fit_tolerance: float = Field(gt=0.0)
    rho_minimum: float
    rho_maximum: float
    rho_step: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _valid_search_space(self) -> Self:
        if self.minimum_inner_training_observed_gameweeks < self.inner_holdout_observed_gameweeks:
            raise ValueError("inner training history cannot be shorter than the holdout")
        if any(value <= 0.0 for value in self.half_life_days):
            raise ValueError("half-life values must be positive")
        if tuple(sorted(set(self.half_life_days))) != self.half_life_days:
            raise ValueError("half-life values must be unique and increasing")
        if any(value <= 0.0 for value in self.prior_matches):
            raise ValueError("prior-match values must be positive")
        if tuple(sorted(set(self.prior_matches))) != self.prior_matches:
            raise ValueError("prior-match values must be unique and increasing")
        if self.fallback_half_life_days is not None and (
            self.fallback_half_life_days not in self.half_life_days
        ):
            raise ValueError("fallback half-life must be in the declared grid or null")
        if self.fallback_prior_matches not in self.prior_matches:
            raise ValueError("fallback prior strength must be in the declared grid")
        if self.rho_minimum >= self.rho_maximum:
            raise ValueError("rho_minimum must be below rho_maximum")
        return self


class Phase1StageACandidateV3Policy(_Frozen):
    """Pre-registered Candidate V3 search space: a sequential dynamic team-goals filter.

    Candidate V3 is a *development-only* structural probe, not a promotion candidate. It
    exists to test whether a sequential, mean-reverting online Poisson filter adapts to
    changing team strength more honestly than V2's batch re-fit. Its policy is additive to
    the contract: it shares none of V2's fields, changes no baseline, gate, tolerance, or
    eligible row, and is never substituted for V2 by the default harness command. The
    `development_only` flag is pinned `True` so a config that silently promoted V3 to a
    promotion candidate would fail to load.
    """

    name: Literal["dynamic_team_goals_v3"]
    development_only: Literal[True]
    inner_holdout_observed_gameweeks: int = Field(ge=1)
    minimum_inner_training_observed_gameweeks: int = Field(ge=1)
    # Per-match Poisson log-likelihood gradient step (adaptation speed).
    learning_rate: tuple[float, ...] = Field(min_length=1)
    # Per-appearance retention: state persistence / mean reversion within a season.
    retention: tuple[float, ...] = Field(min_length=1)
    # Explicit between-season shrinkage applied once at each season boundary.
    season_retention: tuple[float, ...] = Field(min_length=1)
    fallback_learning_rate: float = Field(gt=0.0)
    fallback_retention: float = Field(gt=0.0, le=1.0)
    fallback_season_retention: float = Field(gt=0.0, le=1.0)
    promoted_attack_prior: float = Field(gt=0.0)
    promoted_defence_prior: float = Field(gt=0.0)
    xg_policy: Literal["use_when_measured_scaled_to_goals"]
    rate_floor: float = Field(gt=0.0)
    log_strength_cap: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _valid_search_space(self) -> Self:
        if self.minimum_inner_training_observed_gameweeks < self.inner_holdout_observed_gameweeks:
            raise ValueError("inner training history cannot be shorter than the holdout")
        for label, grid, lo, hi in (
            ("learning_rate", self.learning_rate, 0.0, None),
            ("retention", self.retention, 0.0, 1.0),
            ("season_retention", self.season_retention, 0.0, 1.0),
        ):
            if any(value <= lo for value in grid):
                raise ValueError(f"{label} values must be greater than {lo}")
            if hi is not None and any(value > hi for value in grid):
                raise ValueError(f"{label} values must not exceed {hi}")
            if tuple(sorted(set(grid))) != grid:
                raise ValueError(f"{label} values must be unique and increasing")
        if self.fallback_learning_rate not in self.learning_rate:
            raise ValueError("fallback learning rate must be in the declared grid")
        if self.fallback_retention not in self.retention:
            raise ValueError("fallback retention must be in the declared grid")
        if self.fallback_season_retention not in self.season_retention:
            raise ValueError("fallback season retention must be in the declared grid")
        return self


class Phase1StageACandidateV4Policy(_Frozen):
    """Pre-registered Candidate V4: the leakage-safe sequential dynamic team-goals filter.

    V4 is the structural successor to the *invalidated* V3. It keeps V3's mean-reverting online
    Poisson filter but fixes the four defects that voided V3's development number. Three of the
    fixes are procedure pins declared here as ``Literal[True]`` so that ``extra="forbid"`` makes a
    config that silently weakens one fail to load rather than be ignored:

    * ``holdout_walk_forward`` -- the inner holdout is a true per-observed-gameweek walk-forward
      (predict every fixture in a gameweek from the pre-gameweek state, score, then absorb that
      gameweek's results before advancing), never the one-frozen-state scoring V3 used.
    * ``cold_start_in_fitting`` -- the six-match cold-start prior is applied in the fitting
      residual as well as in prediction, not only at prediction time.
    * ``returning_promoted_count_reset`` -- a club's eligible match count is reset for every
      newly promoted season (including a club relegated and promoted back), while incumbents
      keep their declared summer retention.

    The fourth fix replaces V3's full-archive promoted constants with a fold-local estimator:
    ``promoted_prior_source = fold_local_earlier_cohorts`` estimates the prior from promoted
    cohorts whose matches are inside the fold (seasons strictly before the prediction season),
    excludes the current promoted cohort from its own prior, and falls back to a declared
    neutral ``1.0 / 1.0`` when no eligible cohort exists. ``promoted_prior_min_matches`` fixes
    the sample behaviour (a cohort club needs this many matches in its promotion season to
    count) and ``promoted_prior_shrinkage_matches`` fixes the shrinkage weight toward neutral.

    Like V3 this block is additive and optional, shares no field with V2, substitutes for
    nothing, changes no baseline, gate, tolerance, or eligible row, and is never loaded into the
    default harness command. ``development_only`` is pinned ``True``: V4 is judged by no gate
    here until it is evaluated, and no V4 historical number exists yet.
    """

    name: Literal["dynamic_team_goals_v4"]
    development_only: Literal[True]
    inner_holdout_observed_gameweeks: int = Field(ge=1)
    minimum_inner_training_observed_gameweeks: int = Field(ge=1)
    holdout_walk_forward: Literal[True]
    cold_start_in_fitting: Literal[True]
    returning_promoted_count_reset: Literal[True]
    learning_rate: tuple[float, ...] = Field(min_length=1)
    retention: tuple[float, ...] = Field(min_length=1)
    season_retention: tuple[float, ...] = Field(min_length=1)
    fallback_learning_rate: float = Field(gt=0.0)
    fallback_retention: float = Field(gt=0.0, le=1.0)
    fallback_season_retention: float = Field(gt=0.0, le=1.0)
    promoted_prior_source: Literal["fold_local_earlier_cohorts"]
    fallback_attack_prior: float = Field(gt=0.0)
    fallback_defence_prior: float = Field(gt=0.0)
    promoted_prior_min_matches: int = Field(ge=1)
    promoted_prior_shrinkage_matches: float = Field(ge=0.0)
    xg_policy: Literal["use_when_measured_scaled_to_goals"]
    rate_floor: float = Field(gt=0.0)
    log_strength_cap: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _valid_search_space(self) -> Self:
        if self.minimum_inner_training_observed_gameweeks < self.inner_holdout_observed_gameweeks:
            raise ValueError("inner training history cannot be shorter than the holdout")
        for label, grid, lo, hi in (
            ("learning_rate", self.learning_rate, 0.0, None),
            ("retention", self.retention, 0.0, 1.0),
            ("season_retention", self.season_retention, 0.0, 1.0),
        ):
            if any(value <= lo for value in grid):
                raise ValueError(f"{label} values must be greater than {lo}")
            if hi is not None and any(value > hi for value in grid):
                raise ValueError(f"{label} values must not exceed {hi}")
            if tuple(sorted(set(grid))) != grid:
                raise ValueError(f"{label} values must be unique and increasing")
        if self.fallback_learning_rate not in self.learning_rate:
            raise ValueError("fallback learning rate must be in the declared grid")
        if self.fallback_retention not in self.retention:
            raise ValueError("fallback retention must be in the declared grid")
        if self.fallback_season_retention not in self.season_retention:
            raise ValueError("fallback season retention must be in the declared grid")
        return self


class Phase1BaselinePolicy(_Frozen):
    stage_a: frozenset[str]
    downstream_player_points: frozenset[str]


class Phase1MetricPolicy(_Frozen):
    primary: Literal["mean_log_score"]
    primary_direction: Literal["lower_is_better"]
    proper_distribution: frozenset[str]
    diagnostics: frozenset[str]
    calibration: frozenset[str]
    ranking: frozenset[str]
    downstream_player_points: frozenset[str]


# The version that predates the amendment log. Typed as a plain `str` rather than inlined,
# because the rule below is a general policy about versions and not a statement about whichever
# literal `contract_version` currently pins.
ORIGINAL_PHASE1_CONTRACT_VERSION: str = "1.0"


class Phase1Amendment(_Frozen):
    """One recorded change to a pre-registered contract.

    Amending a gate after seeing a candidate's results is the failure this whole file exists
    to prevent, so an amendment has to say when it happened and how many candidates had been
    evaluated by then. The number is not checkable, but requiring it to be written down makes
    a dishonest amendment a false statement rather than an omission.
    """

    version: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    candidates_evaluated_before_amendment: int = Field(ge=0)
    changed: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    tolerance_rationale: str | None = None
    deferred: str | None = None


class Phase1PromotionGate(_Frozen):
    compare_against: Literal["best_eligible_required_stage_a_baseline"]
    comparison_population: Literal["same_eligible_predictions"]
    relative_lift_formula: Literal["(baseline - candidate) / abs(baseline)"]
    minimum_primary_relative_lift: float = Field(ge=0.0)
    maximum_crps_relative_regression: float = Field(ge=0.0)
    # Randomised-PIT band coverage. The superseded `interval_80_maximum_absolute_error` gated
    # the raw central interval, which for a count distribution is set by the discreteness of
    # the pmf rather than by the model -- see amendment 1.1. `extra="forbid"` means a config
    # still carrying the old key fails to load rather than being silently ignored.
    pit_interval_80_maximum_absolute_error: float = Field(ge=0.0, le=1.0)
    minimum_fixture_coverage: float = Field(gt=0.0, le=1.0)
    minimum_fold_count: int = Field(ge=1)
    require_each_reported_season_to_pass: Literal[True]
    require_zero_leakage_failures: Literal[True]


class Phase1ReportingPolicy(_Frozen):
    dimensions: frozenset[str]
    counts: frozenset[str]


class Phase1EvaluationConfig(_Frozen):
    """Executable entry and promotion contract for the Stage A walk-forward."""

    contract_version: Literal["1.5"]
    phase: Literal[1]
    amendments: tuple[Phase1Amendment, ...] = ()
    target: Phase1TargetPolicy
    cutoff: Phase1CutoffPolicy
    training: Phase1TrainingPolicy
    stage_a_candidate: Phase1StageACandidatePolicy
    # Candidate V3 is a development-only structural probe. Optional and additive: absent
    # from every V1/V2 evaluation, it never substitutes for V2 and changes no gate. V3's single
    # historical development result is invalidated (see docs/phase1-candidate-v3-invalidation.md);
    # the block is retained frozen rather than repaired.
    stage_a_candidate_v3: Phase1StageACandidateV3Policy | None = None
    # Candidate V4 is the leakage-safe successor to the invalidated V3. Optional and additive in
    # the same way: it shares no field with V2/V3, substitutes for nothing, and is never loaded
    # by the default harness command. Pre-registered before any V4 evaluation.
    stage_a_candidate_v4: Phase1StageACandidateV4Policy | None = None
    baselines: Phase1BaselinePolicy
    metrics: Phase1MetricPolicy
    promotion: Phase1PromotionGate
    reporting: Phase1ReportingPolicy

    @model_validator(mode="after")
    def _required_comparisons_and_outputs(self) -> Self:
        required_stage_a = {
            "league_home_away_goals",
            "trailing_goals_attack_defence",
            "trailing_xg_attack_defence",
            "naive_fdr",
            "promoted_team_pooled_prior",
        }
        missing_stage_a = required_stage_a - self.baselines.stage_a
        if missing_stage_a:
            raise ValueError(
                f"Phase 1 missing required Stage A baselines: {sorted(missing_stage_a)}"
            )

        required_player = {
            "fpl_ep_next_recorded_rules",
            "trailing_5_recorded_points",
            "naive_fdr",
        }
        missing_player = required_player - self.baselines.downstream_player_points
        if missing_player:
            raise ValueError(
                f"Phase 1 missing downstream player-point baselines: {sorted(missing_player)}"
            )

        required_proper = {"mean_log_score", "mean_crps"}
        if missing := required_proper - self.metrics.proper_distribution:
            raise ValueError(f"Phase 1 missing proper distribution metrics: {sorted(missing)}")
        required_calibration = {
            "randomized_pit",
            "interval_80_coverage",
            "pit_interval_80_coverage",
        }
        if missing := required_calibration - self.metrics.calibration:
            raise ValueError(f"Phase 1 missing calibration outputs: {sorted(missing)}")
        required_dimensions = {"fold", "season", "promoted_status", "home_away"}
        if missing := required_dimensions - self.reporting.dimensions:
            raise ValueError(f"Phase 1 missing report dimensions: {sorted(missing)}")
        required_counts = {"predictions", "exclusions", "cold_starts", "uncertainty"}
        if missing := required_counts - self.reporting.counts:
            raise ValueError(f"Phase 1 missing report counts: {sorted(missing)}")

        # A version bump is how a changed gate becomes visible, so it may not happen without
        # the record that says what changed and why. Without this the contract could be
        # rewritten between two commits and read as though it had always said so.
        if self.contract_version != ORIGINAL_PHASE1_CONTRACT_VERSION and not any(
            amendment.version == self.contract_version for amendment in self.amendments
        ):
            raise ValueError(
                f"Phase 1 contract version {self.contract_version} has no amendment record; "
                "a pre-registered gate may not change without one"
            )
        return self


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def repo_root() -> Path:
    """Locate the repository root by walking up to the directory holding `config/`."""
    for candidate in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (candidate / "config" / "sources.yaml").is_file():
            return candidate
    raise FileNotFoundError("could not locate repository root (no config/sources.yaml found)")


def config_dir() -> Path:
    return repo_root() / "config"


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} did not parse to a mapping")
    return loaded


@functools.cache
def load_sources(path: Path | None = None) -> SourcesConfig:
    return SourcesConfig.model_validate(_read_yaml(path or config_dir() / "sources.yaml"))


@functools.cache
def load_scoring_rules(ruleset_id: RulesetId, path: Path | None = None) -> ScoringRules:
    """Load one ruleset. `ruleset_id` uses underscores, e.g. "2026_27"."""
    resolved = path or config_dir() / f"scoring_{ruleset_id}.yaml"
    if not resolved.is_file():
        raise FileNotFoundError(f"no scoring config for ruleset {ruleset_id!r} at {resolved}")
    rules = ScoringRules.model_validate(_read_yaml(resolved))
    if rules.ruleset_id != ruleset_id:
        raise ValueError(
            f"{resolved} declares ruleset_id {rules.ruleset_id!r}, expected {ruleset_id!r}"
        )
    return rules


def available_rulesets() -> list[RulesetId]:
    """Every ruleset with a config file, sorted. Drives the target table's columns."""
    prefix, suffix = "scoring_", ".yaml"
    return sorted(
        path.name[len(prefix) : -len(suffix)] for path in config_dir().glob(f"{prefix}*{suffix}")
    )


@functools.cache
def load_data_quality(path: Path | None = None) -> DataQualityConfig:
    return DataQualityConfig.model_validate(_read_yaml(path or config_dir() / "data_quality.yaml"))


@functools.cache
def load_phase1_evaluation(path: Path | None = None) -> Phase1EvaluationConfig:
    return Phase1EvaluationConfig.model_validate(
        _read_yaml(path or config_dir() / "phase1_evaluation.yaml")
    )
