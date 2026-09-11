"""Frozen H parameters projected onto all CURRENT roster keepers, without fitting.

Reads retained evidence only. Target labels/appearance never enter the returned
projector; presence in H's scored cohort is solely an exact reproduction witness.
The formal J runner owns component acceptance and complete reference-cache pins.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.gk_saves_v1 import NAME as CURRENT_SAVES_NAME
from fpl.models.points_composition import ComponentDistributions, FixturePlayer
from fpl.types import Position
from fpl.validate.current_component_reference_cache import _pmf as _decode_pmf
from fpl.validate.development_reference_components import (
    NAME as REFERENCE_NAME,
)
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    ReferencePlayerComponents,
)
from fpl.validate.metrics import Distribution
from fpl.validate.minutes_baselines import TargetRow
from fpl.validate.player_saves_opportunity import (
    EVIDENCE_CLASS,
    MINIMUM_MEASURED_SIDES,
    NAME,
    OosShotForecast,
    PooledShotPrecision,
    predict_saves,
)
from fpl.validate.retrospective_minutes_proxy import EVIDENCE_CLASS as REFERENCE_EVIDENCE_CLASS

H_RESULT_SHA256 = "79e61b51951e04795c8acb34a3e17db6e1fa417ed3717f7014b40d71ecf39ed2"
PHASE_A_SHA256 = "f4cc595384102112ba2c41f118396d4176a6f7000a6f3c1753b5edf1a1ae952f"
H_ROWS_BY_SEASON = {"2023-24": 776, "2024-25": 770, "2025-26": 767}
H_FOLDS = 114
PHASE_A_ROWS = 3800
PHASE_A_FOLDS = 189
_MARGIN = timedelta(hours=6)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    _require(stamp.utcoffset() is not None, "aware original evidence timestamp required")
    return stamp


def _maximum(values: list[str | None]) -> datetime | None:
    return max((_time(v) for v in values if v is not None), default=None)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path, expected: str, sources: dict[str, str]) -> dict[str, Any]:
    body = path.read_bytes()
    _require(hashlib.sha256(body).hexdigest() == expected, f"frozen source SHA256 differs: {path}")
    sources[str(path.resolve())] = expected
    raw = json.loads(body)
    _require(isinstance(raw, dict), "retained artifact must be an object")
    return dict(raw)


def _pmf(raw: Any) -> Distribution:
    result = _decode_pmf(raw, 11)
    _require(
        math.isclose(math.fsum(result), 1, rel_tol=0, abs_tol=1e-12), "saves PMF unit mass differs"
    )
    return result


@dataclass(frozen=True, slots=True)
class _ShotSource:
    forecast: OosShotForecast
    was_home: bool


@dataclass(frozen=True, slots=True)
class _SavedFold:
    precision: PooledShotPrecision
    save_fraction: float


@dataclass(frozen=True, slots=True)
class _Witness:
    team_code: int
    incumbent: Distribution
    candidate: Distribution


@dataclass(frozen=True, slots=True)
class SavesProjection:
    """Outcome-free saved inputs; dictionaries are immutable after validation."""

    _shots: Mapping[tuple[str, int, int], _ShotSource]
    _folds: Mapping[tuple[str, int], _SavedFold]
    _witnesses: Mapping[tuple[str, int, int], _Witness]
    _source_files: Mapping[str, str]
    _provenance: Mapping[str, Any]
    _reproduction: Mapping[str, Any]

    @property
    def source_files(self) -> dict[str, str]:
        return dict(self._source_files)

    @property
    def provenance(self) -> dict[str, Any]:
        return dict(self._provenance)

    @property
    def reproduction(self) -> dict[str, Any]:
        return dict(self._reproduction)

    def project(
        self, reference: DevelopmentReferenceComponents, fixture: int
    ) -> dict[int, Distribution]:
        """Return every GK's conditional PMF for this exact fixture, including DNPs."""
        _require(
            type(reference) is DevelopmentReferenceComponents
            and reference.identity == REFERENCE_NAME
            and reference.evidence_class == REFERENCE_EVIDENCE_CLASS
            and reference.promotion_permitted is False,
            "exact retrospective CURRENT reference required",
        )
        _require(type(fixture) is int and fixture > 0, "exact fixture identity required")
        _require(
            type(reference.rows) is tuple
            and all(
                type(r) is ReferencePlayerComponents
                and type(r.target) is TargetRow
                and type(r.player) is FixturePlayer
                and type(r.player.components) is ComponentDistributions
                for r in reference.rows
            ),
            "exact outcome-free reference predictor types required",
        )
        rows = tuple(r for r in reference.rows if r.target.fixture == fixture)
        _require(bool(rows), "fixture absent from reference")
        _require(len({r.target.code for r in rows}) == len(rows), "duplicate fixture roster code")
        teams = {r.target.team_id: r.team_code for r in rows}
        _require(
            len(teams) == len(set(teams.values())) == 2, "both declared fixture clubs required"
        )
        saved = self._folds[reference.season, reference.gw]
        _require(saved.precision.as_of == reference.as_of, "reference and saved fold cutoff differ")
        _require(
            json.loads(reference.diagnostics_json)["component_parameters"][CURRENT_SAVES_NAME][
                "save_rate"
            ]
            == saved.save_fraction,
            "CURRENT and H saved league save fractions differ",
        )
        result = {}
        for row in rows:
            t, c = row.target, row.player.components
            _require(
                (t.season, t.gw) == (reference.season, reference.gw)
                and t.position is c.position
                and type(t.position) is Position
                and type(t.code) is int
                and t.code == row.player.code
                and teams[t.team_id] == row.team_code
                and t.opponent_team_id in teams
                and t.team_id != t.opponent_team_id,
                "reference player/fixture/club identity differs",
            )
            source = self._shots[t.season, fixture, row.team_code]
            forecast = source.forecast
            _require(
                forecast.gw == t.gw
                and forecast.kickoff == t.kickoff_time
                and forecast.as_of == reference.as_of
                and forecast.attacking_team_code == teams[t.opponent_team_id]
                and forecast.defending_team_code == row.team_code
                and type(t.was_home) is bool
                and source.was_home is not t.was_home,
                "CURRENT roster and OOS opponent/venue/kickoff differ",
            )
            if t.position is not Position.GK:
                continue
            _require(c.saves is not None, "CURRENT keeper saves PMF missing")
            assert c.saves is not None
            _pmf(c.saves)
            predicted = predict_saves(
                forecast, saved.precision, save_fraction=saved.save_fraction, incumbent=c.saves
            )
            # Every GK is already predicted. H cohort membership only adds a witness check.
            witness = self._witnesses.get((t.season, fixture, t.code))
            if witness is not None:
                _require(
                    witness.team_code == row.team_code
                    and witness.incumbent == c.saves
                    and witness.candidate == predicted.probabilities,
                    "retained H overlap differs at zero tolerance",
                )
            result[t.code] = predicted.probabilities
        _require(bool(result), "fixture contains no declared keeper")
        return result


