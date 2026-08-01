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


class DefensiveActionsDumpProvenance(_Frozen):
    """Provenance for a locally-pulled external defensive-actions dump (B-path).

    FBref is unreachable from the build environment, so this records a CSV the operator
    pulled where it is reachable. It is treated as an unverified assumption until the
    2025-26 overlap gate passes -- never promoted to confirmed facts. FBref is not versioned,
    so there is no pinned commit; `pulled_on` is the provenance anchor instead.
    """

    source: str
    license: str
    pulled_with: str
    pulled_on: datetime | None = None


class DefensiveActionsDump(_Frozen):
    csv_path: str
    overlap_season: Season
    provenance: DefensiveActionsDumpProvenance


class SourcesConfig(_Frozen):
    archive: ArchiveSource
    live_api: LiveApiSource
    current_season: CurrentSeason
    paths: Paths
    # Optional until a B-path dump is committed. Absent => the backfill job needs --csv.
    defensive_actions_dump: DefensiveActionsDump | None = None


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

# The exact, ordered amendment history each contract version freezes: (version, candidates
# already evaluated before it). A pre-registered contract's value is that it cannot be rewritten
# between commits and read as if it had always said so, so at a given version the amendment
# sequence -- not just the current entry -- is pinned. Reordering, dropping, duplicating, or
# altering a count fails to load. Moving to a new version is an explicit code change here.
FROZEN_AMENDMENT_HISTORY: dict[str, tuple[tuple[str, int], ...]] = {
    "1.5": (
        ("1.1", 0),
        ("1.2", 0),
        ("1.3", 1),
        ("1.4", 2),
        ("1.5", 3),
    ),
}


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
    # Candidate V4 is the leakage-safe successor to the invalidated V3. Additive in the same way
    # as V3: it shares no field with V2/V3, substitutes for nothing, and is never loaded by the
    # default harness command. Pre-registered before any V4 evaluation. Required at contract
    # version 1.5: the loader only accepts 1.5, so the V4 block it freezes may not be silently
    # dropped -- a config that deletes it fails to load rather than scoring a different model.
    stage_a_candidate_v4: Phase1StageACandidateV4Policy
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

    @model_validator(mode="after")
    def _amendment_history_is_frozen(self) -> Self:
        """The whole ordered amendment history is pinned, not just the current version.

        A missing, reordered, duplicated, or count-altered amendment would let a pre-registered
        contract be rewritten between commits and read back as if it had always said so. Each
        entry is the (version, candidates_evaluated_before_amendment) pair exactly as frozen for
        this contract version; any difference fails to load. Bumping the contract version is an
        explicit code change that adds a new ``FROZEN_AMENDMENT_HISTORY`` entry.
        """
        expected = FROZEN_AMENDMENT_HISTORY.get(self.contract_version)
        if expected is None:
            return self
        actual = tuple(
            (amendment.version, amendment.candidates_evaluated_before_amendment)
            for amendment in self.amendments
        )
        if actual != expected:
            raise ValueError(
                f"Phase 1 amendment history for contract {self.contract_version} is not the "
                f"frozen record: expected {expected}, got {actual}. The ordered amendment "
                "sequence and candidate counts are pinned and may not be altered."
            )
        return self


# --------------------------------------------------------------------------------------
# Phase 2 evaluation contract (Stage B player minutes)
# --------------------------------------------------------------------------------------


class Phase2Amendment(_Frozen):
    """One recorded change to the Phase 2 contract. Mirrors the Phase 1 discipline: an
    amendment must say when it happened and how many candidates had been evaluated by then,
    so a gate cannot be rewritten between two commits and read as if it had always said so."""

    version: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    candidates_evaluated_before_amendment: int = Field(ge=0)
    changed: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    tolerance_rationale: str | None = None
    deferred: str | None = None


class Phase2TargetPolicy(_Frozen):
    entity: Literal["player"]
    # Player-fixture grain, not player-gameweek: double gameweeks are separate fixtures.
    grain: Literal["season_player_code_fixture"]
    outcome: Literal["minutes_distribution"]
    # Pinned to the exact ruleset whose appearance / clean-sheet thresholds define the 60-minute
    # bin boundary. A different ruleset requires a new contract version, not a silent edit.
    downstream_points_ruleset: Literal["2026_27"]
    # `code` is the stable cross-season player key (1:1 with permanent identity).
    # `element_id`/`element` are season-scoped and reassigned yearly; across this archive
    # element_id 308 is Almiron/Aké/Salah/Ward/Heath across five seasons, so a bare
    # element_id cross-season join merges five different players. Cross-season tracking uses
    # `code`; the only season-local alternative is a (season, element_id) key.
    identity_policy: Literal["code_is_cross_season_player_key"]


class Phase2PopulationPolicy(_Frozen):
    # The REGISTERED FPL PLAYER POPULATION: every player-fixture row with a non-NULL minutes
    # outcome, including registered nonparticipants at minutes=0. Zero-minute rows are never
    # filtered.
    include_zero_minutes: Literal[True]
    eligible_outcome: Literal["minutes_not_null"]
    registered_population: Literal["mart_fact_player_fixture_minutes_not_null"]


# The exact column set the target roster may carry into the minutes model. Identity/schedule
# metadata only: ``code`` is the stable cross-season player key, ``team_id`` is season-qualified,
# and ``minutes`` (the LABEL) is deliberately absent -- it lives outside the model-facing
# projection. Defined here as a plain module constant (NOT imported from ``fpl.features.pit``)
# because ``features.pit -> storage.db -> config`` would be a circular import. The authoritative
# disjointness check against the real ``OUTCOME_COLUMNS`` lives in the test file, where importing
# ``fpl.features.pit`` is safe.
PHASE2_TARGET_ROSTER_PROXY_COLUMNS: frozenset[str] = frozenset(
    {
        "season",
        "gw",
        "fixture",
        "kickoff_time",
        "code",
        "position",
        "team_id",
        "opponent_team_id",
        "was_home",
    }
)
# Outcome / season-scoped-alias columns the proxy must NEVER carry. ``minutes`` is the label;
# ``starts`` is an outcome; ``element_id``/``element`` are season-scoped and reassigned yearly.
PHASE2_TARGET_ROSTER_FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {"element_id", "element", "minutes", "starts"}
)


class Phase2TargetRosterPolicy(_Frozen):
    """Which players to predict, and from what -- the knowledge-time policy.

    The minutes model cannot discover which players to predict from
    ``PointInTimeView.schedule()`` (a team-level schedule projection), and the archive does not
    version player registration, position, or club at the real FPL deadline. This policy records
    honestly that the historical target roster is an UNVERSIONED archive proxy projected from the
    target rows -- analogous to the schedule-cutoff limitation -- and pins the exact safe proxy
    column set plus the live/prospective requirement. The proxy columns are validated to equal
    ``PHASE2_TARGET_ROSTER_PROXY_COLUMNS`` exactly (rejecting additions and deletions) and to be
    disjoint from ``PHASE2_TARGET_ROSTER_FORBIDDEN_COLUMNS``.
    """

    historical_roster_status: Literal["archive_proxy_unversioned_at_real_deadline"]
    historical_source: Literal[
        "archive_player_fixture_identity_schedule_proxy_projected_from_target_rows"
    ]
    proxy_columns: frozenset[str]
    minutes_role: Literal["label_outside_model_facing_projection"]
    live_prospective_registry: Literal[
        "versioned_player_registry_selected_known_at_le_as_of_before_model_sees_entity_team_position"
    ]
    cross_season_team_identity: Literal["season_qualified_team_id_resolved_to_stable_team_code"]
    point_in_time_disclaimer: Literal["not_fully_reconstructable_pit_at_real_deadline"]

    @model_validator(mode="after")
    def _proxy_columns_pinned(self) -> Self:
        if self.proxy_columns != PHASE2_TARGET_ROSTER_PROXY_COLUMNS:
            missing = PHASE2_TARGET_ROSTER_PROXY_COLUMNS - self.proxy_columns
            extra = self.proxy_columns - PHASE2_TARGET_ROSTER_PROXY_COLUMNS
            parts: list[str] = []
            if missing:
                parts.append(f"missing required proxy columns: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected proxy columns: {sorted(extra)}")
            raise ValueError(
                "Phase 2 target roster proxy columns must be exactly "
                f"{sorted(PHASE2_TARGET_ROSTER_PROXY_COLUMNS)}; " + "; ".join(parts)
            )
        overlap = PHASE2_TARGET_ROSTER_FORBIDDEN_COLUMNS & self.proxy_columns
        if overlap:
            raise ValueError(
                "Phase 2 target roster proxy columns must be disjoint from the forbidden "
                f"outcome/alias columns {sorted(PHASE2_TARGET_ROSTER_FORBIDDEN_COLUMNS)}; "
                f"overlap: {sorted(overlap)}"
            )
        if "code" not in self.proxy_columns:
            raise ValueError(
                "Phase 2 target roster proxy columns must include 'code' (the stable "
                "cross-season player key)"
            )
        return self


class Phase2CutoffPolicy(_Frozen):
    split_unit: Literal["observed_gameweek"]
    prediction_time: Literal["archive_first_kickoff_proxy_for_gameweek_deadline"]
    observed_results: Literal["kickoff_time < as_of"]
    snapshot_versions: Literal["known_at <= as_of"]


class Phase2TrainingPolicy(_Frozen):
    window: Literal["expanding"]
    minimum_observed_gameweeks: Literal[8]
    # No minimum player-history exclusion: every eligible row gets a fallback distribution.
    no_minimum_player_history_exclusion: Literal[True]
    cold_start_policy: Literal["every_eligible_row_receives_fallback_distribution"]
    fit_transforms_within_fold: Literal[True]
    preserve_nulls: Literal[True]
    seed: Literal[202627]


class Phase2StageBCandidateV1Policy(_Frozen):
    """Frozen pre-registration for the first Stage B minutes candidate.

    Candidate V1 shrinks the player's trailing-five empirical bin counts toward the
    fold-local current-position prior. Only the prior strength is selected, on a nested
    observed-gameweek walk-forward inside each outer fold. Every field that distinguishes
    the candidate is pinned so a result cannot be followed by a silent policy change.
    """

    name: Literal["shrunk_trailing_5_player_minutes_v1"]
    development_only: Literal[True]
    development_only_reason: Literal[
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_and_archive_evidence_shaped_the_design"
    ]
    grain: Literal["season_player_code_fixture"]
    identity: Literal["stable_code"]
    history_population: Literal[
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero_minutes"
    ]
    history_order: Literal["kickoff_time_then_season_then_fixture"]
    history_window: Literal[5]
    history_observed_results: Literal["kickoff_time < as_of"]
    position_prior: Literal["fold_local_raw_position_minutes_frequency_for_target_current_position"]
    position_prior_fallback: Literal["existing_unsmoothed_all_position_prior_rows"]
    player_bin_counts: Literal["c_k_is_history_count_in_bin_k_and_n_equals_sum_k_c_k"]
    estimator: Literal["p_k(alpha)=(c_k+alpha*q_k)/(n+alpha)"]
    additional_smoothing: Literal["none"]
    scoring_floor_role: Literal["existing_1e-12_floor_is_scoring_only_not_model_smoothing"]
    cold_start_fallback: Literal["when_n_equals_0_distribution_is_exactly_q"]
    prior_strength_grid: tuple[float, ...] = Field(min_length=1)
    selected_parameter: Literal["alpha_only_history_window_remains_5"]
    inner_holdout_observed_gameweeks: Literal[6]
    minimum_earlier_observed_gameweeks: Literal[8]
    inner_walk_forward: Literal[
        "most_recent_6_observed_gameweeks_true_per_gameweek_predict_whole_gameweek_from_pre_gameweek_history_then_score_then_absorb"
    ]
    inner_objective: Literal["pooled_mean_log_score"]
    tie_break: Literal["smallest_alpha"]
    insufficient_inner_history_fallback_alpha: float = Field(gt=0.0)
    fit_scope: Literal["all_transforms_priors_and_grid_selection_are_fold_local"]
    target_label_policy: Literal["target_labels_never_enter_model_inputs"]
    target_position_source: Literal["existing_unversioned_target_roster_proxy_current_position"]
    null_policy: Literal["preserve_nulls"]
    zero_minutes_policy: Literal["include_in_history_and_training"]
    assistant_manager_policy: Literal["excluded_upstream_element_type_5"]
    double_gameweek_policy: Literal[
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    ]
    double_gameweek_same_distribution: Literal[
        "same_code_current_position_may_share_distribution_across_target_gameweek_fixtures_intentional_reportable_not_collapsed"
    ]
    excluded_features: Literal["availability_status_team_opponent_and_home_away_are_not_features"]
    monte_carlo: Literal["out_of_scope_closed_form"]

    @model_validator(mode="after")
    def _exact_candidate_policy(self) -> Self:
        expected_grid = (1.0, 2.0, 5.0, 10.0, 20.0)
        if self.prior_strength_grid != expected_grid:
            raise ValueError(
                "Stage B Candidate V1 prior_strength_grid is pinned to "
                f"{expected_grid}; got {self.prior_strength_grid}"
            )
        if self.insufficient_inner_history_fallback_alpha != 5.0:
            raise ValueError(
                "Stage B Candidate V1 insufficient_inner_history_fallback_alpha is pinned "
                f"to 5.0; got {self.insufficient_inner_history_fallback_alpha!r}"
            )
        return self


