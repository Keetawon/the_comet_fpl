"""Retention removes only proven duplicate operational payloads, never evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest

from fpl.jobs import operational_retention as retention
from fpl.jobs import refresh_dashboard as refresh
from fpl.jobs import sdp_capture_health as health

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cycle(
    runs: Path,
    database: Path,
    serial: int,
    *,
    dashboard: bool = False,
    hours_old: int | None = None,
    healthy: bool = True,
) -> Path:
    finished = NOW - timedelta(hours=hours_old if hours_old is not None else 10 - serial)
    stamp = finished.strftime("%Y%m%dT%H%M%S")
    name = f"dashboard-{stamp}Z-{serial:08x}" if dashboard else f"{stamp}.000000Z-{serial:08x}"
    directory = runs / name
    directory.mkdir(parents=True)
    backup = directory / ("before-outcomes.duckdb" if dashboard else "before.duckdb")
    backup.write_bytes(f"synthetic duplicate backup {serial}".encode())
    payload: dict[str, Any] = {
        "database": str(database.resolve()),
        "started_at": (finished - timedelta(minutes=1)).isoformat(),
        "finished_at": finished.isoformat(),
    }
    if dashboard:
        generation = directory / "generation"
        generation.mkdir()
        (generation / "synthetic.json").write_text('{"test":true}', encoding="utf-8")
        payload.update(status="COMPLETE", retention_policy_version=1)
        _write_json(directory / "receipt.json", payload)
    else:
        payload.update(
            healthy=healthy,
            consumer_ready=healthy,
            exit_code=0 if healthy else 1,
            mode="capture_and_stage",
            backup={"path": str(backup), "sha256": _hash(backup)},
            production_health={"season": "2026-27", "matches_valid": serial},
        )
        _write_json(directory / "report.json", payload)
    (directory / "run.log").write_text("original audit log", encoding="utf-8")
    return directory


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current database sentinel")
    runs, forecasts = tmp_path / "runs", tmp_path / "forecasts"
    runs.mkdir()
    forecasts.mkdir()
    monkeypatch.setattr(retention, "_verify_backup", lambda *args: {"synthetic_proof": True})
    monkeypatch.setattr(retention, "_protected_hashes", lambda *args: set())
    monkeypatch.setattr(retention, "_references", lambda *args: (set(), set()))
    return database, runs, forecasts


def test_latest_two_payloads_are_kept_by_receipt_time_and_health_is_unchanged(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, forecasts = workspace
    captures = [_cycle(runs, database, index) for index in range(4)]
    dashboards = [_cycle(runs, database, index, dashboard=True) for index in range(4)]
    generation_receipt = b'{"retained":"generation evidence"}'
    for directory in dashboards[:2]:
        (directory / "generation" / "receipt.json").write_bytes(generation_receipt)
    # Directory spelling must not override the validated receipt timestamp.
    renamed = captures[0].with_name("20991231T235959.000000Z-00000000")
    captures[0].rename(renamed)
    captures[0] = renamed
    renamed_receipt = json.loads((renamed / "report.json").read_text())
    renamed_receipt["backup"]["path"] = str(renamed / "before.duckdb")
    _write_json(renamed / "report.json", renamed_receipt)
    failed = _cycle(runs, database, 9, hours_old=0, healthy=False)
    original_small = {
        path: path.read_bytes()
        for directory in [*captures, *dashboards, failed]
        for path in directory.iterdir()
        if path.suffix in {".json", ".log"}
    }
    health_arguments = {
        "runs_root": runs,
        "database": database,
        "max_success_age_hours": 24,
        "fail_on_production_failure": True,
        "now": NOW,
    }
    before = health.build_report(**health_arguments)

    retention.prune_runs(database, runs, forecasts)

    for directory in dashboards[:2]:
        assert not (directory / "generation").exists()
        assert not (directory / "before-outcomes.duckdb").exists()
        assert (directory / "generation-retired-receipt.json").read_bytes() == generation_receipt
    for directory in dashboards[2:]:
        assert (directory / "generation" / "synthetic.json").is_file()
        assert (directory / "before-outcomes.duckdb").is_file()
    for directory in captures[:-1]:
        assert not (directory / "before.duckdb").exists()
    assert (captures[-1] / "before.duckdb").is_file()
    assert (failed / "before.duckdb").is_file()
    assert {path: path.read_bytes() for path in original_small} == original_small
    assert health.build_report(**health_arguments) == before
    assert database.read_bytes() == b"current database sentinel"


def test_newer_failed_copy_attempts_cannot_displace_two_verified_backups(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, forecasts = workspace
    verified = [_cycle(runs, database, index) for index in range(3)]
    for serial, age in ((7, 1), (8, 0)):
        failed = _cycle(runs, database, serial, hours_old=age, healthy=False)
        (failed / "before.duckdb").unlink()
        payload = json.loads((failed / "report.json").read_text())
        payload.pop("backup")
        _write_json(failed / "report.json", payload)
    health_arguments = {
        "runs_root": runs,
        "database": database,
        "max_success_age_hours": 24,
        "fail_on_production_failure": True,
        "now": NOW,
    }
    before = health.build_report(**health_arguments)

    retention.prune_runs(database, runs, forecasts)

    assert not (verified[0] / "before.duckdb").exists()
    for directory in verified[-2:]:
        assert (directory / "before.duckdb").is_file()
    assert health.build_report(**health_arguments) == before


@pytest.mark.parametrize("position", ["descendant", "root_ancestor"])
def test_reparse_boundaries_abort_before_any_payload_deletion(
    workspace: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    database, runs, forecasts = workspace
    directories = [_cycle(runs, database, index, dashboard=True) for index in range(4)]
    flagged = directories[-1] / "generation" if position == "descendant" else runs.parent
    original = Path.lstat

    def attributes(path: Path) -> Any:
        actual = original(path)
        if path == flagged:
            return SimpleNamespace(
                st_file_attributes=retention.stat.FILE_ATTRIBUTE_REPARSE_POINT,
                st_mode=actual.st_mode,
            )
        return actual

    monkeypatch.setattr(Path, "lstat", attributes)
    with pytest.raises(ValueError, match=r"(?i)reparse|symlink"):
        retention.prune_runs(database, runs, forecasts)
    for directory in directories:
        assert (directory / "before-outcomes.duckdb").is_file()
        assert (directory / "generation" / "synthetic.json").is_file()


def test_outside_root_target_is_rejected_without_touching_its_bytes(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, _ = workspace
    original = database.read_bytes()
    with pytest.raises(ValueError, match="outside"):
        retention._safe_tree(database, runs)
    assert database.read_bytes() == original


@pytest.mark.parametrize("suffix", [".wal", ".daily-sdp.lock"])
def test_live_database_wal_or_lock_blocks_every_payload_removal(
    workspace: tuple[Path, Path, Path], suffix: str
) -> None:
    database, runs, forecasts = workspace
    directories = [_cycle(runs, database, index, dashboard=True) for index in range(3)]
    Path(str(database) + suffix).write_bytes(b"active writer witness")
    with pytest.raises(ValueError, match=r"(?i)lock|WAL"):
        retention.prune_runs(database, runs, forecasts)
    for directory in directories:
        assert (directory / "before-outcomes.duckdb").is_file()
        assert (directory / "generation" / "synthetic.json").is_file()


def test_forecast_hash_pin_and_forecast_source_are_never_pruned(
    workspace: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, runs, forecasts = workspace
    captures = [_cycle(runs, database, index) for index in range(4)]
    pinned = captures[0] / "before.duckdb"
    frozen = pinned.read_bytes()
    source = captures[1] / "forecast-source.duckdb"
    source.write_bytes(b"exact immutable forecast input")
    forecast = forecasts / "retained.jsonl"
    forecast.write_text(
        json.dumps({"record_type": "manifest", "database_sha256": _hash(pinned)}) + "\n",
        encoding="utf-8",
    )
    forecast_bytes = forecast.read_bytes()
    monkeypatch.setattr(retention, "_protected_hashes", lambda *args: {_hash(pinned)})

    retention.prune_runs(database, runs, forecasts)

    assert pinned.read_bytes() == frozen
    assert source.read_bytes() == b"exact immutable forecast input"
    assert forecast.read_bytes() == forecast_bytes


def test_forecast_headers_are_discovered_recursively(tmp_path: Path) -> None:
    forecasts = tmp_path / "forecasts" / "nested"
    forecasts.mkdir(parents=True)
    expected_hash = "a" * 64
    (forecasts / "frozen.jsonl").write_text(
        json.dumps({"record_type": "manifest", "database_sha256": expected_hash}) + "\n",
        encoding="utf-8",
    )
    assert expected_hash in retention._protected_hashes(forecasts.parent)


@pytest.mark.parametrize(
    "location", ["repo_artifact", "operational_generation", "external_verification"]
)
@pytest.mark.parametrize("serialized", [False, True])
def test_publication_metadata_pins_backup_without_any_forecast_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str, serialized: bool
) -> None:
    repository = tmp_path / "checkout"
    repository.mkdir()
    database, runs, forecasts = (
        tmp_path / "operations" / "operational.duckdb",
        tmp_path / "operations" / "runs",
        tmp_path / "operations" / "forecasts",
    )
    database.parent.mkdir()
    database.write_bytes(b"current database sentinel")
    forecasts.mkdir()
    captures = [_cycle(runs, database, index) for index in range(3)]
    pinned = captures[0] / "before.duckdb"
    original = pinned.read_bytes()
    pinned_hash = _hash(pinned)
    if location == "repo_artifact":
        manifest = repository / "data" / "artifacts" / "retained-publication" / "manifest.json"
    elif location == "operational_generation":
        publication = _cycle(runs, database, 4, dashboard=True)
        manifest = publication / "generation" / "public" / "data" / "manifest.json"
    else:
        manifest = runs.parent / "verification" / "retained-publication" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    source = {"database_sha256": pinned_hash}
    _write_json(manifest, {"source_export": json.dumps(source) if serialized else source})
    manifest_bytes = manifest.read_bytes()
    monkeypatch.setattr(retention, "repo_root", lambda: repository)
    monkeypatch.setattr(
        retention, "_verify_backup", lambda *args: pytest.fail("publication-pinned backup pruned")
    )

    assert pinned_hash in retention._references(runs)[0]
    result = retention.prune_runs(database, runs, forecasts)

    assert pinned.read_bytes() == original
    assert manifest.read_bytes() == manifest_bytes
    assert any(row["reason"] == "immutable source hash pin" for row in result["skipped"])
    assert not list(forecasts.iterdir())


def test_retention_deletion_proofs_do_not_create_permanent_source_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, runs, forecasts = tmp_path / "checkout", tmp_path / "runs", tmp_path / "forecasts"
    repository.mkdir()
    forecasts.mkdir()
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current database sentinel")
    captures = [_cycle(runs, database, index) for index in range(3)]
    backup = captures[0] / "before.duckdb"
    backup_hash = _hash(backup)
    receipt = runs / "retention-20260917T120000Z-deadbeef.json"
    _write_json(
        receipt,
        {
            "schema": "fpl.operational-retention",
            "schema_version": 1,
            "status": "COMPLETE",
            "deleted": [{"retention_proof": {"backup_sha256": backup_hash}}],
        },
    )
    receipt_bytes = receipt.read_bytes()
    monkeypatch.setattr(retention, "repo_root", lambda: repository)
    monkeypatch.setattr(retention, "_verify_backup", lambda *args: {"synthetic_proof": True})

    assert backup_hash not in retention._references(runs)[0]
    retention.prune_runs(database, runs, forecasts)

    assert not backup.exists()
    assert receipt.read_bytes() == receipt_bytes


def test_older_managed_generation_does_not_pin_its_own_backup_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, runs, forecasts = tmp_path / "checkout", tmp_path / "runs", tmp_path / "forecasts"
    repository.mkdir()
    forecasts.mkdir()
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current database sentinel")
    dashboards = [_cycle(runs, database, index, dashboard=True) for index in range(3)]
    backup = dashboards[0] / "before-outcomes.duckdb"
    backup_hash = _hash(backup)
    manifest = dashboards[0] / "generation" / "public" / "data" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    _write_json(manifest, {"source_export": {"database_sha256": backup_hash}})
    manifest_bytes = manifest.read_bytes()
    for directory in dashboards[-2:]:
        retained = directory / "generation" / "public" / "data" / "manifest.json"
        retained.parent.mkdir(parents=True)
        _write_json(retained, {"source_export": {"database_sha256": "c" * 64}})
    monkeypatch.setattr(retention, "repo_root", lambda: repository)
    monkeypatch.setattr(retention, "_verify_backup", lambda *args: {"synthetic_proof": True})

    assert backup_hash not in retention._references(runs)[0]
    retention.prune_runs(database, runs, forecasts)

    assert not backup.exists()
    assert not (dashboards[0] / "generation").exists()
    assert (dashboards[0] / "generation-retired-manifest.json").read_bytes() == manifest_bytes


def test_unreadable_metadata_subtree_aborts_before_backup_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, runs, forecasts = tmp_path / "checkout", tmp_path / "runs", tmp_path / "forecasts"
    blocked = repository / "data" / "artifacts" / "unreadable-publication"
    blocked.mkdir(parents=True)
    forecasts.mkdir()
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current database sentinel")
    captures = [_cycle(runs, database, index) for index in range(3)]
    originals = {p / "before.duckdb": (p / "before.duckdb").read_bytes() for p in captures}
    _write_json(
        blocked / "manifest.json", {"database_sha256": _hash(captures[0] / "before.duckdb")}
    )
    original_iterdir = Path.iterdir

    def iterdir(path: Path) -> Any:
        if path == blocked:
            raise PermissionError("metadata subtree unreadable")
        return original_iterdir(path)

    monkeypatch.setattr(retention, "repo_root", lambda: repository)
    monkeypatch.setattr(Path, "iterdir", iterdir)
    with pytest.raises(PermissionError, match="metadata subtree unreadable"):
        retention.prune_runs(database, runs, forecasts)
    assert {path: path.read_bytes() for path in originals} == originals


@pytest.mark.parametrize("pin_source", ["repository", "forecast"])
def test_manifest_of_an_older_pinned_generation_protects_its_other_source_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pin_source: str
) -> None:
    repository, runs, forecasts = tmp_path / "checkout", tmp_path / "runs", tmp_path / "forecasts"
    repository.mkdir()
    forecasts.mkdir()
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current database sentinel")
    captures = [_cycle(runs, database, index) for index in range(3)]
    dashboards = [_cycle(runs, database, index, dashboard=True) for index in range(3)]
    publication_backup = dashboards[0] / "before-outcomes.duckdb"
    other_source = captures[0] / "before.duckdb"
    publication_hash, source_hash = _hash(publication_backup), _hash(other_source)
    if pin_source == "repository":
        pin = repository / "data" / "artifacts" / "scientific-record" / "manifest.json"
        pin.parent.mkdir(parents=True)
        _write_json(pin, {"source_export": {"database_sha256": publication_hash}})
    else:
        (forecasts / "retained.jsonl").write_text(
            json.dumps({"record_type": "manifest", "database_sha256": publication_hash}) + "\n",
            encoding="utf-8",
        )
    dependency = dashboards[0] / "generation" / "public" / "data" / "manifest.json"
    dependency.parent.mkdir(parents=True)
    _write_json(dependency, {"source_export": {"database_sha256": source_hash}})
    for directory in dashboards[-2:]:
        retained = directory / "generation" / "public" / "data" / "manifest.json"
        retained.parent.mkdir(parents=True)
        _write_json(retained, {"source_export": {"database_sha256": "c" * 64}})
    monkeypatch.setattr(retention, "repo_root", lambda: repository)
    monkeypatch.setattr(
        retention,
        "_verify_backup",
        lambda *args: pytest.fail("retained publication dependency pruned"),
    )

    names: set[str] = set()
    hashes = retention._protected_hashes(forecasts, names)
    assert {publication_hash, source_hash} <= retention._references(
        runs, (hashes, names), database
    )[0]
    retention.prune_runs(database, runs, forecasts)

    assert _hash(publication_backup) == publication_hash
    assert _hash(other_source) == source_hash
    assert dependency.is_file()


@pytest.mark.parametrize("case", ["old_failed_r2", "new_foreign_database"])
def test_preserved_publication_manifests_keep_cross_run_source_backups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    repository, runs, forecasts = tmp_path / "checkout", tmp_path / "runs", tmp_path / "forecasts"
    repository.mkdir()
    forecasts.mkdir()
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current database sentinel")
    captures = [_cycle(runs, database, index) for index in range(3)]
    source = captures[0] / "before.duckdb"
    source_hash = _hash(source)
    owned = [_cycle(runs, database, index, dashboard=True) for index in range(2, 5)]
    exceptional = _cycle(
        runs,
        database,
        0 if case == "old_failed_r2" else 9,
        dashboard=True,
        hours_old=12 if case == "old_failed_r2" else 0,
    )
    receipt = json.loads((exceptional / "receipt.json").read_text())
    if case == "old_failed_r2":
        receipt["public_publication"] = {"status": "FAILED"}
        dependent = exceptional
    else:
        receipt["database"] = str(database.with_name("another.duckdb"))
        dependent = owned[-2]
    _write_json(exceptional / "receipt.json", receipt)
    for directory in [*owned, exceptional]:
        manifest = directory / "generation" / "public" / "data" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        _write_json(
            manifest,
            {
                "source_export": {
                    "database_sha256": source_hash if directory == dependent else "c" * 64
                }
            },
        )
    monkeypatch.setattr(retention, "repo_root", lambda: repository)
    monkeypatch.setattr(retention, "_verify_backup", lambda *args: {"synthetic_proof": True})

    assert source_hash in retention._references(runs, database=database)[0]
    retention.prune_runs(database, runs, forecasts)

    assert _hash(source) == source_hash
    assert (dependent / "generation" / "public" / "data" / "manifest.json").is_file()
    assert (exceptional / "generation").is_dir()


def test_serialized_component_provenance_pins_an_older_source_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current database sentinel")
    runs, forecasts = tmp_path / "runs", tmp_path / "forecasts"
    forecasts.mkdir()
    captures = [_cycle(runs, database, index) for index in range(3)]
    pinned = captures[0] / "before.duckdb"
    original = pinned.read_bytes()
    top_level_hash, component_hash = "a" * 64, "b" * 64
    pinned_receipt = json.loads((pinned.parent / "report.json").read_text())
    pinned_receipt["backup"]["sha256"] = component_hash
    _write_json(pinned.parent / "report.json", pinned_receipt)
    header = {
        "record_type": "manifest",
        "database_sha256": top_level_hash,
        "component_modes": {
            "football_environment.provenance": json.dumps(
                {"source_database_sha256": component_hash}
            )
        },
    }
    (forecasts / "retained.jsonl").write_text(json.dumps(header) + "\n", encoding="utf-8")
    monkeypatch.setattr(retention, "_references", lambda *args: (set(), set()))
    monkeypatch.setattr(
        retention, "_hash", lambda path: component_hash if path == pinned else _hash(path)
    )
    monkeypatch.setattr(
        retention, "_verify_backup", lambda *args: pytest.fail("proof requested for pinned source")
    )

    assert {top_level_hash, component_hash} <= retention._protected_hashes(forecasts)
    result = retention.prune_runs(database, runs, forecasts)

    assert pinned.read_bytes() == original
    assert any(row["reason"] == "immutable source hash pin" for row in result["skipped"])


def test_large_realistic_forecast_header_still_protects_database(tmp_path: Path) -> None:
    expected_hash = "b" * 64
    (tmp_path / "large-forecast.jsonl").write_text(
        json.dumps(
            {
                "record_type": "manifest",
                "fixture_source_provenance": "x" * (3 * 1024 * 1024),
                "database_sha256": expected_hash,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert expected_hash in retention._protected_hashes(tmp_path)


@pytest.mark.parametrize("header", ["{}", '{"database_sha256":"not-a-hash"}', "not json"])
def test_missing_or_malformed_forecast_pin_aborts_before_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"current sentinel")
    runs, forecasts = tmp_path / "runs", tmp_path / "forecasts"
    forecasts.mkdir()
    (forecasts / "frozen.jsonl").write_text(header + "\n", encoding="utf-8")
    directories = [_cycle(runs, database, index) for index in range(3)]
    original = {p / "before.duckdb": (p / "before.duckdb").read_bytes() for p in directories}
    monkeypatch.setattr(retention, "_references", lambda *args: (set(), set()))

    with pytest.raises(ValueError, match=r"(?i)forecast pin|expecting value"):
        retention.prune_runs(database, runs, forecasts)

    assert {path: path.read_bytes() for path in original} == original


def test_legacy_or_different_database_generations_remain_unmodified(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, forecasts = workspace
    legacy = _cycle(runs, database, 0, dashboard=True)
    foreign = _cycle(runs, database, 1, dashboard=True)
    legacy_receipt = json.loads((legacy / "receipt.json").read_text())
    legacy_receipt.pop("retention_policy_version")
    _write_json(legacy / "receipt.json", legacy_receipt)
    foreign_receipt = json.loads((foreign / "receipt.json").read_text())
    foreign_receipt["database"] = str(database.with_name("other.duckdb"))
    foreign_receipt["finished_at"] = NOW.isoformat()
    _write_json(foreign / "receipt.json", foreign_receipt)
    owned = [_cycle(runs, database, index, dashboard=True) for index in range(2, 5)]

    retention.prune_runs(database, runs, forecasts)

    for directory in (legacy, foreign):
        assert (directory / "generation" / "synthetic.json").is_file()
        assert (directory / "before-outcomes.duckdb").is_file()
    assert not (owned[0] / "generation").exists()
    for directory in owned[-2:]:
        assert (directory / "generation" / "synthetic.json").is_file()
        assert (directory / "before-outcomes.duckdb").is_file()


def test_failed_backup_proof_keeps_backup_and_reports_partial(
    workspace: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, runs, forecasts = workspace
    captures = [_cycle(runs, database, index) for index in range(3)]

    def fail_proof(*args: object) -> dict[str, Any]:
        raise ValueError("immutable row is absent from current database")

    monkeypatch.setattr(retention, "_verify_backup", fail_proof)
    result = retention.prune_runs(database, runs, forecasts)

    assert (captures[0] / "before.duckdb").exists()
    assert result["status"] == "PARTIAL"
    assert result["skipped"]


def test_failed_backup_proof_also_keeps_its_dashboard_generation(
    workspace: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, runs, forecasts = workspace
    directories = [_cycle(runs, database, index, dashboard=True) for index in range(3)]

    def fail_proof(*args: object) -> dict[str, Any]:
        raise ValueError("immutable row is absent from current database")

    monkeypatch.setattr(retention, "_verify_backup", fail_proof)
    result = retention.prune_runs(database, runs, forecasts)

    assert result["status"] == "PARTIAL"
    assert (directories[0] / "before-outcomes.duckdb").is_file()
    assert (directories[0] / "generation" / "synthetic.json").is_file()


def test_missing_dashboard_backup_keeps_generation_without_proof(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, forecasts = workspace
    directories = [_cycle(runs, database, index, dashboard=True) for index in range(3)]
    (directories[0] / "before-outcomes.duckdb").unlink()

    result = retention.prune_runs(database, runs, forecasts)

    assert (directories[0] / "generation" / "synthetic.json").is_file()
    assert result["skipped"]


def test_pinned_dashboard_backup_keeps_entire_generation(
    workspace: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, runs, forecasts = workspace
    directories = [_cycle(runs, database, index, dashboard=True) for index in range(3)]
    pinned = directories[0] / "before-outcomes.duckdb"
    original = pinned.read_bytes()
    monkeypatch.setattr(retention, "_protected_hashes", lambda *args: {_hash(pinned)})

    retention.prune_runs(database, runs, forecasts)

    assert pinned.read_bytes() == original
    assert (directories[0] / "generation" / "synthetic.json").is_file()


def test_failed_remote_publication_keeps_its_generation_after_newer_successes(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, forecasts = workspace
    directories = [_cycle(runs, database, index, dashboard=True) for index in range(4)]
    failed = directories[0]
    receipt = json.loads((failed / "receipt.json").read_text())
    receipt["public_publication"] = {"status": "FAILED"}
    _write_json(failed / "receipt.json", receipt)

    retention.prune_runs(database, runs, forecasts)

    assert (failed / "before-outcomes.duckdb").is_file()
    assert (failed / "generation" / "synthetic.json").is_file()


def _tiny_database(path: Path, *, extra_current_row: bool = False) -> None:
    with duckdb.connect(str(path)) as con:
        for table in ("raw_ingest_log", "ledger_prediction_player_gameweek"):
            con.execute(f"CREATE TABLE {table} (id INTEGER, payload VARCHAR)")
            con.execute(f"INSERT INTO {table} VALUES (1, 'frozen')")
            if extra_current_row:
                con.execute(f"INSERT INTO {table} VALUES (2, 'append only')")


def _recovery_pin_files(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    database, runs, forecasts = (
        tmp_path / "operational.duckdb",
        tmp_path / "runs",
        tmp_path / "forecasts",
    )
    _tiny_database(database)
    forecasts.mkdir()
    capture = _cycle(runs, database, 0)
    backup = capture / "before.duckdb"
    backup.write_bytes(database.read_bytes())
    receipt = json.loads((capture / "report.json").read_text())
    receipt["backup"]["sha256"] = _hash(backup)
    _write_json(capture / "report.json", receipt)
    recovery = runs / "surviving" / "recovery.duckdb"
    recovery.parent.mkdir()
    recovery.write_bytes(database.read_bytes())
    return database, runs, forecasts, backup, recovery


@pytest.mark.parametrize("different", [False, True])
def test_hash_only_pin_retires_duplicate_only_when_identical_recovery_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, different: bool
) -> None:
    database, runs, forecasts, backup, recovery = _recovery_pin_files(tmp_path)
    if different:
        backup.unlink()
        _tiny_database(backup, extra_current_row=True)
        receipt = json.loads((backup.parent / "report.json").read_text())
        receipt["backup"]["sha256"] = _hash(backup)
        _write_json(backup.parent / "report.json", receipt)
    backup_bytes, recovery_bytes = backup.read_bytes(), recovery.read_bytes()
    (forecasts / "retained.jsonl").write_text(
        json.dumps({"record_type": "manifest", "database_sha256": _hash(backup)}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retention, "_references", lambda *args: (set(), set()))

    retention.prune_runs(database, runs, forecasts, recovery=recovery)

    assert backup.exists() is different
    if different:
        assert backup.read_bytes() == backup_bytes
    assert recovery.read_bytes() == recovery_bytes


def test_exact_source_path_pin_preserves_original_even_with_identical_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, runs, forecasts, backup, recovery = _recovery_pin_files(tmp_path)
    original = backup.read_bytes()
    (forecasts / "retained.jsonl").write_text(
        json.dumps(
            {
                "record_type": "manifest",
                "database_sha256": _hash(backup),
                "component_modes": {"provenance": json.dumps({"database_path": str(backup)})},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retention, "_references", lambda *args: (set(), set()))
    monkeypatch.setattr(
        retention,
        "_verify_backup",
        lambda *args: pytest.fail("exact source path was not protected"),
    )
    run_names: set[str] = set()
    assert _hash(backup) in retention._protected_hashes(forecasts, run_names)
    assert backup.parent.name in run_names

    retention.prune_runs(database, runs, forecasts, recovery=recovery)

    assert backup.read_bytes() == original
    assert recovery.read_bytes() == original


def test_recovery_snapshot_is_an_exact_copy_without_changing_current_database(
    tmp_path: Path,
) -> None:
    database, destination = tmp_path / "operational.duckdb", tmp_path / "completed"
    destination.mkdir()
    recovery = destination / "recovery.duckdb"
    _tiny_database(database, extra_current_row=True)
    original = database.read_bytes()

    snapshot = retention.create_recovery(database, destination)

    assert Path(snapshot["path"]) == recovery.resolve()
    assert snapshot["sha256"] == hashlib.sha256(original).hexdigest()
    assert recovery.read_bytes() == original
    assert database.read_bytes() == original


@pytest.mark.parametrize("suffix", [".wal", ".daily-sdp.lock"])
def test_recovery_snapshot_refuses_active_database_lock_or_wal(tmp_path: Path, suffix: str) -> None:
    database, destination = tmp_path / "operational.duckdb", tmp_path / "completed"
    destination.mkdir()
    _tiny_database(database)
    original = database.read_bytes()
    Path(str(database) + suffix).write_bytes(b"active writer witness")

    with pytest.raises((ValueError, FileExistsError, RuntimeError), match=r"(?i)lock|WAL"):
        retention.create_recovery(database, destination)

    assert not (destination / "recovery.duckdb").exists()
    assert database.read_bytes() == original


def test_recovery_mode_keeps_one_verified_snapshot_and_two_dashboard_generations(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, forecasts = workspace
    database.unlink()
    _tiny_database(database)
    captures = [_cycle(runs, database, index) for index in range(3)]
    dashboards = [_cycle(runs, database, index, dashboard=True) for index in range(3)]
    for directory in dashboards:
        (directory / "recovery.duckdb").write_bytes(database.read_bytes())
    golden = dashboards[-1] / "recovery.duckdb"
    original = golden.read_bytes()

    retention.prune_runs(database, runs, forecasts, recovery=golden)

    assert golden.read_bytes() == original
    assert database.read_bytes() == original
    for directory in captures:
        assert not (directory / "before.duckdb").exists()
    for directory in dashboards:
        assert not (directory / "before-outcomes.duckdb").exists()
    for directory in dashboards[:-1]:
        assert not (directory / "recovery.duckdb").exists()
    assert not (dashboards[0] / "generation").exists()
    for directory in dashboards[-2:]:
        assert (directory / "generation" / "synthetic.json").is_file()


def test_recovery_snapshot_mismatch_aborts_before_any_deletion(
    workspace: tuple[Path, Path, Path],
) -> None:
    database, runs, forecasts = workspace
    database.unlink()
    _tiny_database(database)
    captures = [_cycle(runs, database, index) for index in range(3)]
    dashboards = [_cycle(runs, database, index, dashboard=True) for index in range(3)]
    snapshot = dashboards[-1] / "recovery.duckdb"
    snapshot.write_bytes(b"stale or changed snapshot")

    with pytest.raises(ValueError, match=r"(?i)recovery|snapshot|match|hash"):
        retention.prune_runs(database, runs, forecasts, recovery=snapshot)

    for directory in captures:
        assert (directory / "before.duckdb").is_file()
    for directory in dashboards:
        assert (directory / "before-outcomes.duckdb").is_file()
        assert (directory / "generation" / "synthetic.json").is_file()


def test_retired_backup_must_be_contained_in_surviving_snapshot_not_advanced_live_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, runs, forecasts = (
        tmp_path / "operational.duckdb",
        tmp_path / "runs",
        tmp_path / "forecasts",
    )
    _tiny_database(database)
    forecasts.mkdir()
    capture = _cycle(runs, database, 0)
    backup = capture / "before.duckdb"
    backup.unlink()
    _tiny_database(backup, extra_current_row=True)
    receipt = json.loads((capture / "report.json").read_text())
    receipt["backup"]["sha256"] = _hash(backup)
    _write_json(capture / "report.json", receipt)
    dashboard = _cycle(runs, database, 1, dashboard=True)
    (dashboard / "before-outcomes.duckdb").write_bytes(database.read_bytes())
    golden = dashboard / "recovery.duckdb"
    golden.write_bytes(database.read_bytes())
    original_verify = retention._verify_backup
    proof_targets = []

    def prove(survivor: Path, retiring: Path) -> dict[str, Any]:
        assert survivor == golden
        if not proof_targets:
            # The live store advances after the initial snapshot equality check.
            with duckdb.connect(str(database)) as con:
                for table in ("raw_ingest_log", "ledger_prediction_player_gameweek"):
                    con.execute(f"INSERT INTO {table} VALUES (2, 'append only')")
        proof_targets.append(survivor)
        return original_verify(survivor, retiring)

    monkeypatch.setattr(retention, "_references", lambda *args: (set(), set()))
    monkeypatch.setattr(retention, "_verify_backup", prove)
    result = retention.prune_runs(database, runs, forecasts, recovery=golden)

    assert proof_targets
    assert result["status"] == "PARTIAL"
    assert backup.is_file()
    assert isinstance(original_verify(database, backup), dict)


@pytest.mark.parametrize("changed_table", ["raw_ingest_log", "ledger_prediction_player_gameweek"])
def test_real_backup_proof_requires_exact_raw_and_ledger_rows(
    tmp_path: Path, changed_table: str
) -> None:
    current, backup = tmp_path / "current.duckdb", tmp_path / "before.duckdb"
    _tiny_database(current, extra_current_row=True)
    _tiny_database(backup)
    before = backup.read_bytes()
    assert isinstance(retention._verify_backup(current, backup), dict)
    assert backup.read_bytes() == before
    with duckdb.connect(str(current)) as con:
        con.execute(f"UPDATE {changed_table} SET payload='changed' WHERE id=1")
    with pytest.raises(ValueError, match=r"(?i)row|subset|immutable|missing"):
        retention._verify_backup(current, backup)
    assert backup.read_bytes() == before


def test_unknown_backup_schema_fails_closed(tmp_path: Path) -> None:
    current, backup = tmp_path / "current.duckdb", tmp_path / "before.duckdb"
    _tiny_database(current)
    _tiny_database(backup)
    for path in (current, backup):
        with duckdb.connect(str(path)) as con:
            con.execute("CREATE TABLE unknown_scientific_state (id INTEGER)")
    with pytest.raises(ValueError, match=r"(?i)unknown|schema|table"):
        retention._verify_backup(current, backup)
    assert backup.is_file()


@pytest.mark.parametrize("failure", ["local", "r2_result", "r2_exception"])
def test_failed_refresh_never_prunes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from fpl.publish import r2_dashboard

    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"test db sentinel")
    monkeypatch.setattr(
        refresh, "prune_runs", lambda *args, **kwargs: pytest.fail("pruning after failed refresh")
    )
    monkeypatch.setattr(
        refresh,
        "create_recovery",
        lambda *args, **kwargs: pytest.fail("snapshot after failed refresh"),
    )

    def complete(*args: object, **kwargs: object) -> dict[str, Any]:
        if failure == "local":
            raise RuntimeError("injected local publication failure")
        return {}

    def publish(*args: object, **kwargs: object) -> dict[str, Any]:
        if failure == "r2_exception":
            raise RuntimeError("injected remote publication failure")
        return {"status": "FAILED"}

    monkeypatch.setattr(refresh, "complete", complete)
    monkeypatch.setattr(r2_dashboard, "publish_r2_dashboard", publish)
    args = _refresh_args(tmp_path, database)
    if failure != "local":
        args += ["--r2-config", str(tmp_path / "r2.json")]
    assert refresh.main(args) == 1
    receipt = next((tmp_path / "runs").glob("dashboard-*/receipt.json"))
    assert receipt.is_file()


def _refresh_args(tmp_path: Path, database: Path) -> list[str]:
    return [
        "--db",
        str(database),
        "--runs",
        str(tmp_path / "runs"),
        "--forecast-dir",
        str(tmp_path / "forecasts"),
        "--preview-public",
        str(tmp_path / "public"),
        "--plan-store",
        str(tmp_path / "plans"),
        "--skip-capture",
    ]


def test_successful_refresh_writes_complete_receipt_before_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operational.duckdb"
    database.write_bytes(b"test db sentinel")
    monkeypatch.setattr(refresh, "complete", lambda *args, **kwargs: {})
    calls = []

    def create(database: Path, destination: Path) -> dict[str, Any]:
        receipt = next((tmp_path / "runs").glob("dashboard-*/receipt.json"))
        assert json.loads(receipt.read_text())["status"] == "COMPLETE"
        recovery = destination / "recovery.duckdb"
        recovery.write_bytes(database.read_bytes())
        calls.append("snapshot")
        return {"path": str(recovery.resolve()), "sha256": _hash(recovery)}

    def prune(*args: object, **kwargs: object) -> dict[str, Any]:
        receipt = next((tmp_path / "runs").glob("dashboard-*/receipt.json"))
        assert json.loads(receipt.read_text())["status"] == "COMPLETE"
        assert Path(str(kwargs["recovery"])).read_bytes() == database.read_bytes()
        calls.append("prune")
        return {"status": "COMPLETE", "deleted": [], "skipped": []}

    monkeypatch.setattr(refresh, "create_recovery", create)
    monkeypatch.setattr(refresh, "prune_runs", prune)
    assert refresh.main(_refresh_args(tmp_path, database)) == 0
    assert calls == ["snapshot", "prune"]
