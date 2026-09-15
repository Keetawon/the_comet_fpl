"""SDP prospective-evidence pair registry.

Deterministic and network-free. A synthetic SDP primary artifact and its incumbent
shadow artifact (environment disabled) are bound as one pre-deadline evidence pair,
inserting both ledger vintages and the pair in one transaction. The tests pin: canonical
artifact handling, atomic rollback with zero partial predictions, deep membership and
manifest parity, mandatory SDP provenance validated against retained raw payloads,
official-deadline enforcement against a monkeypatched real clock, idempotence (including
after the deadline has passed), dirty-worktree and future-run refusal, separate
append-only outcomes, and that recording never touches prior predictions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    ForecastPlayerFixtureRow,
    ForecastTeamFixtureRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    artifact_bytes,
    write_artifact_atomic,
)
from fpl.jobs.record_sdp_evidence import main as record_cli
from fpl.jobs.report_sdp_evidence import main as report_cli
from fpl.storage import ledger, sdp_evidence
from fpl.storage.db import connect, initialise
from fpl.storage.ledger import (
    DuplicateRunError,
    LedgerOutcome,
    OutcomeValueConflictError,
    TeamLedgerOutcome,
    attach_outcomes,
    attach_team_outcomes,
)
from fpl.storage.sdp_evidence import (
    ArtifactNotCanonicalError,
    DeadlineEvidenceError,
    PairVerificationError,
    derive_prediction_id,
    record_pair,
)

HASH = "a" * 64
STATS_SHA = "b" * 64
META_SHA = "d" * 64
MODEL_SHA = "c" * 64
BOOTSTRAP_AT = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
SOURCE_AT = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
# Honest flow ordering: the forecast's knowledge cutoff precedes the record entry
# instant, which precedes the official deadline, which precedes kickoff.
AS_OF = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
RECORDED_AT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
SEASON = "2026-27"


def _pmf(mean: float) -> tuple[float, ...]:
    """An exact two-point distribution on {k, k+1} whose mean is ``mean``."""
    if mean == 0.0:
        return (1.0,)
    lower = int(mean)
    frac = mean - lower
    return (*tuple(0.0 for _ in range(lower)), 1.0 - frac, frac)


def _convolve(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    out = [0.0] * (len(left) + len(right) - 1)
    for left_index, left_mass in enumerate(left):
        for right_index, right_mass in enumerate(right):
            out[left_index + right_index] += left_mass * right_mass
    return tuple(out)


def _kickoff(gw: int) -> datetime:
    return KICKOFF + timedelta(days=7 * (gw - 1))


def _bootstrap_payload(*witnessed_gws: int) -> dict[str, Any]:
    deadlines = {
        1: "2026-08-21T17:30:00+00:00",
        2: "2026-08-28T17:30:00+00:00",
        3: "2026-09-12T17:30:00+00:00",
    }
    return {
        "events": [{"id": gw, "deadline_time": deadlines[gw]} for gw in witnessed_gws],
        "elements": [],
        "teams": [],
    }


def _capture(con: Any, capture_id: str, captured_at: datetime, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    con.execute(
        """
        INSERT INTO snapshot_capture (capture_id, captured_at, season, gw, mode, payload_count,
                                      manifest, manifest_sha256)
        VALUES (?, ?, ?, NULL, 'test', 1, '{}', ?)
        """,
        [capture_id, captured_at, SEASON, hashlib.sha256(b"{}").hexdigest()],
    )
    con.execute(
        """
        INSERT INTO snapshot_payload (capture_id, endpoint, parameter, payload, sha256,
                                      byte_count, row_count)
        VALUES (?, 'bootstrap-static', '', ?, ?, ?, ?)
        """,
        [capture_id, body, sha, len(body.encode("utf-8")), len(payload.get("elements", ()) or ())],
    )
    return sha


def _raw_payload(
    con: Any, payload_id: str, fetched_at: datetime, body: dict[str, Any], sha: str
) -> None:
    text = json.dumps(body)
    con.execute(
        """
        INSERT INTO raw_pl_sdp_payload (payload_id, provider, endpoint, request_path,
                                        params_json, season, sdp_match_id, fetched_at,
                                        status_code, payload, sha256, byte_count)
        VALUES (?, 'pl_sdp', 'match_stats', '/stats', '{}', ?, 9001, ?, 200, ?, ?, ?)
        """,
        [payload_id, SEASON, fetched_at, text, sha, len(text.encode("utf-8"))],
    )


def _contracts() -> dict[str, ContractIdentity]:
    return {
        "scoring": ContractIdentity(name="scoring_2026_27", version="2026_27", sha256=HASH),
        "phase2_minutes": ContractIdentity(name="phase2_evaluation", version="1.4", sha256=HASH),
        "phase3_attacking": ContractIdentity(name="phase3_evaluation", version="1.3", sha256=HASH),
    }


def _canonical_provenance(**overrides: Any) -> dict[str, Any]:
    """The FULL canonical SdpStateRow.provenance shape emitted by sdp_runtime.

    The declared artifact entry and the mocked normative reader are built from this one
    shape so an exact-match validation is exercised honestly, including every field the
    real reader emits (identity, normalization version, and both metadata receipts).
    """
    value: dict[str, Any] = {
        "provider": "pl_sdp",
        "provider_match_id": 9001,
        "competition": 8,
        "season": SEASON,
        "payload_id": "stats-1",
        "payload_sha256": STATS_SHA,
        "fetched_at": SOURCE_AT.isoformat(),
        "known_at": SOURCE_AT.isoformat(),
        "match_metadata_payload_id": "meta-1",
        "match_metadata_sha256": META_SHA,
        "fpl_metadata_capture_id": "capture-fpl-1",
        "fpl_metadata_known_at": SOURCE_AT.isoformat(),
        "normalization_version": "sdp_production_health_v1",
        "schema_version": 3,
    }
    value.update(overrides)
    return value


def _source_version() -> dict[str, Any]:
    return _canonical_provenance()


def _environment_provenance(
    shadow_hash: str,
    gws: tuple[int, ...],
    *,
    selectors: tuple[str, ...] | None = None,
    model: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cutoff": AS_OF.isoformat(),
        "primary": "sdp_v2",
        "fallback": "trailing_goals_attack_defence",
        "model_sha256": MODEL_SHA if model else None,
        "model_known_at": SOURCE_AT.isoformat() if model else None,
        "model_version": "tactical_v1" if model else None,
        "source_versions": [_source_version()] if model else [],
        "decisions": [
            {
                "season": SEASON,
                "gw": gw,
                "fixture": 2000 + gw,
                "home_team_code": 70,
                "away_team_code": 80,
                "selector": (selectors or ("SDP_PRIMARY",))[
                    index % len(selectors or ("SDP_PRIMARY",))
                ],
            }
            for index, gw in enumerate(gws)
        ],
        "selector_counts_team_predictions": {"SDP_PRIMARY": 2 * len(gws)},
        "health": {"latest_sdp_known_at": SOURCE_AT.isoformat()},
        "shadow_incumbent_artifact_sha256": shadow_hash,
    }


def _artifact(
    *,
    mean: float,
    code: int = 11,
    fixture_offset: int = 0,
    legs_per_gw: int = 1,
    gws: tuple[int, ...] = (1,),
    base_seed: int = 1,
    as_of: datetime = AS_OF,
    forecast_role: str,
    environment_provenance: dict[str, Any] | None = None,
    bootstrap_capture_id: str = "cap-1",
    bootstrap_known_at: datetime = BOOTSTRAP_AT,
    bootstrap_payload_sha256: str = HASH,
    contracts: dict[str, ContractIdentity] | None = None,
    appearance_mode: str = "seasonal",
) -> ProspectivePointsArtifact:
    gameweek_rows: list[ForecastArtifactRow] = []
    player_fixture_rows: list[ForecastPlayerFixtureRow] = []
    team_fixture_rows: list[ForecastTeamFixtureRow] = []
    distribution = _pmf(mean)
    for gw in gws:
        fixtures = tuple(2001 + fixture_offset + index for index in range(legs_per_gw))
        for fixture in fixtures:
            player_fixture_rows.append(
                ForecastPlayerFixtureRow(
                    season=SEASON,
                    gw=gw,
                    fixture=fixture,
                    code=code,
                    kickoff_time=_kickoff(gw),
                    position="MID",
                    team_id=7,
                    team_code=70,
                    opponent_team_id=8,
                    was_home=True,
                    expected_points=mean,
                    expected_bonus=0.0,
                    distribution=distribution,
                    stage_a_league_average_team=False,
                )
            )
            for team_id, team_code, opponent, was_home, lam in (
                (7, 70, 8, True, 1.5),
                (8, 80, 7, False, 1.1),
            ):
                goals = _pmf(lam)
                team_fixture_rows.append(
                    ForecastTeamFixtureRow(
                        season=SEASON,
                        gw=gw,
                        fixture=fixture,
                        kickoff_time=_kickoff(gw),
                        team_id=team_id,
                        team_code=team_code,
                        opponent_team_id=opponent,
                        was_home=was_home,
                        lambda_for=lam,
                        lambda_against=1.1 if was_home else 1.5,
                        probability_clean_sheet=goals[0],
                        goals_for_distribution=goals,
                        stage_a_league_average_team=False,
                    )
                )
        combined: tuple[float, ...] = (1.0,)
        for _ in fixtures:
            combined = _convolve(combined, distribution)
        gameweek_rows.append(
            ForecastArtifactRow(
                season=SEASON,
                gw=gw,
                code=code,
                web_name="Player",
                position="MID",
                team_id=7,
                team_code=70,
                now_cost=50,
                selected_by_percent=None,
                availability_status="a",
                chance_of_playing=None,
                availability_multiplier=1.0,
                fixture_ids=fixtures,
                kickoff_times=tuple(_kickoff(gw) for _ in fixtures),
                expected_points=round(mean * len(fixtures), 10),
                availability_adjusted_expected_points=round(mean * len(fixtures), 10),
                expected_bonus=0.0,
                distribution=combined,
                cold_start_player=False,
                stage_a_league_average_team=False,
                attacking_signal_cold_start=False,
                assist_signal_cold_start=False,
                transferred_no_rescale=False,
            )
        )
    modes: dict[str, str] = {
        "appearance_mode": appearance_mode,
        "assists_mode": "coupled",
        "attacking_mode": "v3",
        "component.minutes": "trailing_5_player_minutes",
        "component.team_clean_sheet": (
            "sdp_v2_with_incumbent_fallback"
            if forecast_role == "primary"
            else "trailing_goals_attack_defence"
        ),
    }
    if environment_provenance is not None:
        modes["football_environment.primary"] = "sdp_v2"
        modes["football_environment.provenance"] = json.dumps(
            environment_provenance, sort_keys=True, separators=(",", ":"), default=str
        )
    modes["forecast_role"] = forecast_role
    manifest = ForecastArtifactManifest(
        schema_version=2,
        as_of=as_of,
        season=SEASON,
        gw_from=min(gws),
        gw_to=max(gws),
        row_count=len(gws),
        player_fixture_row_count=len(gws) * legs_per_gw,
        team_fixture_row_count=2 * len(gws) * legs_per_gw,
        roster_size=1,
        fixture_count=len(gws) * legs_per_gw,
        monte_carlo_draws=100,
        base_seed=base_seed,
        fixture_points_support_max=40,
        freshness_cold_start=True,
        commit_sha="deadbeef",
        database_sha256=HASH,
        contracts=contracts or _contracts(),
        component_modes=modes,
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id=bootstrap_capture_id,
            bootstrap_known_at=bootstrap_known_at,
            bootstrap_payload_sha256=bootstrap_payload_sha256,
            schedule_capture_ids=(bootstrap_capture_id,),
        ),
    )
    return ProspectivePointsArtifact(
        manifest=manifest,
        rows=tuple(gameweek_rows),
        player_fixture_rows=tuple(player_fixture_rows),
        team_fixture_rows=tuple(team_fixture_rows),
    )


def _paired_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime = RECORDED_AT,
    artifact_gws: tuple[int, ...] = (1,),
    witness_gws: tuple[int, ...] | None = None,
    witness_payload: dict[str, Any] | None = None,
    shadow_kwargs: dict[str, Any] | None = None,
    primary_env: bool = True,
    capture_id: str = "cap-1",
    captured_at: datetime = BOOTSTRAP_AT,
    as_of: datetime = AS_OF,
    bind_hash: str | None = None,
    environment_kwargs: dict[str, Any] | None = None,
    tamper_witness: bool = False,
    seed_raw_payloads: bool = True,
    reader_rows: list[dict[str, Any]] | None = None,
) -> tuple[Any, ProspectivePointsArtifact, str, ProspectivePointsArtifact, str]:
    """Build captures, artifacts, and the mocked normative SDP reader state.

    ``reader_rows`` is the list of canonical provenances the strict reader reports
    (default: one row exactly matching the declared source version; ``[]`` models an
    empty reader, which must refuse any declared source).
    """
    from fpl.storage import sdp_runtime
    from fpl.storage.sdp_runtime import SdpState, SdpStateRow

    monkeypatch.setattr(sdp_evidence, "_now", lambda: now)
    con = initialise(tmp_path / "evidence.duckdb")
    rows = reader_rows if reader_rows is not None else [_canonical_provenance()]
    state = SdpState(
        rows=[
            SdpStateRow(
                season=SEASON,
                gw=1,
                fixture=2001,
                team_code=70,
                opponent_team_code=80,
                was_home=True,
                kickoff=KICKOFF,
                values=(0.0, 0.0, 0.0, 0.0, 0.0),
                metrics={},
                provenance=dict(row),
            )
            for row in rows
        ]
    )
    monkeypatch.setattr(sdp_runtime, "load_sdp_state", lambda _con, cutoff, season: state)
    payload = (
        witness_payload
        if witness_payload is not None
        else _bootstrap_payload(*(witness_gws or artifact_gws))
    )
    payload_sha = _capture(con, capture_id, captured_at, payload)
    if tamper_witness:
        con.execute(
            "UPDATE snapshot_payload SET payload = ? WHERE capture_id = ?",
            [json.dumps({"events": []}), capture_id],
        )
    if seed_raw_payloads:
        _raw_payload(con, "stats-1", SOURCE_AT, {"matchId": 9001}, STATS_SHA)
        _raw_payload(con, "meta-1", SOURCE_AT, {"matchId": 9001}, META_SHA)
    overrides = shadow_kwargs or {}
    shadow = _artifact(
        mean=0.3,
        gws=artifact_gws,
        as_of=as_of,
        forecast_role="shadow_incumbent",
        bootstrap_capture_id=capture_id,
        bootstrap_known_at=captured_at,
        bootstrap_payload_sha256=payload_sha,
        **overrides,
    )
    shadow_hash = hashlib.sha256(artifact_bytes(shadow)).hexdigest()
    environment = None
    if primary_env:
        environment = _environment_provenance(
            bind_hash or shadow_hash, artifact_gws, **(environment_kwargs or {})
        )
    primary = _artifact(
        mean=0.8,
        gws=artifact_gws,
        as_of=as_of,
        forecast_role="primary",
        environment_provenance=environment,
        bootstrap_capture_id=capture_id,
        bootstrap_known_at=captured_at,
        bootstrap_payload_sha256=payload_sha,
    )
    return con, primary, primary_sha(primary), shadow, shadow_hash


def primary_sha(artifact: ProspectivePointsArtifact) -> str:
    return hashlib.sha256(artifact_bytes(artifact)).hexdigest()


def _record(
    con: Any,
    primary: ProspectivePointsArtifact,
    primary_hash: str,
    shadow: ProspectivePointsArtifact,
    shadow_hash: str,
) -> str:
    return record_pair(
        con,
        primary=primary,
        primary_sha256=primary_hash,
        shadow=shadow,
        shadow_sha256=shadow_hash,
    )


def _run_ids(con: Any) -> tuple[str, str]:
    rows = con.execute(
        "SELECT run_id FROM ledger_forecast_run ORDER BY created_at, run_id"
    ).fetchall()
    return (str(rows[0][0]), str(rows[1][0]))


def test_pair_records_vintages_and_pair_atomically_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    prediction_id = _record(con, primary, p_sha, shadow, s_sha)
    pair = sdp_evidence.load_pair(con, prediction_id)
    assert pair is not None
    assert prediction_id == derive_prediction_id(
        primary_run_id=pair["primary_run_id"],
        shadow_run_id=pair["shadow_run_id"],
        season=SEASON,
        gw_from=1,
        gw_to=1,
        as_of_us=round(AS_OF.timestamp() * 1_000_000),
    )
    assert pair["created_at"] == RECORDED_AT.isoformat()
    deadlines = pair["deadline_evidence"]
    assert deadlines["deadlines"] == {"1": "2026-08-21T17:30:00+00:00"}
    assert deadlines["capture_id"] == "cap-1"
    (run_stamps,) = con.execute(
        "SELECT count(DISTINCT epoch_us(created_at)) FROM ledger_forecast_run"
    ).fetchone()
    assert run_stamps == 1  # new ledger vintages carry the same actual record entry stamp
    verification = pair["verification"]
    assert verification["membership"]["player_gameweek_rows"] == 1
    assert verification["membership"]["team_fixture_rows"] == 2
    assert verification["roles"]["shadow_forecast_role"] == "shadow_incumbent"
    assert verification["primary_shadow_hash_binding"]["required"] is True
    assert verification["sdp_provenance"]["consumed_sources"]["stats_payloads_validated"] == 1
    assert pair["source_provenance"]["primary"]["selectable_player_registry_sha256"] is None
    con.close()


def test_record_pair_is_idempotent_and_survives_the_deadline_passing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    first = _record(con, primary, p_sha, shadow, s_sha)
    (before,) = con.execute("SELECT epoch_us(created_at) FROM ledger_sdp_evidence_pair").fetchone()
    monkeypatch.setattr(
        sdp_evidence, "_now", lambda: datetime(2026, 8, 29, tzinfo=UTC)
    )  # deadline long past
    again = _record(con, primary, p_sha, shadow, s_sha)
    assert again == first
    (count, stamps) = con.execute(
        "SELECT count(*), count(DISTINCT epoch_us(created_at)) FROM ledger_sdp_evidence_pair"
    ).fetchone()
    assert (count, stamps) == (1, 1)
    (after,) = con.execute("SELECT epoch_us(created_at) FROM ledger_sdp_evidence_pair").fetchone()
    assert after == before  # the original actual stamp is kept
    con.close()


def test_late_recording_after_the_official_deadline_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path, monkeypatch, now=datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
    )
    with pytest.raises(DeadlineEvidenceError, match="expired deadline"):
        _record(con, primary, p_sha, shadow, s_sha)
    (runs, pairs) = con.execute(
        """
        SELECT (SELECT count(*) FROM ledger_forecast_run),
               (SELECT count(*) FROM ledger_sdp_evidence_pair)
        """
    ).fetchone()
    assert (runs, pairs) == (0, 0)  # zero partial new predictions
    con.close()


def test_a_kickoff_at_or_before_the_record_entry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path, monkeypatch, now=KICKOFF + timedelta(hours=1)
    )
    with pytest.raises(DeadlineEvidenceError, match="kickoff"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()


def test_non_canonical_artifact_bytes_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, _p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    with pytest.raises(ArtifactNotCanonicalError, match="canonical"):
        _record(con, primary, "0" * 64, shadow, s_sha)
    con.close()


def test_membership_and_component_differences_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = {
        "membership": {"code": 12},
        "fixture": {"fixture_offset": 1},
        "double_gameweek": {"legs_per_gw": 2},
        "component": {"appearance_mode": "model"},
    }
    for label, overrides in cases.items():
        work = tmp_path / label
        con, primary, p_sha, shadow, s_sha = _paired_database(
            work, monkeypatch, shadow_kwargs=overrides
        )
        with pytest.raises(PairVerificationError):
            _record(con, primary, p_sha, shadow, s_sha)
        (pairs,) = con.execute("SELECT count(*) FROM ledger_sdp_evidence_pair").fetchone()
        assert pairs == 0, label
        con.close()


def test_a_different_live_source_is_refused_by_manifest_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, _s_sha = _paired_database(tmp_path, monkeypatch)
    drifted_manifest = shadow.manifest.model_copy(
        update={
            "live_inputs": shadow.manifest.live_inputs.model_copy(
                update={"selectable_player_registry_sha256": "e" * 64}
            )
        }
    )
    drifted = dataclass_replace(shadow, manifest=drifted_manifest)
    with pytest.raises(PairVerificationError, match="live inputs"):
        _record(con, primary, p_sha, drifted, primary_sha(drifted))
    con.close()


def test_sdp_provenance_is_mandatory_and_shadow_must_be_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch, primary_env=False)
    with pytest.raises(PairVerificationError, match=r"football_environment\.provenance"):
        _record(con, primary, p_sha, shadow, s_sha)

    env = _environment_provenance(s_sha, (1,))
    drifted_manifest = shadow.manifest.model_copy(
        update={
            "component_modes": {
                **shadow.manifest.component_modes,
                "football_environment.primary": "sdp_v2",
                "football_environment.provenance": json.dumps(
                    env, sort_keys=True, separators=(",", ":"), default=str
                ),
            }
        }
    )
    shadow_with_env = dataclass_replace(shadow, manifest=drifted_manifest)
    with pytest.raises(PairVerificationError, match="must not carry SDP primary provenance"):
        _record(con, primary, p_sha, shadow_with_env, primary_sha(shadow_with_env))
    (pairs,) = con.execute("SELECT count(*) FROM ledger_sdp_evidence_pair").fetchone()
    assert pairs == 0
    con.close()


def test_the_bound_shadow_hash_must_equal_the_canonical_shadow_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch, bind_hash="f" * 64)
    with pytest.raises(PairVerificationError, match="canonical"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()


def test_an_empty_strict_reader_cannot_witness_declared_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No fail-open hole: a reader yielding zero rows must reject declared sources."""
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch, reader_rows=[])
    with pytest.raises(PairVerificationError, match="yields no cutoff-eligible rows"):
        _record(con, primary, p_sha, shadow, s_sha)
    (pairs,) = con.execute("SELECT count(*) FROM ledger_sdp_evidence_pair").fetchone()
    assert pairs == 0
    con.close()


