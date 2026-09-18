from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from fpl.jobs import operational_lock as locking


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=20)
    return child.pid


def test_recovers_dead_legacy_owner_and_preserves_original_bytes(tmp_path: Path) -> None:
    lock = tmp_path / ".daily-sdp.lock"
    original = f'{{ "pid": {_dead_pid()}, "started_at": "original time" }}\n'.encode()
    lock.write_bytes(original)
    checked: list[bool] = []
    with locking.operational_lock(lock, validate_recovery=lambda: checked.append(True)) as receipt:
        assert receipt is not None
        assert checked == [True]
        assert receipt["original_lock_sha256"] == hashlib.sha256(original).hexdigest()
        archive = Path(receipt["original_lock_path"])
        assert archive.read_bytes() == original
        assert json.loads((archive.parent / "receipt.json").read_text()) == receipt
        assert json.loads(lock.read_bytes())["pid"] == os.getpid()
    assert not lock.exists()
    assert archive.read_bytes() == original
    assert lock.with_name(lock.name + ".guard").exists()
    with locking.operational_lock(lock) as recovered:
        assert recovered is None


@pytest.mark.parametrize("payload", [b"", b"not JSON", b"[]", b"{}", b'{"pid":true}', b'{"pid":0}'])
def test_malformed_metadata_is_preserved(tmp_path: Path, payload: bytes) -> None:
    lock = tmp_path / ".dashboard-refresh.lock"
    lock.write_bytes(payload)
    with pytest.raises(FileExistsError, match="unrecognized"):
        with locking.operational_lock(lock):
            pytest.fail("malformed owner admitted")
    assert lock.read_bytes() == payload
    assert not lock.with_name(lock.name + ".recovered").exists()


@pytest.mark.parametrize("alive", [True, None])
def test_live_or_unknown_pid_is_preserved(tmp_path: Path, monkeypatch, alive: bool | None) -> None:
    lock = tmp_path / "job.lock"
    original = json.dumps({"pid": os.getpid()}).encode()
    lock.write_bytes(original)
    monkeypatch.setattr(locking, "_pid_alive", lambda _: alive)
    with pytest.raises(FileExistsError, match="active or unknown"):
        with locking.operational_lock(lock):
            pytest.fail("unproven dead owner admitted")
    assert lock.read_bytes() == original


def test_native_pid_probe_keeps_current_process_alive() -> None:
    assert locking._pid_alive(os.getpid()) is True
    assert locking._pid_alive(_dead_pid()) is False


def test_wal_veto_keeps_dead_lock_and_wal_untouched(tmp_path: Path) -> None:
    lock, wal = tmp_path / "job.lock", tmp_path / "database.wal"
    original = json.dumps({"pid": _dead_pid()}).encode()
    lock.write_bytes(original)
    wal.write_bytes(b"unresolved WAL bytes")
    with pytest.raises(RuntimeError, match="unresolved WAL"):
        with locking.operational_lock(
            lock, wal=wal, validate_recovery=lambda: pytest.fail("probe after WAL veto")
        ):
            pytest.fail("WAL admitted")
    assert lock.read_bytes() == original
    assert wal.read_bytes() == b"unresolved WAL bytes"
    assert not lock.with_name(lock.name + ".recovered").exists()


def test_failed_database_probe_preserves_orphan(tmp_path: Path) -> None:
    lock = tmp_path / "job.lock"
    original = json.dumps({"pid": _dead_pid()}).encode()
    lock.write_bytes(original)

    def fail() -> None:
        raise RuntimeError("external DuckDB writer")

    with pytest.raises(RuntimeError, match="external DuckDB writer"):
        with locking.operational_lock(lock, validate_recovery=fail):
            pytest.fail("unsafe database admitted")
    assert lock.read_bytes() == original
    assert not lock.with_name(lock.name + ".recovered").exists()


def test_real_process_crash_releases_guard_and_next_start_recovers(tmp_path: Path) -> None:
    lock = tmp_path / "job.lock"
    script = """
import os, sys
from pathlib import Path
from fpl.jobs.operational_lock import operational_lock
with operational_lock(Path(sys.argv[1])):
    os._exit(19)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(lock)], capture_output=True, timeout=20, check=False
    )
    assert child.returncode == 19, child.stderr
    original = lock.read_bytes()
    with locking.operational_lock(lock) as receipt:
        assert receipt is not None
        assert Path(receipt["original_lock_path"]).read_bytes() == original
    assert not lock.exists()


def test_nested_and_separate_process_overlap_are_rejected(tmp_path: Path) -> None:
    lock = tmp_path / "job.lock"
    script = """
import sys
from pathlib import Path
from fpl.jobs.operational_lock import operational_lock
try:
    with operational_lock(Path(sys.argv[1])):
        sys.exit(7)
except FileExistsError:
    sys.exit(0)
"""
    with locking.operational_lock(lock):
        with pytest.raises(FileExistsError):
            with locking.operational_lock(lock):
                pytest.fail("nested owner admitted")
        original = lock.read_bytes()
        child = subprocess.run(
            [sys.executable, "-c", script, str(lock)], capture_output=True, timeout=20, check=False
        )
        assert child.returncode == 0, child.stderr
        assert lock.read_bytes() == original
    assert not lock.exists()


def test_competing_startups_recover_once_and_admit_only_one_owner(tmp_path: Path) -> None:
    lock = tmp_path / "job.lock"
    original = json.dumps({"pid": _dead_pid()}).encode()
    lock.write_bytes(original)
    script = """
import sys
from pathlib import Path
from fpl.jobs.operational_lock import operational_lock
sys.stdin.readline()
try:
    with operational_lock(Path(sys.argv[1])) as receipt:
        print('recovered' if receipt else 'new', flush=True)
        sys.stdin.readline()
except FileExistsError:
    print('blocked', flush=True)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(lock)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            assert child.stdin is not None
            child.stdin.write("start\n")
            child.stdin.flush()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outputs = []
            for child in children:
                assert child.stdout is not None
                outputs.append(pool.submit(child.stdout.readline))
            try:
                observed = [output.result(timeout=20).strip() for output in outputs]
            except TimeoutError:
                for child in children:
                    child.kill()
                raise
        assert sorted(observed) == ["blocked", "recovered"]
        for child in children:
            if child.poll() is None:
                assert child.stdin is not None
                child.stdin.close()
            child.wait(timeout=20)
            assert child.returncode == 0
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=20)
    archives = list(lock.with_name(lock.name + ".recovered").glob("*/original.lock"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == original
    assert not lock.exists()


def test_body_failure_releases_lock_and_does_not_delete_replacement(tmp_path: Path) -> None:
    lock = tmp_path / "job.lock"
    with pytest.raises(RuntimeError, match="setup failed"):
        with locking.operational_lock(lock):
            raise RuntimeError("setup failed")
    assert not lock.exists()
    with locking.operational_lock(lock):
        lock.write_bytes(b"manual replacement")
    assert lock.read_bytes() == b"manual replacement"
