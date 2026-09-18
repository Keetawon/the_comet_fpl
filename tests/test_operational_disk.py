"""Offline byte-budget guards before copying recovery or staging databases."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fpl.jobs import build_db
from fpl.jobs import operational_disk as disk


@pytest.mark.parametrize(
    ("projected_gib", "status"), [(30, "OK"), (29, "WARNING"), (20, "WARNING")]
)
def test_exact_thresholds_and_missing_destination_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    projected_gib: int,
    status: str,
) -> None:
    queried: list[Path] = []

    def usage(path: Path) -> SimpleNamespace:
        queried.append(path)
        return SimpleNamespace(free=(projected_gib + 3) * disk.GIB)

    monkeypatch.setattr(disk.shutil, "disk_usage", usage)
    destination = tmp_path / "future" / "backup.duckdb"
    report = disk.check_disk_space(destination, 3 * disk.GIB)
    assert queried == [tmp_path.resolve()]
    assert report["required_bytes"] == 3 * disk.GIB
    assert report["projected_free_bytes"] == projected_gib * disk.GIB
    assert report["status"] == status
    assert ("Low disk space" in caplog.text) == (status == "WARNING")
    assert not destination.parent.exists()


def test_existing_destination_still_reserves_full_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "backup.duckdb"
    destination.write_bytes(b"existing recovery evidence")
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: SimpleNamespace(free=21 * disk.GIB))
    with pytest.raises(RuntimeError, match="allocation blocked"):
        disk.check_disk_space(destination, disk.GIB + 1)
    assert destination.read_bytes() == b"existing recovery evidence"


@pytest.mark.parametrize("required", [-1, True, 1.5])
def test_invalid_size_fails_closed(tmp_path: Path, required: int) -> None:
    with pytest.raises(ValueError, match="nonnegative integer"):
        disk.check_disk_space(tmp_path, required)


def test_shared_database_copy_blocks_before_writing_or_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "live.duckdb"
    source.write_bytes(b"source remains intact")
    destination = tmp_path / "before.duckdb"
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: SimpleNamespace(free=20 * disk.GIB))
    with pytest.raises(RuntimeError, match="minimum is 20 GiB"):
        build_db._prepare_temporary_database(source, destination)
    assert source.read_bytes() == b"source remains intact"
    assert not destination.exists()


def test_shared_database_copy_preserves_hash_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "live.duckdb"
    source.write_bytes(b"existing version")
    destination = tmp_path / "before.duckdb"
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: SimpleNamespace(free=40 * disk.GIB))
    digest = build_db._prepare_temporary_database(source, destination)
    assert digest == build_db._sha256(source) == build_db._sha256(destination)
    assert source.read_bytes() == destination.read_bytes()


def test_unresolved_wal_is_rejected_before_disk_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "live.duckdb"
    source.write_bytes(b"existing version")
    wal = build_db._wal_path(source)
    wal.write_bytes(b"unresolved")

    def unexpected_disk_query(path: Path) -> SimpleNamespace:
        raise AssertionError("WAL refusal must precede allocation checks")

    monkeypatch.setattr(disk.shutil, "disk_usage", unexpected_disk_query)
    with pytest.raises(RuntimeError, match="exists"):
        build_db._prepare_temporary_database(source, tmp_path / "before.duckdb")
    assert wal.read_bytes() == b"unresolved"


def test_absent_source_never_allocates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_disk_query(path: Path) -> SimpleNamespace:
        raise AssertionError("No existing database means no copy allocation")

    monkeypatch.setattr(disk.shutil, "disk_usage", unexpected_disk_query)
    assert (
        build_db._prepare_temporary_database(tmp_path / "absent.duckdb", tmp_path / "new.duckdb")
        is None
    )