class Phase2StageBCandidateV2Policy(_Frozen):
    """Frozen pre-registration for the recency-weighted Stage B minutes candidate.

    Candidate V2 is Candidate V1 with exactly ONE change: a geometric recency weight on the same
    trailing-5 window. For the i-th most-recent row (i = 0 newest) the weight is ``decay ** i``;
    weighted bin mass ``w_k = sum of decay**i over trailing rows in bin k``; ``W = sum_k w_k``;
    and ``p_k(decay, alpha) = (w_k + alpha*q_k) / (W + alpha)``. At ``decay = 1.0`` this is
    bit-identical to V1 (``w_k = c_k``, ``W = n``), so V2 is a strict generalisation. ``decay``
    and ``alpha`` are selected jointly by the same nested six-observed-gameweek walk-forward V1
    uses. Every distinguishing field is pinned so a result cannot be followed by a silent change.
    """

    name: Literal["recency_weighted_trailing_player_minutes_v2"]
    development_only: Literal[True]
    development_only_reason: Literal[
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_and_archive_evidence_shaped_the_design"
    ]
    grain: Literal["season_player_code_fixture"]
    identity: Literal["stable_code"]
    history_population: Literal[
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero_minutes"
    ]
    history_order: Literal["kickoff_time_then_season_then_fixture"]
    history_window: Literal[5]
    history_observed_results: Literal["kickoff_time < as_of"]
    position_prior: Literal["fold_local_raw_position_minutes_frequency_for_target_current_position"]
    position_prior_fallback: Literal["existing_unsmoothed_all_position_prior_rows"]
    recency_weight: Literal["geometric_decay_power_i_on_trailing_window_i_zero_is_newest"]
    player_bin_mass: Literal["w_k_is_sum_of_decay_to_the_i_over_trailing_rows_in_bin_k"]
    total_weight: Literal["W_equals_sum_k_w_k"]
    estimator: Literal["p_k(decay,alpha)=(w_k+alpha*q_k)/(W+alpha)"]
    reduces_to_v1_when_decay_is_one: Literal[True]
    additional_smoothing: Literal["none"]
    scoring_floor_role: Literal["existing_1e-12_floor_is_scoring_only_not_model_smoothing"]
    cold_start_fallback: Literal["when_W_equals_0_distribution_is_exactly_q"]
    decay_grid: tuple[float, ...] = Field(min_length=1)
    prior_strength_grid: tuple[float, ...] = Field(min_length=1)
    selected_parameter: Literal["decay_and_alpha_history_window_remains_5"]
    inner_holdout_observed_gameweeks: Literal[6]
    minimum_earlier_observed_gameweeks: Literal[8]
    inner_walk_forward: Literal[
        "most_recent_6_observed_gameweeks_true_per_gameweek_predict_whole_gameweek_from_pre_gameweek_history_then_score_then_absorb"
    ]
    inner_objective: Literal["pooled_mean_log_score"]
    tie_break: Literal["largest_decay_then_smallest_alpha"]
    insufficient_inner_history_fallback_decay: float = Field(gt=0.0, le=1.0)
    insufficient_inner_history_fallback_alpha: float = Field(gt=0.0)
    fit_scope: Literal["all_transforms_priors_and_grid_selection_are_fold_local"]
    target_label_policy: Literal["target_labels_never_enter_model_inputs"]
    target_position_source: Literal["existing_unversioned_target_roster_proxy_current_position"]
    null_policy: Literal["preserve_nulls"]
    zero_minutes_policy: Literal["include_in_history_and_training"]
    assistant_manager_policy: Literal["excluded_upstream_element_type_5"]
    double_gameweek_policy: Literal[
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    ]
    double_gameweek_same_distribution: Literal[
        "same_code_current_position_may_share_distribution_across_target_gameweek_fixtures_intentional_reportable_not_collapsed"
    ]
    excluded_features: Literal["availability_status_team_opponent_and_home_away_are_not_features"]
    monte_carlo: Literal["out_of_scope_closed_form"]

    @model_validator(mode="after")
    def _exact_candidate_policy(self) -> Self:
        expected_decay = (1.0, 0.9, 0.7, 0.5, 0.3)
        if self.decay_grid != expected_decay:
            raise ValueError(
                "Stage B Candidate V2 decay_grid is pinned to "
                f"{expected_decay}; got {self.decay_grid}"
            )
        expected_alpha = (1.0, 2.0, 5.0, 10.0, 20.0)
        if self.prior_strength_grid != expected_alpha:
            raise ValueError(
                "Stage B Candidate V2 prior_strength_grid is pinned to "
                f"{expected_alpha}; got {self.prior_strength_grid}"
            )
        if self.insufficient_inner_history_fallback_decay != 1.0:
            raise ValueError(
                "Stage B Candidate V2 insufficient_inner_history_fallback_decay is pinned "
                f"to 1.0 (== V1); got {self.insufficient_inner_history_fallback_decay!r}"
            )
        if self.insufficient_inner_history_fallback_alpha != 5.0:
            raise ValueError(
                "Stage B Candidate V2 insufficient_inner_history_fallback_alpha is pinned "
                f"to 5.0; got {self.insufficient_inner_history_fallback_alpha!r}"
            )
        return self


class Phase2StageBCandidateV3Policy(_Frozen):
    """Frozen pre-registration for the concentration-adaptive-shrinkage Stage B minutes candidate.

    Candidate V3 is Candidate V2 with exactly ONE change: the shrinkage strength adapts to how
    concentrated the player's own recency-weighted trailing history is. With the same geometric
    weights ``w_k`` and ``W = sum_k w_k``, the weighted bin shares ``s_k = w_k / W`` give a
    normalised Herfindahl concentration ``C = (sum_k s_k**2 - 1/4) / (1 - 1/4)`` in ``[0, 1]``
    (``C = 1`` when all weighted mass is in one bin, ``C = 0`` when the four shares are equal).
    The effective prior strength is ``alpha_eff = alpha * (1 - lambda*C)`` and

        p_k(decay, alpha, lambda) = (w_k + alpha_eff*q_k) / (W + alpha_eff).

    At ``lambda = 0`` this is bit-identical to V2 (``alpha_eff = alpha``), so V3 is a strict
    generalisation. The motivation is diagnosed from V2's evidence: V2 failed the v1.2
    starter-ranking gate almost entirely on goalkeepers, whose near-deterministic (concentrated)
    histories are blurred by a uniform shrinkage; shrinking less where the history is already
    concentrated sharpens both the log score and the ranking on exactly those rows. ``decay``,
    ``alpha``, and ``lambda`` are selected jointly by the SAME six-observed-gameweek nested
    walk-forward V1/V2 use (pooled inner mean log score); the inner objective is deliberately NOT
    switched to a ranking metric, so V3 stays comparable and un-gamed. Every distinguishing field
    is pinned so a result cannot be followed by a silent policy change.
    """

    name: Literal["concentration_adaptive_shrinkage_player_minutes_v3"]
    development_only: Literal[True]
    development_only_reason: Literal[
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_and_archive_evidence_shaped_the_design"
    ]
    grain: Literal["season_player_code_fixture"]
    identity: Literal["stable_code"]
    history_population: Literal[
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero_minutes"
    ]
    history_order: Literal["kickoff_time_then_season_then_fixture"]
    history_window: Literal[5]
    history_observed_results: Literal["kickoff_time < as_of"]
    position_prior: Literal["fold_local_raw_position_minutes_frequency_for_target_current_position"]
    position_prior_fallback: Literal["existing_unsmoothed_all_position_prior_rows"]
    recency_weight: Literal["geometric_decay_power_i_on_trailing_window_i_zero_is_newest"]
    player_bin_mass: Literal["w_k_is_sum_of_decay_to_the_i_over_trailing_rows_in_bin_k"]
    total_weight: Literal["W_equals_sum_k_w_k"]
    weighted_share: Literal["s_k_equals_w_k_over_W"]
    concentration: Literal["C_equals_(sum_k_s_k_squared_minus_one_quarter)_over_three_quarters"]
    effective_prior_strength: Literal["alpha_eff_equals_alpha_times_(1_minus_lambda_times_C)"]
    effective_prior_strength_floor: Literal["alpha_eff_clamped_at_zero"]
    estimator: Literal["p_k(decay,alpha,lambda)=(w_k+alpha_eff*q_k)/(W+alpha_eff)"]
    reduces_to_v2_when_lambda_is_zero: Literal[True]
    additional_smoothing: Literal["none"]
    scoring_floor_role: Literal["existing_1e-12_floor_is_scoring_only_not_model_smoothing"]
    cold_start_fallback: Literal["when_W_equals_0_distribution_is_exactly_q"]
    decay_grid: tuple[float, ...] = Field(min_length=1)
    prior_strength_grid: tuple[float, ...] = Field(min_length=1)
    adaptation_grid: tuple[float, ...] = Field(min_length=1)
    selected_parameter: Literal["decay_and_alpha_and_lambda_history_window_remains_5"]
    inner_holdout_observed_gameweeks: Literal[6]
    minimum_earlier_observed_gameweeks: Literal[8]
    inner_walk_forward: Literal[
        "most_recent_6_observed_gameweeks_true_per_gameweek_predict_whole_gameweek_from_pre_gameweek_history_then_score_then_absorb"
    ]
    inner_objective: Literal["pooled_mean_log_score"]
    tie_break: Literal["smallest_lambda_then_largest_decay_then_smallest_alpha"]
    insufficient_inner_history_fallback_decay: float = Field(gt=0.0, le=1.0)
    insufficient_inner_history_fallback_alpha: float = Field(gt=0.0)
    insufficient_inner_history_fallback_lambda: float = Field(ge=0.0, le=1.0)
    fit_scope: Literal["all_transforms_priors_and_grid_selection_are_fold_local"]
    target_label_policy: Literal["target_labels_never_enter_model_inputs"]
    target_position_source: Literal["existing_unversioned_target_roster_proxy_current_position"]
    null_policy: Literal["preserve_nulls"]
    zero_minutes_policy: Literal["include_in_history_and_training"]
    assistant_manager_policy: Literal["excluded_upstream_element_type_5"]
    double_gameweek_policy: Literal[
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    ]
    double_gameweek_same_distribution: Literal[
        "same_code_current_position_may_share_distribution_across_target_gameweek_fixtures_intentional_reportable_not_collapsed"
    ]
    excluded_features: Literal["availability_status_team_opponent_and_home_away_are_not_features"]
    monte_carlo: Literal["out_of_scope_closed_form"]

    @model_validator(mode="after")
    def _exact_candidate_policy(self) -> Self:
        expected_decay = (1.0, 0.9, 0.7, 0.5, 0.3)
        if self.decay_grid != expected_decay:
            raise ValueError(
                "Stage B Candidate V3 decay_grid is pinned to "
                f"{expected_decay}; got {self.decay_grid}"
            )
        expected_alpha = (1.0, 2.0, 5.0, 10.0, 20.0)
        if self.prior_strength_grid != expected_alpha:
            raise ValueError(
                "Stage B Candidate V3 prior_strength_grid is pinned to "
                f"{expected_alpha}; got {self.prior_strength_grid}"
            )
        expected_lambda = (0.0, 0.25, 0.5, 0.75, 1.0)
        if self.adaptation_grid != expected_lambda:
            raise ValueError(
                "Stage B Candidate V3 adaptation_grid is pinned to "
                f"{expected_lambda}; got {self.adaptation_grid}"
            )
        if self.insufficient_inner_history_fallback_decay != 1.0:
            raise ValueError(
                "Stage B Candidate V3 insufficient_inner_history_fallback_decay is pinned "
                f"to 1.0 (== V1/V2); got {self.insufficient_inner_history_fallback_decay!r}"
            )
        if self.insufficient_inner_history_fallback_alpha != 5.0:
            raise ValueError(
                "Stage B Candidate V3 insufficient_inner_history_fallback_alpha is pinned "
                f"to 5.0; got {self.insufficient_inner_history_fallback_alpha!r}"
            )
        if self.insufficient_inner_history_fallback_lambda != 0.0:
            raise ValueError(
                "Stage B Candidate V3 insufficient_inner_history_fallback_lambda is pinned "
                f"to 0.0 (== V2, no adaptation); got "
                f"{self.insufficient_inner_history_fallback_lambda!r}"
            )
        return self


