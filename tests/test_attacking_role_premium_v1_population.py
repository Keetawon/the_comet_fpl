"""Population identity and label isolation; no predictive scoring or model fitting."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from fpl.features.attacking_role_premium_v1 import UsageObservation, UsageTarget
from fpl.validate.attacking_role_premium_v1 import (
    PopulationRow,
    RegistryPlayer,
    ScheduledFixture,
    SourceSnapshot,
    _integer,
    _observation,
    build_population,
    load_population,
    reconcile_audit,
    target_key,
)

AS_OF = datetime(2023, 8, 16, 2, tzinfo=UTC)
KICKOFF = datetime(2023, 8, 18, 19, tzinfo=UTC)
OBSERVED = datetime(2023, 8, 23, 2, tzinfo=UTC)


def row(*, code: int = 101, fixture: int = 8, xg: float = 0.2) -> PopulationRow:
    observation = UsageObservation(
        season="2023-24",
        gameweek=2,
        fixture_id=fixture,
        kickoff_time=KICKOFF,
        player_code=code,
        fpl_position="DEF",
        minutes=50,
        starts=1,
        xg=xg,
        xa=0.1,
        source_known_at=OBSERVED,
        available_at=OBSERVED,
        evidence_class="ARCHIVED_AS_OF",
        source_snapshot_id="b" * 40,
        source_sha256="c" * 64,
    )
    target = UsageTarget("2023-24", 2, fixture, KICKOFF, code, "DEF", 10, 20, "HOME")
    return PopulationRow(observation, target, 1)


def snapshot(*, code: int = 101, team: int = 10, position: str = "DEF") -> SourceSnapshot:
    return SourceSnapshot(
        snapshot_id="a" * 40,
        known_at=AS_OF,
        capture_known_at=datetime(2026, 9, 8, tzinfo=UTC),
        registry=MappingProxyType({code: RegistryPlayer(1, code, position, team)}),
        fixtures=MappingProxyType({8: ScheduledFixture(8, 2, KICKOFF, 10, 20)}),
        hashes=MappingProxyType(
            dict.fromkeys(("stats", "registry", "fixtures", "teams"), "c" * 64)
        ),
    )


def test_targets_have_no_actual_opportunity_or_exposure_labels() -> None:
    population = build_population((row(),), (snapshot(),), (2,))
    target = population.folds[0].targets[0]
    assert set(asdict(target)) == {
        "season",
        "gameweek",
        "fixture_id",
        "kickoff_time",
        "player_code",
        "fpl_position",
        "team_code",
        "opponent_team_code",
        "venue",
    }
    label = population.outcomes[target_key(target)]
    assert (label.xg, label.xa, label.minutes, label.starts) == (0.2, 0.1, 50, 1)
    with pytest.raises(TypeError):
        population.outcomes[target_key(target)] = label  # type: ignore[index]
    assert population.receipt["paired_minutes_ge_45"] == 1


def test_target_outcome_change_never_changes_population_identity_fingerprint() -> None:
    first = build_population((row(),), (snapshot(),), (2,))
    changed = build_population((row(xg=9.0),), (snapshot(),), (2,))
    assert first.folds == changed.folds
    assert first.receipt["population_sha256"] == changed.receipt["population_sha256"]
    assert first.outcomes != changed.outcomes


def test_latest_labels_are_separate_from_all_original_history_versions() -> None:
    first = row()
    revised = replace(
        first,
        observation=replace(
            first.observation,
            xg=0.8,
            source_known_at=datetime(2023, 8, 24, tzinfo=UTC),
            available_at=datetime(2023, 8, 24, tzinfo=UTC),
            source_snapshot_id="d" * 40,
        ),
    )
    result = build_population((first, revised), (snapshot(),), (2,))
    assert result.outcomes[target_key(first.target_identity)].xg == 0.8
    assert tuple(r.xg for r in result.history) == (0.2, 0.8)


def test_duplicate_normalized_version_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate normalized"):
        build_population((row(), row()), (snapshot(),), (2,))


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (snapshot(code=999), "NO_CUTOFF_REGISTRY"),
        (snapshot(team=20), "CUTOFF_CLUB_MISMATCH"),
        (snapshot(position="MID"), "CUTOFF_POSITION_MISMATCH"),
    ],
)
def test_exact_registry_position_and_temporal_club_exclusions(
    source: SourceSnapshot,
    reason: str,
) -> None:
    result = build_population((row(),), (source,), (2,))
    assert not result.folds[0].targets
    assert result.receipt["exclusions"] == {reason: 1}
    assert result.receipt["target_rows"] == 0


def test_target_population_must_match_the_whole_cutoff_schedule() -> None:
    source = snapshot()
    source = replace(
        source, fixtures={**source.fixtures, 99: ScheduledFixture(99, 2, KICKOFF, 30, 40)}
    )
    result = build_population((row(),), (source,), (2,))
    assert not result.folds
    assert result.receipt["exclusions"] == {"NO_WHOLE_FUTURE_GW_SNAPSHOT": 1}


def test_later_snapshot_cannot_resolve_earlier_whole_gw_exclusion() -> None:
    source = snapshot()
    early = replace(
        source, fixtures={**source.fixtures, 99: ScheduledFixture(99, 2, KICKOFF, 30, 40)}
    )
    later = replace(source, snapshot_id="e" * 40, known_at=OBSERVED)
    assert (
        build_population((row(),), (early,), (2,)).receipt
        == build_population((row(),), (early, later), (2,)).receipt
    )


def test_pre_cutoff_schedule_kickoff_retained_in_target_descriptor() -> None:
    source = snapshot()
    scheduled = replace(source.fixtures[8], kickoff_time=datetime(2023, 8, 18, 20, tzinfo=UTC))
    source = replace(source, fixtures={8: scheduled})
    population = build_population((row(),), (source,), (2,))
    assert population.folds[0].targets[0].kickoff_time == scheduled.kickoff_time
    assert population.history[0].kickoff_time == KICKOFF


def test_missing_minutes_and_xa_are_not_zero_filled() -> None:
    original = row()
    missing = replace(original, observation=replace(original.observation, minutes=None, xa=None))
    result = build_population((missing,), (snapshot(),), (2,))
    label = result.outcomes[target_key(original.target_identity)]
    assert label.xa is None and label.minutes is None
    assert result.receipt["paired_minutes_ge_45"] == 0


def test_audit_disagreement_fails_closed() -> None:
    population = build_population((row(),), (snapshot(),), (2,))
    audit: dict[str, Any] = {"folds": [{"gw": 2, "status": "NO_WHOLE_FUTURE_GW_SNAPSHOT"}]}
    with pytest.raises(ValueError, match="schedule exclusion"):
        reconcile_audit(population, audit)


def test_frozen_input_hash_rejected_before_source_loading(tmp_path: Path) -> None:
    paths = [tmp_path / name for name in ("manifest", "audit", "scope", "observations")]
    for path in paths:
        path.write_bytes(b"altered frozen artifact")
    with pytest.raises(ValueError, match="artifact hash changed"):
        load_population(*paths)


def test_integral_decimal_gameweek_and_absence_are_distinct() -> None:
    assert _integer("2.0") == 2
    assert _integer("", optional=True) is None
    assert _integer(0) == 0
    with pytest.raises(ValueError, match="invalid exact"):
        _integer("2.1")


def raw_observation() -> tuple[dict[str, Any], SourceSnapshot]:
    source = replace(snapshot(), known_at=OBSERVED)
    raw = {
        **asdict(row().target_identity),
        "kickoff_time": KICKOFF.isoformat(),
        "source_snapshot_id": source.snapshot_id,
        "source_known_at": OBSERVED.isoformat(),
        "available_at": OBSERVED.isoformat(),
        "capture_known_at": source.capture_known_at.isoformat(),
        "source_sha256": "c" * 64,
        "evidence_class": "ARCHIVED_AS_OF",
        "source_element_id": 1,
        "provenance": dict(source.hashes),
        "minutes": 50,
        "starts": 1,
        "expected_goals": 0.2,
        "expected_assists": None,
        "shots": None,
        "shots_on_target": None,
        "box_touches": None,
        "key_passes": None,
    }
    return raw, source


@pytest.mark.parametrize(
    "field",
    ["source_known_at", "available_at", "capture_known_at", "source_sha256", "evidence_class"],
)
def test_observation_availability_and_provenance_are_bound(field: str) -> None:
    raw, source = raw_observation()
    assert _observation(raw, {source.snapshot_id: source}).observation.xa is None
    raw[field] = {"source_sha256": "d" * 64, "evidence_class": "RETROSPECTIVE_DEVELOPMENT"}.get(
        field,
        "2023-08-11T00:00:00Z",
    )
    with pytest.raises(ValueError, match="availability/provenance"):
        _observation(raw, {source.snapshot_id: source})


def test_no_name_matching_can_resolve_a_different_player_code() -> None:
    raw, source = raw_observation()
    raw["player_code"] = 999
    raw["web_name"] = "Same Name"
    with pytest.raises(KeyError):
        _observation(raw, {source.snapshot_id: source})


def test_deterministic_population_replay_and_input_order() -> None:
    first, second = row(), row(code=202)
    source = snapshot()
    source = replace(source, registry={**source.registry, 202: RegistryPlayer(2, 202, "DEF", 10)})
    left = build_population((first, second), (source,), (2,))
    right = build_population((second, first), (source,), (2,))
    assert left.folds == right.folds and left.receipt == right.receipt
    assert left.history == right.history


def test_prior_coverage_uses_original_available_versions_and_excludes_whole_target_gw() -> None:
    target = row()
    before = datetime(2023, 8, 12, tzinfo=UTC)
    original = PopulationRow(
        replace(
            target.observation,
            fixture_id=1,
            gameweek=1,
            kickoff_time=before,
            starts=None,
            available_at=AS_OF,
            source_known_at=AS_OF,
        ),
        replace(target.target_identity, fixture_id=1, gameweek=1, kickoff_time=before),
        1,
    )
    history = []
    for fixture_id in (1, 2, 3):
        first = replace(
            original,
            observation=replace(original.observation, fixture_id=fixture_id),
            target_identity=replace(original.target_identity, fixture_id=fixture_id),
        )
        history.extend(
            (
                first,
                replace(
                    first,
                    observation=replace(
                        first.observation,
                        starts=1,
                        source_snapshot_id="f" * 40,
                    ),
                ),
            )
        )
    same_gw = replace(
        original,
        observation=replace(
            original.observation,
            fixture_id=9,
            gameweek=2,
        ),
        target_identity=replace(original.target_identity, fixture_id=9, gameweek=2),
    )
    same_gw_final = replace(
        same_gw,
        observation=replace(
            same_gw.observation,
            kickoff_time=KICKOFF,
            available_at=OBSERVED,
            source_known_at=OBSERVED,
            source_snapshot_id="f" * 40,
        ),
        target_identity=replace(same_gw.target_identity, kickoff_time=KICKOFF),
    )
    source = snapshot()
    source = replace(
        source,
        fixtures={
            **source.fixtures,
            9: ScheduledFixture(9, 2, KICKOFF, 10, 20),
        },
    )
    population = build_population(
        (target, *history, same_gw, same_gw_final),
        (source,),
        (2,),
    )
    counts = population.receipt["folds"][0]["counts"]
    assert counts["prior_history_present"] == 2
    assert counts["prior_starts_ge_3"] == 0
    assert population.receipt["players_with_prior_starts"] == {"3": 0, "5": 0, "10": 0}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_element_id", 2),
        ("fpl_position", "MID"),
        ("team_code", 20),
        ("opponent_team_code", 10),
    ],
)
def test_normalized_identity_cannot_override_same_snapshot_evidence(field: str, value: Any) -> None:
    raw, source = raw_observation()
    raw[field] = value
    with pytest.raises(ValueError, match="identity contradiction"):
        _observation(raw, {source.snapshot_id: source})
