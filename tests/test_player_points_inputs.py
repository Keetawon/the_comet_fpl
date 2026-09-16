"""Invented complete retained artifacts: no fitting and no real source evaluation."""

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.points_composition import ComponentDistributions, FixturePlayer
from fpl.types import Position
from fpl.validate import player_points_inputs as inputs
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    ReferencePlayerComponents,
)
from fpl.validate.minutes_baselines import TargetRow
from fpl.validate.player_saves_opportunity import predict_saves

OLD = datetime(2024, 5, 19, 15, tzinfo=UTC)
CUTOFF = datetime(2025, 8, 15, 19, tzinfo=UTC)
KNOWN = datetime(2026, 9, 7, tzinfo=UTC)
CONTROL = poisson_pmf(3)
ZERO = (1.0,) + (0.0,) * 10


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def phase_row(season, gw, fixture, team, kickoff, predicted):
    return {
        "key": f"{season}:{fixture}:{team}",
        "season": season,
        "gw": gw,
        "fixture": fixture,
        "team_code": team,
        "opponent_team_code": 203 - team,
        "was_home": team == 101,
        "kickoff_time": kickoff.isoformat(),
        "as_of": (OLD if season == "2024-25" else CUTOFF).isoformat(),
        "source_known_at": KNOWN.isoformat(),
        "source_capture_id": f"{fixture:064x}",
        "payload_sha256": f"{fixture + 2000:064x}",
        "maximum_state_source_event": None,
        "maximum_style_training_event": None,
        "predicted_shots": predicted,
        "observed_shots": 10,
        "predictors": [1.0],
    }


def synthetic_artifacts():
    prior = [
        phase_row("2024-25", 38, fixture, team, OLD, None)
        for fixture in range(1, 81)
        for team in (101, 102)
    ]
    targets = [
        phase_row("2025-26", 1, fixture, team, kickoff, shots)
        for fixture, kickoff, shots in ((901, CUTOFF, 12), (902, CUTOFF + timedelta(days=2), 18))
        for team in (101, 102)
    ]
    fits = []
    for season, gw, cutoff, rows, training in (
        ("2024-25", 38, OLD, prior, []),
        ("2025-26", 1, CUTOFF, targets, prior),
    ):
        fits.append(
            {
                "season": season,
                "gw": gw,
                "as_of": cutoff.isoformat(),
                "target_rows": len(rows),
                "prior_completed_rows": len(training),
                "event_time_violations": 0,
                "same_gameweek_violations": 0,
                "stacking_in_sample_rows": 0,
                "stage_fits": {
                    "volume": {
                        "training_rows": len(training),
                        "training_keys_sha256": digest(sorted(r["key"] for r in training)),
                        "maximum_training_event": OLD.isoformat() if training else None,
                        "maximum_training_prediction_cutoff": OLD.isoformat() if training else None,
                    }
                },
            }
        )
    phase = {
        "completed": True,
        "promotion_permitted": False,
        "evidence_class": inputs.EVIDENCE_CLASS,
        "provenance": {
            "clean_worktree": True,
            "known_at_rewritten": False,
            "database_sha256": "d" * 64,
            "git_head": "a" * 40,
        },
        "historical_chance_predictions": prior + targets,
        "historical_fit_provenance": fits,
    }
    precision = {
        "as_of": CUTOFF.isoformat(),
        "excluded_gw": ["2025-26", 1],
        "measured_sides": 160,
        "shots": 1600,
        "sot": 640,
        "fraction": 0.4,
        "maximum_training_event": OLD.isoformat(),
        "source_keys": [
            [r["season"], r["fixture"], r["team_code"], r["source_capture_id"]] for r in prior
        ],
    }
    rows = []
    for source in targets:
        if source["team_code"] != 102:
            continue
        rate = source["predicted_shots"] * 0.4 * 0.5
        rows.append(
            {
                "season": "2025-26",
                "gw": 1,
                "fixture": source["fixture"],
                "code": 10,
                "team_code": 101,
                "as_of": CUTOFF.isoformat(),
                "kickoff": source["kickoff_time"],
                "was_home": True,
                "upstream_key": source["key"],
                "upstream_hash": "pending",
                "maximum_upstream_training_event": OLD.isoformat(),
                "save_fraction": 0.5,
                "pmfs": {"incumbent": list(CONTROL), "candidate": list(poisson_pmf(rate))},
                "candidate_rate": rate,
                "expected_sot_faced": rate / 0.5,
                "fallback": False,
                "observed_minutes": 90,
                "saves": 99,
                "original_capture": {
                    **{k: source[k] for k in ("season", "gw", "fixture", "team_code")},
                    "capture_id": source["source_capture_id"],
                    "payload_sha256": source["payload_sha256"],
                    "known_at": source["source_known_at"],
                    "kickoff": source["kickoff_time"],
                },
            }
        )
    provenance = {
        "candidate": inputs.NAME,
        "evidence_class": inputs.EVIDENCE_CLASS,
        "clean_worktree": True,
        "production_promotion": False,
        "known_at_rewritten": False,
        "database_sha256": "d" * 64,
        "git_head": "b" * 40,
        "source_sha256": {
            name: hashlib.sha256(Path(inspect.getfile(fn)).read_bytes()).hexdigest()
            for fn, name in (
                (predict_saves, "src/fpl/validate/player_saves_opportunity.py"),
                (poisson_pmf, "src/fpl/models/attacking_baselines.py"),
            )
        },
    }
    return phase, {"precision": precision, "rows": rows}, provenance


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(inputs, "PHASE_A_ROWS", 164)
    monkeypatch.setattr(inputs, "PHASE_A_FOLDS", 2)
    monkeypatch.setattr(inputs, "H_FOLDS", 1)
    monkeypatch.setattr(inputs, "H_ROWS_BY_SEASON", {"2025-26": 2})

    def write(mutate=None):
        phase, fold, provenance = synthetic_artifacts()
        if mutate:
            mutate(phase, fold, provenance)
        chance_path = tmp_path / "phase_a.json"
        chance_path.write_text(json.dumps(phase), encoding="utf-8")
        chance_hash = hashlib.sha256(chance_path.read_bytes()).hexdigest()
        monkeypatch.setattr(inputs, "PHASE_A_SHA256", chance_hash)
        for row in fold["rows"]:
            row["upstream_hash"] = chance_hash
        fold_path = tmp_path / "2025-26-gw01.json"
        fold_path.write_text(json.dumps(fold), encoding="utf-8")
        result = {
            "completed": True,
            "promotion_permitted": False,
            "provenance": provenance,
            "folds": [
                {
                    "file": fold_path.name,
                    "sha256": hashlib.sha256(fold_path.read_bytes()).hexdigest(),
                    "rows": len(fold["rows"]),
                }
            ],
            "rows": fold["rows"],
            "coverage": {
                "target_identity_sha256": digest(
                    sorted((r["season"], r["gw"], r["fixture"], r["code"]) for r in fold["rows"])
                )
            },
        }
        (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        path = tmp_path / "result.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        monkeypatch.setattr(
            inputs, "H_RESULT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
        )
        return path, chance_path

    return write