def _phase_a(
    raw: dict[str, Any],
) -> tuple[dict[tuple[str, int, int], _ShotSource], dict[str, dict[str, Any]]]:
    provenance = raw["provenance"]
    _require(
        raw["completed"] is True
        and raw["promotion_permitted"] is False
        and raw["evidence_class"] == EVIDENCE_CLASS
        and provenance["clean_worktree"] is True
        and provenance["known_at_rewritten"] is False,
        "completed retrospective OOS Phase A evidence required",
    )
    records = raw["historical_chance_predictions"]
    keyed = {r["key"]: r for r in records}
    fits = {(f["season"], f["gw"]): f for f in raw["historical_fit_provenance"]}
    _require(len(records) == len(keyed) == PHASE_A_ROWS, "Phase A duplicate/missing row keys")
    _require(
        len(fits) == len(raw["historical_fit_provenance"]) == PHASE_A_FOLDS,
        "Phase A duplicate/missing fold keys",
    )
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    result = {}
    for row in records:
        key = row["season"], row["gw"]
        groups[key].append(row)
        expected = f"{row['season']}:{row['fixture']}:{row['team_code']}"
        _require(row["key"] == expected, "Phase A stable source key differs")
        opposite = keyed[f"{row['season']}:{row['fixture']}:{row['opponent_team_code']}"]
        cutoff, kickoff = _time(row["as_of"]), _time(row["kickoff_time"])
        _require(
            opposite["opponent_team_code"] == row["team_code"]
            and opposite["team_code"] != row["team_code"]
            and opposite["gw"] == row["gw"]
            and type(row["was_home"]) is bool
            and opposite["was_home"] is not row["was_home"]
            and _time(opposite["as_of"]) == cutoff
            and _time(opposite["kickoff_time"]) == kickoff
            and kickoff >= cutoff,
            "Phase A reciprocal fixture/cutoff identity differs",
        )
        _time(row["source_known_at"])  # Original later capture time stays retrospective.
        for field in ("source_capture_id", "payload_sha256"):
            value = row[field]
            _require(
                isinstance(value, str)
                and len(value) == 64
                and all(c in "0123456789abcdef" for c in value),
                "original Phase A capture identity/hash missing",
            )
        volume = fits[key]["stage_fits"]["volume"]
        maximum = _maximum(
            [
                row["maximum_state_source_event"],
                row["maximum_style_training_event"],
                volume["maximum_training_event"],
            ]
        )
        _require(maximum is None or maximum + _MARGIN < cutoff, "Phase A future upstream event")
        shots = row["predicted_shots"]
        _require(
            shots is None or (type(shots) in (int, float) and math.isfinite(shots) and shots >= 0),
            "Phase A predicted volume is invalid",
        )
        result[row["season"], row["fixture"], row["opponent_team_code"]] = _ShotSource(
            OosShotForecast(
                row["season"],
                row["gw"],
                row["fixture"],
                row["team_code"],
                row["opponent_team_code"],
                cutoff,
                kickoff,
                shots,
                maximum,
                PHASE_A_SHA256,
            ),
            row["was_home"],
        )
    _require(set(groups) == set(fits), "Phase A forecast/fold identities differ")
    for key, group in groups.items():
        fold, cutoff = fits[key], _time(fits[key]["as_of"])
        _require(
            fold["target_rows"] == len(group)
            and cutoff == min(_time(r["kickoff_time"]) for r in group)
            and all(_time(r["as_of"]) == cutoff for r in group)
            and all(
                fold[name] == 0
                for name in (
                    "event_time_violations",
                    "same_gameweek_violations",
                    "stacking_in_sample_rows",
                )
            ),
            "Phase A complete-GW temporal isolation differs",
        )
        prior = [
            r
            for r in records
            if _time(r["kickoff_time"]) < cutoff and (r["season"], r["gw"]) != key
        ]
        volume_rows = [
            r for r in prior if r["observed_shots"] is not None and r["predictors"] is not None
        ]
        volume = fold["stage_fits"]["volume"]
        _require(
            fold["prior_completed_rows"] == len(prior)
            and volume["training_rows"] == len(volume_rows)
            and volume["training_keys_sha256"] == _digest(sorted(r["key"] for r in volume_rows))
            and _maximum([volume["maximum_training_event"]])
            == _maximum([r["kickoff_time"] for r in volume_rows])
            and _maximum([volume["maximum_training_prediction_cutoff"]])
            == _maximum([r["as_of"] for r in volume_rows]),
            "Phase A frozen volume training-key provenance differs",
        )
    return result, keyed


