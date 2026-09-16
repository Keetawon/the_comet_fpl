"""Offline complete typed-reference round-trip, provenance and write-once guards."""

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.points_composition import ComponentDistributions, FixturePlayer
from fpl.types import Position
from fpl.validate import current_component_reference_cache as cache
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    ReferenceMinutesRow,
    ReferencePlayerComponents,
    ValidatedMinutesControlCache,
    ValidatedMinutesControlFold,
)
from fpl.validate.minutes_baselines import TargetRow

NOW = datetime(2025, 9, 1, tzinfo=UTC)


def sample(gw=1):
    cutoff = NOW + timedelta(days=7 * gw)
    targets = tuple(
        TargetRow("2025-26", gw, gw, cutoff, n, Position.DEF, n, 3 - n, n == 1) for n in (1, 2)
    )
    minutes = (0.1, 0.2, 0.3, 0.4)
    original = tuple(
        ReferenceMinutesRow(t, t.team_id * 100, minutes, False, False, "{}") for t in targets
    )
    fold = ValidatedMinutesControlFold(
        "2025-26", gw, cutoff, original, "a" * 64, "b" * 64, "c" * 64, "{}"
    )
    players = []
    for t in targets:
        component = ComponentDistributions(
            t.position,
            minutes,
            poisson_pmf(0.2),
            poisson_pmf(0.1),
            poisson_pmf(1.2),
            poisson_pmf(0),
            0.25,
        )
        players.append(
            ReferencePlayerComponents(
                t,
                t.team_id * 100,
                FixturePlayer(t.code, component, -1.5, 2),
                False,
                False,
                (),
                (),
                "{}",
                None,
                0,
                0.2,
                0.1,
                0.18,
                0.09,
                False,
            )
        )
    reference = DevelopmentReferenceComponents(
        "2025-26",
        gw,
        cutoff,
        tuple(players),
        ((gw, 100, poisson_pmf(1.2)), (gw, 200, poisson_pmf(1.2))),
        json.dumps(
            {
                "maximum_prior_kickoff": (cutoff - timedelta(days=7)).isoformat(),
                "minutes_refitted": False,
                "same_gw_history_rows": 0,
                "bps": {"coefficients": [1.0, 2.0]},
            }
        ),
        json.dumps(
            {
                "minutes_manifest_sha256": fold.manifest_sha256,
                "minutes_fold_sha256": fold.fold_sha256,
                "database_sha256": fold.database_sha256,
            }
        ),
    )
    return reference, fold


def test_full_reference_round_trip_is_exact_and_preserves_enum_tuples_nulls():
    original, fold = sample()
    result = cache.decode_reference(json.loads(json.dumps(cache.encode_reference(original))))
    assert result == original
    assert result.rows[0].player.components.position is Position.DEF
    assert isinstance(result.rows[0].player.components.minutes, tuple)
    assert isinstance(result.rows[0].player.components.goals, tuple)
    assert isinstance(result.team_scored, tuple)
    assert result.rows[0].raw_goal_signal is None
    assert result.rows[0].raw_assist_signal == 0
    assert result.rows[0].player.residual_mean == -1.5
    assert result.rows[0].player.components.disciplinary is None
    assert result.diagnostics_json == original.diagnostics_json
    cache.validate_reference(result, fold)


@pytest.mark.parametrize(
    "corruption",
    [
        "outcome",
        "unknown_position",
        "minutes_width",
        "mass",
        "negative",
        "nan",
        "bps_nan",
        "sigma_negative",
        "cards",
        "player_identity",
        "signal_nan",
        "diagnostics_nan",
        "evidence",
        "timezone",
    ],
)
def test_bad_or_target_bearing_reference_is_rejected(corruption):
    raw = cache.encode_reference(sample()[0])
    row = raw["rows"][0]
    component = row["player"]["components"]
    if corruption == "outcome":
        row["target"]["goals_scored"] = 1
    elif corruption == "unknown_position":
        component["position"] = "CAM"
    elif corruption == "minutes_width":
        component["minutes"] = [0, 1]
    elif corruption == "mass":
        component["goals"] = [0.0] * 11
    elif corruption == "negative":
        component["goals"][1] = -0.1
    elif corruption == "nan":
        component["dc_hit_probability"] = float("nan")
    elif corruption == "bps_nan":
        row["player"]["residual_mean"] = float("nan")
    elif corruption == "sigma_negative":
        row["player"]["residual_sigma"] = -1
    elif corruption == "cards":
        component["disciplinary"] = {"by_minutes_bin": [[1, 0, 0]] * 4}
    elif corruption == "player_identity":
        row["player"]["code"] = 999
    elif corruption == "signal_nan":
        row["raw_assist_signal"] = float("nan")
    elif corruption == "diagnostics_nan":
        raw["diagnostics_json"] = '{"hidden":NaN}'
    elif corruption == "evidence":
        raw["promotion_permitted"] = True
    else:
        raw["as_of"] = "2025-01-01T00:00:00"
    with pytest.raises(
        ValueError,
        match=r"reference|Reference|TargetRow|PMF|Position|BPS|current|identity|timezone|JSON",
    ):
        cache.decode_reference(raw)