def reference():
    rows = []
    for fixture, kickoff in ((901, CUTOFF), (902, CUTOFF + timedelta(days=2))):
        for team, code in ((1, 10), (1, 11), (2, 20), (2, 21)):
            target = TargetRow(
                "2025-26", 1, fixture, kickoff, code, Position.GK, team, 3 - team, team == 1
            )
            components = ComponentDistributions(
                Position.GK, (1, 0, 0, 0), ZERO, ZERO, ZERO, CONTROL, 0
            )
            rows.append(
                ReferencePlayerComponents(
                    target,
                    100 + team,
                    FixturePlayer(code, components, 0, 2),
                    False,
                    False,
                    (),
                    (),
                    "{}",
                    None,
                    None,
                    0,
                    0,
                    0,
                    0,
                    False,
                )
            )
    return DevelopmentReferenceComponents(
        "2025-26",
        1,
        CUTOFF,
        tuple(rows),
        (),
        json.dumps({"component_parameters": {inputs.CURRENT_SAVES_NAME: {"save_rate": 0.5}}}),
        "{}",
    )


def test_load_reproduces_retained_probabilities_and_all_gks_without_appearance(artifacts):
    projection = inputs.load_saves_projection(*artifacts())
    actual = projection.project(reference(), 901)
    assert set(actual) == {10, 11, 20, 21}
    assert set(actual.values()) == {poisson_pmf(12 * 0.4 * 0.5)}
    assert projection.reproduction["retained_h_rows"] == 2
    assert projection.reproduction["maximum_absolute_pmf_difference"] == 0
    assert projection.provenance["actual_appearance_used_to_apply"] is False
    assert len(projection.source_files) == 6
    assert not hasattr(projection, "observed_minutes")


def test_dgw_fixture_keys_keep_different_probabilities_for_same_keeper(artifacts):
    projection = inputs.load_saves_projection(*artifacts())
    first, second = (projection.project(reference(), fixture)[10] for fixture in (901, 902))
    assert first == poisson_pmf(12 * 0.4 * 0.5)
    assert second == poisson_pmf(18 * 0.4 * 0.5)
    assert first != second


def test_target_label_and_minutes_changes_do_not_change_projection(artifacts):
    first = inputs.load_saves_projection(*artifacts()).project(reference(), 901)

    def changed_labels(_phase, fold, _provenance):
        for row in fold["rows"]:
            row["observed_minutes"], row["saves"] = 0, None

    projection = inputs.load_saves_projection(*artifacts(changed_labels))
    ref = reference()
    rows = tuple(
        replace(
            r,
            player=replace(r.player, components=replace(r.player.components, minutes=(0, 0, 0, 1))),
        )
        for r in ref.rows
    )
    assert projection.project(replace(ref, rows=rows), 901) == first