def _precision(raw: dict[str, Any], sources: dict[str, dict[str, Any]]) -> PooledShotPrecision:
    cutoff = _time(raw["as_of"])
    key = raw["excluded_gw"]
    _require(isinstance(key, list) and len(key) == 2, "saved precision GW key malformed")
    source_keys = tuple(tuple(k) for k in raw["source_keys"])
    _require(len({k[:3] for k in source_keys}) == len(source_keys), "duplicate precision source")
    measured = []
    for source_key in source_keys:
        _require(len(source_key) == 4, "precision source key malformed")
        season, fixture, team, capture = source_key
        source = sources[f"{season}:{fixture}:{team}"]
        _require(
            source["source_capture_id"] == capture
            and _time(source["kickoff_time"]) + _MARGIN < cutoff
            and (source["season"], source["gw"]) != tuple(key),
            "saved precision source identity or target-GW/completion boundary differs",
        )
        measured.append(source)
    ordered = sorted(
        measured,
        key=lambda r: (_time(r["kickoff_time"]), r["season"], r["fixture"], r["team_code"]),
    )
    _require(measured == ordered, "saved precision source order differs")
    _require(
        type(raw["measured_sides"]) is int
        and raw["measured_sides"] == len(measured)
        and type(raw["shots"]) is int
        and type(raw["sot"]) is int
        and 0 <= raw["sot"] <= raw["shots"]
        and all(r["observed_shots"] is not None for r in measured)
        and raw["shots"] == sum(r["observed_shots"] for r in measured)
        and _maximum([raw["maximum_training_event"]])
        == _maximum([r["kickoff_time"] for r in measured]),
        "saved precision sufficient-statistic provenance differs",
    )
    expected = (
        raw["sot"] / raw["shots"]
        if len(measured) >= MINIMUM_MEASURED_SIDES and raw["shots"] > 0
        else None
    )
    _require(raw["fraction"] == expected, "saved precision ratio/fallback differs")
    return PooledShotPrecision(
        cutoff,
        (key[0], key[1]),
        raw["measured_sides"],
        raw["shots"],
        raw["sot"],
        raw["fraction"],
        _maximum([raw["maximum_training_event"]]),
        source_keys,
    )


