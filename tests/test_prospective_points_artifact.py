"""Offline contract tests for the stable prospective-points JSONL boundary."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from fpl.artifacts.prospective_points import (
    ArtifactError,
    ArtifactFixtureInput,
    ArtifactPlayerInput,
    ContractIdentity,
    ForecastArtifactManifest,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    artifact_bytes,
    build_artifact_rows,
    read_artifact,
    read_artifact_bytes,
    write_artifact_atomic,
)

AS_OF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
HASH = "a" * 64


def _players() -> tuple[ArtifactPlayerInput, ...]:
    return (
        ArtifactPlayerInput(
            code=101,
            web_name="One",
            position="MID",
            team_id=1,
            team_code=11,
            now_cost=75,
            selected_by_percent=None,
            availability_status="d",
            chance_of_playing=25.0,
            availability_multiplier=0.25,
            cold_start_player=False,
            attacking_signal_cold_start=False,
            assist_signal_cold_start=True,
            transferred_no_rescale=False,
        ),
        ArtifactPlayerInput(
            code=202,
            web_name=None,
            position="GK",
            team_id=2,
            team_code=None,
            now_cost=None,
            selected_by_percent=1.2,
            availability_status="a",
            chance_of_playing=None,
            availability_multiplier=1.0,
            cold_start_player=True,
            attacking_signal_cold_start=True,
            assist_signal_cold_start=True,
            transferred_no_rescale=False,
        ),
    )


def _fixtures() -> tuple[ArtifactFixtureInput, ...]:
    return (
        ArtifactFixtureInput(
            season="2026-27",
            gw=1,
            fixture=10,
            kickoff_time=datetime(2026, 8, 22, 14, tzinfo=UTC),
            code=101,
            expected_bonus=0.2,
            distribution=(0.25, 0.75),
            stage_a_league_average_team=False,
        ),
        ArtifactFixtureInput(
            season="2026-27",
            gw=1,
            fixture=11,
            kickoff_time=datetime(2026, 8, 24, 19, tzinfo=UTC),
            code=101,
            expected_bonus=0.3,
            distribution=(0.5, 0.5),
            stage_a_league_average_team=True,
        ),
    )


def _manifest(row_count: int) -> ForecastArtifactManifest:
    contract = ContractIdentity(name="contract", version="1", sha256=HASH)
    return ForecastArtifactManifest(
        as_of=AS_OF,
        season="2026-27",
        gw_from=1,
        gw_to=2,
        row_count=row_count,
        roster_size=2,
        fixture_count=2,
        monte_carlo_draws=100,
        base_seed=7,
        fixture_points_support_max=34,
        freshness_cold_start=True,
        commit_sha="deadbeef",
        database_sha256=HASH,
        contracts={"scoring": contract, "minutes": contract},
        component_modes={"attacking": "coupled"},
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="capture-1",
            bootstrap_known_at=datetime(2026, 8, 3, tzinfo=UTC),
            bootstrap_payload_sha256=HASH,
            schedule_capture_ids=("capture-1",),
        ),
    )


def _artifact() -> ProspectivePointsArtifact:
    rows = build_artifact_rows(
        season="2026-27",
        gw_from=1,
        gw_to=2,
        players=_players(),
        fixtures=_fixtures(),
    )
    return ProspectivePointsArtifact(manifest=_manifest(len(rows)), rows=rows)


def test_complete_roster_gameweek_grain_convolves_dgw_and_preserves_blank() -> None:
    rows = _artifact().rows
    assert [(row.gw, row.code) for row in rows] == [(1, 101), (1, 202), (2, 101), (2, 202)]

    double = rows[0]
    assert double.fixture_ids == (10, 11)
    assert double.distribution == pytest.approx((0.125, 0.5, 0.375))
    assert double.expected_points == pytest.approx(1.25)
    assert double.expected_bonus == pytest.approx(0.5)
    assert double.stage_a_league_average_team is True

    blank = rows[-1]
    assert blank.fixture_ids == ()
    assert blank.distribution == (1.0,)
    assert blank.expected_points == 0.0


def test_availability_is_separate_overlay_and_nulls_survive_jsonl(tmp_path: Path) -> None:
    artifact = _artifact()
    row = artifact.rows[0]
    assert row.distribution == pytest.approx((0.125, 0.5, 0.375))
    assert row.expected_points == pytest.approx(1.25)
    assert row.availability_adjusted_expected_points == pytest.approx(0.3125)

    path = tmp_path / "nested" / "forecast.jsonl"
    write_artifact_atomic(path, artifact)
    parsed = read_artifact(path)
    assert parsed == artifact
    raw_row = json.loads(path.read_text(encoding="utf-8").splitlines()[2])
    assert raw_row["web_name"] is None
    assert raw_row["now_cost"] is None
    assert raw_row["chance_of_playing"] is None


def test_canonical_bytes_do_not_depend_on_input_order() -> None:
    first = _artifact()
    rows = build_artifact_rows(
        season="2026-27",
        gw_from=1,
        gw_to=2,
        players=tuple(reversed(_players())),
        fixtures=tuple(reversed(_fixtures())),
    )
    second = ProspectivePointsArtifact(manifest=_manifest(len(rows)), rows=rows)
    assert artifact_bytes(first) == artifact_bytes(second)


def test_absent_registry_binding_preserves_legacy_canonical_bytes() -> None:
    payload = artifact_bytes(_artifact())
    manifest = json.loads(payload.splitlines()[0])
    assert "selectable_player_registry_sha256" not in manifest["live_inputs"]
    assert artifact_bytes(read_artifact_bytes(payload)) == payload


def test_manifest_requires_complete_hashes_and_reconciled_row_count() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        ContractIdentity(name="bad", version="1", sha256="not-a-hash")
    with pytest.raises(ValidationError, match=r"roster\*horizon"):
        _manifest(row_count=3)


def test_duplicate_player_fixture_grain_is_rejected() -> None:
    duplicate = (*_fixtures(), _fixtures()[0])
    with pytest.raises(ArtifactError, match="duplicate player-fixture"):
        build_artifact_rows(
            season="2026-27",
            gw_from=1,
            gw_to=2,
            players=_players(),
            fixtures=duplicate,
        )


def test_atomic_replace_failure_preserves_old_artifact_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "forecast.jsonl"
    path.write_text("previous\n", encoding="utf-8")

    def fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        write_artifact_atomic(path, _artifact())

    assert path.read_text(encoding="utf-8") == "previous\n"
    assert list(tmp_path.glob(".forecast.jsonl.*.tmp")) == []
