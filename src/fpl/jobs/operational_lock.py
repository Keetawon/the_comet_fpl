"""Crash-recoverable local job locks; uncertain owners and database WALs fail closed."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4


def _pid_alive(pid: int) -> bool | None:
    """Return False only after the operating system proves the process has exited."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        if pid > 0xFFFFFFFF:
            return None
        # SYNCHRONIZE allows a zero-time wait, with no permission to kill or modify it.
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None  # invalid PID
        try:
            state = kernel.WaitForSingleObject(handle, 0)
            return False if state == 0 else True if state == 258 else None
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        return None
    return True


def _guard_lock(handle: BinaryIO, *, release: bool = False) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB)


def _check_wal(wal: Path | None) -> None:
    if wal is not None and wal.exists():
        raise RuntimeError("unresolved WAL: close writers and inspect recovery before retrying")


def _recover(
    path: Path,
    *,
    wal: Path | None,
    validate_recovery: Callable[[], None] | None,
) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            original = handle.read(65537)
    except FileNotFoundError:
        return None
    try:
        if len(original) > 65536:
            raise ValueError("oversized metadata")
        metadata = json.loads(original)
        pid = metadata.get("pid") if isinstance(metadata, dict) else None
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError("missing or invalid PID")
    except (ValueError, UnicodeError) as exc:
        raise FileExistsError(f"unrecognized operational lock metadata: {path}") from exc
    if _pid_alive(pid) is not False:
        raise FileExistsError(f"operational lock owner is active or unknown (PID {pid}): {path}")
    _check_wal(wal)
    if validate_recovery is not None:
        validate_recovery()
    _check_wal(wal)
    now = datetime.now(UTC)
    archive = path.with_name(path.name + ".recovered") / (
        now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex
    )
    archive.mkdir(parents=True)
    original_path = archive / "original.lock"
    with original_path.open("xb") as handle:
        handle.write(original)
        handle.flush()
        os.fsync(handle.fileno())
    receipt: dict[str, Any] = {
        "lock_path": str(path.resolve()),
        "previous_pid": pid,
        "recovered_at": now.isoformat(),
        "original_lock_path": str(original_path.resolve()),
        "original_lock_sha256": hashlib.sha256(original).hexdigest(),
    }
    with (archive / "receipt.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    # Cooperating callers hold the guard. Also refuse an unexpected manual replacement.
    if path.read_bytes() != original:
        raise FileExistsError(f"operational lock changed during recovery: {path}")
    path.unlink()
    return receipt


@contextmanager
def operational_lock(
    path: Path,
    *,
    wal: Path | None = None,
    validate_recovery: Callable[[], None] | None = None,
) -> Iterator[dict[str, Any] | None]:
    """Hold an OS guard and PID sidecar; archive only proven-dead owners before reuse.

    The guard file is permanent: unlinking it could give contenders different inodes.
    The OS releases its lock on process death. Legacy sidecars require a valid dead PID;
    age, malformed metadata and permission failures never authorize recovery.
    """
    guard = path.with_name(path.name + ".guard")
    with guard.open("a+b", buffering=0) as handle:
        try:
            _guard_lock(handle)
        except OSError as exc:
            raise FileExistsError(f"operational lock is held or unavailable: {path}") from exc
        try:
            _check_wal(wal)
            recovered = _recover(path, wal=wal, validate_recovery=validate_recovery)
            metadata = json.dumps(
                {"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat(), "id": uuid4().hex}
            ).encode("utf-8")
            with path.open("xb") as sidecar:
                sidecar.write(metadata)
                sidecar.flush()
                os.fsync(sidecar.fileno())
            try:
                yield recovered
            finally:
                try:
                    if path.read_bytes() == metadata:
                        path.unlink()
                except FileNotFoundError:
                    pass
        finally:
            _guard_lock(handle, release=True)
