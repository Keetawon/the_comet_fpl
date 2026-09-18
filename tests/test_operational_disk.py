"""Offline byte-budget guards for operational copies, not general database builds."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from fpl.jobs import build_db, daily_pl_sdp
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


def test_operational_backup_blocks_before_copying_or_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "live.duckdb"
    with duckdb.connect(str(source)) as con:
        con.execute("CREATE TABLE retained(i INTEGER)")
    before = build_db._sha256(source)
    destination = tmp_path / "before.duckdb"
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: SimpleNamespace(free=20 * disk.GIB))
    with pytest.raises(RuntimeError, match="minimum is 20 GiB"):
        with daily_pl_sdp.writer_lock(source, backup=destination):
            pytest.fail("low space allowed database write")
    assert build_db._sha256(source) == before
    assert not destination.exists()
    assert not Path(str(source) + ".daily-sdp.lock").exists()


def test_operational_backup_preserves_hash_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "live.duckdb"
    with duckdb.connect(str(source)) as con:
        con.execute("CREATE TABLE retained(i INTEGER)")
    before = build_db._sha256(source)
    destination = tmp_path / "before.duckdb"
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: SimpleNamespace(free=40 * disk.GIB))
    with daily_pl_sdp.writer_lock(source, backup=destination) as con:
        assert con.execute("SELECT count(*) FROM retained").fetchone() == (0,)
    assert before == build_db._sha256(source) == build_db._sha256(destination)
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
    with pytest.raises(RuntimeError, match="WAL"):
        with daily_pl_sdp.writer_lock(source, backup=tmp_path / "before.duckdb"):
            pytest.fail("unresolved WAL allowed copy")
    assert wal.read_bytes() == b"unresolved"


def test_general_build_copy_does_not_inherit_operational_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "research.duckdb"
    source.write_bytes(b"tiny non-operational copy")
    destination = tmp_path / "rebuild.duckdb"
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    assert build_db._prepare_temporary_database(source, destination) == build_db._sha256(source)
    assert destination.read_bytes() == source.read_bytes()


def test_absent_source_never_allocates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_disk_query(path: Path) -> SimpleNamespace:
        raise AssertionError("No existing database means no copy allocation")

    monkeypatch.setattr(disk.shutil, "disk_usage", unexpected_disk_query)
    assert (
        build_db._prepare_temporary_database(tmp_path / "absent.duckdb", tmp_path / "new.duckdb")
        is None
    )