class Phase2MinuteBin(_Frozen):
    """One ordered minute bin. Keys are frozen; boundaries are explicit config data."""

    key: Literal["0", "1_59", "60_89", "90"]
    minutes_min: int = Field(ge=0)
    # None means unbounded above (the "90" bin folds 90-or-above into full match).
    minutes_max: int | None


def _expected_bin_range(key: str) -> tuple[int, int | None]:
    """Derive the expected ``(minutes_min, minutes_max)`` from the frozen bin KEY text.

    The numeric range is a property of the key string itself, never hardcoded separately, so
    the key is the single source of the range and contiguity is structural:

      - ``"0"``    => ``(0, 0)``        -- bare point bin at zero
      - ``"1_59"`` => ``(1, 59)``       -- split on ``"_"`` yields the closed range
      - ``"60_89"``=> ``(60, 89)``
      - ``"90"``   => ``(90, None)``    -- bare point bin, open-ended above (90-or-above folds)
    """
    if "_" in key:
        low_text, high_text = key.split("_", 1)
        return int(low_text), int(high_text)
    point = int(key)
    if point == 0:
        return 0, 0
    return point, None  # bare "90" is open-ended above


class Phase2OutputPolicy(_Frozen):
    bins: tuple[Phase2MinuteBin, ...]

    @model_validator(mode="after")
    def _ordered_contiguous_four_bins(self) -> Self:
        if len(self.bins) != 4:
            raise ValueError("Stage B requires exactly four minute bins")
        keys = tuple(bin_.key for bin_ in self.bins)
        expected_keys: tuple[str, ...] = ("0", "1_59", "60_89", "90")
        if keys != expected_keys:
            raise ValueError(
                f"Stage B bin keys must be exactly {expected_keys} in order; got {keys}"
            )
        # Bin numeric ranges are DERIVED FROM THE FROZEN KEY TEXT, never hardcoded separately.
        # Validating each bin's min/max against its key-derived expectation also enforces
        # contiguity and the open-ended "90" tail structurally.
        for bin_ in self.bins:
            expected_min, expected_max = _expected_bin_range(bin_.key)
            if bin_.minutes_min != expected_min:
                raise ValueError(
                    f'Stage B bin "{bin_.key}" minutes_min must equal the key-derived value '
                    f"{expected_min}; got {bin_.minutes_min}"
                )
            if bin_.minutes_max != expected_max:
                raise ValueError(
                    f'Stage B bin "{bin_.key}" minutes_max must equal the key-derived value '
                    f"{expected_max}; got {bin_.minutes_max}"
                )
        return self

    def long_bin_lower_boundary(self) -> int:
        """The 60-minute lower boundary of the "60_89" bin, read from this contract.

        This is the value the loader cross-checks against the downstream ruleset's
        appearance.long_play_minutes and clean_sheets.minimum_minutes. It is never hardcoded.
        """
        return self.bins[2].minutes_min


# The exact, name-keyed pin table for the four Stage B baselines. Each entry fixes the
# identity, population, order, window, and fallback its name requires; the per-baseline
# ``model_validator`` rejects any field that drifts from its pin.
_PHASE2_BASELINE_PINS: dict[str, dict[str, str | int | None]] = {
    "position_minutes_frequency": {
        "identity": "target_position",
        "population": "all_prior_eligible_rows_at_target_position",
        "order": "none_applicable_all_rows",
        "window": None,
        "fallback": "unsmoothed_all_position_prior_rows",
        "estimator": "raw_empirical_bin_frequency_count_divided_by_n",
    },
    "last_observed_player_minutes": {
        "identity": "stable_code",
        "population": "most_recent_prior_player_fixture_row",
        "order": "kickoff_time_then_season_then_fixture",
        "window": None,
        "fallback": "position_minutes_frequency",
        "estimator": "raw_empirical_bin_frequency_count_divided_by_n",
    },
    "trailing_5_player_minutes": {
        "identity": "stable_code",
        "population": "up_to_5_most_recent_prior_player_fixture_rows_including_zero",
        "order": "kickoff_time_then_season_then_fixture",
        "window": 5,
        "fallback": "position_minutes_frequency",
        "estimator": "raw_empirical_bin_frequency_count_divided_by_n",
    },
    "trailing_5_team_position_minutes": {
        "identity": "season_qualified_team_id_resolved_to_stable_team_code",
        "population": (
            "all_prior_eligible_rows_at_target_position_in_clubs_5_most_recent_completed_fixtures"
        ),
        "order": "kickoff_time_then_season_then_fixture",
        "window": 5,
        "fallback": "position_minutes_frequency",
        "estimator": "raw_empirical_bin_frequency_count_divided_by_n",
    },
}


class Phase2BaselineDefinition(_Frozen):
    """One frozen Stage B baseline definition.

    The discriminating ``name`` selects the exact deterministic algorithm; a ``model_validator``
    pins every other field to the value that name requires, so any drift in window, smoothing,
    fallback, order, identity, or population fails to load. Probability estimates are raw
    ``count / n`` with NO additive smoothing (``additive_smoothing`` is pinned to ``"none"``);
    a one-hot zero probability REMAINS zero and is handled only by the registered
    log-probability floor (see ``Phase2ScoringCalibrationPolicy``).
    """

    name: Literal[
        "position_minutes_frequency",
        "last_observed_player_minutes",
        "trailing_5_player_minutes",
        "trailing_5_team_position_minutes",
    ]
    identity: Literal[
        "target_position",
        "stable_code",
        "season_qualified_team_id_resolved_to_stable_team_code",
    ]
    population: Literal[
        "all_prior_eligible_rows_at_target_position",
        "most_recent_prior_player_fixture_row",
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero",
        "all_prior_eligible_rows_at_target_position_in_clubs_5_most_recent_completed_fixtures",
    ]
    order: Literal[
        "none_applicable_all_rows",
        "kickoff_time_then_season_then_fixture",
    ]
    window: int | None
    additive_smoothing: Literal["none"]
    fallback: Literal[
        "unsmoothed_all_position_prior_rows",
        "position_minutes_frequency",
    ]
    # The probability estimator: raw empirical bin frequency = count of
    # occurrences in a bin divided by total n (a one-hot / empirical frequency
    # distribution over the four ordered minute bins; for last-observed this is
    # effectively a one-row empirical frequency / one-hot). A Literal so any
    # other value is rejected, and pinned per-name via ``_PHASE2_BASELINE_PINS``
    # so changing it on any baseline fails to load.
    estimator: Literal["raw_empirical_bin_frequency_count_divided_by_n"]

    @model_validator(mode="after")
    def _pinned_to_name(self) -> Self:
        pinned = _PHASE2_BASELINE_PINS[self.name]
        for field_name, expected_value in pinned.items():
            actual = getattr(self, field_name)
            if actual != expected_value:
                raise ValueError(
                    f'Stage B baseline "{self.name}" has {field_name}={actual!r} but the '
                    f"frozen definition pins it to {expected_value!r}"
                )
        return self


class Phase2BaselinePolicy(_Frozen):
    stage_b: frozenset[str]
    definitions: tuple[Phase2BaselineDefinition, ...]
    # ep_next is points, not minutes; pinned as excluded so it cannot be silently added.
    excluded: frozenset[str]

    @model_validator(mode="after")
    def _definitions_match_stage_b(self) -> Self:
        names = [definition.name for definition in self.definitions]
        if len(names) != len(set(names)):
            raise ValueError(
                f"Stage B baseline definitions have duplicate names: {names}; each baseline "
                "must be defined exactly once"
            )
        if set(names) != self.stage_b:
            raise ValueError(
                f"Stage B baseline definition names {sorted(set(names))} must match the "
                f"stage_b set exactly {sorted(self.stage_b)}"
            )
        return self


class Phase2MetricPolicy(_Frozen):
    primary: Literal["mean_log_score"]
    primary_direction: Literal["lower_is_better"]
    proper_distribution: frozenset[str]
    binary_guardrails: frozenset[str]
    calibration: frozenset[str]
    reliability_buckets_carry_n: Literal[True]
    ranking: frozenset[str]


class Phase2PromotionGate(_Frozen):
    compare_against: Literal["best_eligible_required_stage_b_baseline"]
    comparison_population: Literal["same_eligible_predictions"]
    relative_lift_formula: Literal["(baseline - candidate) / abs(baseline)"]
    # Amendment 1.2: each bounded guardrail is measured against the best required baseline value of
    # its OWN metric (RPS/Brier lower-is-better, Spearman higher-is-better), not the single
    # best-by-log-score baseline. Pinned in the contract so the runner cannot quietly revert.
    guardrail_comparison: Literal["best_baseline_per_metric"]
    minimum_primary_relative_lift: float
    # AGGREGATE guardrails only: RPS and Brier non-regression are evaluated on the full
    # prediction set, never per season. ONLY mean log score has a per-season non-regression
    # rule (``require_no_season_mean_log_score_regression``).
    maximum_ranked_probability_score_relative_regression: float
    maximum_brier_relative_regression_any_minutes: float
    maximum_brier_relative_regression_60_plus: float
    # Amendment 1.2: the starter-ranking guardrail. Higher Spearman-p60 is better; a candidate must
    # not regress vs the best baseline Spearman. Group-constant baselines (undefined Spearman) are
    # excluded from the baseline max, and a candidate whose own Spearman is undefined FAILS.
    maximum_spearman_p60_relative_regression: float
    pit_interval_80_maximum_absolute_error: float
    minimum_fold_count: Literal[181]
    require_no_season_mean_log_score_regression: Literal[True]
    require_zero_leakage_failures: Literal[True]
    # Pinned to exactly 1.0: every eligible row must receive a prediction. May not be relaxed.
    minimum_prediction_coverage: float

    @field_validator("minimum_primary_relative_lift")
    @classmethod
    def _lift_pinned(cls, value: float) -> float:
        if value != 0.01:
            raise ValueError(f"minimum_primary_relative_lift is pinned to 0.01; got {value!r}")
        return value

    @field_validator("maximum_ranked_probability_score_relative_regression")
    @classmethod
    def _rps_regression_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError(
                "maximum_ranked_probability_score_relative_regression is pinned to 0.0 "
                f"(aggregate guardrail only; got {value!r})"
            )
        return value

    @field_validator("maximum_brier_relative_regression_any_minutes")
    @classmethod
    def _brier_any_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError(
                "maximum_brier_relative_regression_any_minutes is pinned to 0.0 "
                f"(aggregate guardrail only; got {value!r})"
            )
        return value

    @field_validator("maximum_brier_relative_regression_60_plus")
    @classmethod
    def _brier_60_plus_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError(
                "maximum_brier_relative_regression_60_plus is pinned to 0.0 "
                f"(aggregate guardrail only; got {value!r})"
            )
        return value

    @field_validator("maximum_spearman_p60_relative_regression")
    @classmethod
    def _spearman_p60_regression_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError(
                "maximum_spearman_p60_relative_regression is pinned to 0.0 "
                f"(starter-ranking no-regression gate, amendment 1.2; got {value!r})"
            )
        return value

    @field_validator("pit_interval_80_maximum_absolute_error")
    @classmethod
    def _pit_error_pinned(cls, value: float) -> float:
        if value != 0.05:
            raise ValueError(
                f"pit_interval_80_maximum_absolute_error is pinned to 0.05; got {value!r}"
            )
        return value

    @field_validator("minimum_prediction_coverage")
    @classmethod
    def _coverage_is_total(cls, value: float) -> float:
        if value != 1.0:
            raise ValueError(
                "minimum_prediction_coverage is pinned to 1.0: every eligible row must "
                "receive a prediction, and this gate may not be relaxed"
            )
        return value


class Phase2ReportingPolicy(_Frozen):
    dimensions: frozenset[str]
    counts: frozenset[str]
    starts_reporting: Literal["measured_only"]


class Phase2HistoricalFeaturePolicy(_Frozen):
    availability_status: Literal["excluded_unavailable_in_archive"]
    point_in_time_only: Literal["reconstructable_fields_only"]
    live_availability_prospective_candidate: Literal["separately_named_prospective_only"]
    # The historical number is a development number on the local archive, NOT an upper bound.
    historical_score_is: Literal["development_number_not_upper_bound"]


