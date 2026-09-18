"""Lossless local-only audit DB archives; never uploads or rewrites scientific receipts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from fpl.jobs.operational_disk import check_disk_space
from fpl.jobs.operational_lock import operational_lock

_CHUNK = 1024 * 1024
_PROTECTED = {"data", ".venv", "predictions", "plan-server", "dashboard-plans", "r2", "credentials"}


class _Reader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def _safe(path: Path, root: Path) -> Path:
    path, root = path.absolute(), root.absolute()
    if path == root or not path.is_relative_to(root):
        raise ValueError("audit archive path must be inside the explicit root")
    if any(part.lower() in _PROTECTED for part in (root.name, *path.relative_to(root).parts[:-1])):
        raise ValueError("audit archiving refuses active data/runtime/forecast directories")
    for ancestor in (path, *path.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if ancestor.is_symlink() or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("audit archiving refuses symlink/reparse paths")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise ValueError("resolved audit archive path escapes root")
    if any(part.lower() in _PROTECTED for part in resolved.relative_to(root.resolve()).parts[:-1]):
        raise ValueError("audit archiving refuses active data/runtime/forecast directories")
    return resolved


def _paths(source: Path, root: Path) -> tuple[Path, Path, Path]:
    source = _safe(source, root)
    if source.suffix != ".duckdb":
        raise ValueError("audit source must have a .duckdb suffix")
    archive = _safe(source.with_name(source.name + ".gz"), root)
    receipt = _safe(source.with_name(source.name + ".gz.receipt.json"), root)
    return source, archive, receipt


def _idle(source: Path) -> None:
    for suffix in (".wal", ".daily-sdp.lock", ".lock"):
        if source.with_name(source.name + suffix).exists():
            raise ValueError("audit database has an unresolved lock/WAL")


def _digest(handle: _Reader) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    while block := handle.read(_CHUNK):
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def _file_digest(path: Path) -> tuple[str, int]:
    with path.open("rb") as handle:
        return _digest(handle)


def _unpacked_digest(path: Path) -> tuple[str, int]:
    with gzip.open(path, "rb") as handle:
        return _digest(handle)


def _signature(source: Path) -> tuple[int, int, int, int]:
    info = source.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("audit source must be a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _publish(temporary: Path, destination: Path) -> None:
    # Atomic exclusive publication: unlike POSIX rename, link cannot replace a file.
    os.link(temporary, destination)
    temporary.unlink()


def _verify(source: Path, archive: Path, receipt_path: Path) -> dict[str, Any]:
    receipt: dict[str, Any] = json.loads(receipt_path.read_bytes())
    if (
        receipt.get("schema_version") != 1
        or receipt.get("source_path") != str(source)
        or receipt.get("archive_path") != str(archive)
        or receipt.get("encoding") != "gzip-mtime-0"
        or not isinstance(receipt.get("source_bytes"), int)
        or isinstance(receipt.get("source_bytes"), bool)
        or receipt["source_bytes"] < 0
    ):
        raise ValueError("audit archive receipt identity mismatch")
    if _file_digest(archive) != (receipt.get("archive_sha256"), receipt.get("archive_bytes")):
        raise ValueError("compressed audit archive hash/size mismatch")
    if _unpacked_digest(archive) != (receipt.get("source_sha256"), receipt["source_bytes"]):
        raise ValueError("decompressed audit archive hash/size mismatch")
    return receipt


def verify_audit_archive(source: Path, root: Path) -> dict[str, Any]:
    """Verify replay bytes against the append-only receipt without restoring a DB."""
    return _verify(*_paths(source, root))


def compress_audit_database(
    source: Path, root: Path, *, retire_source: bool = True
) -> dict[str, Any]:
    """Archive an explicitly selected idle audit DB; caller holds operational writer gates.

    Source removal occurs only after fsync, exclusive archive/receipt publication,
    decompressed hash verification and a final unchanged-source check. An interrupted
    attempt may leave a valid archive without a receipt; it never discards its source.
    """
    source, archive, receipt_path = _paths(source, root)
    _idle(source)
    lock = _safe(source.with_name(source.name + ".archive.lock"), root)
    with operational_lock(lock):
        _idle(source)
        if receipt_path.exists():
            receipt = _verify(source, archive, receipt_path)
            if not source.exists():
                return receipt
        else:
            signature = _signature(source)
            original_hash, original_bytes = _file_digest(source)
            if not archive.exists():
                # Gzip can slightly expand incompressible bytes; reserve a conservative bound.
                check_disk_space(archive, original_bytes + original_bytes // 100 + _CHUNK)
                temporary = _safe(archive.with_name(archive.name + ".tmp-" + uuid4().hex), root)
                try:
                    with temporary.open("xb") as output:
                        with (
                            gzip.GzipFile(
                                filename="", mode="wb", fileobj=output, mtime=0, compresslevel=1
                            ) as packed,
                            source.open("rb") as incoming,
                        ):
                            shutil.copyfileobj(incoming, packed, _CHUNK)
                        output.flush()
                        os.fsync(output.fileno())
                    if _unpacked_digest(temporary) != (original_hash, original_bytes):
                        raise ValueError("temporary compressed audit data failed verification")
                    _idle(source)
                    if _signature(source) != signature:
                        raise ValueError("audit source changed during compression")
                    _publish(temporary, archive)
                finally:
                    temporary.unlink(missing_ok=True)
            if _unpacked_digest(archive) != (original_hash, original_bytes):
                raise ValueError("existing audit archive collides with source")
            if _signature(source) != signature:
                raise ValueError("audit source changed during compression")
            packed_hash, packed_bytes = _file_digest(archive)
            receipt = {
                "schema_version": 1,
                "source_path": str(source),
                "source_sha256": original_hash,
                "source_bytes": original_bytes,
                "archive_path": str(archive),
                "archive_sha256": packed_hash,
                "archive_bytes": packed_bytes,
                "encoding": "gzip-mtime-0",
                "compression_level": 1,
                "verified_at": datetime.now(UTC).isoformat(),
                "storage_scope": "LOCAL_PRIVATE_AUDIT",
            }
            temporary = _safe(
                receipt_path.with_name(receipt_path.name + ".tmp-" + uuid4().hex), root
            )
            try:
                with temporary.open("xb") as output:
                    output.write((json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
                    output.flush()
                    os.fsync(output.fileno())
                _publish(temporary, receipt_path)
            finally:
                temporary.unlink(missing_ok=True)
        _idle(source)
        _safe(source, root)
        signature = _signature(source)
        if _file_digest(source) != (receipt["source_sha256"], receipt["source_bytes"]):
            raise ValueError("audit source changed; original preserved")
        if _signature(source) != signature:
            raise ValueError("audit source changed during final verification")
        _idle(source)
        if retire_source:
            source.unlink()
        return receipt


def restore_audit_database(source: Path, root: Path) -> dict[str, Any]:
    """Restore only the receipt's original path, byte-for-byte, without overwriting it."""
    source, archive, receipt_path = _paths(source, root)
    _idle(source)
    lock = _safe(source.with_name(source.name + ".archive.lock"), root)
    with operational_lock(lock):
        if source.exists():
            raise FileExistsError(f"restore refuses to overwrite {source}")
        receipt = _verify(source, archive, receipt_path)
        check_disk_space(source, receipt["source_bytes"])
        temporary = _safe(source.with_name(source.name + ".restore-" + uuid4().hex), root)
        try:
            with temporary.open("xb") as output, gzip.open(archive, "rb") as incoming:
                shutil.copyfileobj(incoming, output, _CHUNK)
                output.flush()
                os.fsync(output.fileno())
            if _file_digest(temporary) != (receipt["source_sha256"], receipt["source_bytes"]):
                raise ValueError("restored audit data failed verification")
            _idle(source)
            _safe(source, root)
            _publish(temporary, source)
        finally:
            temporary.unlink(missing_ok=True)
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("compress", "restore", "verify"))
    parser.add_argument("--source", required=True, type=Path, help="Original .duckdb path")
    parser.add_argument("--root", required=True, type=Path, help="Explicit operations root")
    args = parser.parse_args()
    functions = {
        "compress": compress_audit_database,
        "restore": restore_audit_database,
        "verify": verify_audit_archive,
    }
    print(json.dumps(functions[args.operation](args.source, args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