def test_declared_source_provenance_identity_mismatch_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path,
        monkeypatch,
        reader_rows=[_canonical_provenance(payload_id="stats-OTHER")],
    )
    with pytest.raises(PairVerificationError, match="not a cutoff-eligible match"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()

    con2, primary2, p2, shadow2, s2 = _paired_database(
        tmp_path / "sha",
        monkeypatch,
        reader_rows=[_canonical_provenance(payload_sha256="9" * 64)],
    )
    with pytest.raises(PairVerificationError, match="not a cutoff-eligible match"):
        _record(con2, primary2, p2, shadow2, s2)
    con2.close()


def test_declared_source_provenance_version_mismatch_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path,
        monkeypatch,
        reader_rows=[_canonical_provenance(normalization_version="sdp_production_health_v0")],
    )
    with pytest.raises(PairVerificationError, match="disagrees with the strict SDP reader"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()

    # A declared entry missing any canonical reader field is not a full witness either.
    con2, primary2, _p2, shadow2, s2 = _paired_database(tmp_path / "shape", monkeypatch)
    env = _environment_provenance(s2, (1,))
    env["source_versions"][0].pop("normalization_version")
    drifted_manifest = primary2.manifest.model_copy(
        update={
            "component_modes": {
                **primary2.manifest.component_modes,
                "football_environment.provenance": json.dumps(
                    env, sort_keys=True, separators=(",", ":"), default=str
                ),
            }
        }
    )
    drifted = dataclass_replace(primary2, manifest=drifted_manifest)
    with pytest.raises(PairVerificationError, match="full canonical reader shape"):
        _record(con2, drifted, primary_sha(drifted), shadow2, s2)
    con2.close()


def test_a_future_known_consumed_source_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, _p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    env = _environment_provenance(s_sha, (1,))
    env["source_versions"][0]["known_at"] = (AS_OF + timedelta(days=1)).isoformat()
    drifted_manifest = primary.manifest.model_copy(
        update={
            "component_modes": {
                **primary.manifest.component_modes,
                "football_environment.provenance": json.dumps(
                    env, sort_keys=True, separators=(",", ":"), default=str
                ),
            }
        }
    )
    drifted = dataclass_replace(primary, manifest=drifted_manifest)
    with pytest.raises(PairVerificationError, match="disagrees with the strict SDP reader"):
        _record(con, drifted, primary_sha(drifted), shadow, s_sha)
    con.close()


def test_the_adopted_team_clean_sheet_mode_pair_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The exact adopted pair (SDP-primary primary side, incumbent shadow side) records.
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    assert primary.manifest.component_modes["component.team_clean_sheet"] == (
        "sdp_v2_with_incumbent_fallback"
    )
    assert shadow.manifest.component_modes["component.team_clean_sheet"] == (
        "trailing_goals_attack_defence"
    )
    assert _record(con, primary, p_sha, shadow, s_sha)
    con.close()

    # Any other clean-sheet mode difference is refused.
    con2, primary2, p2, shadow2, _s2 = _paired_database(tmp_path / "wrongcs", monkeypatch)
    drifted_manifest = shadow2.manifest.model_copy(
        update={
            "component_modes": {
                **shadow2.manifest.component_modes,
                "component.team_clean_sheet": "some_other_team_environment",
            }
        }
    )
    drifted_shadow = dataclass_replace(shadow2, manifest=drifted_manifest)
    with pytest.raises(PairVerificationError, match=r"component\.team_clean_sheet"):
        _record(con2, primary2, p2, drifted_shadow, primary_sha(drifted_shadow))
    con2.close()


def test_metadata_delayed_known_at_is_the_normalized_maximum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A metadata-delayed normalized known_at is accepted when the reader witnesses it."""
    delayed = SOURCE_AT + timedelta(hours=2)
    delayed_provenance = _canonical_provenance(
        known_at=delayed.isoformat(),
        fpl_metadata_known_at=delayed.isoformat(),
    )
    con, primary, _p_sha, shadow, s_sha = _paired_database(
        tmp_path, monkeypatch, reader_rows=[delayed_provenance]
    )
    env = _environment_provenance(s_sha, (1,))
    env["source_versions"][0].update(
        {
            "known_at": delayed.isoformat(),
            "fpl_metadata_known_at": delayed.isoformat(),
        }
    )
    drifted_manifest = primary.manifest.model_copy(
        update={
            "component_modes": {
                **primary.manifest.component_modes,
                "football_environment.provenance": json.dumps(
                    env, sort_keys=True, separators=(",", ":"), default=str
                ),
            }
        }
    )
    drifted = dataclass_replace(primary, manifest=drifted_manifest)
    prediction_id = _record(con, drifted, primary_sha(drifted), shadow, s_sha)
    pair = sdp_evidence.load_pair(con, prediction_id)
    assert pair is not None
    assert (
        pair["verification"]["sdp_provenance"]["consumed_sources"]["metadata_receipts_validated"]
        == 1
    )
    con.close()

    # A known_at beyond the reader's normalized maximum is a disagreement, not a delay.
    con2, primary2, _p2, shadow2, s2 = _paired_database(
        tmp_path / "wrongmax", monkeypatch, reader_rows=[delayed_provenance]
    )
    env2 = _environment_provenance(s2, (1,))
    env2["source_versions"][0].update(
        {
            "known_at": (SOURCE_AT + timedelta(hours=3)).isoformat(),
            "fpl_metadata_known_at": delayed.isoformat(),
        }
    )
    drifted2 = dataclass_replace(
        primary2,
        manifest=primary2.manifest.model_copy(
            update={
                "component_modes": {
                    **primary2.manifest.component_modes,
                    "football_environment.provenance": json.dumps(
                        env2, sort_keys=True, separators=(",", ":"), default=str
                    ),
                }
            }
        ),
    )
    with pytest.raises(PairVerificationError, match="disagrees with the strict SDP reader"):
        _record(con2, drifted2, primary_sha(drifted2), shadow2, s2)
    con2.close()


def test_an_all_fallback_forecast_with_missing_model_still_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path,
        monkeypatch,
        environment_kwargs={"model": False, "selectors": ("SDP_MISSING_FALLBACK",)},
    )
    assert primary.manifest.component_modes["football_environment.provenance"]
    prediction_id = _record(con, primary, p_sha, shadow, s_sha)
    pair = sdp_evidence.load_pair(con, prediction_id)
    assert pair is not None
    environment = pair["verification"]["sdp_provenance"]
    assert environment["model_sha256"] is None  # null absence is preserved, never zero-filled
    assert environment["decision_coverage"]["all_fallback"] is True
    assert environment["consumed_sources"]["stats_payloads_validated"] == 0
    con.close()


def test_sdp_primary_selectors_without_a_valid_model_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path, monkeypatch, environment_kwargs={"model": False}
    )
    with pytest.raises(PairVerificationError, match="require valid frozen model provenance"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()


def test_bootstrap_known_after_the_cutoff_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path, monkeypatch, captured_at=AS_OF + timedelta(hours=1)
    )
    with pytest.raises(DeadlineEvidenceError, match="after the forecast cutoff"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()


def test_the_witness_bytes_are_rehashed_and_event_identities_unique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(
        tmp_path, monkeypatch, tamper_witness=True
    )
    with pytest.raises(DeadlineEvidenceError, match="hash"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()

    duplicated = _bootstrap_payload(1)
    duplicated["events"].append({"id": 1, "deadline_time": "2026-08-21T17:30:00+00:00"})
    con2, primary2, p2, shadow2, s2 = _paired_database(
        tmp_path / "dupes", monkeypatch, witness_payload=duplicated
    )
    with pytest.raises(DeadlineEvidenceError, match="duplicate event identity"):
        _record(con2, primary2, p2, shadow2, s2)
    con2.close()


def test_dirty_worktree_or_future_run_rows_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    _record(con, primary, p_sha, shadow, s_sha)
    primary_run, shadow_run = _run_ids(con)
    # Replay the same pair from a state where the pair row is gone but the runs are dirty.
    con.execute("DELETE FROM ledger_sdp_evidence_pair")
    con.execute(
        "UPDATE ledger_forecast_run SET worktree_clean = FALSE WHERE run_id = ?", [shadow_run]
    )
    with pytest.raises(PairVerificationError, match="dirty worktree"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.execute(
        "UPDATE ledger_forecast_run SET worktree_clean = TRUE WHERE run_id = ?", [shadow_run]
    )
    con.execute(
        "UPDATE ledger_forecast_run SET created_at = ? WHERE run_id = ?",
        [RECORDED_AT + timedelta(hours=1), primary_run],
    )
    with pytest.raises(PairVerificationError, match="must already exist"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()


def test_a_failure_after_the_first_vintage_insert_rolls_everything_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure after the primary vintage was inserted")

    monkeypatch.setattr(ledger, "_insert_predictions", boom)
    with pytest.raises(RuntimeError, match="simulated failure"):
        _record(con, primary, p_sha, shadow, s_sha)
    (runs, gw_rows, pairs) = con.execute(
        """
        SELECT (SELECT count(*) FROM ledger_forecast_run),
               (SELECT count(*) FROM ledger_prediction_player_gameweek),
               (SELECT count(*) FROM ledger_sdp_evidence_pair)
        """
    ).fetchone()
    assert (runs, gw_rows, pairs) == (0, 0, 0)
    con.close()


def test_a_fresh_database_needs_both_artifacts_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    prediction_id = _record(con, primary, p_sha, shadow, s_sha)
    primary_run, shadow_run = _run_ids(con)
    for run_id in (primary_run, shadow_run):
        (gw, teams) = con.execute(
            """
            SELECT (SELECT count(*) FROM ledger_prediction_player_gameweek WHERE run_id = ?),
                   (SELECT count(*) FROM ledger_prediction_team_fixture WHERE run_id = ?)
            """,
            [run_id, run_id],
        ).fetchone()
        assert (gw, teams) == (1, 2)
    # Re-presenting with a run id conflict is impossible by derivation, but a mutated
    # stored hash must fail closed rather than silently rebind.
    con.execute(
        "UPDATE ledger_sdp_evidence_pair SET shadow_artifact_sha256 = ? WHERE prediction_id = ?",
        ["1" * 64, prediction_id],
    )
    with pytest.raises(sdp_evidence.PairConflictError, match="different bound values"):
        _record(con, primary, p_sha, shadow, s_sha)
    con.close()


def test_outcomes_stay_separate_append_only_and_predictions_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    prediction_id = _record(con, primary, p_sha, shadow, s_sha)
    pair_before = sdp_evidence.load_pair(con, prediction_id)
    predictions_before = con.execute(
        "SELECT run_id, code, gw, distribution FROM ledger_prediction_player_gameweek "
        "ORDER BY run_id, gw, code"
    ).fetchall()

    assert all(
        row["outcome"] is None for row in sdp_evidence.pair_team_fixture_rows(con, pair_before)
    )
    team_pair = [
        TeamLedgerOutcome(
            season=SEASON,
            fixture=2001,
            team_id=team_id,
            team_code=team_code,
            opponent_team_id=opponent,
            gw=1,
            kickoff_time=KICKOFF,
            was_home=was_home,
            goals_for=goals_for,
            goals_against=goals_against,
        )
        for team_id, team_code, opponent, was_home, goals_for, goals_against in (
            (7, 70, 8, True, 2, 1),
            (8, 80, 7, False, 1, 2),
        )
    ]
    assert attach_team_outcomes(con, team_pair) == 2
    assert attach_team_outcomes(con, team_pair) == 0  # exact repeat is idempotent
    with pytest.raises(OutcomeValueConflictError):
        attach_team_outcomes(
            con,
            [
                TeamLedgerOutcome(
                    season=SEASON,
                    fixture=2001,
                    team_id=7,
                    team_code=70,
                    opponent_team_id=8,
                    gw=1,
                    kickoff_time=KICKOFF,
                    was_home=True,
                    goals_for=3,
                    goals_against=1,
                ),
                TeamLedgerOutcome(
                    season=SEASON,
                    fixture=2001,
                    team_id=8,
                    team_code=80,
                    opponent_team_id=7,
                    gw=1,
                    kickoff_time=KICKOFF,
                    was_home=False,
                    goals_for=1,
                    goals_against=3,
                ),
            ],
        )
    assert (
        attach_outcomes(
            con,
            [
                LedgerOutcome(
                    season=SEASON,
                    code=11,
                    fixture=2001,
                    total_points_as_recorded=6,
                    points_under_rules_2026_27=7,
                )
            ],
        )
        == 1
    )
    with pytest.raises(DuplicateRunError):
        attach_outcomes(
            con,
            [
                LedgerOutcome(
                    season=SEASON,
                    code=11,
                    fixture=2001,
                    total_points_as_recorded=6,
                    points_under_rules_2026_27=7,
                )
            ],
        )

    assert (
        con.execute(
            "SELECT run_id, code, gw, distribution FROM ledger_prediction_player_gameweek "
            "ORDER BY run_id, gw, code"
        ).fetchall()
        == predictions_before
    )
    assert sdp_evidence.load_pair(con, prediction_id) == pair_before
    for row in sdp_evidence.pair_team_fixture_rows(con, sdp_evidence.load_pair(con, prediction_id)):
        assert row["outcome"] is not None
        assert row["outcome"]["goals_for"] == (2 if row["team_id"] == 7 else 1)
        if row["role"] == "primary":
            assert row["selector"] == "SDP_PRIMARY"
        else:
            assert row["selector"] is None
    con.close()


def _witness_gw_final(con: Any) -> None:
    """One finished fixture row: the minimal official gameweek finality witness."""
    con.execute(
        """
        INSERT INTO stg_fixture (season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
                                 team_h_score, team_a_score, finished)
        VALUES (?, 2001, NULL, 1, ?, 7, 8, 2, 1, TRUE)
        """,
        [SEASON, KICKOFF],
    )


def test_the_player_gameweek_grain_requires_official_gw_finality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    prediction_id = _record(con, primary, p_sha, shadow, s_sha)
    sdp_evidence.load_pair(con, prediction_id)
    assert (
        attach_outcomes(
            con,
            [
                LedgerOutcome(
                    season=SEASON,
                    code=11,
                    fixture=2001,
                    total_points_as_recorded=6,
                    points_under_rules_2026_27=7,
                )
            ],
        )
        == 1
    )
    # Every leg is attached, but with no official gameweek finality witness in the
    # database the gameweek outcome must remain unavailable (never scored, never zero).
    unavailable = sdp_evidence.pair_player_gameweek_rows(
        con, sdp_evidence.load_pair(con, prediction_id)
    )
    for row in unavailable:
        assert row["outcome"]["attached"] is False
        assert "finality" in row["outcome"]["reason"]

    _witness_gw_final(con)
    attached = sdp_evidence.pair_player_gameweek_rows(
        con, sdp_evidence.load_pair(con, prediction_id)
    )
    for row in attached:
        assert row["outcome"]["attached"] is True
        assert row["outcome"]["points_under_rules_2026_27"] == 7
        assert row["outcome"]["total_points_as_recorded"] == 6
    con.close()


def test_record_cli_from_artifact_paths_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    con, primary, _p, shadow, _s = _paired_database(tmp_path, monkeypatch)
    con.close()
    primary_path = tmp_path / "gw.jsonl"
    shadow_path = tmp_path / "gw.shadow-incumbent.jsonl"
    write_artifact_atomic(primary_path, primary)
    write_artifact_atomic(shadow_path, shadow)
    db = str(tmp_path / "evidence.duckdb")
    argv = ["--primary", str(primary_path), "--shadow", str(shadow_path), "--db", db]
    assert record_cli(argv) == 0
    assert record_cli(argv) == 0  # identical repeat: same id, original stamp
    (pairs,) = (
        connect(tmp_path / "evidence.duckdb", read_only=True)
        .execute("SELECT count(*) FROM ledger_sdp_evidence_pair")
        .fetchone()
    )
    assert pairs == 1
    # A mutated artifact file (different canonical bytes) refuses rather than rebinding.
    drifted = primary_path.read_text(encoding="utf-8").replace('"base_seed":1', '"base_seed":1 ')
    primary_path.write_text(drifted, encoding="utf-8")
    assert record_cli(argv) == 1
    assert "refused" in capsys.readouterr().err
    con = connect(tmp_path / "evidence.duckdb", read_only=True)
    (pairs,) = con.execute("SELECT count(*) FROM ledger_sdp_evidence_pair").fetchone()
    con.close()
    assert pairs == 1


def test_record_cli_owns_the_writer_lock_and_never_creates_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    con, primary, _p, shadow, _s = _paired_database(tmp_path, monkeypatch)
    con.close()
    primary_path = tmp_path / "gw.jsonl"
    shadow_path = tmp_path / "gw.shadow-incumbent.jsonl"
    write_artifact_atomic(primary_path, primary)
    write_artifact_atomic(shadow_path, shadow)
    argv = [
        "--primary",
        str(primary_path),
        "--shadow",
        str(shadow_path),
        "--db",
        str(tmp_path / "absent.duckdb"),
    ]
    assert record_cli(argv) == 1
    assert "does not exist" in capsys.readouterr().err
    assert not (tmp_path / "absent.duckdb").exists()  # no schema-only fallback was created


def test_report_cli_exposes_standing_operations_and_grains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    con, primary, p_sha, shadow, s_sha = _paired_database(tmp_path, monkeypatch)
    prediction_id = _record(con, primary, p_sha, shadow, s_sha)
    con.close()
    output = tmp_path / "report.json"
    assert (
        report_cli(
            [
                "--prediction-id",
                prediction_id,
                "--db",
                str(tmp_path / "evidence.duckdb"),
                "--grain",
                "all",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "fpl.sdp-evidence-pair-report/v2"
    assert report["standing"]["adoption"] == "owner_directed_sdp_v2_architectural_adoption"
    assert report["operations"]["selector_counts_team_predictions"] == {"SDP_PRIMARY": 2}
    assert report["operations"]["sdp_fallback"] == "trailing_goals_attack_defence"
    assert len(report["team_fixture_rows"]) == 4
    assert len(report["player_fixture_rows"]) == 2
    assert len(report["player_gameweek_rows"]) == 2
    assert (
        report["operations"]["outcome_attachment_counts"]["team_fixture_rows"]["primary"][
            "attached"
        ]
        == 0
    )
    assert any("development-only" in note for note in report["notes"])
    assert report_cli(["--prediction-id", "0" * 64, "--db", str(tmp_path / "evidence.duckdb")]) == 1
    assert "refused" in capsys.readouterr().err


def test_finality_uses_latest_fixture_gameweek_after_rescheduling() -> None:
    with connect(":memory:") as con:
        con.execute("""
            CREATE TABLE stg_live_fixture_version (
                season VARCHAR, fixture INTEGER, gw INTEGER, finished BOOLEAN,
                known_at TIMESTAMPTZ, capture_id VARCHAR
            )
        """)
        con.executemany(
            "INSERT INTO stg_live_fixture_version VALUES (?,?,?,?,?,?)",
            [
                ("2026-27", 1, 4, True, AS_OF, "a"),
                ("2026-27", 2, 4, False, AS_OF, "a"),
                ("2026-27", 2, 5, False, AS_OF + timedelta(hours=1), "b"),
            ],
        )
        assert sdp_evidence._official_gameweek_final(con, "2026-27", 4) is True
        assert sdp_evidence._official_gameweek_final(con, "2026-27", 5) is False
