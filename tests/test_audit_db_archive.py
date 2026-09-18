from __future__ import annotations

import gzip
import hashlib
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fpl.jobs import audit_db_archive as archive


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "verification" / "frozen.duckdb"
    path.parent.mkdir()
    path.write_bytes(bytes(range(256)) * 4096)
    monkeypatch.setattr(archive, "check_disk_space", Mock(return_value={"status": "OK"}))
    return path


def test_lossless_compression_and_exact_path_restore(source: Path, tmp_path: Path) -> None:
    original = source.read_bytes()
    receipt = archive.compress_audit_database(source, tmp_path)
    assert not source.exists()
    assert receipt["source_path"] == str(source.resolve())
    assert receipt["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["source_bytes"] == len(original)
    assert receipt["archive_bytes"] < receipt["source_bytes"]
    assert receipt["storage_scope"] == "LOCAL_PRIVATE_AUDIT"
    assert gzip.decompress(Path(receipt["archive_path"]).read_bytes()) == original
    assert archive.verify_audit_archive(source, tmp_path) == receipt
    assert archive.restore_audit_database(source, tmp_path) == receipt
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError, match="overwrite"):
        archive.restore_audit_database(source, tmp_path)
    assert source.read_bytes() == original


def test_idempotent_receipt_is_never_rewritten(source: Path, tmp_path: Path) -> None:
    first = archive.compress_audit_database(source, tmp_path)
    receipt_path = Path(str(source) + ".gz.receipt.json")
    original = receipt_path.read_bytes()
    assert archive.compress_audit_database(source, tmp_path) == first
    assert receipt_path.read_bytes() == original
    archive.restore_audit_database(source, tmp_path)
    assert archive.compress_audit_database(source, tmp_path) == first
    assert receipt_path.read_bytes() == original


def test_compressed_bytes_are_deterministic(source: Path, tmp_path: Path) -> None:
    second = source.with_name("second.duckdb")
    second.write_bytes(source.read_bytes())
    first_receipt = archive.compress_audit_database(source, tmp_path, retire_source=False)
    second_receipt = archive.compress_audit_database(second, tmp_path)
    assert first_receipt["archive_sha256"] == second_receipt["archive_sha256"]
    assert source.exists()


def test_forecasts_and_frozen_manifests_are_untouched(source: Path, tmp_path: Path) -> None:
    manifest = source.parent / "manifest.json"
    frozen = json.dumps({"database": str(source), "sha256": archive._file_digest(source)[0]})
    manifest.write_text(frozen)
    forecast = tmp_path / "predictions" / "frozen.jsonl"
    forecast.parent.mkdir()
    forecast.write_text(frozen)
    archive.compress_audit_database(source, tmp_path)
    assert manifest.read_text() == frozen
    assert forecast.read_text() == frozen


@pytest.mark.parametrize("suffix", [".wal", ".lock", ".daily-sdp.lock"])
def test_unresolved_wal_or_lock_preserves_everything(
    source: Path, tmp_path: Path, suffix: str
) -> None:
    original = source.read_bytes()
    blocker = Path(str(source) + suffix)
    blocker.write_bytes(b"unresolved")
    with pytest.raises(ValueError, match="lock/WAL"):
        archive.compress_audit_database(source, tmp_path)
    assert source.read_bytes() == original
    assert blocker.read_bytes() == b"unresolved"
    assert not Path(str(source) + ".gz").exists()


def test_existing_archive_collision_preserves_source(source: Path, tmp_path: Path) -> None:
    original = source.read_bytes()
    packed = Path(str(source) + ".gz")
    packed.write_bytes(gzip.compress(b"different", mtime=0))
    with pytest.raises(ValueError, match="collides"):
        archive.compress_audit_database(source, tmp_path)
    assert source.read_bytes() == original
    assert gzip.decompress(packed.read_bytes()) == b"different"


