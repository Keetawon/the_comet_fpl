"""Verify committed snapshot packages and load them into the live capture contract."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import duckdb

from fpl.config import load_sources
from fpl.ingest.live_snapshot import CapturedPayload, CaptureResult, capture_payload, write_capture

_ELEMENT_MEMBER: Final[re.Pattern[str]] = re.compile(r"^(?:\./)?([0-9]+)\.json$")


def _verify_files(directory: Path) -> bytes:
    checksum_path = directory / "SHA256SUMS"
    raw = checksum_path.read_bytes()
    seen: set[str] = set()
    for line in raw.decode("utf-8").splitlines():
        expected, separator, declared_path = line.partition("  ")
        if not separator or len(expected) != 64:
            raise ValueError(f"invalid checksum line in {checksum_path}: {line!r}")
        filename = Path(declared_path).name
        path = directory / filename
        if not path.is_file():
            raise ValueError(f"snapshot payload is missing: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"snapshot checksum mismatch: {path}")
        seen.add(filename)
    if not seen:
        raise ValueError(f"no payload checksums in {checksum_path}")
    archives = {path.name for path in directory.glob("*.gz")}
    if seen != archives:
        raise ValueError(
            f"checksum inventory mismatch in {directory}: checked={sorted(seen)}, "
            f"archives={sorted(archives)}"
        )
    return raw


def _read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _payloads(directory: Path, manifest: dict[str, Any]) -> list[CapturedPayload]:
    captured = [
        capture_payload(
            "bootstrap-static", _read_gzip_json(directory / "bootstrap-static.json.gz")
        ),
        capture_payload("fixtures", _read_gzip_json(directory / "fixtures.json.gz")),
    ]
    history_archive = directory / "element-summary.tar.gz"
    if history_archive.is_file():
        with tarfile.open(history_archive, "r:gz") as archive:
            for member in sorted(archive.getmembers(), key=lambda item: item.name):
                if member.isdir() and member.name in {".", "./"}:
                    continue
                match = _ELEMENT_MEMBER.fullmatch(member.name)
                if not member.isfile() or match is None:
                    raise ValueError(f"unsafe or unexpected element archive member: {member.name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"could not read element archive member: {member.name}")
                captured.append(
                    capture_payload(
                        "element-summary",
                        json.loads(stream.read()),
                        parameter=match.group(1),
                    )
                )
        summary_count = len(captured) - 2
        expected_summaries = manifest.get("element_payloads")
        if expected_summaries is not None and summary_count != int(expected_summaries):
            raise ValueError(
                f"element-summary count mismatch: expected {expected_summaries}, "
                f"found {summary_count}"
            )
        expected_rows = manifest.get("player_fixture_rows")
        actual_rows = sum(
            len(item.payload.get("history", []))
            for item in captured
            if item.endpoint == "element-summary" and isinstance(item.payload, dict)
        )
        if expected_rows is not None and actual_rows != int(expected_rows):
            raise ValueError(
                f"player-fixture row mismatch: expected {expected_rows}, found {actual_rows}"
            )
        return captured

    event_files = sorted(directory.glob("event-live-*.json.gz"))
    if event_files:
        if len(event_files) != 1:
            raise ValueError(f"expected one event-live payload in {directory}")
        parameter = event_files[0].name.removeprefix("event-live-").removesuffix(".json.gz")
        if not parameter.isdigit():
            parameter = str(manifest.get("event_live", {}).get("gw", ""))
        captured.append(
            capture_payload("event-live", _read_gzip_json(event_files[0]), parameter=parameter)
        )
    return captured


def load_directory(con: duckdb.DuckDBPyConnection, directory: Path) -> CaptureResult | None:
    """Verify and load one workflow snapshot. Re-loading the same directory is a no-op."""
    manifest_path = directory / "manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if str(manifest.get("schema_version", "1")) != "1":
        raise ValueError(f"unsupported snapshot schema in {manifest_path}")
    checksums = _verify_files(directory)
    identity = "file-" + hashlib.sha256(manifest_raw + checksums).hexdigest()
    exists = con.execute(
        "SELECT count(*) FROM snapshot_capture WHERE capture_id = ?", [identity]
    ).fetchone()
    if exists and exists[0]:
        return None

    captured_at_raw = str(manifest["captured_at"]).replace("Z", "+00:00")
    captured_at = datetime.fromisoformat(captured_at_raw)
    history_gw = manifest.get("history_through_gw")
    event_live = manifest.get("event_live")
    event_gw = event_live.get("gw") if isinstance(event_live, dict) else None
    gw_raw = history_gw if history_gw is not None else event_gw
    gw_text = str(gw_raw or "")
    gw = int(gw_text) if gw_text.isdigit() else None
    mode = "player-history" if (directory / "element-summary.tar.gz").is_file() else "daily"
    season_raw = manifest.get("season")
    if season_raw is None and manifest.get("bootstrap_first_deadline"):
        start_year = int(str(manifest["bootstrap_first_deadline"])[:4])
        season_raw = f"{start_year}-{str(start_year + 1)[2:]}"
    season = str(season_raw or load_sources().current_season.season)
    return write_capture(
        con,
        _payloads(directory, manifest),
        season=season,
        gw=gw,
        mode=mode,
        captured_at=captured_at,
        capture_id=identity,
    )