class Phase2ScoringCalibrationPolicy(_Frozen):
    """Frozen scoring / calibration definitions for Stage B.

    Values and semantics are pinned; a config that silently weakens a log-probability floor, a
    metric definition, the randomised-PIT band, the PIT seed, or the reliability grid fails to
    load. This block freezes DEFINITIONS only -- the metric FUNCTIONS themselves are implemented
    in a separate slice (``validate`` / ``models``), not here.
    """

    log_probability_floor: float
    ranked_probability_score: Literal[
        "sum_of_squared_ordered_category_cdf_errors_not_physical_minute_distance"
    ]
    brier: Literal["squared_binary_probability_error"]
    randomized_pit_band: tuple[float, float]
    randomized_pit_seed: Literal[202627]
    reliability_edges: tuple[float, ...]
    reliability_buckets: Literal["left_closed_right_open_except_final_bucket_right_closed"]
    reliability_bucket_n: Literal[True]

    @field_validator("log_probability_floor")
    @classmethod
    def _log_probability_floor_pinned(cls, value: float) -> float:
        if value != 1e-12:
            raise ValueError(f"log_probability_floor is pinned to 1e-12; got {value!r}")
        return value

    @field_validator("randomized_pit_band")
    @classmethod
    def _pit_band_pinned(cls, value: tuple[float, float]) -> tuple[float, float]:
        if value != (0.1, 0.9):
            raise ValueError(f"randomized_pit_band is pinned to (0.1, 0.9); got {value!r}")
        return value

    @field_validator("reliability_edges")
    @classmethod
    def _reliability_edges_pinned(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        expected = tuple(round(i / 10, 1) for i in range(11))
        if value != expected:
            raise ValueError(
                f"reliability_edges is pinned to 0.0..1.0 in 0.1 steps ({expected}); got {value!r}"
            )
        return value


class Phase2MonteCarloPolicy(_Frozen):
    scope: Literal["out_of_scope_closed_form_marginal"]


# The original Phase 2 contract version. A non-original version requires an amendment record;
# the original does not. Mirrors the Phase 1 original-version discipline.
ORIGINAL_PHASE2_CONTRACT_VERSION: str = "1.0"

# The exact ordered Phase 2 amendment record at each supported contract version. A
# baseline-only run is not a candidate evaluation. Reordering, dropping, duplicating, or
# changing the count must fail closed.
FROZEN_PHASE2_AMENDMENT_HISTORY: dict[str, tuple[tuple[str, int], ...]] = {
    "1.1": (("1.1", 0),),
    "1.2": (("1.1", 0), ("1.2", 1)),
    "1.3": (("1.1", 0), ("1.2", 1), ("1.3", 1)),
    "1.4": (("1.1", 0), ("1.2", 1), ("1.3", 1), ("1.4", 2)),
}


def _require_exact_set(actual: frozenset[str], required: set[str], *, label: str) -> None:
    """Exact-set check: reject additions as well as deletions.

    Keeps the ``missing required <label>`` wording so existing tests stay valid; unexpected
    extras get a parallel ``unexpected <label>`` message. Used for every frozen Stage B set so
    a baseline, metric, dimension, or count cannot be silently added or dropped.
    """
    if actual == required:
        return
    missing = required - actual
    extra = actual - required
    parts: list[str] = []
    if missing:
        parts.append(f"missing required {label}: {sorted(missing)}")
    if extra:
        parts.append(f"unexpected {label}: {sorted(extra)}")
    raise ValueError(f"Phase 2 {label} must be exactly {sorted(required)}; " + "; ".join(parts))


class Phase2EvaluationConfig(_Frozen):
    """Executable entry and promotion contract for the Stage B (player minutes) walk-forward.

    Stage B predicts a four-bin minutes distribution over the registered FPL player
    population. No model is fit by this contract. Version 1.0 froze the population, grain,
    identity policy, bin shape, baselines, metrics, and promotion gate before any candidate
    existed; additive amendment 1.1 freezes Candidate V1's design without changing those
    policies. The 60-minute bin boundary is cross-checked against the configured downstream
    ruleset at load time via :meth:`verify_minutes_boundary`.
    """

    contract_version: Literal["1.4"]
    phase: Literal[2]
    amendments: tuple[Phase2Amendment, ...] = ()
    target: Phase2TargetPolicy
    target_roster: Phase2TargetRosterPolicy
    population: Phase2PopulationPolicy
    cutoff: Phase2CutoffPolicy
    training: Phase2TrainingPolicy
    stage_b_candidate_v1: Phase2StageBCandidateV1Policy
    # Candidate V2 (recency-weighted trailing minutes) is required at contract version 1.3. It is
    # additive: it changes no population/roster/bin/baseline/metric/gate and is judged by the 1.2
    # gate unchanged. Required here so a 1.4 config that silently drops it fails to load.
    stage_b_candidate_v2: Phase2StageBCandidateV2Policy
    # Candidate V3 (concentration-adaptive shrinkage) is required at contract version 1.4. It is
    # additive: it changes no population/roster/bin/baseline/metric/gate and is judged by the 1.2
    # gate unchanged. Required here so a 1.4 config that silently drops it fails to load.
    stage_b_candidate_v3: Phase2StageBCandidateV3Policy
    output: Phase2OutputPolicy
    baselines: Phase2BaselinePolicy
    metrics: Phase2MetricPolicy
    promotion: Phase2PromotionGate
    reporting: Phase2ReportingPolicy
    historical_features: Phase2HistoricalFeaturePolicy
    scoring_calibration: Phase2ScoringCalibrationPolicy
    monte_carlo: Phase2MonteCarloPolicy

    @model_validator(mode="after")
    def _required_baselines_metrics_and_outputs(self) -> Self:
        # Every frozen Stage B set is EXACT: a baseline, metric, dimension, or count may be
        # neither silently dropped nor silently added.
        _require_exact_set(
            self.baselines.stage_b,
            {
                "position_minutes_frequency",
                "last_observed_player_minutes",
                "trailing_5_player_minutes",
                "trailing_5_team_position_minutes",
            },
            label="Stage B baselines",
        )
        _require_exact_set(
            self.baselines.excluded,
            {"fpl_ep_next_recorded_rules"},
            label="excluded baselines",
        )
        _require_exact_set(
            self.metrics.proper_distribution,
            {"mean_log_score", "mean_ranked_probability_score"},
            label="proper distribution metrics",
        )
        _require_exact_set(
            self.metrics.binary_guardrails,
            {"mean_brier_any_minutes", "mean_brier_60_plus"},
            label="binary guardrail metrics",
        )
        _require_exact_set(
            self.metrics.calibration,
            {
                "randomized_pit",
                "pit_interval_80_coverage",
                "reliability_any_minutes",
                "reliability_60_plus",
            },
            label="calibration outputs",
        )
        _require_exact_set(
            self.metrics.ranking,
            {"spearman_p60_within_position_gameweek"},
            label="ranking outputs",
        )
        _require_exact_set(
            self.reporting.dimensions,
            {
                "fold",
                "season",
                "position",
                "home_away",
                "transfer_status",
                "player_history_cohort",
            },
            label="report dimensions",
        )
        _require_exact_set(
            self.reporting.counts,
            {"predictions", "exclusions", "cold_starts", "uncertainty"},
            label="report counts",
        )
        return self

    @model_validator(mode="after")
    def _version_needs_amendment_record_unless_original(self) -> Self:
        """A non-original version must carry its amendment record; the original (1.0) need not."""
        if self.contract_version != ORIGINAL_PHASE2_CONTRACT_VERSION and not any(
            amendment.version == self.contract_version for amendment in self.amendments
        ):
            raise ValueError(
                f"Phase 2 contract version {self.contract_version} has no amendment record; "
                "a pre-registered gate may not change without one"
            )
        return self

    @model_validator(mode="after")
    def _amendment_history_is_frozen(self) -> Self:
        """Reject a missing, reordered, duplicated, or count-altered amendment record."""
        expected = FROZEN_PHASE2_AMENDMENT_HISTORY.get(self.contract_version)
        if expected is None:
            return self
        actual = tuple(
            (amendment.version, amendment.candidates_evaluated_before_amendment)
            for amendment in self.amendments
        )
        if actual != expected:
            raise ValueError(
                f"Phase 2 amendment history for contract {self.contract_version} is not the "
                f"frozen record: expected {expected}, got {actual}. The ordered amendment "
                "sequence and candidate counts are pinned and may not be altered."
            )
        return self

    def verify_minutes_boundary(self, scoring: ScoringRules) -> Self:
        """Fail closed unless the long-bin lower boundary matches both scoring thresholds.

        The 60-minute boundary between the "1_59" and "60_89" bins is the appearance /
        clean-sheet threshold in the downstream ruleset. It is read from this contract's bin
        definition (never hardcoded in Python) and cross-checked against BOTH
        ``appearance.long_play_minutes`` and ``clean_sheets.minimum_minutes``. If the two
        thresholds disagree with each other, if either disagrees with the contract boundary,
        or if the boundary exceeds 90 minutes, this raises and a new contract / output shape is
        required.
        """
        boundary = self.output.long_bin_lower_boundary()
        long_play = scoring.appearance.long_play_minutes
        clean_sheet = scoring.clean_sheets.minimum_minutes
        if long_play != clean_sheet:
            raise ValueError(
                f"downstream ruleset {scoring.ruleset_id!r} is internally inconsistent: "
                f"appearance.long_play_minutes ({long_play}) != "
                f"clean_sheets.minimum_minutes ({clean_sheet}); the Stage B bin boundary "
                "must match a single threshold"
            )
        if boundary != long_play:
            raise ValueError(
                f"Stage B long-bin lower boundary is {boundary} but downstream ruleset "
                f"{scoring.ruleset_id!r} appearance.long_play_minutes and "
                f"clean_sheets.minimum_minutes are both {long_play}; the contract output "
                "shape must match the scoring threshold, or vice versa"
            )
        if boundary > 90:
            raise ValueError(
                f"Stage B long-bin lower boundary {boundary} exceeds 90 minutes, which is "
                "impossible for a match; the contract output shape is invalid"
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


@functools.cache
def load_phase2_evaluation(
    path: Path | None = None,
    *,
    scoring_path: Path | None = None,
) -> Phase2EvaluationConfig:
    """Load the Phase 2 Stage B contract and cross-check the 60-minute bin boundary.

    ``scoring_path`` is the seam for offline tests: it is forwarded to
    :func:`load_scoring_rules` for the contract's ``downstream_points_ruleset``, so a test can
    inject a temporary scoring YAML whose threshold disagrees with the contract and assert the
    loader fails closed. In production it is ``None`` and the configured ruleset is loaded.
    """
    contract = Phase2EvaluationConfig.model_validate(
        _read_yaml(path or config_dir() / "phase2_evaluation.yaml")
    )
    scoring = load_scoring_rules(contract.target.downstream_points_ruleset, path=scoring_path)
    return contract.verify_minutes_boundary(scoring)


# --------------------------------------------------------------------------------------
# Phase 3 evaluation contract (Stage C player attacking goals)
# --------------------------------------------------------------------------------------


class Phase3Amendment(_Frozen):
    """One recorded change to the Phase 3 contract. Mirrors Phase 1 & 2 discipline."""

    version: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    candidates_evaluated_before_amendment: int = Field(ge=0)
    changed: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    tolerance_rationale: str | None = None
    deferred: str | None = None


class Phase3TargetPolicy(_Frozen):
    entity: Literal["player"]
    grain: Literal["season_player_code_fixture"]
    outcome: Literal["goals_distribution"]
    downstream_points_ruleset: Literal["2026_27"]
    identity_policy: Literal["code_is_cross_season_player_key"]


class Phase3PopulationPolicy(_Frozen):
    include_zero_minutes: Literal[True]
    eligible_outcome: Literal["minutes_not_null"]
    registered_population: Literal["mart_fact_player_fixture_minutes_not_null"]


PHASE3_TARGET_ROSTER_PROXY_COLUMNS: frozenset[str] = frozenset(
    {
        "season",
        "gw",
        "fixture",
        "kickoff_time",
        "code",
        "position",
        "team_id",
        "opponent_team_id",
        "was_home",
    }
)
PHASE3_TARGET_ROSTER_FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {"element_id", "element", "goals_scored", "goals"}
)


class Phase3TargetRosterPolicy(_Frozen):
    historical_roster_status: Literal["archive_proxy_unversioned_at_real_deadline"]
    historical_source: Literal[
        "archive_player_fixture_identity_schedule_proxy_projected_from_target_rows"
    ]
    proxy_columns: frozenset[str]
    minutes_role: Literal["label_outside_model_facing_projection"]
    live_prospective_registry: Literal[
        "versioned_player_registry_selected_known_at_le_as_of_before_model_sees_entity_team_position"
    ]
    cross_season_team_identity: Literal["season_qualified_team_id_resolved_to_stable_team_code"]
    point_in_time_disclaimer: Literal["not_fully_reconstructable_pit_at_real_deadline"]

    @model_validator(mode="after")
    def _proxy_columns_pinned(self) -> Self:
        if self.proxy_columns != PHASE3_TARGET_ROSTER_PROXY_COLUMNS:
            missing = PHASE3_TARGET_ROSTER_PROXY_COLUMNS - self.proxy_columns
            extra = self.proxy_columns - PHASE3_TARGET_ROSTER_PROXY_COLUMNS
            parts: list[str] = []
            if missing:
                parts.append(f"missing required proxy columns: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected proxy columns: {sorted(extra)}")
            raise ValueError(
                "Phase 3 target roster proxy columns must be exactly "
                f"{sorted(PHASE3_TARGET_ROSTER_PROXY_COLUMNS)}; " + "; ".join(parts)
            )
        overlap = PHASE3_TARGET_ROSTER_FORBIDDEN_COLUMNS & self.proxy_columns
        if overlap:
            raise ValueError(
                "Phase 3 target roster proxy columns must be disjoint from forbidden "
                f"outcome/alias columns {sorted(PHASE3_TARGET_ROSTER_FORBIDDEN_COLUMNS)}; "
                f"overlap: {sorted(overlap)}"
            )
        if "code" not in self.proxy_columns:
            raise ValueError(
                "Phase 3 target roster proxy columns must include 'code' (stable "
                "cross-season player key)"
            )
        return self


class Phase3CutoffPolicy(_Frozen):
    split_unit: Literal["observed_gameweek"]
    prediction_time: Literal["archive_first_kickoff_proxy_for_gameweek_deadline"]
    observed_results: Literal["kickoff_time < as_of"]
    snapshot_versions: Literal["known_at <= as_of"]


class Phase3TrainingPolicy(_Frozen):
    window: Literal["expanding"]
    minimum_observed_gameweeks: Literal[8]
    no_minimum_player_history_exclusion: Literal[True]
    cold_start_policy: Literal["every_eligible_row_receives_fallback_distribution"]
    fit_transforms_within_fold: Literal[True]
    preserve_nulls: Literal[True]
    seed: Literal[202627]


class Phase3XgSignalPolicy(_Frozen):
    xg_handling: Literal["use_when_measured_within_covered_seasons"]
    xg_covered_seasons_judging: Literal[True]
    xg_covered_seasons: tuple[Season, ...]
    finishing_persistence: Literal["shrink_almost_fully_to_positional_mean"]
    fallback_signal: Literal["threat"]


class Phase3StageCCandidateV1Policy(_Frozen):
    """Frozen pre-registration for the first Stage C attacking candidate.

    Candidate V1 is the v1.0 ``trailing_player_goal_rate_poisson`` baseline with one
    change: where xG (``expected_goals``) is measured, the player's recent GOALS signal
    is replaced by recent xG, and the player's own finishing (goals - xG) is shrunk
    almost fully to the positional mean (within-position finishing persistence is at the
    noise floor: FWD 0.138 / MID 0.060 / DEF -0.103 in ``docs/research-adaptation.md``).
    Where xG is unmeasured the candidate falls back to the EXACT v1.0 trailing-player
    baseline, so it reduces to that baseline bit-for-bit in 2021-22 (no xG) and partially
    in 2022-23 (xG measured only from GW16). Unlike the Stage B candidates this is a
    FIXED closed-form estimator: no parameter grid, no inner walk-forward selection, so
    ``selected_parameter`` is pinned to ``none``. ``alpha`` mirrors the v1.0 trailing
    baseline's shrinkage (5.0) so the only change is goals -> xG; ``finishing_keep`` is
    pinned to 0.05 (finishing shrunk 95% to the positional mean). Every distinguishing
    field is pinned so a result cannot be followed by a silent policy change. The block
    is additive: it changes no v1.0 population, target roster, baseline, metric, gate,
    seed, or calibration field.
    """

    name: Literal["xg_informed_trailing_player_goals_v1"]
    development_only: Literal[True]
    development_only_reason: Literal[
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_and_archive_evidence_shaped_the_design"
    ]
    grain: Literal["season_player_code_fixture"]
    identity: Literal["stable_code"]
    history_population: Literal["up_to_5_most_recent_prior_player_fixture_rows_including_zero"]
    history_order: Literal["kickoff_time_then_season_then_fixture"]
    history_window: Literal[5]
    history_observed_results: Literal["kickoff_time < as_of"]
    signal: Literal["expected_goals_where_measured_else_fallback_to_v1_trailing_baseline"]
    xg_handling: Literal["use_when_measured_per_row_null_is_unmeasured"]
    positional_goal_mean: Literal[
        "fold_local_mean_goals_per_appearance_at_target_position_equal_to_v1_positional_baseline"
    ]
    positional_xg_mean: Literal[
        "fold_local_mean_expected_goals_per_appearance_over_xg_measured_prior_rows_at_target_position"
    ]
    trailing_xg_shrinkage: Literal[
        "shrunk_xg_equals_(sum_x_plus_alpha_times_pos_x)_over_(m_plus_alpha)"
    ]
    finishing_policy: Literal["finishing_shrunk_almost_fully_to_positional_mean_keep_0.05"]
    finishing_term: Literal["0.05_times_player_finishing_plus_0.95_times_positional_finishing"]
    rate: Literal["rate_equals_shrunk_xg_plus_finishing_term_clamped_at_zero"]
    fallback_to_v1: Literal[
        "when_no_xg_measured_trailing_row_or_no_positional_xg_mean_rate_is_exact_v1_trailing_shrunk_goals_rate"
    ]
    cold_start_fallback: Literal[
        "when_n_equals_0_rate_is_positional_goal_mean_equal_to_v1_baseline"
    ]
    reduces_to_v1_baseline: Literal[
        "when_all_trailing_xg_unmeasured_candidate_equals_v1_trailing_baseline_bit_for_bit"
    ]
    alpha: float
    finishing_keep: float
    poisson_max_goals: Literal[10]
    estimator: Literal["poisson_goal_count_distribution_over_0_to_10"]
    additional_smoothing: Literal["none"]
    scoring_floor_role: Literal["existing_1e-12_floor_is_scoring_only_not_model_smoothing"]
    selected_parameter: Literal["none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"]
    fit_scope: Literal["positional_means_and_player_histories_recomputed_within_each_fold"]
    target_label_policy: Literal["target_labels_never_enter_model_inputs"]
    target_position_source: Literal["existing_unversioned_target_roster_proxy_current_position"]
    null_policy: Literal["preserve_nulls"]
    zero_minutes_policy: Literal["include_in_history_and_training"]
    assistant_manager_policy: Literal["excluded_upstream_element_type_5"]
    double_gameweek_policy: Literal[
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    ]
    monte_carlo: Literal["out_of_scope_closed_form"]

    @model_validator(mode="after")
    def _exact_candidate_policy(self) -> Self:
        if self.alpha != 5.0:
            raise ValueError(
                f"Stage C Candidate V1 alpha is pinned to 5.0 (== v1.0 trailing baseline); "
                f"got {self.alpha!r}"
            )
        if self.finishing_keep != 0.05:
            raise ValueError(
                "Stage C Candidate V1 finishing_keep is pinned to 0.05 (finishing shrunk 95% "
                f"to the positional mean); got {self.finishing_keep!r}"
            )
        return self


class Phase3StageCCandidateV2Policy(_Frozen):
    """Frozen pre-registration for Stage C attacking Candidate V2 (coupled team share).

    Candidate V2 is a STRUCTURAL change from V1: instead of predicting each player's goals
    independently from their own trailing history, it allocates the frozen Stage A team-goal
    expectation among a club's players by a trailing attacking share (Poisson thinning). For a
    fixture whose club has Stage A expected goals ``lambda_team`` and whose player ``i`` has
    share ``p_i`` (summing to 1 over the club's eligible roster in the fixture), the per-player
    rate is ``rate_i = lambda_team * p_i`` and the prediction is ``Poisson(rate_i)``; the
    per-player marginals are exact independent Poissons whose rates sum to ``lambda_team``
    (structural conservation).

    The Stage A model is the FROZEN ``trailing_goals_attack_defence`` baseline, refit fold-local
    on team-match history with ``kickoff_time < as_of`` -- reused, never reimplemented. Club
    identity is the stable ``team_code`` (resolved from the season-qualified ``team_id`` via
    ``mart_dim_team``); a bare ``team_id`` is never joined across seasons (R data contract).

    R6 appearance-vs-rate correction (V2's defining change over V1): each player's trailing
    attacking signal is computed over their APPEARED prior rows only (``minutes > 0``), so a
    did-not-play prior row cannot dilute a per-appearance rate; availability is separated from
    rate. The signal is trailing ``expected_goals`` where measured, else trailing ``threat``
    (NULL means unmeasured and is never zero-filled). Zero-minute TARGET rows stay in the
    eligible scored population; a player with no attacking output contributes a near-zero share.

    Like V1 this is a FIXED closed-form estimator (no parameter grid, no inner walk-forward):
    ``selected_parameter`` is pinned to ``none`` and ``alpha`` mirrors the v1.0 trailing
    baseline (5.0) so the only structural change is the team-share coupling. Every distinguishing
    field is pinned so a result cannot be followed by a silent policy change. The block is
    additive: it changes no v1.0/1.1 population, target roster, baseline, metric, gate, seed, or
    calibration field, and is judged by the unchanged v1.0 promotion gate.
    """

    name: Literal["coupled_team_share_attacking_goals_v2"]
    development_only: Literal[True]
    development_only_reason: Literal[
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_and_archive_evidence_shaped_the_design"
    ]
    grain: Literal["season_player_code_fixture"]
    identity: Literal["stable_code"]
    stage_a_model: Literal["frozen_trailing_goals_attack_defence_reused_not_reimplemented"]
    stage_a_fit: Literal["fold_local_on_team_match_history_kickoff_time_lt_as_of"]
    team_identity: Literal[
        "team_code_resolved_from_season_qualified_team_id_via_mart_dim_team_never_bare_team_id"
    ]
    share_denominator: Literal[
        "club_eligible_players_in_fixture_the_existing_unversioned_target_roster_proxy_shared_with_baselines_not_new_leakage"
    ]
    share_signal: Literal[
        "trailing_expected_goals_where_measured_else_threat_over_appeared_prior_rows"
    ]
    appeared_rows_filter: Literal[
        "prior_rows_with_minutes_gt_0_only_did_not_play_prior_rows_excluded_from_rate"
    ]
    signal_per_appearance: Literal["mean_signal_over_trailing_appeared_rows"]
    history_window: Literal[5]
    history_order: Literal["kickoff_time_then_season_then_fixture"]
    history_observed_results: Literal["kickoff_time < as_of"]
    share_normalization: Literal["club_roster_signals_normalised_to_sum_to_one"]
    rate: Literal["rate_i_equals_lambda_team_times_share_i"]
    conservation: Literal["poisson_thinning_sum_i_rate_i_equals_lambda_team_on_the_coupled_path"]
    cold_start_share: Literal[
        "when_no_appeared_prior_row_signal_is_fold_local_positional_goal_mean_equal_to_v1_baseline"
    ]
    equal_share_fallback: Literal["when_club_roster_signal_sum_is_zero_equal_shares_among_roster"]
    stage_a_uninformative_fallback: Literal[
        "when_stage_a_training_window_empty_rate_is_exact_v1_trailing_baseline_per_player"
    ]
    reduces_to_baseline: Literal[
        "where_stage_a_is_uninformative_candidate_equals_v1_trailing_player_goal_rate_poisson_bit_for_bit"
    ]
    poisson_max_goals: Literal[10]
    estimator: Literal["poisson_goal_count_distribution_over_0_to_10"]
    additional_smoothing: Literal["none"]
    scoring_floor_role: Literal["existing_1e-12_floor_is_scoring_only_not_a_model_rate_floor"]
    selected_parameter: Literal["none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"]
    fit_scope: Literal["stage_a_and_player_shares_fitted_within_each_fold_on_kickoff_time_lt_as_of"]
    target_label_policy: Literal["target_labels_never_enter_model_inputs"]
    target_position_source: Literal["existing_unversioned_target_roster_proxy_current_position"]
    null_policy: Literal["preserve_nulls_xg_threat_null_means_unmeasured_never_zero_filled"]
    zero_minutes_policy: Literal["target_zero_minute_rows_scored_roster_is_the_eligible_population"]
    assistant_manager_policy: Literal["excluded_upstream_element_type_5"]
    double_gameweek_policy: Literal[
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    ]
    monte_carlo: Literal["out_of_scope_closed_form"]
    alpha: float

    @model_validator(mode="after")
    def _exact_candidate_policy(self) -> Self:
        if self.alpha != 5.0:
            raise ValueError(
                "Stage C Candidate V2 alpha is pinned to 5.0 (== v1.0 trailing baseline, used by "
                f"the stage_a_uninformative fallback); got {self.alpha!r}"
            )
        return self


class Phase3StageCCandidateV3Policy(_Frozen):
    """Frozen pre-registration for Stage C attacking Candidate V3 (minutes-gated coupled share).

    Candidate V3 is Candidate V2 with the per-player rate gated by an explicit Stage B minutes
    input, fully separating appearance probability from per-appearance attacking rate (R6). From
    the frozen Stage B BASELINE ``trailing_5_player_minutes`` (a deterministic baseline, not an
    unpromoted candidate) it derives, fold-local on player-fixture history with
    ``kickoff_time < as_of``, each player's appearance probability
    ``p_play = P(minutes >= 1) = 1 - dist[0]``. The coupled team-share rate is then scaled by the
    appearance probability and RENORMALISED so the team total stays at ``lambda_team``:

        weighted_i = share_i * p_play_i
        rate_i = lambda_team * weighted_i / sum_j(weighted_j)   =>   sum_i rate_i = lambda_team.

    The renormalisation (rather than a sub-``lambda_team`` total) keeps the V2 conservation
    property: mass from low-``p_play`` players is redistributed to players more likely to appear.
    It reduces EXACTLY to V2 when minutes gating is disabled (and to the V2 allocation when every
    ``p_play == 1``). The Stage B minutes input is a DEVELOPMENT PROXY (a baseline, so it introduces
    no unpromoted-candidate dependency), stated as an additional reason the verdict is dev-only.

    Like V1/V2 this is a FIXED closed-form estimator (no parameter grid, no inner walk-forward):
    ``alpha`` mirrors the v1.0 trailing baseline (5.0) and is used only by the stage-A-uninformative
    fallback. Every distinguishing field is pinned so a result cannot be followed by a silent policy
    change. The block is additive: it changes no v1.0/1.1/1.2 population, target roster, baseline,
    metric, gate, seed, or calibration field, and is judged by the unchanged v1.0 promotion gate.
    """

    name: Literal["minutes_gated_coupled_team_share_attacking_goals_v3"]
    development_only: Literal[True]
    development_only_reason: Literal[
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_and_stage_b_minutes_input_is_a_development_proxy"
    ]
    grain: Literal["season_player_code_fixture"]
    identity: Literal["stable_code"]
    stage_a_model: Literal["frozen_trailing_goals_attack_defence_reused_not_reimplemented"]
    stage_a_fit: Literal["fold_local_on_team_match_history_kickoff_time_lt_as_of"]
    team_identity: Literal[
        "team_code_resolved_from_season_qualified_team_id_via_mart_dim_team_never_bare_team_id"
    ]
    share_denominator: Literal[
        "club_eligible_players_in_fixture_the_existing_unversioned_target_roster_proxy_shared_with_baselines_not_new_leakage"
    ]
    share_signal: Literal[
        "trailing_expected_goals_where_measured_else_threat_over_appeared_prior_rows"
    ]
    appeared_rows_filter: Literal[
        "prior_rows_with_minutes_gt_0_only_did_not_play_prior_rows_excluded_from_rate"
    ]
    signal_per_appearance: Literal["mean_signal_over_trailing_appeared_rows"]
    history_window: Literal[5]
    history_order: Literal["kickoff_time_then_season_then_fixture"]
    history_observed_results: Literal["kickoff_time < as_of"]
    share_normalization: Literal["club_roster_signals_normalised_to_sum_to_one"]
    minutes_source: Literal[
        "frozen_stage_b_baseline_trailing_5_player_minutes_development_proxy_not_a_candidate"
    ]
    minutes_baseline: Literal["trailing_5_player_minutes"]
    minutes_fit: Literal["fold_local_on_player_fixture_history_kickoff_time_lt_as_of"]
    appearance_probability: Literal[
        "p_play_equals_one_minus_trailing5_minutes_distribution_bin_zero"
    ]
    minutes_gating: Literal["rate_i_equals_lambda_team_times_renormalised_share_i_times_p_play_i"]
    conservation: Literal[
        "renormalise_share_i_times_p_play_i_to_sum_to_one_so_sum_i_rate_i_equals_lambda_team"
    ]
    reduces_to_v2_when_gating_off: Literal[True]
    minutes_rate_separation: Literal[
        "minutes_and_per_appearance_attacking_rate_are_separate_components_R6"
    ]
    cold_start_share: Literal[
        "when_no_appeared_prior_row_signal_is_fold_local_positional_goal_mean_equal_to_v1_baseline"
    ]
    equal_share_fallback: Literal["when_club_roster_signal_sum_is_zero_equal_shares_among_roster"]
    stage_a_uninformative_fallback: Literal[
        "when_stage_a_training_window_empty_rate_is_exact_v1_trailing_baseline_per_player"
    ]
    reduces_to_v2: Literal["when_minutes_gating_disabled_candidate_equals_v2_bit_for_bit"]
    poisson_max_goals: Literal[10]
    estimator: Literal["poisson_goal_count_distribution_over_0_to_10"]
    additional_smoothing: Literal["none"]
    scoring_floor_role: Literal["existing_1e-12_floor_is_scoring_only_not_a_model_rate_floor"]
    selected_parameter: Literal["none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"]
    fit_scope: Literal[
        "stage_a_player_shares_and_stage_b_minutes_all_fitted_within_each_fold_on_kickoff_time_lt_as_of"
    ]
    target_label_policy: Literal["target_labels_never_enter_model_inputs"]
    target_position_source: Literal["existing_unversioned_target_roster_proxy_current_position"]
    null_policy: Literal["preserve_nulls_xg_threat_null_means_unmeasured_never_zero_filled"]
    zero_minutes_policy: Literal["target_zero_minute_rows_scored_roster_is_the_eligible_population"]
    assistant_manager_policy: Literal["excluded_upstream_element_type_5"]
    double_gameweek_policy: Literal[
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    ]
    monte_carlo: Literal["out_of_scope_closed_form"]
    alpha: float

    @model_validator(mode="after")
    def _exact_candidate_policy(self) -> Self:
        if self.alpha != 5.0:
            raise ValueError(
                "Stage C Candidate V3 alpha is pinned to 5.0 (== v1.0 trailing baseline, used by "
                f"the stage_a_uninformative fallback); got {self.alpha!r}"
            )
        return self


_PHASE3_BASELINE_PINS: dict[str, dict[str, str | int | None]] = {
    "positional_goal_rate_poisson": {
        "identity": "target_position",
        "population": "all_prior_eligible_rows_at_target_position",
        "order": "none_applicable_all_rows",
        "window": None,
        "fallback": "unsmoothed_all_position_prior_rows",
        "estimator": "positional_mean_goals_per_appearance_poisson",
    },
    "trailing_player_goal_rate_poisson": {
        "identity": "stable_code",
        "population": "up_to_5_most_recent_prior_player_fixture_rows_including_zero",
        "order": "kickoff_time_then_season_then_fixture",
        "window": 5,
        "fallback": "positional_goal_rate_poisson",
        "estimator": "player_goals_per_appearance_shrunk_to_positional_mean_poisson",
    },
}


class Phase3BaselineDefinition(_Frozen):
    name: Literal[
        "positional_goal_rate_poisson",
        "trailing_player_goal_rate_poisson",
    ]
    identity: Literal["target_position", "stable_code"]
    population: Literal[
        "all_prior_eligible_rows_at_target_position",
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero",
    ]
    order: Literal[
        "none_applicable_all_rows",
        "kickoff_time_then_season_then_fixture",
    ]
    window: int | None
    additive_smoothing: Literal["none"]
    fallback: Literal[
        "unsmoothed_all_position_prior_rows",
        "positional_goal_rate_poisson",
    ]
    estimator: Literal[
        "positional_mean_goals_per_appearance_poisson",
        "player_goals_per_appearance_shrunk_to_positional_mean_poisson",
    ]

    @model_validator(mode="after")
    def _pinned_to_name(self) -> Self:
        pinned = _PHASE3_BASELINE_PINS[self.name]
        for field_name, expected_value in pinned.items():
            actual = getattr(self, field_name)
            if actual != expected_value:
                raise ValueError(
                    f'Stage C baseline "{self.name}" has {field_name}={actual!r} but frozen '
                    f"definition pins it to {expected_value!r}"
                )
        return self


class Phase3BaselinePolicy(_Frozen):
    stage_c_attacking: frozenset[str]
    definitions: tuple[Phase3BaselineDefinition, ...]
    excluded: frozenset[str]

    @model_validator(mode="after")
    def _definitions_match_stage_c(self) -> Self:
        names = [definition.name for definition in self.definitions]
        if len(names) != len(set(names)):
            raise ValueError(f"Stage C baseline definitions have duplicate names: {names}")
        if set(names) != self.stage_c_attacking:
            expected_set = sorted(self.stage_c_attacking)
            actual_set = sorted(set(names))
            raise ValueError(
                f"Stage C baseline definition names {actual_set} "
                f"must match stage_c_attacking {expected_set}"
            )
        return self


class Phase3MetricPolicy(_Frozen):
    primary: Literal["mean_log_score"]
    primary_direction: Literal["lower_is_better"]
    proper_distribution: frozenset[str]
    binary_guardrails: frozenset[str]
    calibration: frozenset[str]
    reliability_buckets_carry_n: Literal[True]


class Phase3PromotionGate(_Frozen):
    compare_against: Literal["best_eligible_required_stage_c_attacking_baseline"]
    comparison_population: Literal["same_eligible_predictions"]
    relative_lift_formula: Literal["(baseline - candidate) / abs(baseline)"]
    guardrail_comparison: Literal["best_baseline_per_metric"]
    minimum_primary_relative_lift: float
    maximum_ranked_probability_score_relative_regression: float
    maximum_brier_relative_regression_at_least_one_goal: float
    pit_interval_80_maximum_absolute_error: float
    minimum_fold_count: Literal[181]
    minimum_prediction_coverage: float
    require_no_season_mean_log_score_regression: Literal[True]
    require_zero_leakage_failures: Literal[True]

    @field_validator("minimum_primary_relative_lift")
    @classmethod
    def _lift_pinned(cls, value: float) -> float:
        if value != 0.01:
            raise ValueError(f"minimum_primary_relative_lift is pinned to 0.01; got {value!r}")
        return value

    @field_validator("maximum_ranked_probability_score_relative_regression")
    @classmethod
    def _rps_regression_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError(
                "maximum_ranked_probability_score_relative_regression is pinned to 0.0"
            )
        return value

    @field_validator("maximum_brier_relative_regression_at_least_one_goal")
    @classmethod
    def _brier_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError("maximum_brier_relative_regression_at_least_one_goal is pinned to 0.0")
        return value

    @field_validator("pit_interval_80_maximum_absolute_error")
    @classmethod
    def _pit_error_pinned(cls, value: float) -> float:
        if value != 0.05:
            raise ValueError("pit_interval_80_maximum_absolute_error is pinned to 0.05")
        return value

    @field_validator("minimum_prediction_coverage")
    @classmethod
    def _coverage_is_total(cls, value: float) -> float:
        if value != 1.0:
            raise ValueError("minimum_prediction_coverage is pinned to 1.0")
        return value


class Phase3ReportingPolicy(_Frozen):
    dimensions: frozenset[str]
    counts: frozenset[str]


class Phase3HistoricalFeaturePolicy(_Frozen):
    availability_status: Literal["excluded_unavailable_in_archive"]
    point_in_time_only: Literal["reconstructable_fields_only"]
    live_availability_prospective_candidate: Literal["separately_named_prospective_only"]
    historical_score_is: Literal["development_number_not_upper_bound"]


class Phase3ScoringCalibrationPolicy(_Frozen):
    log_probability_floor: float
    ranked_probability_score: Literal[
        "sum_of_squared_ordered_category_cdf_errors_not_physical_minute_distance"
    ]
    brier: Literal["squared_binary_probability_error"]
    randomized_pit_band: tuple[float, float]
    randomized_pit_seed: Literal[202627]
    reliability_edges: tuple[float, ...]
    reliability_buckets: Literal["left_closed_right_open_except_final_bucket_right_closed"]
    reliability_bucket_n: Literal[True]

    @field_validator("log_probability_floor")
    @classmethod
    def _log_floor_pinned(cls, value: float) -> float:
        if value != 1e-12:
            raise ValueError("log_probability_floor is pinned to 1e-12")
        return value


class Phase3MonteCarloPolicy(_Frozen):
    scope: Literal["out_of_scope_closed_form_marginal"]


ORIGINAL_PHASE3_CONTRACT_VERSION: str = "1.0"
FROZEN_PHASE3_AMENDMENT_HISTORY: dict[str, tuple[tuple[str, int], ...]] = {
    "1.0": (),
    "1.1": (("1.1", 0),),
    "1.2": (("1.1", 0), ("1.2", 1)),
    "1.3": (("1.1", 0), ("1.2", 1), ("1.3", 2)),
}


class Phase3EvaluationConfig(_Frozen):
    contract_version: str
    phase: Literal[3]
    amendments: tuple[Phase3Amendment, ...] = ()
    target: Phase3TargetPolicy
    target_roster: Phase3TargetRosterPolicy
    population: Phase3PopulationPolicy
    cutoff: Phase3CutoffPolicy
    training: Phase3TrainingPolicy
    xg_signal_policy: Phase3XgSignalPolicy
    # Candidate V1 (xG-informed trailing player goals) is required at contract version 1.1. It is
    # additive: it changes no v1.0 population/roster/baseline/metric/gate and is judged by the
    # unchanged v1.0 promotion gate. Required here so a 1.1 config that silently drops it fails to
    # load rather than scoring a different model.
    stage_c_candidate_v1: Phase3StageCCandidateV1Policy
    # Candidate V2 (coupled team-share attacking goals) is required at contract version 1.2. It is
    # additive: it changes no v1.0/1.1 population/roster/baseline/metric/gate and is judged by the
    # unchanged v1.0 promotion gate. Required here so a 1.2 config that silently drops it fails to
    # load rather than scoring a different model.
    stage_c_candidate_v2: Phase3StageCCandidateV2Policy
    # Candidate V3 (minutes-gated coupled team share) is required at contract version 1.3. It is
    # additive: it changes no v1.0/1.1/1.2 population/roster/baseline/metric/gate and is judged by
    # the unchanged v1.0 promotion gate. Required here so a 1.3 config that silently drops it fails
    # to load rather than scoring a different model.
    stage_c_candidate_v3: Phase3StageCCandidateV3Policy
    baselines: Phase3BaselinePolicy
    metrics: Phase3MetricPolicy
    promotion: Phase3PromotionGate
    reporting: Phase3ReportingPolicy
    historical_features: Phase3HistoricalFeaturePolicy
    scoring_calibration: Phase3ScoringCalibrationPolicy
    monte_carlo: Phase3MonteCarloPolicy

    @model_validator(mode="after")
    def _required_baselines_metrics_and_outputs(self) -> Self:
        _require_exact_set(
            self.baselines.stage_c_attacking,
            {
                "positional_goal_rate_poisson",
                "trailing_player_goal_rate_poisson",
            },
            label="Stage C attacking baselines",
        )
        _require_exact_set(
            self.baselines.excluded,
            {"fpl_ep_next_recorded_rules"},
            label="excluded baselines",
        )
        _require_exact_set(
            self.metrics.proper_distribution,
            {"mean_log_score", "mean_ranked_probability_score"},
            label="proper distribution metrics",
        )
        _require_exact_set(
            self.metrics.binary_guardrails,
            {"mean_brier_at_least_one_goal"},
            label="binary guardrail metrics",
        )
        _require_exact_set(
            self.metrics.calibration,
            {
                "randomized_pit",
                "pit_interval_80_coverage",
                "reliability_at_least_one_goal",
            },
            label="calibration outputs",
        )
        _require_exact_set(
            self.reporting.dimensions,
            {"fold", "season", "position", "home_away"},
            label="report dimensions",
        )
        _require_exact_set(
            self.reporting.counts,
            {"predictions", "exclusions", "cold_starts", "uncertainty"},
            label="report counts",
        )
        return self

    @model_validator(mode="after")
    def _version_needs_amendment_record_unless_original(self) -> Self:
        if self.contract_version != ORIGINAL_PHASE3_CONTRACT_VERSION and not any(
            amendment.version == self.contract_version for amendment in self.amendments
        ):
            raise ValueError(
                f"Phase 3 contract version {self.contract_version} has no amendment record; "
                "a pre-registered gate may not change without one"
            )
        return self

    @model_validator(mode="after")
    def _amendment_history_is_frozen(self) -> Self:
        expected = FROZEN_PHASE3_AMENDMENT_HISTORY.get(self.contract_version)
        if expected is None:
            return self
        actual = tuple(
            (amendment.version, amendment.candidates_evaluated_before_amendment)
            for amendment in self.amendments
        )
        if actual != expected:
            raise ValueError(
                f"Phase 3 amendment history for contract {self.contract_version} is not the "
                f"frozen record: expected {expected}, got {actual}."
            )
        return self


@functools.cache
def load_phase3_evaluation(path: Path | None = None) -> Phase3EvaluationConfig:
    return Phase3EvaluationConfig.model_validate(
        _read_yaml(path or config_dir() / "phase3_evaluation.yaml")
    )


# --------------------------------------------------------------------------------------
# Phase 3 Stage C (player attacking assists) evaluation contract
#
# A SEPARATE frozen contract from the Stage C goals contract above. Assists are a distinct FPL
# label with their own signal (expected_assists / creativity) and their own version counter, so
# this contract never perturbs the goals contract. It mirrors the goals loader's frozen
# pre-registration discipline. The generic Phase 3 policy classes with no label-specific Literal
# (amendment record, population, cutoff, training, metric set shape, reporting, historical
# features, scoring calibration, Monte Carlo) are reused unchanged; only the label-specific
# policies (target outcome, target roster forbidden columns, xA signal, baseline names, gate
# field name) are mirrored here.
# --------------------------------------------------------------------------------------


class Phase3StageCAssistsTargetPolicy(_Frozen):
    entity: Literal["player"]
    grain: Literal["season_player_code_fixture"]
    outcome: Literal["assists_distribution"]
    downstream_points_ruleset: Literal["2026_27"]
    identity_policy: Literal["code_is_cross_season_player_key"]


# The assist label column and its aliases are forbidden as target-roster proxy columns (the
# label stays outside the model-facing projection). Same nine label-free proxy columns as the
# goals contract are required.
PHASE3_STAGE_C_ASSISTS_TARGET_ROSTER_FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {"element_id", "element", "assists"}
)