def test_corrupt_archive_never_restores(source: Path, tmp_path: Path) -> None:
    receipt = archive.compress_audit_database(source, tmp_path)
    Path(receipt["archive_path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash/size"):
        archive.restore_audit_database(source, tmp_path)
    assert not source.exists()


def test_interrupted_receipt_publication_keeps_source_and_can_resume(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = source.read_bytes()
    publish = archive._publish

    def interrupt(temporary: Path, destination: Path) -> None:
        if destination.name.endswith("receipt.json"):
            raise OSError("simulated interruption")
        publish(temporary, destination)

    monkeypatch.setattr(archive, "_publish", interrupt)
    with pytest.raises(OSError, match="interruption"):
        archive.compress_audit_database(source, tmp_path)
    assert source.read_bytes() == original
    assert Path(str(source) + ".gz").exists()
    assert not Path(str(source) + ".gz.receipt.json").exists()
    assert not list(source.parent.glob("*.tmp-*"))
    monkeypatch.setattr(archive, "_publish", publish)
    archive.compress_audit_database(source, tmp_path)
    archive.restore_audit_database(source, tmp_path)
    assert source.read_bytes() == original


def test_failed_temporary_verification_never_publishes_or_deletes(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = source.read_bytes()
    monkeypatch.setattr(archive, "_unpacked_digest", lambda _: ("bad", 0))
    with pytest.raises(ValueError, match="failed verification"):
        archive.compress_audit_database(source, tmp_path)
    assert source.read_bytes() == original
    assert not Path(str(source) + ".gz").exists()
    assert not list(source.parent.glob("*.tmp-*"))


def test_source_mutation_is_not_retired(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unpacked = archive._unpacked_digest

    def mutate(path: Path) -> tuple[str, int]:
        result = unpacked(path)
        source.write_bytes(b"new data")
        return result

    monkeypatch.setattr(archive, "_unpacked_digest", mutate)
    with pytest.raises(ValueError, match="changed"):
        archive.compress_audit_database(source, tmp_path)
    assert source.read_bytes() == b"new data"
    assert not Path(str(source) + ".gz").exists()


def test_receipt_identity_collision_fails_closed(source: Path, tmp_path: Path) -> None:
    receipt = archive.compress_audit_database(source, tmp_path, retire_source=False)
    receipt["source_path"] = "different"
    Path(str(source) + ".gz.receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="identity"):
        archive.compress_audit_database(source, tmp_path)
    assert source.exists()


@pytest.mark.parametrize("folder", sorted(archive._PROTECTED))
def test_protected_directories_refused(source: Path, tmp_path: Path, folder: str) -> None:
    protected = tmp_path / folder / "protected.duckdb"
    protected.parent.mkdir()
    protected.write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="active"):
        archive.compress_audit_database(protected, tmp_path)
    assert protected.exists()


def test_traversal_to_active_data_is_refused(source: Path, tmp_path: Path) -> None:
    protected = tmp_path / "data" / "protected.duckdb"
    protected.parent.mkdir()
    protected.write_bytes(source.read_bytes())
    traversal = source.parent / ".." / "data" / "protected.duckdb"
    with pytest.raises(ValueError, match="active"):
        archive.compress_audit_database(traversal, tmp_path)
    assert protected.exists()


def test_outside_root_is_refused(source: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside"):
        archive.compress_audit_database(source, tmp_path / "other")
    assert source.exists()


def test_reparse_path_is_refused_without_following_link(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lstat = Path.lstat

    def reparse(path: Path) -> object:
        if path == source:
            return SimpleNamespace(
                st_mode=stat.S_IFREG, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="symlink/reparse"):
        archive.compress_audit_database(source, tmp_path)
    assert source.exists()


def test_disk_guard_blocks_compression_and_restore(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = Mock(side_effect=RuntimeError("insufficient disk space"))
    monkeypatch.setattr(archive, "check_disk_space", guard)
    with pytest.raises(RuntimeError, match="disk space"):
        archive.compress_audit_database(source, tmp_path)
    assert source.exists()
    assert guard.call_args.args[1] > source.stat().st_size
    monkeypatch.setattr(archive, "check_disk_space", Mock())
    receipt = archive.compress_audit_database(source, tmp_path)
    monkeypatch.setattr(archive, "check_disk_space", guard)
    with pytest.raises(RuntimeError, match="disk space"):
        archive.restore_audit_database(source, tmp_path)
    assert not source.exists()
    assert guard.call_args.args[1] == receipt["source_bytes"]