@pytest.mark.parametrize(
    "field", ["target", "minutes", "proxy", "lineage", "cutoff", "future", "refit", "source"]
)
def test_valid_pmf_still_must_match_exact_reference_roster_and_provenance(field):
    value, fold = sample()
    first = value.rows[0]
    if field == "target":
        value = replace(
            value, rows=(replace(first, target=replace(first.target, code=999)), *value.rows[1:])
        )
    elif field == "minutes":
        comp = replace(first.player.components, minutes=(1, 0, 0, 0))
        value = replace(
            value,
            rows=(replace(first, player=replace(first.player, components=comp)), *value.rows[1:]),
        )
    elif field == "proxy":
        value = replace(value, rows=(replace(first, direct_price_proxy=True), *value.rows[1:]))
    elif field == "lineage":
        value = replace(
            value,
            rows=(replace(first, selector_provenance_json='{"changed":true}'), *value.rows[1:]),
        )
    elif field == "cutoff":
        value = replace(value, as_of=NOW)
    elif field == "source":
        provenance = json.loads(value.provenance_json)
        provenance["database_sha256"] = "x" * 64
        value = replace(value, provenance_json=json.dumps(provenance))
    else:
        diagnostics = json.loads(value.diagnostics_json)
        if field == "future":
            diagnostics["maximum_prior_kickoff"] = value.as_of.isoformat()
        else:
            diagnostics["minutes_refitted"] = True
        value = replace(value, diagnostics_json=json.dumps(diagnostics))
    with pytest.raises(ValueError, match=r"reference|duplicate"):
        cache.validate_reference(value, fold)