@pytest.mark.parametrize("shots", [None, 0.0])
def test_missing_opportunity_is_incumbent_and_explicit_zero_is_point_mass(artifacts, shots):
    def change_volume(phase, fold, _provenance):
        for row in phase["historical_chance_predictions"]:
            if row["season"] == "2025-26":
                row["predicted_shots"] = shots
        for row in fold["rows"]:
            row["pmfs"]["candidate"] = list(CONTROL if shots is None else ZERO)
            row["fallback"] = shots is None
            row["candidate_rate"] = row["expected_sot_faced"] = None if shots is None else 0

    projection = inputs.load_saves_projection(*artifacts(change_volume))
    assert set(projection.project(reference(), 901).values()) == {
        CONTROL if shots is None else ZERO
    }


@pytest.mark.parametrize("which", ["result.json", "phase_a.json", "2025-26-gw01.json"])
def test_every_external_artifact_hash_is_enforced(artifacts, which):
    paths = artifacts()
    path = paths[0].parent / which
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA256 differs"):
        inputs.load_saves_projection(*paths)


@pytest.mark.parametrize(
    "defect",
    [
        "capture",
        "precision_source",
        "precision_fraction",
        "save_fraction",
        "candidate",
        "duplicate",
        "phase_cutoff",
        "phase_training",
    ],
)
def test_inconsistent_retained_evidence_fails_closed(artifacts, defect):
    def mutate(phase, fold, _provenance):
        if defect == "capture":
            fold["rows"][0]["original_capture"]["payload_sha256"] = "e" * 64
        elif defect == "precision_source":
            fold["precision"]["source_keys"][0][3] = "e" * 64
        elif defect == "precision_fraction":
            fold["precision"]["fraction"] = 0.5
        elif defect == "save_fraction":
            fold["rows"][0]["save_fraction"] = 0.6
        elif defect == "candidate":
            fold["rows"][0]["pmfs"]["candidate"] = list(ZERO)
        elif defect == "duplicate":
            phase["historical_chance_predictions"][-1] = deepcopy(
                phase["historical_chance_predictions"][-2]
            )
        elif defect == "phase_cutoff":
            phase["historical_chance_predictions"][-1]["as_of"] = (
                CUTOFF + timedelta(hours=1)
            ).isoformat()
        else:
            phase["historical_fit_provenance"][-1]["stage_fits"]["volume"][
                "training_keys_sha256"
            ] = "e" * 64

    messages = {
        "capture": "capture identity",
        "precision_source": "precision source identity",
        "precision_fraction": "ratio/fallback",
        "save_fraction": "one unchanged",
        "candidate": "zero tolerance",
        "duplicate": "duplicate/missing row",
        "phase_cutoff": "reciprocal fixture/cutoff",
        "phase_training": "training-key",
    }
    with pytest.raises(ValueError, match=messages[defect]):
        inputs.load_saves_projection(*artifacts(mutate))


@pytest.mark.parametrize("defect", ["clock", "venue", "incumbent", "fraction", "duplicate"])
def test_projection_rejects_mismatched_current_reference(artifacts, defect):
    projection = inputs.load_saves_projection(*artifacts())
    ref = reference()
    rows = list(ref.rows)
    if defect == "clock":
        ref = replace(ref, as_of=CUTOFF + timedelta(seconds=1))
    elif defect == "fraction":
        ref = replace(
            ref,
            diagnostics_json=json.dumps(
                {"component_parameters": {inputs.CURRENT_SAVES_NAME: {"save_rate": 0.6}}}
            ),
        )
    elif defect == "duplicate":
        ref = replace(ref, rows=(*ref.rows, ref.rows[0]))
    elif defect == "venue":
        rows[0] = replace(rows[0], target=replace(rows[0].target, was_home=False))
        ref = replace(ref, rows=tuple(rows))
    else:
        rows[0] = replace(
            rows[0],
            player=replace(
                rows[0].player, components=replace(rows[0].player.components, saves=ZERO)
            ),
        )
        ref = replace(ref, rows=tuple(rows))
    messages = {
        "clock": "cutoff differ",
        "fraction": "save fractions differ",
        "duplicate": "duplicate fixture roster",
        "venue": "opponent/venue/kickoff",
        "incumbent": "zero tolerance",
    }
    with pytest.raises(ValueError, match=messages[defect]):
        projection.project(ref, 901)


def test_loader_and_projection_never_fit_or_compose_points(artifacts, monkeypatch):
    from fpl.models import points_composition
    from fpl.models.gk_saves_v1 import GkSavesV1
    from fpl.validate import player_saves_opportunity

    def forbidden(*_args, **_kwargs):
        raise AssertionError("fitting is forbidden during saved projection")

    monkeypatch.setattr(GkSavesV1, "fit", forbidden)
    monkeypatch.setattr(player_saves_opportunity, "fit_precision", forbidden)
    monkeypatch.setattr(points_composition, "compose_fixture_full_points", forbidden)
    assert len(inputs.load_saves_projection(*artifacts()).project(reference(), 901)) == 4
