"""One bounded, raw-preserving historical acquisition; no modelling or database writes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import re
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from fpl.config import repo_root
from fpl.jobs.competitive_participation_pilot import (
    ResponseRecorder,
    file_sha256,
    publish_bytes,
    publish_json,
)

LOGGER = logging.getLogger(__name__)
SOURCE = "vaastav/Fantasy-Premier-League"
AUDIT_PATH = "results/historical_player_attacking_source_audit_2026-09-08.json"
PATHS = {
    "stats": "data/2023-24/gws/merged_gw.csv",
    "registry": "data/2023-24/players_raw.csv",
    "fixtures": "data/2023-24/fixtures.csv",
    "teams": "data/2023-24/teams.csv",
}
IMPLEMENTATION = (
    "src/fpl/jobs/backfill_historical_player_attacking.py",
    "src/fpl/validate/historical_player_attacking.py",
    "src/fpl/jobs/competitive_participation_pilot.py",
    "src/fpl/config.py",
)
VERSION_METADATA = frozenset(
    {
        "source_name",
        "source_record_id",
        "source_snapshot_id",
        "snapshot_id",
        "source_known_at",
        "capture_known_at",
        "available_at",
        "source_sha256",
        "provenance",
        "interpretation_known_at",
        "evidence_class",
    }
)


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("source and capture timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def source_url(snapshot: dict[str, Any], role: str) -> str:
    return f"https://raw.githubusercontent.com/{SOURCE}/{snapshot['commit_sha']}/{snapshot['paths'][role]}"


def load_scope(path: Path) -> dict[str, Any]:
    scope = yaml.safe_load(path.read_bytes())
    if not isinstance(scope, dict) or scope.get("contract_version") != "1.0":
        raise ValueError("unsupported historical acquisition contract")
    if scope.get("source_repository") != SOURCE or scope.get("season") != "2023-24":
        raise ValueError("source/season is outside the bounded historical acquisition")
    if scope.get("evidence_class") != "ARCHIVED_AS_OF":
        raise ValueError("only separately audited archived-as-of snapshots are licensed")
    if not re.fullmatch(r"[a-z][a-z0-9_]+", str(scope.get("study_id", ""))):
        raise ValueError("unsafe acquisition identity")
    limits = scope["limits"]
    if not (
        0 < limits["maximum_urls"] <= 152
        and 0 < limits["maximum_attempts"] <= 304
        and 0 < limits["maximum_bytes"] <= 192 * 1024 * 1024
        and limits["minimum_interval_seconds"] >= 1.5
        and limits["max_retries"] in (0, 1)
    ):
        raise ValueError("acquisition limits exceed the authorized bounds")
    snapshots = scope["snapshots"]
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 38:
        raise ValueError("expected one to 38 explicitly frozen snapshots")
    gameweeks = scope["gameweeks"]
    if (
        not isinstance(gameweeks, list)
        or not gameweeks
        or any(type(gw) is not int or not 1 <= gw <= 38 for gw in gameweeks)
        or gameweeks != sorted(set(gameweeks))
        or scope["positions"] != ["DEF", "MID", "FWD"]
    ):
        raise ValueError("invalid bounded gameweek/position population")
    seen: set[str] = set()
    previous: datetime | None = None
    for snapshot in snapshots:
        commit = snapshot["commit_sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", commit) or commit in seen:
            raise ValueError("duplicate or invalid source commit")
        seen.add(commit)
        if not re.fullmatch(r"[0-9a-f]{40}", snapshot["tree_sha"]):
            raise ValueError("source tree identity is required")
        if snapshot["paths"] != PATHS:
            raise ValueError("a snapshot changed the fixed source path allowlist")
        if snapshot["snapshot_id"] != commit:
            raise ValueError("snapshot identity must be its immutable source commit")
        known = instant(snapshot["source_known_at"])
        if known != max(instant(snapshot[k]) for k in ("author_date", "committer_date")):
            raise ValueError("historical knowledge must retain the audited conservative date")
        if not datetime(2023, 7, 1, tzinfo=UTC) <= known < datetime(2024, 7, 1, tzinfo=UTC):
            raise ValueError("historical source timestamp is outside the audited season")
        if previous is not None and known < previous:
            raise ValueError("snapshots are not in source-availability order")
        previous = known
        witness = snapshot["audited_source_witness"]
        if not re.fullmatch(r"[0-9a-f]{64}", witness) or witness != scope["frozen_inputs"].get(
            AUDIT_PATH
        ):
            raise ValueError("snapshot lacks its independently audited frozen source witness")
    urls = {source_url(s, role) for s in snapshots for role in PATHS}
    if len(urls) > limits["maximum_urls"] or set(scope.get("cache", {})) - urls:
        raise ValueError("request/cache identity exceeds the frozen allowlist")
    return dict(scope)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def pinned_inputs(root: Path, config: Path, scope: dict[str, Any]) -> dict[str, Any]:
    hashes: dict[str, str] = {}
    for name, expected in scope["frozen_inputs"].items():
        path = root / name
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input changed: {name}")
        hashes[name] = actual
    audit = json.loads((root / AUDIT_PATH).read_bytes())
    chronology = audit["commit_history"]["2023-24"]["chronology"]
    commits = {row["commit_sha"]: row for row in chronology}
    if len(commits) != len(chronology):
        raise ValueError("source audit has duplicate commit identities")
    for snapshot in scope["snapshots"]:
        witnessed = commits.get(snapshot["commit_sha"])
        if witnessed is None or any(
            snapshot[key] != witnessed[key]
            for key in ("tree_sha", "parent_shas", "author_date", "committer_date")
        ):
            raise ValueError("frozen snapshot metadata differs from the independent source audit")
        if instant(snapshot["source_known_at"]) != max(
            instant(witnessed[k]) for k in ("author_date", "committer_date")
        ):
            raise ValueError("snapshot availability differs from its independent source audit")
    return {
        "git_head": git(root, "rev-parse", "HEAD"),
        "config_sha256": file_sha256(config),
        "implementation_sha256": {p: file_sha256(root / p) for p in IMPLEMENTATION},
        "frozen_inputs_sha256": hashes,
    }


def reserve_claim(root: Path, study_id: str, provenance: dict[str, Any]) -> Path:
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = root / common
    directory = common.resolve(strict=True) / "historical-player-attacking-backfill"
    if directory.is_symlink():
        raise ValueError("shared acquisition claim directory cannot be a symlink")
    directory.mkdir(exist_ok=True)
    path = directory / f"{study_id}.claim.json"
    publish_json(
        path,
        {
            "study_id": study_id,
            "claimed_at": datetime.now(UTC).isoformat(),
            "kind": "data_acquisition_not_model_evaluation",
            "provenance": provenance,
            "network_restart_permitted": False,
        },
    )
    return path


def retained_source(url: str, item: dict[str, Any]) -> dict[str, Any]:
    receipt_path = Path(item["receipt_file"])
    receipt = json.loads(receipt_path.read_bytes())
    raw_path = Path(item["raw_file"])
    payload = raw_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if (
        receipt["url"] != url
        or receipt["status"] != 200
        or receipt["sha256"] != digest
        or item["sha256"] != digest
        or receipt["bytes"] != len(payload)
    ):
        raise ValueError("retained raw receipt/content/request identity differs")
    instant(receipt["captured_at_utc"])
    return {
        "url": url,
        "raw_file": str(raw_path.resolve()),
        "receipt_file": str(receipt_path.resolve()),
        "sha256": digest,
        "bytes": len(payload),
        "captured_at": receipt["captured_at_utc"],
        "content_type": receipt.get("headers", {}).get("content-type"),
    }


class AcquisitionRecorder(ResponseRecorder):
    def __init__(self, directory: Path, limits: dict[str, Any]) -> None:
        super().__init__(directory, limits["maximum_urls"], limits["minimum_interval_seconds"])
        self.maximum_attempts = int(limits["maximum_attempts"])

    def request(self, request: httpx.Request) -> None:
        if len(self.attempts) >= self.maximum_attempts:
            raise ValueError("bounded HTTP attempt budget exhausted")
        super().request(request)


def acquire_sources(scope: dict[str, Any], output: Path) -> dict[str, dict[str, Any]]:
    """Retain the complete fixed raw scope before any normalization is attempted."""
    recorder = AcquisitionRecorder(output, scope["limits"])
    sources: dict[str, dict[str, Any]] = {}
    byte_count = 0
    maximum_bytes = int(scope["limits"]["maximum_bytes"])
    try:
        with httpx.Client(
            timeout=30, follow_redirects=False, event_hooks={"request": [recorder.request]}
        ) as client:
            for snapshot in scope["snapshots"]:
                for role in PATHS:
                    url = source_url(snapshot, role)
                    cached = scope.get("cache", {}).get(url)
                    if cached is not None:
                        source = retained_source(url, cached)
                        byte_count += source["bytes"]
                        if byte_count > maximum_bytes:
                            raise ValueError("retained raw byte budget exhausted")
                        sources[url] = source
                        continue
                    for attempt in range(int(scope["limits"]["max_retries"]) + 1):
                        try:
                            with client.stream("GET", url) as response:
                                chunks: list[bytes] = []
                                for chunk in response.iter_bytes(65536):
                                    byte_count += len(chunk)
                                    if byte_count > maximum_bytes:
                                        raise ValueError(
                                            "HTTP response exceeds the raw byte budget"
                                        )
                                    chunks.append(chunk)
                                retained = httpx.Response(
                                    response.status_code,
                                    # iter_bytes has already decoded HTTP content encoding.
                                    headers={
                                        k: v
                                        for k, v in response.headers.items()
                                        if k not in {"content-encoding", "content-length"}
                                    },
                                    content=b"".join(chunks),
                                    request=response.request,
                                )
                                recorder.response(retained)
                                status = response.status_code
                        except httpx.HTTPError:
                            if attempt < scope["limits"]["max_retries"]:
                                continue
                            raise
                        receipt = recorder.responses[-1]
                        if status == 200:
                            source = retained_source(
                                url,
                                {
                                    "receipt_file": str(
                                        output / f"response-{receipt['sequence']:04d}.json"
                                    ),
                                    "raw_file": str(output / receipt["raw_file"]),
                                    "sha256": receipt["sha256"],
                                },
                            )
                            sources[url] = source
                            break
                        if (status == 429 or status >= 500) and attempt < scope["limits"][
                            "max_retries"
                        ]:
                            continue
                        raise ValueError(f"bounded source request returned HTTP {status}: {url}")
                    LOGGER.info(
                        "Retained %s/%s fixed source URLs",
                        len(sources),
                        4 * len(scope["snapshots"]),
                    )
        publish_json(output / "source-index.json", sources)
        publish_json(
            output / "acquisition-receipt.json",
            {
                "attempts": recorder.attempts,
                "responses": recorder.responses,
                "retained_bytes": byte_count,
            },
        )
    except Exception as error:
        publish_json(
            output / "acquisition-failure.json",
            {
                "error": str(error),
                "sources": sources,
                "attempts": recorder.attempts,
                "responses": recorder.responses,
                "retained_bytes": byte_count,
            },
        )
        raise
    return sources


def football_content(row: dict[str, Any]) -> bytes:
    return canonical({k: v for k, v in row.items() if k not in VERSION_METADATA})


def append_changed(
    rows: list[dict[str, Any]],
    previous: dict[tuple[str, int, int], bytes],
    identities: dict[tuple[str, int], int],
    reverse: dict[tuple[str, int], int],
) -> tuple[list[dict[str, Any]], int, int]:
    """Keep A->B->A revisions, skipping only consecutive unchanged football content."""
    changed: list[dict[str, Any]] = []
    unchanged = revisions = 0
    batch: set[tuple[str, int, int]] = set()
    for row in rows:
        key = (str(row["season"]), int(row["player_code"]), int(row["fixture_id"]))
        if key in batch:
            raise ValueError("duplicate player/fixture in one source snapshot")
        batch.add(key)
        element = int(row["source_element_id"])
        anchor, reversed_anchor = (key[0], element), (key[0], key[1])
        if (
            identities.get(anchor, key[1]) != key[1]
            or reverse.get(reversed_anchor, element) != element
        ):
            raise ValueError("cross-snapshot deterministic player identity contradiction")
        identities[anchor], reverse[reversed_anchor] = key[1], element
        content = football_content(row)
        if previous.get(key) == content:
            unchanged += 1
        else:
            revisions += key in previous
            changed.append(row)
            previous[key] = content
    return changed, unchanged, revisions


def normalize_sources(
    scope: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    output: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    from fpl.validate.historical_player_attacking import (
        BackfillScope,
        SnapshotEvidence,
        parse_snapshot,
    )

    expected = {source_url(s, role) for s in scope["snapshots"] for role in PATHS}
    if set(sources) != expected:
        raise ValueError("source index differs from the complete frozen URL population")
    previous: dict[tuple[str, int, int], bytes] = {}
    identities: dict[tuple[str, int], int] = {}
    reverse: dict[tuple[str, int], int] = {}
    emitted: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    bounded = BackfillScope(
        (scope["season"],),
        tuple(scope["gameweeks"]),
        tuple(s["snapshot_id"] for s in scope["snapshots"]),
    )
    for snapshot in scope["snapshots"]:
        selected = {role: sources[source_url(snapshot, role)] for role in PATHS}
        raw: dict[str, bytes] = {}
        for role, item in selected.items():
            checked = retained_source(item["url"], item)
            if checked != item:
                raise ValueError("source index differs from immutable raw receipt")
            raw[role] = Path(item["raw_file"]).read_bytes()
        capture = max(instant(s["captured_at"]) for s in selected.values())
        observations = parse_snapshot(
            stats_bytes=raw["stats"],
            registry_bytes=raw["registry"],
            fixtures_bytes=raw["fixtures"],
            teams_bytes=raw["teams"],
            scope=bounded,
            evidence=SnapshotEvidence(
                season=scope["season"],
                snapshot_id=snapshot["snapshot_id"],
                evidence_class="ARCHIVED_AS_OF",
                author_at=instant(snapshot["author_date"]),
                committer_at=instant(snapshot["committer_date"]),
                capture_known_at=capture,
                expected_hashes=tuple((role, s["sha256"]) for role, s in selected.items()),
                audited_source_witness=snapshot["audited_source_witness"],
            ),
        )
        # Validate every registry anchor, including keepers and players without match rows.
        for player in csv.DictReader(io.StringIO(raw["registry"].decode("utf-8-sig"))):
            element, code = int(player["id"]), int(player["code"])
            anchor, reversed_anchor = (scope["season"], element), (scope["season"], code)
            if (
                identities.get(anchor, code) != code
                or reverse.get(reversed_anchor, element) != element
            ):
                raise ValueError("cross-snapshot registry identity contradiction")
            identities[anchor], reverse[reversed_anchor] = code, element
        rows: list[dict[str, Any]] = []
        for observation in observations:
            row = asdict(observation)
            for key, value in row.items():
                if isinstance(value, datetime):
                    row[key] = value.isoformat()
            row["provenance"] = {
                **dict(observation.provenance),
                "execution_git_sha": provenance["git_head"],
                "scope_sha256": provenance["config_sha256"],
                "tree_sha": snapshot["tree_sha"],
            }
            rows.append(row)
        kept, unchanged, revisions = append_changed(rows, previous, identities, reverse)
        emitted.extend(kept)
        reports.append(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "source_known_at": snapshot["source_known_at"],
                "capture_known_at": capture.isoformat(),
                "parsed_rows": len(rows),
                "new_or_changed_rows": len(kept),
                "unchanged_rows": unchanged,
                "revisions": revisions,
            }
        )
        LOGGER.info(
            "Normalized snapshot %s: %s rows, %s new/changed", len(reports), len(rows), len(kept)
        )
    normalized = b"".join(canonical(row) + b"\n" for row in emitted)
    publish_bytes(output / "observations.jsonl", normalized)
    fields = (
        "shots",
        "shots_on_target",
        "expected_goals",
        "expected_assists",
        "key_passes",
        "box_touches",
    )
    return {
        "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
        "normalized_bytes": len(normalized),
        "normalized_versions": len(emitted),
        "unique_player_fixtures": len(previous),
        "unique_players": len({r["player_code"] for r in emitted}),
        "unique_registry_players": len(reverse),
        "gameweeks": sorted({r["gameweek"] for r in emitted}),
        "position_version_counts": dict(
            sorted(Counter(r["fpl_position"] for r in emitted).items())
        ),
        "field_missing_version_counts": {f: sum(r.get(f) is None for r in emitted) for f in fields},
        "snapshots": reports,
        "source_versions": sources,
        "official_deadlines": None,
        "sample_adequacy": "requires separate chronological coverage audit; no model evaluation",
    }


def run(
    config: Path, output: Path, *, replay: Path | None = None, root: Path | None = None
) -> dict[str, Any]:
    root = root or repo_root()
    scope = load_scope(config)
    current = pinned_inputs(root, config, scope)
    if git(root, "branch", "--show-current") != scope["expected_branch"]:
        raise ValueError("historical acquisition is authorized only on the named V2 branch")
    if git(root, "status", "--porcelain"):
        raise ValueError("freeze a clean committed worktree before acquisition/replay")
    if output.exists():
        raise FileExistsError("output must be a new immutable directory")
    original: dict[str, Any] | None = None
    if replay is not None:
        original = json.loads((replay / "manifest.json").read_bytes())
        provenance = original["provenance"]
        for key in ("config_sha256", "implementation_sha256", "frozen_inputs_sha256"):
            if provenance[key] != current[key]:
                raise ValueError(
                    "offline replay requires the identical frozen interpretation inputs"
                )
        claim = original["claim"]
    else:
        provenance = current
        claim = str(reserve_claim(root, scope["study_id"], provenance))
    output.mkdir(parents=True, exist_ok=False)
    try:
        if replay is None:
            sources = acquire_sources(scope, output)
        else:
            sources = json.loads((replay / "source-index.json").read_bytes())
            publish_json(output / "source-index.json", sources)
        summary = normalize_sources(scope, sources, output, provenance)
        if original is not None and summary["normalized_sha256"] != original["normalized_sha256"]:
            raise ValueError("offline replay changed the normalized bytes")
        if pinned_inputs(root, config, scope) != current or git(root, "status", "--porcelain"):
            raise ValueError("Git/config/parser/frozen inputs changed during bounded acquisition")
        manifest = {
            "contract_version": "1.0",
            "study_id": scope["study_id"],
            "kind": "historical_data_backfill_not_model_evaluation",
            "claim": claim,
            "created_at": datetime.now(UTC).isoformat(),
            "provenance": provenance,
            "postflight": current,
            "replay_of": str(replay) if replay else None,
            **summary,
        }
        publish_json(output / "manifest.json", manifest)
        return manifest
    except Exception as error:
        publish_json(
            output / "failure.json",
            {
                "error": str(error),
                "claim": claim,
                "provenance": provenance,
                "created_at": datetime.now(UTC).isoformat(),
                "network_restart_permitted": False,
            },
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=repo_root() / "config/historical_player_attacking_backfill.yaml",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    result = run(args.config, args.output_dir, replay=args.replay)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "study_id",
                    "normalized_versions",
                    "unique_player_fixtures",
                    "normalized_sha256",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