def test_cache_refuses_existing_output_before_any_baseline_fit(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no model or database access expected")

    monkeypatch.setattr(cache, "build_reference_components", forbidden)
    with pytest.raises(ValueError, match="write-once"):
        cache.build_cache(
            root=tmp_path, db=tmp_path / "a.duckdb", minutes_cache=tmp_path, output=tmp_path
        )


def test_dirty_worktree_refused_before_reserving_claim(tmp_path, monkeypatch):
    @contextmanager
    def connection(*args, **kwargs):
        yield object()

    monkeypatch.setattr(cache, "connect", connection)

    def dirty(*args, **kwargs):
        raise ValueError("dirty worktree")

    monkeypatch.setattr(cache, "git_clean_head", dirty)
    with pytest.raises(ValueError, match="dirty"):
        cache.build_cache(
            root=tmp_path / "repo",
            db=tmp_path / "source.duckdb",
            minutes_cache=tmp_path,
            output=tmp_path / "newcache",
        )
    assert not (tmp_path / "newcache").exists()


def test_failure_retains_claim_and_finished_batch_no_resume(tmp_path, monkeypatch):
    @contextmanager
    def connection(*args, **kwargs):
        yield object()

    monkeypatch.setattr(cache, "connect", connection)
    monkeypatch.setattr(cache, "snapshot", lambda *args: {"fixed": True})
    values = [sample(1), sample(2)]
    monkeypatch.setattr(
        cache,
        "read_minutes_control_cache",
        lambda *args, **kwargs: ValidatedMinutesControlCache(tuple(f for _, f in values), "{}"),
    )
    claim = tmp_path / "retainedclaim.json"

    def reserve(*args):
        cache.publish_json(claim, {"reserved": True})
        return claim

    monkeypatch.setattr(cache, "reserve_program_claim", reserve)

    def build(_con, fold):
        if fold.gw == 2:
            raise ValueError("synthetic reference failure")
        return values[0][0]

    monkeypatch.setattr(cache, "build_reference_components", build)
    output = tmp_path / "newcache"
    with pytest.raises(ValueError, match="synthetic reference failure"):
        cache.build_cache(
            root=tmp_path / "repo", db=tmp_path / "source", minutes_cache=tmp_path, output=output
        )
    failure = json.loads((output / "failure.json").read_bytes())
    assert claim.is_file() and (output / "2025-26-gw01.json").is_file()
    assert failure["claim_preserved"] and not failure["retry_permitted"]
    assert len(failure["completed_folds"]) == 1
    assert not (output / "manifest.json").exists()


def test_manifest_hash_guard_runs_before_reference_reader_or_any_fit(tmp_path):
    cache.publish_json(tmp_path / "manifest.json", {"tampered": True})
    with pytest.raises(ValueError, match="manifest hash"):
        cache.load_component_reference_cache(
            tmp_path,
            root=tmp_path,
            db=tmp_path / "none",
            minutes_cache=tmp_path,
            expected_manifest_sha256="a" * 64,
        )


def test_postflight_revalidates_external_minutes_files_before_manifest(tmp_path, monkeypatch):
    @contextmanager
    def connection(*args, **kwargs):
        yield object()

    monkeypatch.setattr(cache, "connect", connection)
    monkeypatch.setattr(cache, "snapshot", lambda *args: {"fixed": True})
    reference, fold = sample(1)
    calls = 0

    def read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("external minutes fold content SHA changed")
        return ValidatedMinutesControlCache((fold,), "{}")

    monkeypatch.setattr(cache, "read_minutes_control_cache", read)
    monkeypatch.setattr(cache, "build_reference_components", lambda *args: reference)
    monkeypatch.setattr(cache, "reserve_program_claim", lambda *args: tmp_path / "claim.json")
    output = tmp_path / "reference"
    with pytest.raises(ValueError, match="external minutes fold content SHA"):
        cache.build_cache(
            root=tmp_path / "repo", db=tmp_path / "source", minutes_cache=tmp_path, output=output
        )
    assert calls == 2
    failure = json.loads((output / "failure.json").read_bytes())
    assert len(failure["completed_folds"]) == 1
    assert not (output / "manifest.json").exists()


def test_no_full_points_draw_or_minutes_model_import():
    source = Path(cache.__file__).read_text(encoding="utf-8")
    assert "compose_fixture_full_points" not in source
    assert "ConcentrationAdaptive" not in source


@pytest.fixture
def retained_typed_cache(tmp_path, monkeypatch):
    # The upstream minutes validator is independently tested on all86,755 rows.
    # This fixture isolates all114 downstream fold receipts with tiny synthetic rosters.
    output = tmp_path / "reference"
    output.mkdir()
    values = [sample(gw) for gw in range(1, 115)]
    reference_db = tmp_path / "source.duckdb"
    cache.publish_json(reference_db, {"synthetic_not_duckdb": True})
    provenance = {
        "evidence_class": cache.EVIDENCE_CLASS,
        "worktree_clean": True,
        "promotion_permitted": False,
        "minutes_refitted": False,
        "challenger_fitted": False,
        "source_sha256": {},
        "database_sha256": cache.file_sha256(reference_db),
    }
    cache.publish_json(output / "provenance.json", provenance)
    receipts = []
    for reference, fold in values:
        name = f"2025-26-gw{fold.gw:02d}.json"
        cache.publish_json(output / name, cache.encode_reference(reference))
        receipts.append(
            {
                "file": name,
                "season": fold.season,
                "gw": fold.gw,
                "rows": len(fold.rows),
                "sha256": cache.file_sha256(output / name),
            }
        )
    manifest = {
        "completed": True,
        "identity": cache.NAME,
        "reference": cache.REFERENCE,
        "typed_round_trip_exact": True,
        "points_monte_carlo_drawn": False,
        "counts": cache.EXPECTED_COUNTS,
        "provenance": provenance,
        "folds": receipts,
    }
    cache.publish_json(output / "manifest.json", manifest)
    monkeypatch.setattr(cache, "source_pins", lambda root: {})
    monkeypatch.setattr(
        cache,
        "read_minutes_control_cache",
        lambda *args, **kwargs: ValidatedMinutesControlCache(tuple(f for _, f in values), "{}"),
    )
    kwargs = {
        "root": tmp_path,
        "db": reference_db,
        "minutes_cache": tmp_path,
        "expected_manifest_sha256": cache.file_sha256(output / "manifest.json"),
    }
    return output, kwargs, values


def test_all114_receipts_decode_without_any_fit(retained_typed_cache, monkeypatch):
    output, kwargs, values = retained_typed_cache

    def forbidden(*args, **kwargs):
        raise AssertionError("reader must not fit a model")

    monkeypatch.setattr(cache, "build_reference_components", forbidden)
    result = cache.load_component_reference_cache(output, **kwargs)
    assert result == tuple(reference for reference, _fold in values)
    assert len(result) == 114


def test_even_last_fold_hash_corruption_is_rejected(retained_typed_cache):
    output, kwargs, _ = retained_typed_cache
    path = output / "2025-26-gw114.json"
    # Test-owned fixture corruption, not any retained project evidence.
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="fold content SHA"):
        cache.load_component_reference_cache(output, **kwargs)


def test_original_database_drift_and_unresolved_wal_rejected(retained_typed_cache):
    output, kwargs, _ = retained_typed_cache
    cache.publish_json(Path(str(kwargs["db"]) + ".wal"), {"synthetic": True})
    with pytest.raises(ValueError, match=r"database changed|WAL"):
        cache.load_component_reference_cache(output, **kwargs)