class Phase3StageCAssistsTargetRosterPolicy(_Frozen):
    historical_roster_status: Literal["archive_proxy_unversioned_at_real_deadline"]
    historical_source: Literal[
        "archive_player_fixture_identity_schedule_proxy_projected_from_target_rows"
    ]
    proxy_columns: frozenset[str]
    minutes_role: Literal["label_outside_model_facing_projection"]
    live_prospective_registry: Literal[
        "versioned_player_registry_selected_known_at_le_as_of_before_model_sees_entity_team_position"
    ]
    cross_season_team_identity: Literal["season_qualified_team_id_resolved_to_stable_team_code"]
    point_in_time_disclaimer: Literal["not_fully_reconstructable_pit_at_real_deadline"]

    @model_validator(mode="after")
    def _proxy_columns_pinned(self) -> Self:
        if self.proxy_columns != PHASE3_TARGET_ROSTER_PROXY_COLUMNS:
            missing = PHASE3_TARGET_ROSTER_PROXY_COLUMNS - self.proxy_columns
            extra = self.proxy_columns - PHASE3_TARGET_ROSTER_PROXY_COLUMNS
            parts: list[str] = []
            if missing:
                parts.append(f"missing required proxy columns: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected proxy columns: {sorted(extra)}")
            raise ValueError(
                "Stage C assists target roster proxy columns must be exactly "
                f"{sorted(PHASE3_TARGET_ROSTER_PROXY_COLUMNS)}; " + "; ".join(parts)
            )
        overlap = PHASE3_STAGE_C_ASSISTS_TARGET_ROSTER_FORBIDDEN_COLUMNS & self.proxy_columns
        if overlap:
            forbidden = sorted(PHASE3_STAGE_C_ASSISTS_TARGET_ROSTER_FORBIDDEN_COLUMNS)
            raise ValueError(
                "Stage C assists target roster proxy columns must be disjoint from forbidden "
                f"outcome/alias columns {forbidden}; overlap: {sorted(overlap)}"
            )
        return self