def load_saves_projection(h_result: Path, phase_a_result: Path) -> SavesProjection:
    """Validate pinned result/fold bytes and reproduce H PMFs without fitting/scoring."""
    h_result, phase_a_result = h_result.resolve(), phase_a_result.resolve()
    files: dict[str, str] = {}
    h = _read(h_result, H_RESULT_SHA256, files)
    phase_a = _read(phase_a_result, PHASE_A_SHA256, files)
    provenance = h["provenance"]
    _require(
        h["completed"] is True
        and provenance["candidate"] == NAME
        and provenance["evidence_class"] == EVIDENCE_CLASS
        and provenance["clean_worktree"] is True
        and provenance["production_promotion"] is False
        and provenance["known_at_rewritten"] is False
        and h["promotion_permitted"] is False
        and provenance["database_sha256"] == phase_a["provenance"]["database_sha256"],
        "H complete retrospective reference provenance differs",
    )
    separate = h_result.parent / "provenance.json"
    _require(
        _read(separate, _hash_file(separate), files) == provenance,
        "H separate provenance receipt differs",
    )
    for function, name in (
        (predict_saves, "src/fpl/validate/player_saves_opportunity.py"),
        (poisson_pmf, "src/fpl/models/attacking_baselines.py"),
    ):
        path = Path(inspect.getfile(function)).resolve()
        expected = provenance["source_sha256"][name]
        _require(_hash_file(path) == expected, "frozen saves predictor source changed")
        files[str(path)] = expected
    shots, source_rows = _phase_a(phase_a)
    folds: dict[tuple[str, int], _SavedFold] = {}
    witnesses: dict[tuple[str, int, int], _Witness] = {}
    retained = []
    for entry in h["folds"]:
        path = (h_result.parent / entry["file"]).resolve()
        _require(path.parent == h_result.parent, "H fold path escapes retained directory")
        body = _read(path, entry["sha256"], files)
        precision = _precision(body["precision"], source_rows)
        key = precision.excluded_gw
        _require(
            path.name == f"{key[0]}-gw{key[1]:02d}.json"
            and key not in folds
            and len(body["rows"]) == entry["rows"] > 0,
            "H fold duplicate identity/path/count differs",
        )
        fractions = {r["save_fraction"] for r in body["rows"]}
        _require(len(fractions) == 1, "H fold must retain one unchanged save fraction")
        fraction = next(iter(fractions))
        _require(
            type(fraction) in (int, float) and math.isfinite(fraction) and 0 <= fraction <= 1,
            "H save fraction invalid",
        )
        folds[key] = _SavedFold(precision, fraction)
        for row in body["rows"]:
            source = shots[row["season"], row["fixture"], row["team_code"]]
            forecast = source.forecast
            _require(
                (row["season"], row["gw"]) == key
                and _time(row["as_of"]) == precision.as_of == forecast.as_of
                and _time(row["kickoff"]) == forecast.kickoff
                and row["was_home"] is not source.was_home
                and row["upstream_hash"] == PHASE_A_SHA256
                and row["upstream_key"]
                == f"{row['season']}:{row['fixture']}:{forecast.attacking_team_code}"
                and _maximum([row["maximum_upstream_training_event"]])
                == forecast.maximum_upstream_training_event,
                "retained H row OOS source/cutoff/identity differs",
            )
            original = row["original_capture"]
            phase_source = source_rows[row["upstream_key"]]
            _require(
                all(
                    original[k] == phase_source[k] for k in ("season", "gw", "fixture", "team_code")
                )
                and original["capture_id"] == phase_source["source_capture_id"]
                and original["payload_sha256"] == phase_source["payload_sha256"]
                and _time(original["known_at"]) == _time(phase_source["source_known_at"])
                and _time(original["kickoff"]) == _time(phase_source["kickoff_time"]),
                "retained H original source capture identity differs",
            )
            incumbent, candidate = (_pmf(row["pmfs"][arm]) for arm in ("incumbent", "candidate"))
            predicted = predict_saves(
                forecast, precision, save_fraction=fraction, incumbent=incumbent
            )
            _require(
                predicted.probabilities == candidate
                and predicted.rate == row["candidate_rate"]
                and predicted.expected_sot_faced == row["expected_sot_faced"]
                and predicted.fallback is row["fallback"],
                "retained H PMF/formula differs at zero tolerance",
            )
            tag = row["season"], row["fixture"], row["code"]
            _require(tag not in witnesses, "duplicate retained keeper witness")
            witnesses[tag] = _Witness(row["team_code"], incumbent, candidate)
        retained.extend(body["rows"])
    _require(retained == h["rows"], "H result/fold row copies differ")
    _require(
        dict(Counter(r["season"] for r in retained)) == H_ROWS_BY_SEASON,
        "H retained keeper population differs",
    )
    expected_folds = {
        (r["season"], r["gw"]) for r in source_rows.values() if r["season"] in H_ROWS_BY_SEASON
    }
    _require(
        set(folds) == expected_folds and len(folds) == H_FOLDS,
        "H complete retained fold population differs",
    )
    _require(
        _digest(sorted((r["season"], r["gw"], r["fixture"], r["code"]) for r in retained))
        == h["coverage"]["target_identity_sha256"],
        "H target identity digest differs",
    )
    return SavesProjection(
        MappingProxyType(shots),
        MappingProxyType(folds),
        MappingProxyType(witnesses),
        MappingProxyType(files),
        MappingProxyType(
            {
                "component": NAME,
                "evidence_class": EVIDENCE_CLASS,
                "h_result_sha256": H_RESULT_SHA256,
                "phase_a_result_sha256": PHASE_A_SHA256,
                "h_git_head": provenance["git_head"],
                "phase_a_git_head": phase_a["provenance"]["git_head"],
                "database_sha256": provenance["database_sha256"],
                "conditional_on_appearance": True,
                "actual_appearance_used_to_apply": False,
                "models_refitted": False,
                "known_at_rewritten": False,
                "promotion_permitted": False,
            }
        ),
        MappingProxyType(
            {
                "retained_h_rows": len(witnesses),
                "retained_h_folds": len(folds),
                "phase_a_rows": len(shots),
                "phase_a_folds": PHASE_A_FOLDS,
                "maximum_absolute_pmf_difference": 0.0,
                "absolute_tolerance": 0.0,
            }
        ),
    )
