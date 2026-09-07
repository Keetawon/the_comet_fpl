"""Owner-selected, inference-only reuse of the frozen Tactical/Chance arithmetic.

No fit function or historical evaluation is called. The terminal retained parameters
are chosen by time, not by score. Current state uses only strictly known EPL evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from fpl.artifacts.fixture_environment import FixtureEnvironment, TeamEnvironment
from fpl.features.pit import AsOf
from fpl.football_configuration import FootballEnvironmentConfig
from fpl.storage.sdp_runtime import SdpHealthError, SdpState, SdpStateRow
from fpl.validate.chance_creation import (
    MAX_GOALS,
    QUALITY_CEILING,
    QUALITY_FLOOR,
    RATE_FLOOR,
    FractionalPoissonMeanModel,
)
from fpl.validate.metrics import Distribution, poisson_pmf
from fpl.validate.tactical_matchup import _prediction
from fpl.validate.tactical_math import RidgeModel, Scaler
from fpl.validate.tactical_state import DIMENSIONS, current_state


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def _scaler(value: dict[str, Any]) -> Scaler:
    means, scales = tuple(value["means"]), tuple(value["scales"])
    if (
        len(means) != len(scales)
        or any(not math.isfinite(v) for v in (*means, *scales))
        or min(scales) <= 0
    ):
        raise ValueError("invalid frozen scaler")
    return Scaler(means, scales)


def _mean_model(value: dict[str, Any]) -> FractionalPoissonMeanModel:
    return FractionalPoissonMeanModel(
        scaler=_scaler(value["scaler"]),
        coefficients=tuple(value["coefficients"]),
        penalty=value["penalty"],
        training_rows=value["training_rows"],
        iterations=value["iterations"],
        objective=value["objective"],
        final_gradient=tuple(value["final_gradient"]),
        final_newton_step=tuple(value["final_newton_step"]),
        diagnostics=(),
    )


@dataclass(frozen=True)
class FrozenSdpModel:
    payload: dict[str, Any]
    sha256: str
    style: list[RidgeModel | None]
    volume: FractionalPoissonMeanModel
    quality: FractionalPoissonMeanModel

    @classmethod
    def load(
        cls, root: Path, config: FootballEnvironmentConfig, cutoff: datetime
    ) -> FrozenSdpModel:
        body = (root / config.frozen_parameters).read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != config.frozen_parameters_sha256:
            raise SdpHealthError("SDP_SCHEMA_FALLBACK", "frozen model artifact hash mismatch")
        value = json.loads(body)
        known = datetime.fromisoformat(value["known_at"])
        AsOf(known)
        if known > cutoff:
            raise SdpHealthError("SDP_MISSING_FALLBACK", "model was not known at prediction cutoff")
        for name, expected in value["frozen_source_sha256"].items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
                raise SdpHealthError(
                    "SDP_SCHEMA_FALLBACK", f"frozen inference source changed: {name}"
                )
        styles: list[RidgeModel | None] = []
        for name in DIMENSIONS:
            m = value["style_fits"][name]["model"]
            styles.append(
                RidgeModel(
                    _scaler(m["scaler"]),
                    tuple(tuple(row) for row in m["coefficients"]),
                    m["penalty"],
                    m["training_rows"],
                )
            )
        return cls(
            value,
            digest,
            styles,
            _mean_model(value["stage_fits"]["volume"]["model"]),
            _mean_model(value["stage_fits"]["quality"]["model"]),
        )

    def predict(
        self,
        history: Sequence[SdpStateRow],
        *,
        season: str,
        gw: int,
        fixture: int,
        kickoff: datetime,
        cutoff: datetime,
        home_code: int,
        away_code: int,
        incumbent: dict[tuple[int, int], Distribution],
    ) -> FixtureEnvironment:
        # The frozen pure function reads structural identity/time/values only. Keep the
        # production record's distinct type and actual provenance; instantiate no retrospective
        # observation/capability. Its historical nominal annotation cannot describe this adapter.
        states = [
            current_state(cast(Any, history), code, season, cutoff, gw)
            for code in (home_code, away_code)
        ]
        predictions = [
            _prediction(states[i], states[1 - i], i == 0, self.style)[1] for i in range(2)
        ]
        rates = []
        shots = []
        xgs = []
        for i, code in enumerate((home_code, away_code)):
            own = math.fsum(j * p for j, p in enumerate(incumbent[fixture, code]))
            other = math.fsum(
                j * p for j, p in enumerate(incumbent[fixture, (away_code, home_code)[i]])
            )
            values = (*predictions[i], *predictions[1 - i])
            if any(v is None for v in values) or min(own, other) <= 0:
                raise SdpHealthError("SDP_INCOMPLETE_FALLBACK", "tactical state unavailable")
            x = [
                *[float(v) for v in values if v is not None],
                float(i == 0),
                math.log(own),
                math.log(other),
            ]
            volume = self.volume.predict_mean(x, self.payload["stage_fits"]["volume"]["anchor"])
            quality = self.quality.predict_mean(x, self.payload["stage_fits"]["quality"]["anchor"])
            xg = volume * max(QUALITY_FLOOR, min(QUALITY_CEILING, quality))
            rate = max(RATE_FLOOR, xg * self.payload["conversion_fit"]["conversion"])
            shots.append(volume)
            xgs.append(xg)
            rates.append(rate)
        pmfs = [poisson_pmf(rate, max_goals=MAX_GOALS) for rate in rates]
        means = [math.fsum(j * p for j, p in enumerate(pmf)) for pmf in pmfs]
        sides = []
        for i, code in enumerate((home_code, away_code)):
            precision = predictions[i][0]
            opponent_precision = predictions[1 - i][0]
            sides.append(
                TeamEnvironment(
                    team_code=code,
                    was_home=i == 0,
                    goal_distribution=pmfs[i],
                    expected_goals=means[i],
                    expected_goals_against=means[1 - i],
                    expected_shots=shots[i],
                    expected_shots_against=shots[1 - i],
                    # SOT is a context projection from the frozen tactical precision forecast.
                    expected_shots_on_target=shots[i] * precision
                    if precision is not None
                    else None,
                    expected_shots_on_target_against=shots[1 - i] * opponent_precision
                    if opponent_precision is not None
                    else None,
                    expected_possession=predictions[i][2],
                    predicted_xg=xgs[i],
                    tactical_context=dict(zip(DIMENSIONS, predictions[i], strict=True)),
                    opponent_tactical_context=dict(
                        zip(DIMENSIONS, predictions[1 - i], strict=True)
                    ),
                    cold_start=not any(r.season == season and r.team_code == code for r in history),
                    signal_coverage={"goals": True, "shots": True, "expected_goals": True},
                )
            )
        return FixtureEnvironment(
            season,
            fixture,
            gw,
            kickoff,
            sides[0],
            sides[1],
            engine="sdp_v2",
            provenance={"model_sha256": self.sha256, "cutoff": cutoff.isoformat()},
        )


def select_environments(
    *,
    state: SdpState,
    model: FrozenSdpModel | None,
    model_failure: str | None,
    cutoff: datetime,
    season: str,
    schedule: pl.DataFrame,
    team_map: dict[int, int],
    incumbent: dict[tuple[int, int], Distribution],
) -> tuple[dict[tuple[int, int], Distribution], dict[str, Any]]:
    AsOf(cutoff)
    chosen = dict(incumbent)
    decisions: list[dict[str, Any]] = []
    # Defence in depth at the selector boundary, even for an in-process caller.
    safe_rows = [
        r
        for r in state.rows
        if r.kickoff < cutoff and datetime.fromisoformat(r.provenance["known_at"]) <= cutoff
    ]
    valid_keys = {(r.season, r.fixture, r.team_code) for r in safe_rows}
    for target in schedule.filter(pl.col("was_home")).sort("fixture").iter_rows(named=True):
        fixture, gw = int(target["fixture"]), int(target["gw"])
        home, away = team_map.get(target["team_id"]), team_map.get(target["opponent_team_id"])
        reason = model_failure or state.global_failure
        if home is None or away is None or home == away:
            reason = "SDP_IDENTITY_FALLBACK"
        history = [r for r in safe_rows if not (r.season == season and r.gw == gw)]
        if reason is None:
            for code in (home, away):
                required = sorted(
                    (
                        (key, time)
                        for key, time in state.expected.items()
                        if key[0] == season and key[2] == code and time < cutoff
                    ),
                    key=lambda item: (item[1], item[0]),
                    reverse=True,
                )[:5]
                for key, _ in required:
                    if key not in valid_keys:
                        reason = state.failures.get(key[:2], "SDP_MISSING_FALLBACK")
                        break
                if reason:
                    break
        if reason is None and not history:
            reason = "SDP_MISSING_FALLBACK"
        decision: dict[str, Any] = {
            "season": season,
            "gw": gw,
            "fixture": fixture,
            "home_team_code": home,
            "away_team_code": away,
            "incumbent_goal_pmfs": {
                str(code): incumbent[fixture, code]
                for code in (home, away)
                if code is not None and (fixture, code) in incumbent
            },
        }
        environment = None
        if reason is None and model is not None and home is not None and away is not None:
            try:
                environment = model.predict(
                    history,
                    season=season,
                    gw=gw,
                    fixture=fixture,
                    kickoff=target["kickoff_time"],
                    cutoff=cutoff,
                    home_code=home,
                    away_code=away,
                    incumbent=incumbent,
                )
            except (ValueError, KeyError, OverflowError) as error:
                reason = (
                    error.reason if isinstance(error, SdpHealthError) else "SDP_SCHEMA_FALLBACK"
                )
                decision["detail"] = str(error)
        if environment is not None:
            reason = "SDP_PRIMARY"
            for side in (environment.home, environment.away):
                chosen[fixture, side.team_code] = side.goal_distribution
            decision["environment"] = asdict(environment)
        decision["selector"] = reason or "SDP_MISSING_FALLBACK"
        decisions.append(decision)
    counts = Counter(d["selector"] for d in decisions)
    versions = {canonical(r.provenance): r.provenance for r in safe_rows}
    return chosen, {
        "schema_version": 1,
        "cutoff": cutoff.isoformat(),
        "primary": "sdp_v2",
        "fallback": "trailing_goals_attack_defence",
        "decisions": decisions,
        "model_sha256": model.sha256 if model else None,
        "model_known_at": model.payload["known_at"] if model else None,
        "model_version": model.payload["model_version"] if model else None,
        "source_versions": [versions[key] for key in sorted(versions)],
        "selector_counts_team_predictions": {k: 2 * v for k, v in sorted(counts.items())},
        "health": {
            "matches_expected": len({key[:2] for key in state.expected}),
            "matches_valid": sum(key[0] == season for key in valid_keys) // 2,
            "source_rows_valid_all_seasons": len(valid_keys),
            "current_match_failures": {
                str(key): value for key, value in sorted(state.failures.items()) if key[0] == season
            },
            "matches_using_fallback": len(decisions) - counts["SDP_PRIMARY"],
            "schema_validation_failures": sum(
                v == "SDP_SCHEMA_FALLBACK" for v in state.failures.values()
            )
            + int(state.global_failure == "SDP_SCHEMA_FALLBACK"),
            "identity_failures": sum(v == "SDP_IDENTITY_FALLBACK" for v in state.failures.values())
            + int(state.global_failure == "SDP_IDENTITY_FALLBACK"),
            "latest_completed_match": max(state.expected.values(), default=None),
            "latest_sdp_known_at": max((r.provenance["known_at"] for r in safe_rows), default=None),
            "diagnostics": state.diagnostics,
        },
    }