class Phase3StageCAssistsXaSignalPolicy(_Frozen):
    """The expected_assists (xA) signal policy, the assists analogue of the goals xG policy.

    ``expected_assists`` has the SAME measured-coverage profile as ``expected_goals`` (NULL in
    2021-22, partial in 2022-23, 100% in 2023-24+) and is judged within the xA-covered seasons.
    ``creativity`` (the FPL-native creative index) is measured 100% every season and is the
    fallback signal where xA is absent, exactly as ``threat`` is the goals fallback.
    """

    xa_handling: Literal["use_when_measured_within_covered_seasons"]
    xa_covered_seasons_judging: Literal[True]
    xa_covered_seasons: tuple[Season, ...]
    residual_persistence: Literal["shrink_almost_fully_to_positional_mean"]
    fallback_signal: Literal["creativity"]


_PHASE3_STAGE_C_ASSISTS_BASELINE_PINS: dict[str, dict[str, str | int | None]] = {
    "positional_assist_rate_poisson": {
        "identity": "target_position",
        "population": "all_prior_eligible_rows_at_target_position",
        "order": "none_applicable_all_rows",
        "window": None,
        "fallback": "unsmoothed_all_position_prior_rows",
        "estimator": "positional_mean_assists_per_appearance_poisson",
    },
    "trailing_player_assist_rate_poisson": {
        "identity": "stable_code",
        "population": "up_to_5_most_recent_prior_player_fixture_rows_including_zero",
        "order": "kickoff_time_then_season_then_fixture",
        "window": 5,
        "fallback": "positional_assist_rate_poisson",
        "estimator": "player_assists_per_appearance_shrunk_to_positional_mean_poisson",
    },
}


