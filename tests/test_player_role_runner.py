"""Offline role runner guards and hand-computable source/denominator boundaries."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from fpl.jobs.competitive_participation_pilot import file_sha256, publish_json
from fpl.storage.competitive_workload import semantic_identity
from fpl.validate import dev_player_role_history as runner


def record(fixture: int = 1) -> dict[str, Any]:
    kickoff = datetime(2025, 8, 1 + fixture * 7, tzinfo=UTC).isoformat()
    rows = []
    for code, role, team in ((1, "Defender", 3), (2, "Forward", 7), (3, "Substitute", 3)):
        started = code != 3
        rows.append(
            {
                "code": code,
                "provider_player_id": code + 100,
                "team_code": team,
                "provider_team_id": team,
                "started": started,
                "provider_position": role,
                "membership": "starting_xi" if started else "bench",
            }
        )
    result = {
        "season": "2025-26",
        "competition_id": 8,
        "match_id": 1000 + fixture,
        "fpl_fixture": fixture,
        "fpl_gw": fixture,
        "kickoff": kickoff,
        "capture_known_at": "2026-09-07T08:00:00+00:00",
        "interpretation_known_at": "2026-09-07T09:00:00+00:00",
        "interpretation_id": runner.INTERPRETATION_ID,
        "version_id": f"v{fixture}",
        "capture_complete": True,
        "interpretation_valid": True,
        "errors": [],
        "rows": rows,
        "raw_match": {
            "matchId": 1000 + fixture,
            "kickoff": kickoff,
            "resultType": "NormalResult",
            "homeTeam": {"id": 3, "score": 1},
            "awayTeam": {"id": 7, "score": 0},
        },
        "source_versions": {"lineups": {"sha256": "a" * 64}},
        "maximum_retained_event_timestamp": None,
        "verified_end_at": None,
        "identity_source": {"method": "exact-season-opta", "database_sha256": "b" * 64},
    }
    result["semantic_sha256"] = semantic_identity(result)
    return result


def fixture_inputs(tmp_path: Path, *, missing_start: bool = False) -> tuple[Path, Path]:
    database = tmp_path / "synthetic.duckdb"
    cache = tmp_path / "cache"
    cache.mkdir()
    folds = []
    with duckdb.connect(str(database)) as con:
        con.execute(
            "CREATE TABLE dev_competitive_match_version(interpretation_id VARCHAR,record_json JSON)"
        )
        con.execute("CREATE TABLE mart_dim_player(season VARCHAR,code INTEGER,opta_code VARCHAR)")
        con.execute("CREATE TABLE mart_dim_team(season VARCHAR,team_id INTEGER,team_code INTEGER)")
        con.execute("""CREATE TABLE mart_fact_player_fixture(
            season VARCHAR,fixture INTEGER,gw INTEGER,
            code INTEGER,team_id INTEGER,starts INTEGER,kickoff_time TIMESTAMPTZ,
            was_home BOOLEAN,opponent_team_id INTEGER)""")
        for code in range(1, 5):
            con.execute(
                "INSERT INTO mart_dim_player VALUES ('2025-26',?,?)", [code, f"p{100 + code}"]
            )
        con.execute("INSERT INTO mart_dim_team VALUES ('2025-26',3,3),('2025-26',7,7)")
        for fixture in (1, 2):
            source = record(fixture)
            if missing_start and fixture == 2:
                source["rows"] = [r for r in source["rows"] if r["code"] != 2]
                source["semantic_sha256"] = semantic_identity(source)
            con.execute(
                "INSERT INTO dev_competitive_match_version VALUES (?,?)",
                [runner.INTERPRETATION_ID, json.dumps(source)],
            )
            rows = []
            for code in range(1, 5):
                team, opposite = (7, 3) if code == 2 else (3, 7)
                con.execute(
                    "INSERT INTO mart_fact_player_fixture VALUES ('2025-26',?,?,?,?,?,?,?,?)",
                    [
                        fixture,
                        fixture,
                        code,
                        team,
                        int(code <= 2),
                        source["kickoff"],
                        team == 3,
                        opposite,
                    ],
                )
                rows.append(
                    {
                        "target": {
                            "season": "2025-26",
                            "fixture": fixture,
                            "gw": fixture,
                            "code": code,
                            "kickoff_time": source["kickoff"],
                            "team_id": team,
                            "opponent_team_id": opposite,
                            "was_home": team == 3,
                            "position": "IGNORED_NEVER_FEATURE",
                        },
                        "team_code": team,
                        "price_proxy_dependent": code == 4,
                        "selector_provenance": {
                            "archive_price_lineage": ["retained-not-a-role-feature"]
                            if code == 4
                            else []
                        },
                        "raw_v3_distribution": "POISON_NOT_READ",
                        "minutes_distribution": "POISON_NOT_READ",
                    }
                )
            name = f"gw{fixture}.json"
            publish_json(
                cache / name,
                {"season": "2025-26", "gw": fixture, "as_of": source["kickoff"], "rows": rows},
            )
            folds.append(
                {
                    "season": "2025-26",
                    "gw": fixture,
                    "file": name,
                    "rows": 4,
                    "sha256": file_sha256(cache / name),
                }
            )
    manifest = cache / "manifest.json"
    publish_json(
        manifest,
        {
            "completed": True,
            "counts": {"2025-26": 29747},
            "folds": folds,
            "provenance": {
                "database_sha256": runner.FIXED_POLICY["minutes_cache_source_database_sha256"]
            },
        },
    )
    return database, manifest


def test_coverage_denominator_is_all_starters_not_provider_subset(tmp_path: Path) -> None:
    db, manifest = fixture_inputs(tmp_path, missing_start=True)
    before = file_sha256(db)
    inputs = runner.build_inputs(db, manifest)
    assert inputs.coverage["all_fpl_starters"] == 4
    assert inputs.coverage["eligible_starting_labels"] == 3
    assert inputs.coverage["starting_label_coverage"] == 0.75
    assert not inputs.coverage["coverage_gate_passed"]
    assert len(inputs.targets) == 8
    assert file_sha256(db) == before
    assert not Path(str(db) + ".wal").exists()


def test_all_roster_and_proxy_lineage_retained_without_target_stats(tmp_path: Path) -> None:
    db, manifest = fixture_inputs(tmp_path)
    inputs = runner.build_inputs(db, manifest)
    assert len(inputs.targets) == 8 and len(inputs.labels) == 4
    assert inputs.coverage["minutes_cache_proxy_rows"] == 2
    assert inputs.roster_metadata["2025-26:1:4"]["cache_selector_provenance"][
        "archive_price_lineage"
    ]
    for target in inputs.targets:
        assert not hasattr(target, "started")
        assert not hasattr(target, "minutes")
        assert not hasattr(target, "position")
    # Minimal test schema has no goals, points, minutes, value or FPL-position columns.


def test_cache_original_database_cannot_be_relabelled_as_staged_database(tmp_path: Path) -> None:
    db, manifest = fixture_inputs(tmp_path)
    value = json.loads(manifest.read_bytes())
    value["provenance"]["database_sha256"] = file_sha256(db)
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="ORIGINAL archive"):
        runner.build_inputs(db, manifest)


def test_dirty_formal_run_stops_before_inputs_fit_or_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(runner, "load_contract", lambda *args: {})

    def refuse(_: Path) -> str:
        raise ValueError("dirty worktree")

    monkeypatch.setattr(runner, "_clean_branch", refuse)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("input load/model fit must not occur")

    monkeypatch.setattr(runner, "build_inputs", forbidden)
    monkeypatch.setattr(runner, "forecast_role_batch", forbidden)
    with pytest.raises(ValueError, match="dirty"):
        runner.run(
            root=root,
            database=tmp_path / "db",
            minutes_manifest=tmp_path / "manifest",
            stage_report=tmp_path / "stage",
            coverage_report=tmp_path / "coverage",
            config=root / runner.CONFIG,
            output=tmp_path / "output",
        )
    assert not (root / "data/evaluation-claims").exists()


def test_runner_projection_excludes_self_target_and_future_labels(tmp_path: Path) -> None:
    db, manifest = fixture_inputs(tmp_path)
    inputs = runner.build_inputs(db, manifest)
    target = [t for t in inputs.targets if t.gw == 1]
    early = runner.forecast_role_batch(inputs.history, target)
    assert early.prior_role_targets == 0
    assert all(r.probabilities == (0.25, 0.25, 0.25, 0.25) for r in early.predictions)
    later = runner.forecast_role_batch(inputs.history, [t for t in inputs.targets if t.gw == 2])
    assert later.prior_role_targets == 2
    assert all(
        s.gw == 1 and s.kickoff < later.as_of for r in later.predictions for s in r.recent_sources
    )


def test_earliest_original_capture_not_latest_interpretation_or_validity() -> None:
    first = record()
    first["interpretation_valid"] = False
    first["errors"] = ["unknown"]
    first["interpretation_known_at"] = "2026-09-10T00:00:00+00:00"
    first["semantic_sha256"] = semantic_identity(first)
    later = record()
    later["capture_known_at"] = "2026-09-08T00:00:00+00:00"
    later["version_id"] = "later"
    later["semantic_sha256"] = semantic_identity(later)
    selected = runner.select_versions([later, first])
    assert selected == [first]
    assert selected[0]["capture_known_at"] == "2026-09-07T08:00:00+00:00"


def test_cache_manifest_cannot_escape_its_directory(tmp_path: Path) -> None:
    _, manifest = fixture_inputs(tmp_path)
    value = json.loads(manifest.read_bytes())
    value["folds"][0]["file"] = "../elsewhere.json"
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="escapes"):
        runner._cache_roster(manifest)


def test_database_wal_and_hash_guards(tmp_path: Path) -> None:
    db, _ = fixture_inputs(tmp_path)
    with pytest.raises(ValueError, match="fingerprint drift"):
        runner._database_guard(db, "c" * 64)
    Path(str(db) + ".wal").touch()
    with pytest.raises(ValueError, match="WAL"):
        runner._database_guard(db, file_sha256(db))


def test_repository_claim_cannot_be_bypassed_by_another_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = tmp_path / "common"
    common.mkdir()
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: str(common))
    claim = runner._claim(tmp_path, {"claim": "one candidate"})
    before = claim.read_bytes()
    with pytest.raises(FileExistsError):
        runner._claim(tmp_path / "another_worktree", {"claim": "another output does not matter"})
    assert claim.read_bytes() == before


def test_unfinished_earliest_bundle_does_not_block_first_complete_final_capture() -> None:
    first = record()
    first["raw_match"]["resultType"] = "Live"
    first["semantic_sha256"] = semantic_identity(first)
    later = record()
    later["version_id"] = "later_final"
    later["capture_known_at"] = "2026-09-08T00:00:00+00:00"
    later["semantic_sha256"] = semantic_identity(later)
    assert runner.select_versions([first, later]) == [later]


def test_clean_branch_refuses_dirty_and_wrong_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def dirty(_: Path) -> str:
        raise ValueError("dirty worktree")

    monkeypatch.setattr(runner, "git_clean_head", dirty)
    with pytest.raises(ValueError, match="dirty"):
        runner._clean_branch(tmp_path)
    monkeypatch.setattr(runner, "git_clean_head", lambda _: "a" * 40)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: "main\n")
    with pytest.raises(ValueError, match="V2 branch"):
        runner._clean_branch(tmp_path)


def contract_fixture(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    path = root / runner.CONFIG
    path.parent.mkdir(parents=True)
    contract = {
        "policy": deepcopy(runner.FIXED_POLICY),
        "pins": dict.fromkeys(runner.PIN_KEYS, "a" * 64),
        "expected_eligible_starting_labels": 8000,
    }
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    monkeypatch.setattr(runner, "CONFIG_SHA256", file_sha256(path))
    return path, contract


def test_contract_exact_policy_pins_and_pending_real_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path, contract = contract_fixture(tmp_path, monkeypatch)
    assert runner.load_contract(tmp_path, path) == contract
    path.write_text(path.read_text() + "# changed bytes\n")
    with pytest.raises(ValueError, match="exact bytes"):
        runner.load_contract(tmp_path, path)


@pytest.mark.parametrize("change", ["grid", "threshold", "extra_pin", "small_population"])
def test_contract_refuses_unregistered_changes(
    change: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path, contract = contract_fixture(tmp_path, monkeypatch)
    if change == "grid":
        contract["policy"]["grid"] = [1, 2]
    elif change == "threshold":
        contract["policy"]["minimum_starting_label_coverage"] = 0.90
    elif change == "extra_pin":
        contract["pins"]["unregistered"] = "b" * 64
    else:
        contract["expected_eligible_starting_labels"] = 7941
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    monkeypatch.setattr(runner, "CONFIG_SHA256", file_sha256(path))
    with pytest.raises(ValueError, match="role"):
        runner.load_contract(tmp_path, path)


def test_matched_persistence_is_scored_but_not_substituted_for_primary_gate() -> None:
    rows = []
    for gw in (1, 2):
        for role in runner.ROLES:
            p = [0.1] * 4
            p[runner.ROLES.index(role)] = 0.7
            persistence = [0.05] * 4
            persistence[runner.ROLES.index(role)] = 0.85
            rows.append(
                {
                    "key": f"{gw}-{role}",
                    "gw": gw,
                    "actual_role": role,
                    "was_home": True,
                    "recent_measured_starts": 5,
                    "price_proxy_dependent": False,
                    "probabilities": {
                        "candidate": p,
                        "pooled_prior": [0.25] * 4,
                        "smoothed_last_role": [0.25] * 4,
                        "recent_state_persistence": persistence,
                    },
                }
            )
    result = runner.summarize(rows)
    assert result["verdict"] == "SUPPORTED_FOR_DEVELOPMENT"
    assert not result["transition_attribution_supported"]
    assert result["scores"]["overall"]["candidate"]["mean_log_score"] == pytest.approx(
        -math.log(0.7)
    )
    assert result["scores"]["overall"]["candidate"]["multinomial_brier"] == pytest.approx(0.12)
    assert result["paired"]["pooled_prior"]["gw_clusters"] == 2
