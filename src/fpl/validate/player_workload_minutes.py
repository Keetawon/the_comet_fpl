"""Bounded retrospective workload/role correction to the CURRENT minutes PMF.

Pure development capability: no database, I/O, role fitting, minutes refitting,
prospective flag or formal scoring. Inputs carry prequential source provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, cast

from fpl.validate.competitive_workload_view import (
    CompetitiveFixtureKey,
    ObservedParticipationSnapshot,
)
from fpl.validate.minutes_baselines import MinutesDistribution
from fpl.validate.player_role_history import (
    EVIDENCE_CLASS as ROLE_EVIDENCE,
)
from fpl.validate.player_role_history import (
    NAME as ROLE_NAME,
)
from fpl.validate.player_role_history import RoleBatchForecast, RoleTarget
from fpl.validate.retrospective_minutes_proxy import EVIDENCE_CLASS as CONTROL_EVIDENCE
from fpl.validate.retrospective_minutes_proxy import NAME as CONTROL_NAME

if TYPE_CHECKING:
    from fpl.validate.development_reference_components import (
        ReferenceMinutesRow,
        ValidatedMinutesControlFold,
    )

NAME: Final = "retrospective_workload_role_minutes_offset_v1"
EVIDENCE_CLASS: Final = "retrospective_workload_role_and_archive_price_proxy_development"
WORKLOAD_EVIDENCE: Final = "retrospective_observed_participation_lower_bound_development"
RIDGE: Final = 1.0
STEP_SIZE: Final = 2.0 / 3.0
MAX_ITERATIONS: Final = 200
GRADIENT_TOLERANCE: Final = 1e-10
MINIMUM_PRIOR_BATCHES: Final = 8
MINIMUM_PRIOR_ROWS: Final = 200
WORKLOAD_HOURS: Final = 168
VOLUME_CAP_MINUTES: Final = 180.0
STAGE_B_MINIMUM_FOLDS: Final = 181
type Features = tuple[float, float, float, float]
type Coefficients = tuple[Features, Features, Features]
ZERO_COEFFICIENTS: Final[Coefficients] = ((0.0,) * 4,) * 3


def _aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("minutes prediction/source cutoffs must be timezone aware")


def _hash(value: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("prequential artifact SHA256 is required")


def _pmf(value: Sequence[float]) -> None:
    if len(value) != 4 or any(isinstance(p, bool) or not math.isfinite(p) or p < 0 for p in value):
        raise ValueError("four finite nonnegative probabilities required")
    if not math.isclose(math.fsum(value), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("categorical probability mass must be one")


def _key(target: RoleTarget) -> tuple[str, int, int, int, int, datetime, datetime]:
    return (
        target.season,
        target.gw,
        target.fixture,
        target.code,
        target.team_code,
        target.kickoff,
        target.as_of,
    )


@dataclass(frozen=True, slots=True)
class PrequentialMinutesControl:
    """One already generated cache PMF, not a request to refit the minutes model."""

    target: RoleTarget
    probabilities: MinutesDistribution
    maximum_prior_event: datetime | None
    manifest_sha256: str
    fold_sha256: str
    cold_start: bool
    price_proxy_dependent: bool
    selector_provenance_json: str
    comparator: str = CONTROL_NAME
    evidence_class: str = CONTROL_EVIDENCE

    def __post_init__(self) -> None:
        if type(self.target) is not RoleTarget:
            raise ValueError("exact outcome-free typed target required")
        if type(self.probabilities) is not tuple:
            raise ValueError("immutable cached probability tuple required")
        _pmf(self.probabilities)
        _hash(self.manifest_sha256)
        _hash(self.fold_sha256)
        if self.comparator != CONTROL_NAME or self.evidence_class != CONTROL_EVIDENCE:
            raise ValueError("only the frozen retrospective current-selector control is accepted")
        if type(self.cold_start) is not bool or type(self.price_proxy_dependent) is not bool:
            raise ValueError("cold/proxy status must be explicit booleans")
        if self.price_proxy_dependent and not self.cold_start:
            raise ValueError("established own minutes cannot use the cold-price proxy")
        if not self.selector_provenance_json:
            raise ValueError("original selector/price lineage is required")
        if self.maximum_prior_event is not None:
            _aware(self.maximum_prior_event)
            if self.maximum_prior_event >= self.target.as_of:
                raise ValueError("control fit contains target/future observations")


@dataclass(frozen=True, slots=True)
class WorkloadMinutesInput:
    control: PrequentialMinutesControl
    workload: ObservedParticipationSnapshot | None
    role_batch: RoleBatchForecast | None
    # Exact verified SDP identity and COMPLETE target-GW crosswalk, not pulse_id.
    target_provider_fixture: CompetitiveFixtureKey | None
    target_gw_provider_fixtures: frozenset[CompetitiveFixtureKey]


def control_from_cache(
    fold: ValidatedMinutesControlFold, row: ReferenceMinutesRow
) -> PrequentialMinutesControl:
    """Pure bridge from an already fully validated reference, never load/refit the cache."""
    if row not in fold.rows:
        raise ValueError("row does not belong to the validated minutes fold")
    t = row.target
    metadata = json.loads(fold.metadata_json)
    maximum = metadata["maximum_prior_kickoff"]
    return PrequentialMinutesControl(
        RoleTarget(
            t.season,
            t.gw,
            t.fixture,
            t.code,
            row.team_code,
            t.kickoff_time,
            fold.as_of,
            f"minutes-cache:{fold.manifest_sha256}:{fold.fold_sha256}",
        ),
        row.minutes,
        None if maximum is None else datetime.fromisoformat(maximum),
        fold.manifest_sha256,
        fold.fold_sha256,
        row.cold_start,
        row.price_proxy_dependent,
        row.selector_provenance_json,
    )


@dataclass(frozen=True, slots=True)
class WorkloadMinutesObservation:
    """Label kept outside the predictor object; bins follow frozen Stage B order."""

    predictors: WorkloadMinutesInput
    observed_bin: int

    def __post_init__(self) -> None:
        if type(self.predictors) is not WorkloadMinutesInput:
            raise ValueError("typed outcome-free predictors required")
        if type(self.observed_bin) is not int or self.observed_bin not in range(4):
            raise ValueError("observed minutes label must be one of four fixed bins")


@dataclass(frozen=True, slots=True)
class WorkloadFeatureEvidence:
    features: Features | None
    fallback_reason: str | None
    witnessed_nominal_minutes_lower_bound: float | None
    role_probabilities: Features | None
    role_source_sha256: str | None
    maximum_workload_kickoff: datetime | None
    source_versions: tuple[tuple[str, str, str, str, str], ...]
    completion_time_proxy: bool
    unknown_workload_reasons: tuple[str, ...]


def _fallback(reason: str) -> WorkloadFeatureEvidence:
    return WorkloadFeatureEvidence(None, reason, None, None, None, None, (), False, ())


def workload_role_features(inputs: WorkloadMinutesInput) -> WorkloadFeatureEvidence:
    """Validate existing prequential sources; NEVER infer zero workload or exact rest."""
    if (
        type(inputs) is not WorkloadMinutesInput
        or type(inputs.control) is not PrequentialMinutesControl
    ):
        raise ValueError("only explicitly retrospective typed inputs are accepted")
    control, target = inputs.control, inputs.control.target
    if control.cold_start:
        return _fallback("cold_start_exact_control")
    if any(p == 0 for p in control.probabilities):
        return _fallback("control_support_zero_exact_control")
    fixture = inputs.target_provider_fixture
    if fixture is None:
        return _fallback("target_provider_identity_unavailable")
    if (
        fixture not in inputs.target_gw_provider_fixtures
        or any(type(k) is not CompetitiveFixtureKey for k in inputs.target_gw_provider_fixtures)
        or any(
            k.provider != "pl_sdp" or k.competition_id != 8 or k.season != target.season
            for k in inputs.target_gw_provider_fixtures
        )
    ):
        raise ValueError("complete target-GW PL crosswalk/exclusion is inconsistent")
    workload, roles = inputs.workload, inputs.role_batch
    if workload is None:
        return _fallback("positive_workload_unavailable")
    if roles is None:
        return _fallback("prequential_role_forecast_unavailable")
    if type(workload) is not ObservedParticipationSnapshot or type(roles) is not RoleBatchForecast:
        raise ValueError("wrong workload/role evidence capability")
    if (
        workload.code != target.code
        or workload.identity.code != target.code
        or workload.as_of != target.as_of
        or workload.evidence_class != WORKLOAD_EVIDENCE
        or workload.promotion_permitted
        or not workload.identity.source_identity
        or isinstance(workload.identity.provider_player_id, bool)
        or workload.identity.provider_player_id <= 0
        or not workload.scope_team_codes
        or workload.excluded_target_gw_fixtures != inputs.target_gw_provider_fixtures
    ):
        raise ValueError("workload identity/cutoff/evidence/exclusion contradicts target")
    if (roles.season, roles.gw, roles.as_of) != (target.season, target.gw, target.as_of):
        raise ValueError("role forecast is not from the historical target-GW cutoff")
    if roles.name != ROLE_NAME or roles.evidence_class != ROLE_EVIDENCE:
        raise ValueError("role forecaster identity/evidence differs")
    _hash(roles.source_rows_sha256)
    matched = [r for r in roles.predictions if _key(r.target) == _key(target)]
    if len(matched) != 1:
        raise ValueError("role forecast target identity missing or duplicated")
    role = matched[0]
    if role.evidence_class != ROLE_EVIDENCE or role.promotion_permitted:
        raise ValueError("role prediction evidence differs")
    if role.maximum_prior_event is not None and role.maximum_prior_event >= target.as_of:
        raise ValueError("in-sample/future role training data is forbidden")
    for source in role.recent_sources:
        if (
            source.code != target.code
            or source.team_code != target.team_code
            or source.kickoff >= target.as_of
            or source.completed is not True
            or (
                source.competition_id == 8
                and (source.season, source.gw) == (target.season, target.gw)
            )
        ):
            raise ValueError("target-GW/future/other-club role source is forbidden")
        if any(
            t is not None and t >= target.as_of
            for t in (source.max_event_at, source.verified_end_at)
        ):
            raise ValueError("role source had not ended at its forecast cutoff")
        if source.verified_end_at is None and source.kickoff + timedelta(hours=6) >= target.as_of:
            raise ValueError("role completion lacks the six-hour development margin")
        if source.provider_player_id != workload.identity.provider_player_id:
            raise ValueError("role/workload provider player crosswalk contradicts stable identity")
    _pmf(role.probabilities)
    if not role.witnessed_current_club_spell or role.recent_measured_starts == 0:
        return _fallback("role_history_cold_exact_control")
    if role.recent_measured_starts != len(role.recent_sources) or role.maximum_prior_event is None:
        raise ValueError("role history count/max-event provenance is inconsistent")
    windows = [w for w in workload.windows if w.hours == WORKLOAD_HOURS]
    if len(windows) != 1:
        raise ValueError("exactly one seven-day lower-bound workload window required")
    window = windows[0]
    nominal = window.nominal_minutes_lower_bound
    if nominal is None or not window.witnessed_fixtures:
        return _fallback("positive_workload_unavailable")
    if isinstance(nominal, bool) or not math.isfinite(nominal) or nominal < 0:
        raise ValueError("workload nominal lower bound must remain measured nonnegative volume")
    selected = {v.fixture.key: v for v in workload.selected_versions}
    if len(selected) != len(workload.selected_versions) or len(
        set(window.witnessed_fixtures)
    ) != len(window.witnessed_fixtures):
        raise ValueError("duplicate workload revision/fixture")
    measured = []
    versions = []
    kickoffs = []
    completion_proxy = False
    for key in window.witnessed_fixtures:
        if key in inputs.target_gw_provider_fixtures or key not in selected:
            raise ValueError("target-GW or unretained workload observation")
        version = selected[key]
        _hash(version.payload_sha256)
        _aware(version.capture_known_at)
        _aware(version.interpretation_known_at)
        if not version.capture_id or not version.interpretation_id:
            raise ValueError("original capture/interpretation identity required")
        kickoff = version.fixture.kickoff
        if not target.as_of - timedelta(hours=WORKLOAD_HOURS) <= kickoff < target.as_of:
            raise ValueError("workload observation is outside the pre-target seven-day window")
        if not version.capture_complete or version.fixture.completed is not True or version.errors:
            raise ValueError("workload witness is not a complete validated match")
        if any(
            t is not None and t >= target.as_of
            for t in (version.maximum_retained_event_timestamp, version.verified_end_at)
        ):
            raise ValueError("workload source had not ended at cutoff")
        if version.verified_end_at is None and kickoff + timedelta(hours=6) >= target.as_of:
            raise ValueError("workload completion lacks the six-hour development margin")
        observations = [r for r in version.observations if r.code == target.code]
        if len(observations) != 1:
            raise ValueError("workload player identity missing/duplicated in witnessed fixture")
        row = observations[0]
        if (
            row.provider_player_id != workload.identity.provider_player_id
            or row.appeared is not True
            or row.errors
        ):
            raise ValueError("exact positive workload player witness is inconsistent")
        if row.nominal_minutes is not None:
            if (
                isinstance(row.nominal_minutes, bool)
                or not math.isfinite(row.nominal_minutes)
                or not 0 <= row.nominal_minutes <= 120
            ):
                raise ValueError("nominal source minutes out of range")
            measured.append(row.nominal_minutes)
        kickoffs.append(kickoff)
        completion_proxy |= version.verified_end_at is None
        versions.append(
            (
                version.capture_id,
                version.payload_sha256,
                version.capture_known_at.isoformat(),
                version.interpretation_id,
                version.interpretation_known_at.isoformat(),
            )
        )
    if not measured or math.fsum(measured) != nominal:
        raise ValueError("lower-bound aggregate differs from its actual measured source rows")
    if nominal == 0:
        return _fallback("witnessed_zero_nominal_volume_exact_control")
    volume = min(nominal / VOLUME_CAP_MINUTES, 1.0)
    features = cast(Features, tuple(volume * p for p in role.probabilities))
    return WorkloadFeatureEvidence(
        features,
        None,
        nominal,
        role.probabilities,
        roles.source_rows_sha256,
        max(kickoffs),
        tuple(sorted(versions)),
        completion_proxy,
        window.unknown_reasons,
    )


def _probabilities(
    control: MinutesDistribution, x: Features, beta: Coefficients
) -> MinutesDistribution:
    logits = [math.log(control[0])]
    logits.extend(
        math.log(control[k + 1]) + math.fsum(b * f for b, f in zip(row, x, strict=True))
        for k, row in enumerate(beta)
    )
    largest = max(logits)
    weights = [math.exp(v - largest) for v in logits]
    total = math.fsum(weights)
    return cast(MinutesDistribution, tuple(w / total for w in weights))


def _objective_gradient(
    rows: Sequence[tuple[Features, MinutesDistribution, int]], beta: Coefficients
) -> tuple[float, Coefficients]:
    pmfs = [_probabilities(p, x, beta) for x, p, _y in rows]
    n = len(rows)
    objective = (
        math.fsum(-math.log(pmf[y]) for pmf, (_x, _p, y) in zip(pmfs, rows, strict=True)) / n
    )
    objective += RIDGE / 2 * math.fsum(b * b for row in beta for b in row)
    gradient = cast(
        Coefficients,
        tuple(
            tuple(
                RIDGE * beta[k][j]
                + math.fsum(
                    (pmf[k + 1] - float(y == k + 1)) * x[j]
                    for pmf, (x, _p, y) in zip(pmfs, rows, strict=True)
                )
                / n
                for j in range(4)
            )
            for k in range(3)
        ),
    )
    return objective, gradient


@dataclass(frozen=True, slots=True)
class MinutesCorrectionFit:
    season: str
    gw: int
    as_of: datetime
    coefficients: Coefficients
    eligible_rows: int
    eligible_batches: int
    prior_rows: int
    fallback_counts: tuple[tuple[str, int], ...]
    maximum_prior_target_kickoff: datetime | None
    training_rows_sha256: str
    iterations: int
    final_gradient_inf: float
    objective_trace: tuple[float, ...]
    enabled: bool
    evidence_class: str = EVIDENCE_CLASS
    identity: str = NAME
    promotion_permitted: bool = False
    synthesis_eligible: bool = False


def fit_minutes_correction(
    history: Sequence[WorkloadMinutesObservation], *, season: str, gw: int, as_of: datetime
) -> MinutesCorrectionFit:
    """One immutable pre-GW fit over prior PREQUENTIAL predictions, never random splits."""
    _aware(as_of)
    if not season or isinstance(gw, bool) or gw <= 0:
        raise ValueError("explicit target season/GW required")
    if any(type(row) is not WorkloadMinutesObservation for row in history):
        raise ValueError("only typed prequential minutes observations may train correction")
    prior = sorted(
        (
            r
            for r in history
            if r.predictors.control.target.kickoff + timedelta(hours=6) < as_of
            and (r.predictors.control.target.season, r.predictors.control.target.gw) != (season, gw)
        ),
        key=lambda r: (r.predictors.control.target.kickoff, _key(r.predictors.control.target)),
    )
    identities = set()
    batch_cutoffs: dict[tuple[str, int], datetime] = {}
    batch_clubs: dict[tuple[str, int, int], int] = {}
    rows = []
    lineage = []
    batches = set()
    fallbacks: Counter[str] = Counter()
    for row in prior:
        target = row.predictors.control.target
        identity = target.season, target.fixture, target.code
        if identity in identities:
            raise ValueError("duplicate historical player-fixture label")
        identities.add(identity)
        batch = target.season, target.gw
        if batch in batch_cutoffs and batch_cutoffs[batch] != target.as_of:
            raise ValueError("all upstream predictions in one GW must share one pre-GW cutoff")
        batch_cutoffs[batch] = target.as_of
        player_batch = target.season, target.gw, target.code
        if player_batch in batch_clubs and batch_clubs[player_batch] != target.team_code:
            raise ValueError("historical same-GW stable club identity contradicts")
        batch_clubs[player_batch] = target.team_code
        if target.as_of >= as_of:
            raise ValueError("historical upstream prediction was not generated before outer cutoff")
        evidence = workload_role_features(row.predictors)
        if evidence.features is None:
            fallbacks[evidence.fallback_reason or "unavailable"] += 1
            continue
        rows.append((evidence.features, row.predictors.control.probabilities, row.observed_bin))
        batches.add(batch)
        lineage.append(
            {
                "control": asdict(row.predictors.control),
                "features": asdict(evidence),
                "observed_bin": row.observed_bin,
            }
        )
    encoded = json.dumps(
        lineage, default=str, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    enabled = len(rows) >= MINIMUM_PRIOR_ROWS and len(batches) >= MINIMUM_PRIOR_BATCHES
    beta = ZERO_COEFFICIENTS
    trace = []
    iterations, norm = 0, 0.0
    if enabled:
        for iterations in range(MAX_ITERATIONS + 1):
            objective, gradient = _objective_gradient(rows, beta)
            norm = max(abs(v) for row in gradient for v in row)
            if not math.isfinite(objective) or not math.isfinite(norm):
                raise ValueError("nonfinite categorical offset optimization")
            trace.append(objective)
            if norm <= GRADIENT_TOLERANCE:
                break
            if iterations == MAX_ITERATIONS:
                raise ValueError("categorical offset solver did not converge under frozen policy")
            beta = cast(
                Coefficients,
                tuple(
                    tuple(b - STEP_SIZE * g for b, g in zip(br, gr, strict=True))
                    for br, gr in zip(beta, gradient, strict=True)
                ),
            )
    return MinutesCorrectionFit(
        season,
        gw,
        as_of,
        beta,
        len(rows),
        len(batches),
        len(prior),
        tuple(sorted(fallbacks.items())),
        max((r.predictors.control.target.kickoff for r in prior), default=None),
        hashlib.sha256(encoded).hexdigest(),
        iterations,
        norm,
        tuple(trace),
        enabled,
    )


@dataclass(frozen=True, slots=True)
class WorkloadMinutesPrediction:
    target: RoleTarget
    probabilities: MinutesDistribution
    control_probabilities: MinutesDistribution
    feature_evidence: WorkloadFeatureEvidence
    correction_applied: bool
    fallback_reason: str | None
    training_rows_sha256: str
    price_proxy_dependent: bool
    evidence_class: str = EVIDENCE_CLASS
    promotion_permitted: bool = False


def predict_minutes_batch(
    model: MinutesCorrectionFit, inputs: Sequence[WorkloadMinutesInput]
) -> tuple[WorkloadMinutesPrediction, ...]:
    """All target-GW predictions use the same frozen fit, including separate DGW legs."""
    if (
        type(model) is not MinutesCorrectionFit
        or model.identity != NAME
        or model.evidence_class != EVIDENCE_CLASS
        or model.promotion_permitted
        or model.synthesis_eligible
    ):
        raise ValueError("only the explicit unpromoted development correction is accepted")
    if not inputs or min(r.control.target.kickoff for r in inputs) != model.as_of:
        raise ValueError("complete target-GW first-kickoff batch required")
    excluded = inputs[0].target_gw_provider_fixtures
    if any(r.target_gw_provider_fixtures != excluded for r in inputs):
        raise ValueError("all target-GW legs must exclude the same entire fixture batch")
    keys = set()
    clubs: dict[int, int] = {}
    result = []
    for item in inputs:
        target, control = item.control.target, item.control.probabilities
        if (target.season, target.gw, target.as_of) != (model.season, model.gw, model.as_of):
            raise ValueError("every target-GW fixture must use the exact frozen pre-GW fit")
        key = target.fixture, target.code
        if key in keys:
            raise ValueError("duplicate target player-fixture")
        keys.add(key)
        if target.code in clubs and clubs[target.code] != target.team_code:
            raise ValueError("target-GW stable club identity contradicts")
        clubs[target.code] = target.team_code
        evidence = workload_role_features(item)
        reason = evidence.fallback_reason
        if not model.enabled:
            reason = reason or "insufficient_prior_eight_batches_or_200_rows"
        elif model.coefficients == ZERO_COEFFICIENTS:
            reason = reason or "zero_correction_exact_control"
        elif evidence.features is not None and all(
            math.fsum(b * x for b, x in zip(row, evidence.features, strict=True)) == 0
            for row in model.coefficients
        ):
            reason = reason or "zero_effective_adjustment_exact_control"
        changed = reason is None and evidence.features is not None
        probabilities = (
            _probabilities(control, evidence.features, model.coefficients)
            if changed and evidence.features is not None
            else control
        )
        _pmf(probabilities)
        result.append(
            WorkloadMinutesPrediction(
                target,
                probabilities,
                control,
                evidence,
                changed,
                reason,
                model.training_rows_sha256,
                item.control.price_proxy_dependent,
            )
        )
    return tuple(result)