class Phase3StageCAssistsBaselineDefinition(_Frozen):
    name: Literal[
        "positional_assist_rate_poisson",
        "trailing_player_assist_rate_poisson",
    ]
    identity: Literal["target_position", "stable_code"]
    population: Literal[
        "all_prior_eligible_rows_at_target_position",
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero",
    ]
    order: Literal[
        "none_applicable_all_rows",
        "kickoff_time_then_season_then_fixture",
    ]
    window: int | None
    additive_smoothing: Literal["none"]
    fallback: Literal[
        "unsmoothed_all_position_prior_rows",
        "positional_assist_rate_poisson",
    ]
    estimator: Literal[
        "positional_mean_assists_per_appearance_poisson",
        "player_assists_per_appearance_shrunk_to_positional_mean_poisson",
    ]

    @model_validator(mode="after")
    def _pinned_to_name(self) -> Self:
        pinned = _PHASE3_STAGE_C_ASSISTS_BASELINE_PINS[self.name]
        for field_name, expected_value in pinned.items():
            actual = getattr(self, field_name)
            if actual != expected_value:
                raise ValueError(
                    f'Stage C assists baseline "{self.name}" has {field_name}={actual!r} but '
                    f"frozen definition pins it to {expected_value!r}"
                )
        return self


class Phase3StageCAssistsBaselinePolicy(_Frozen):
    stage_c_attacking_assists: frozenset[str]
    definitions: tuple[Phase3StageCAssistsBaselineDefinition, ...]
    excluded: frozenset[str]

    @model_validator(mode="after")
    def _definitions_match_stage_c(self) -> Self:
        names = [definition.name for definition in self.definitions]
        if len(names) != len(set(names)):
            raise ValueError(f"Stage C assists baseline definitions have duplicate names: {names}")
        if set(names) != self.stage_c_attacking_assists:
            expected_set = sorted(self.stage_c_attacking_assists)
            actual_set = sorted(set(names))
            raise ValueError(
                f"Stage C assists baseline definition names {actual_set} "
                f"must match stage_c_attacking_assists {expected_set}"
            )
        return self


