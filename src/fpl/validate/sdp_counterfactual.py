"""Validation-only SDP input counterfactual; never historical production evidence.

The frozen model and health reader run at an actual retained evidence time. Only
their availability is counterfactually assumed; match time, FPL population,
source hashes, original knowledge timestamps and scoring arithmetic stay intact.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import polars as pl

from fpl.features.pit import AsOf
from fpl.football_configuration import load_football_environment
from fpl.models.sdp_environment import FrozenSdpModel, canonical
from fpl.storage.sdp_runtime import SdpHealthError, SdpState, load_sdp_state
from fpl.validate.metrics import Distribution

SOURCE_PATH = "src/fpl/models/sdp_environment.py"
SOURCE_SHA256 = "425365df9c5e2215ccb5705869f8777a0fe45a5780b7e49234918b6f249dd985"
MODEL_SHA256 = "043ae6ab2afef1064ce7a3d8544552b7f4fae247216daff6556257fe01f1526b"
MODEL_STATE_SHA256 = "89424cbc8f0953e2455dafe0605cfe3c0bcf56f4c9aaae62d2c3b652dec31455"
EVIDENCE_CLASS = "retrospective_development_counterfactual"
VERSION_POLICY = (
    "latest_whole_source_at_frozen_actual_evidence_time_with_unchanged_production_health;"
    "invalid_latest_never_revives_older_version;historical_event_cutoff_only"
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _state_digest(state: SdpState) -> str:
    return _digest(
        {
            "rows": [asdict(row) for row in state.rows],
            "expected": sorted((key, value) for key, value in state.expected.items()),
            "failures": sorted(state.failures.items()),
            "global_failure": state.global_failure,
            "diagnostics": state.diagnostics,
        }
    )


@dataclass(frozen=True)
class FrozenCounterfactualInputs:
    season: str
    evidence_as_of: datetime
    state: SdpState
    model: FrozenSdpModel
    source_db_sha256: str
    source_code_sha256: str = SOURCE_SHA256
    state_sha256: str = field(init=False)
    model_state_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        AsOf(self.evidence_as_of)
        if self.evidence_as_of > datetime.now(UTC):
            raise ValueError("counterfactual evidence time must be an actual past capture frontier")
        if self.source_code_sha256 != SOURCE_SHA256:
            raise ValueError("frozen SDP selector source differs")
        if len(self.source_db_sha256) != 64:
            raise ValueError("source database content hash required")
        if self.model.sha256 != MODEL_SHA256 or _digest(asdict(self.model)) != MODEL_STATE_SHA256:
            raise ValueError("only the unchanged frozen SDP model is licensed")
        known = datetime.fromisoformat(self.model.payload["known_at"])
        AsOf(known)
        if known > self.evidence_as_of:
            raise ValueError("model is unavailable at the actual evidence frontier")
        object.__setattr__(self, "state", deepcopy(self.state))
        object.__setattr__(self, "model", deepcopy(self.model))
        object.__setattr__(self, "state_sha256", _state_digest(self.state))
        object.__setattr__(self, "model_state_sha256", _digest(asdict(self.model)))

    def verify(self) -> None:
        if self.state_sha256 != _state_digest(self.state) or self.model_state_sha256 != _digest(
            asdict(self.model)
        ):
            raise ValueError("frozen counterfactual inputs changed after capture")
        source = Path(__file__).resolve().parents[3] / SOURCE_PATH
        if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
            raise ValueError("frozen SDP selector source differs")


def load_counterfactual_inputs(
    con: duckdb.DuckDBPyConnection,
    *,
    repo: Path,
    db_path: Path,
    evidence_as_of: datetime,
    season: str,
) -> FrozenCounterfactualInputs:
    """Freeze unchanged source-health output; no fit, score, timestamp edit or DB write."""
    AsOf(evidence_as_of)
    if evidence_as_of > datetime.now(UTC):
        raise ValueError("actual evidence time cannot be in the future")
    source_hash = hashlib.sha256((repo / SOURCE_PATH).read_bytes()).hexdigest()
    if source_hash != SOURCE_SHA256:
        raise ValueError("frozen SDP selector source differs")
    attached = [
        Path(row[2]).resolve() for row in con.execute("PRAGMA database_list").fetchall() if row[2]
    ]
    if db_path.resolve() not in attached:
        raise ValueError("source database path does not identify the supplied connection")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    model = FrozenSdpModel.load(repo, load_football_environment(), evidence_as_of)
    state = load_sdp_state(con, cutoff=evidence_as_of, season=season)
    if hashlib.sha256(db_path.read_bytes()).hexdigest() != before:
        raise ValueError("source database changed while freezing counterfactual inputs")
    return FrozenCounterfactualInputs(season, evidence_as_of, state, model, before, source_hash)


def _historical_state(
    inputs: FrozenCounterfactualInputs,
    strict: SdpState,
    *,
    cutoff: datetime,
    target_gw: int,
    current_fixture_gameweeks: Mapping[int, int],
) -> SdpState:
    """Preserve cutoff-known required fixtures; reconcile later SDP identity against them."""
    failures = dict(inputs.state.failures)
    expected = {}
    for key, kickoff in strict.expected.items():
        if key[0] != inputs.season or kickoff >= cutoff:
            continue
        gw = current_fixture_gameweeks.get(key[1])
        if gw is None:
            raise ValueError("required historical fixture lacks cutoff-known gameweek identity")
        if gw < target_gw:
            expected[key] = kickoff
    rows = []
    for row in inputs.state.rows:
        if row.kickoff >= cutoff:
            continue
        if row.season == inputs.season:
            gw = current_fixture_gameweeks.get(row.fixture)
            if gw is None:
                continue  # Later FPL fixture identity cannot enlarge the historical population.
            if gw >= target_gw:
                continue
            if (
                row.gw != gw
                or expected.get(row.key) != row.kickoff
                or expected.get((row.season, row.fixture, row.opponent_team_code)) != row.kickoff
            ):
                failures[row.season, row.fixture] = "SDP_IDENTITY_FALLBACK"
                continue
        known = datetime.fromisoformat(row.provenance["known_at"])
        AsOf(known)
        if known > inputs.evidence_as_of:
            raise ValueError("SDP source exceeds the frozen actual evidence frontier")
        rows.append(row)
    invalid = {key for key, reason in failures.items() if reason == "SDP_IDENTITY_FALLBACK"}
    rows = [row for row in rows if (row.season, row.fixture) not in invalid]
    prior_fixtures = {key[:2] for key in expected} | {(r.season, r.fixture) for r in rows}
    return SdpState(
        rows=rows,
        expected=expected,
        failures={key: value for key, value in failures.items() if key in prior_fixtures},
        global_failure=inputs.state.global_failure,
        diagnostics=list(inputs.state.diagnostics),
    )


def select_counterfactual_environments(
    inputs: FrozenCounterfactualInputs,
    *,
    state: SdpState,
    model: FrozenSdpModel | None,
    model_failure: str | None,
    cutoff: datetime,
    season: str,
    schedule: pl.DataFrame,
    team_map: dict[int, int],
    incumbent: dict[tuple[int, int], Distribution],
    current_fixture_gameweeks: Mapping[int, int],
) -> tuple[dict[tuple[int, int], Distribution], dict[str, Any]]:
    """Only the declared knowledge-time waiver differs from frozen selector arithmetic."""
    AsOf(cutoff)
    inputs.verify()
    if season != inputs.season or cutoff > inputs.evidence_as_of:
        raise ValueError("counterfactual target differs from the frozen source scope")
    if any(
        type(k) is not int or k <= 0 or type(v) is not int or v <= 0
        for k, v in current_fixture_gameweeks.items()
    ):
        raise ValueError("exact positive fixture/gameweek identity required")
    if datetime.fromisoformat(inputs.model.payload["parameter_fold"]["as_of"]) >= cutoff:
        raise ValueError("frozen model training frontier must precede the target cutoff")
    gws = schedule["gw"].unique().to_list()
    if len(gws) != 1 or type(gws[0]) is not int:
        raise ValueError("one whole target gameweek required per counterfactual invocation")
    target_gw = gws[0]
    for target in schedule.iter_rows(named=True):
        if (
            target["kickoff_time"] <= cutoff
            or current_fixture_gameweeks.get(target["fixture"]) != target_gw
            or target.get("season", season) != season
        ):
            raise ValueError("target schedule must be exact cutoff-known future fixtures")
    strict_failure = model_failure
    strict_global = state.global_failure
    strict_diagnostics = list(state.diagnostics)
    state = _historical_state(
        inputs,
        state,
        cutoff=cutoff,
        target_gw=target_gw,
        current_fixture_gameweeks=current_fixture_gameweeks,
    )
    model = inputs.model
    model_failure = model_failure if model_failure != "SDP_MISSING_FALLBACK" else None
    # The following selection/PMF logic mirrors SOURCE_SHA256. No model tuning parameters.
    chosen = dict(incumbent)
    decisions: list[dict[str, Any]] = []
    safe_rows = [r for r in state.rows if r.kickoff < cutoff]
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
        if reason is None and home is not None and away is not None:
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
        "model_sha256": model.sha256,
        "model_known_at": model.payload["known_at"],
        "model_version": model.payload["model_version"],
        "source_versions": [versions[key] for key in sorted(versions)],
        "selector_counts_team_predictions": {k: 2 * v for k, v in sorted(counts.items())},
        "health": {
            "matches_expected": len({key[:2] for key in state.expected}),
            "matches_valid": sum(key[0] == season for key in valid_keys) // 2,
            "source_rows_valid_all_seasons": len(valid_keys),
            "current_match_failures": {
                str(k): v for k, v in sorted(state.failures.items()) if k[0] == season
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
        "counterfactual": {
            "evidence_class": EVIDENCE_CLASS,
            "not_a_historical_prediction": True,
            "evidence_as_of": inputs.evidence_as_of.isoformat(),
            "version_policy": VERSION_POLICY,
            "source_db_sha256": inputs.source_db_sha256,
            "source_selector_sha256": inputs.source_code_sha256,
            "frozen_state_sha256": inputs.state_sha256,
            "strict_model_failure": strict_failure,
            "strict_source_global_failure": strict_global,
            "strict_source_diagnostics": strict_diagnostics,
            "waivers": ["SDP_and_its_crosswalk_source_availability", "frozen_model_availability"],
            "historical_fpl_target_and_required_fixture_population_preserved": True,
            "later_known_source_versions": sum(
                datetime.fromisoformat(v["known_at"]) > cutoff for v in versions.values()
            ),
        },
    }


@contextmanager
def bind_counterfactual_selector(
    inputs: FrozenCounterfactualInputs,
    *,
    cutoff: datetime,
    current_fixture_gameweeks: Mapping[int, int],
) -> Iterator[None]:
    """Bind only inside a dedicated validation process; disabled shadow never calls this."""
    inputs.verify()
    gameweeks = dict(current_fixture_gameweeks)
    if any(
        type(k) is not int or k <= 0 or type(v) is not int or v <= 0 for k, v in gameweeks.items()
    ):
        raise ValueError("exact positive fixture/gameweek identity required")

    def selected(**kwargs: Any) -> tuple[dict[tuple[int, int], Distribution], dict[str, Any]]:
        if kwargs["cutoff"] != cutoff or kwargs["season"] != inputs.season:
            raise ValueError("scoped counterfactual binding cannot change target cutoff/season")
        return select_counterfactual_environments(
            inputs, **kwargs, current_fixture_gameweeks=gameweeks
        )

    with patch("fpl.models.sdp_environment.select_environments", selected):
        yield