class Phase3StageCAssistsPromotionGate(_Frozen):
    compare_against: Literal["best_eligible_required_stage_c_attacking_assists_baseline"]
    comparison_population: Literal["same_eligible_predictions"]
    relative_lift_formula: Literal["(baseline - candidate) / abs(baseline)"]
    guardrail_comparison: Literal["best_baseline_per_metric"]
    minimum_primary_relative_lift: float
    maximum_ranked_probability_score_relative_regression: float
    maximum_brier_relative_regression_at_least_one_assist: float
    pit_interval_80_maximum_absolute_error: float
    minimum_fold_count: Literal[181]
    minimum_prediction_coverage: float
    require_no_season_mean_log_score_regression: Literal[True]
    require_zero_leakage_failures: Literal[True]

    @field_validator("minimum_primary_relative_lift")
    @classmethod
    def _lift_pinned(cls, value: float) -> float:
        if value != 0.01:
            raise ValueError(f"minimum_primary_relative_lift is pinned to 0.01; got {value!r}")
        return value

    @field_validator("maximum_ranked_probability_score_relative_regression")
    @classmethod
    def _rps_regression_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError(
                "maximum_ranked_probability_score_relative_regression is pinned to 0.0"
            )
        return value

    @field_validator("maximum_brier_relative_regression_at_least_one_assist")
    @classmethod
    def _brier_pinned(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError(
                "maximum_brier_relative_regression_at_least_one_assist is pinned to 0.0"
            )
        return value

    @field_validator("pit_interval_80_maximum_absolute_error")
    @classmethod
    def _pit_error_pinned(cls, value: float) -> float:
        if value != 0.05:
            raise ValueError("pit_interval_80_maximum_absolute_error is pinned to 0.05")
        return value

    @field_validator("minimum_prediction_coverage")
    @classmethod
    def _coverage_is_total(cls, value: float) -> float:
        if value != 1.0:
            raise ValueError("minimum_prediction_coverage is pinned to 1.0")
        return value


class Phase3StageCAssistsCandidateV1Policy(_Frozen):
    """Frozen pre-registration for the first Stage C attacking assists candidate.

    Candidate V1 is the v1.0 ``trailing_player_assist_rate_poisson`` baseline with one change:
    where xA (``expected_assists``) is measured, the player's recent ASSISTS signal is replaced by
    recent xA (per row, NULL xA filled by ``creativity`` rescaled to the assist-rate scale), and
    the player's own assist residual (assists - xA) is shrunk almost fully to the positional mean.
    The supporting measurement (assists-minus-xA within-position persistence DEF +0.01 / MID +0.16
    / FWD +0.19 / GK -0.07) is modest, so the residual is shrunk 95% to the positional mean. Where
    xA is unmeasured the candidate falls back to the EXACT v1.0 trailing-player baseline, so it
    reduces to that baseline bit-for-bit in 2021-22 (no xA) and partially in 2022-23 (xA measured
    only from GW16).

    The per-appearance signal is over trailing-5 APPEARED prior rows (``minutes > 0``) only (R6
    appearance-vs-rate), while the fallback uses the baseline's all-rows window so it stays
    bit-identical. Unlike the Stage B candidates this is a FIXED closed-form estimator: no
    parameter grid, no inner walk-forward selection, so ``selected_parameter`` is pinned to
    ``none``. ``alpha`` mirrors the v1.0 trailing baseline's shrinkage (5.0) so the only structural
    change is assists -> xA; ``finishing_keep`` is pinned to 0.05. Every distinguishing field is
    pinned so a result cannot be followed by a silent policy change. The block is additive: it
    changes no v1.0 population, target roster, baseline, metric, gate, seed, or calibration field.
    """

    name: Literal["xa_informed_trailing_player_assists_v1"]
    development_only: Literal[True]
    development_only_reason: Literal[
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_and_archive_evidence_shaped_the_design"
    ]
    grain: Literal["season_player_code_fixture"]
    identity: Literal["stable_code"]
    history_population: Literal[
        "up_to_5_most_recent_prior_appeared_player_fixture_rows_minutes_gt_0"
    ]
    appeared_rows_filter: Literal[
        "signal_window_is_trailing_5_appeared_prior_rows_minutes_gt_0_did_not_play_rows_excluded_R6"
    ]
    history_order: Literal["kickoff_time_then_season_then_fixture"]
    history_window: Literal[5]
    history_observed_results: Literal["kickoff_time < as_of"]
    signal: Literal[
        "expected_assists_where_measured_else_creativity_rescaled_to_assist_rate_scale_per_row"
    ]
    xa_handling: Literal[
        "use_when_measured_per_row_null_is_unmeasured_filled_by_rescaled_creativity"
    ]
    positional_assist_mean: Literal[
        "fold_local_mean_assists_per_appearance_at_target_position_equal_to_v1_positional_baseline"
    ]
    positional_xa_mean: Literal[
        "fold_local_mean_expected_assists_per_appearance_over_xa_measured_appeared_prior_rows_at_target_position"
    ]
    creativity_rescale: Literal[
        "fold_local_positional_factor_pos_assist_mean_over_mean_creativity_per_appearance"
    ]
    trailing_xa_shrinkage: Literal[
        "shrunk_xa_equals_(sum_xa_plus_alpha_times_pos_xa)_over_(n_plus_alpha)"
    ]
    residual_policy: Literal["assist_residual_shrunk_almost_fully_to_positional_mean_keep_0.05"]
    residual_term: Literal[
        "0.05_times_player_assist_residual_plus_0.95_times_positional_assist_residual"
    ]
    rate: Literal["rate_equals_shrunk_xa_plus_residual_term_clamped_at_zero"]
    fallback_to_v1: Literal[
        "when_no_xa_measured_appeared_trailing_row_or_no_positional_xa_mean_rate_is_exact_v1_trailing_shrunk_assists_rate_over_all_rows_window"
    ]
    cold_start_fallback: Literal[
        "when_no_prior_player_row_rate_is_positional_assist_mean_equal_to_v1_baseline"
    ]
    reduces_to_v1_baseline: Literal[
        "when_all_trailing_xa_unmeasured_candidate_equals_v1_trailing_assist_baseline_bit_for_bit"
    ]
    alpha: float
    finishing_keep: float
    poisson_max_assists: Literal[10]
    estimator: Literal["poisson_assist_count_distribution_over_0_to_10"]
    additional_smoothing: Literal["none"]
    scoring_floor_role: Literal["existing_1e-12_floor_is_scoring_only_not_model_smoothing"]
    selected_parameter: Literal["none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"]
    fit_scope: Literal["positional_means_and_player_histories_recomputed_within_each_fold"]
    target_label_policy: Literal["target_labels_never_enter_model_inputs"]
    target_position_source: Literal["existing_unversioned_target_roster_proxy_current_position"]
    null_policy: Literal["preserve_nulls_xa_creativity_null_means_unmeasured_never_zero_filled"]
    zero_minutes_policy: Literal[
        "zero_minute_prior_rows_excluded_from_appeared_signal_window_but_scored_as_targets"
    ]
    assistant_manager_policy: Literal["excluded_upstream_element_type_5"]
    double_gameweek_policy: Literal[
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    ]
    monte_carlo: Literal["out_of_scope_closed_form"]

    @model_validator(mode="after")
    def _exact_candidate_policy(self) -> Self:
        if self.alpha != 5.0:
            raise ValueError(
                f"Stage C assists Candidate V1 alpha is pinned to 5.0 (== v1.0 trailing baseline); "
                f"got {self.alpha!r}"
            )
        if self.finishing_keep != 0.05:
            raise ValueError(
                "Stage C assists Candidate V1 finishing_keep is pinned to 0.05 (assist residual "
                f"shrunk 95% to the positional mean); got {self.finishing_keep!r}"
            )
        return self


ORIGINAL_PHASE3_STAGE_C_ASSISTS_CONTRACT_VERSION: str = "1.0"
FROZEN_PHASE3_STAGE_C_ASSISTS_AMENDMENT_HISTORY: dict[str, tuple[tuple[str, int], ...]] = {
    "1.0": (),
    "1.1": (("1.1", 0),),
}


class Phase3StageCAssistsEvaluationConfig(_Frozen):
    """Executable entry and promotion contract for the Stage C attacking-assists walk-forward.

    Stage C assists predicts a discrete Poisson count distribution over player assists (0..10)
    at ``(season, code, fixture)`` grain. Version 1.0 freezes the population, grain, identity
    policy, xA-signal policy, two baselines, metrics, and promotion gate before any candidate
    exists; this is the baseline-only Stage 1 contract. It carries no candidate block: a
    candidate is pre-registered by a later additive amendment that bumps ``contract_version``
    and adds a matching pinned policy, judged by the unchanged v1.0 gate.
    """

    contract_version: str
    phase: Literal[3]
    amendments: tuple[Phase3Amendment, ...] = ()
    target: Phase3StageCAssistsTargetPolicy
    target_roster: Phase3StageCAssistsTargetRosterPolicy
    population: Phase3PopulationPolicy
    cutoff: Phase3CutoffPolicy
    training: Phase3TrainingPolicy
    xa_signal_policy: Phase3StageCAssistsXaSignalPolicy
    # Candidate V1 (xA-informed trailing player assists) is required from contract version 1.1.
    # It is additive: changes no v1.0 population/roster/baseline/metric/gate; judged by the
    # unchanged v1.0 gate. Optional (None) at v1.0 (baseline-only); required after.
    stage_c_assists_candidate_v1: Phase3StageCAssistsCandidateV1Policy | None = None
    baselines: Phase3StageCAssistsBaselinePolicy
    metrics: Phase3MetricPolicy
    promotion: Phase3StageCAssistsPromotionGate
    reporting: Phase3ReportingPolicy
    historical_features: Phase3HistoricalFeaturePolicy
    scoring_calibration: Phase3ScoringCalibrationPolicy
    monte_carlo: Phase3MonteCarloPolicy

    @model_validator(mode="after")
    def _required_baselines_metrics_and_outputs(self) -> Self:
        _require_exact_set(
            self.baselines.stage_c_attacking_assists,
            {"positional_assist_rate_poisson", "trailing_player_assist_rate_poisson"},
            label="Stage C attacking assists baselines",
        )
        _require_exact_set(
            self.baselines.excluded,
            {"fpl_ep_next_recorded_rules"},
            label="excluded baselines",
        )
        _require_exact_set(
            self.metrics.proper_distribution,
            {"mean_log_score", "mean_ranked_probability_score"},
            label="proper distribution metrics",
        )
        _require_exact_set(
            self.metrics.binary_guardrails,
            {"mean_brier_at_least_one_assist"},
            label="binary guardrail metrics",
        )
        _require_exact_set(
            self.metrics.calibration,
            {
                "randomized_pit",
                "pit_interval_80_coverage",
                "reliability_at_least_one_assist",
            },
            label="calibration outputs",
        )
        _require_exact_set(
            self.reporting.dimensions,
            {"fold", "season", "position", "home_away"},
            label="report dimensions",
        )
        _require_exact_set(
            self.reporting.counts,
            {"predictions", "exclusions", "cold_starts", "uncertainty"},
            label="report counts",
        )
        return self

    @model_validator(mode="after")
    def _candidate_required_after_v1_0(self) -> Self:
        """v1.0 is baseline-only (no candidate); any later version requires Candidate V1."""
        if self.contract_version == ORIGINAL_PHASE3_STAGE_C_ASSISTS_CONTRACT_VERSION:
            if self.stage_c_assists_candidate_v1 is not None:
                raise ValueError(
                    "Stage C assists contract v1.0 is baseline-only and must not carry a "
                    "stage_c_assists_candidate_v1 block"
                )
        elif self.stage_c_assists_candidate_v1 is None:
            raise ValueError(
                f"Stage C assists contract version {self.contract_version} requires a "
                "stage_c_assists_candidate_v1 block; it is missing"
            )
        return self

    @model_validator(mode="after")
    def _version_needs_amendment_record_unless_original(self) -> Self:
        if self.contract_version != ORIGINAL_PHASE3_STAGE_C_ASSISTS_CONTRACT_VERSION and not any(
            amendment.version == self.contract_version for amendment in self.amendments
        ):
            raise ValueError(
                f"Stage C assists contract version {self.contract_version} has no amendment "
                "record; a pre-registered gate may not change without one"
            )
        return self

    @model_validator(mode="after")
    def _amendment_history_is_frozen(self) -> Self:
        expected = FROZEN_PHASE3_STAGE_C_ASSISTS_AMENDMENT_HISTORY.get(self.contract_version)
        if expected is None:
            return self
        actual = tuple(
            (amendment.version, amendment.candidates_evaluated_before_amendment)
            for amendment in self.amendments
        )
        if actual != expected:
            raise ValueError(
                f"Stage C assists amendment history for contract {self.contract_version} is not "
                f"the frozen record: expected {expected}, got {actual}."
            )
        return self


@functools.cache
def load_phase3_stage_c_assists_evaluation(
    path: Path | None = None,
) -> Phase3StageCAssistsEvaluationConfig:
    return Phase3StageCAssistsEvaluationConfig.model_validate(
        _read_yaml(path or config_dir() / "phase3_stage_c_assists_evaluation.yaml")
    )
