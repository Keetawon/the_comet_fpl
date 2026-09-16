"""Bounded raw-only 2025 workload capture; no DB, participation parser or models."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import traceback
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import yaml

from fpl.config import load_sources, repo_root
from fpl.ingest.fpl_api import ApiResponseError, EgressBlockedError
from fpl.ingest.pl_sdp import PlSdpClient, SdpSchemaError, extract_items, parse_match_summary
from fpl.jobs.competitive_participation_pilot import (
    ResponseRecorder,
    file_sha256,
    git_clean_head,
    publish_bytes,
    publish_json,
    raw_identity,
)

CONFIG = "config/competitive_workload_capture.yaml"
CONFIG_SHA256 = "ee04244486dd53feef03b03c821e8660dfa7ea9dcec3e14a66b22442f8e8b64c"
NAME = "competitive_workload_2025_raw_v1"
SOURCE_FILES = (
    CONFIG,
    "config/sources.yaml",
    "docs/competitive-workload-capture.md",
    "src/fpl/jobs/capture_competitive_workload.py",
    "src/fpl/jobs/competitive_participation_pilot.py",
    "src/fpl/ingest/pl_sdp.py",
    "src/fpl/ingest/fpl_api.py",
    "src/fpl/config.py",
    "tests/test_competitive_workload_capture.py",
)
logger = logging.getLogger(__name__)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def load_contract(root: Path) -> dict[str, Any]:
    if file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("raw workload capture contract changed")
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    return contract


@dataclass
class RetainedInputs:
    matches: dict[int, dict[str, Any]]
    metadata: dict[int, dict[str, Any]]
    reused: dict[tuple[int, str], dict[str, Any]]
    files: dict[str, bytes]
    source_hashes: dict[str, str]
    inventory: dict[str, Any]


def load_retained(root: Path, directory: Path, contract: Mapping[str, Any]) -> RetainedInputs:
    """Audit the complete original catalogue/bytes locally, before any HTTP client exists."""
    report_path = root / contract["retained_report"]
    report_bytes = report_path.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != contract["retained_report_sha256"]:
        raise ValueError("retained pilot report fingerprint changed")
    report = json.loads(report_bytes)
    if report["completed"] is not True:
        raise ValueError("retained pilot did not finish raw collection")
    files: dict[str, bytes] = {"pilot-result.json": report_bytes}
    source_hashes = {str(report_path.resolve()): file_sha256(report_path)}

    def retain(name: str) -> bytes:
        if Path(name).name != name or not name or name in {".", ".."}:
            raise ValueError("unsafe retained evidence filename")
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("retained evidence escapes input directory")
        content = path.read_bytes()
        files[name] = content
        source_hashes[str(path)] = hashlib.sha256(content).hexdigest()
        return content

    responses = report["http_responses"]
    attempts = {r["sequence"]: r for r in report["http_attempts"]}
    if len(attempts) != len(report["http_attempts"]):
        raise ValueError("duplicate retained request sequence")
    pages: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    endpoint_responses: dict[tuple[int, str], dict[str, Any]] = {}
    sequences: set[int] = set()
    for meta in responses:
        sequence = meta["sequence"]
        if sequence in sequences or sequence not in attempts:
            raise ValueError("duplicate/unmatched retained response sequence")
        sequences.add(sequence)
        if json.loads(retain(f"response-{sequence:04d}.json")) != meta:
            raise ValueError("original response metadata differs from pinned pilot")
        if json.loads(retain(f"request-{sequence:04d}.json")) != attempts[sequence]:
            raise ValueError("original request metadata differs from pinned pilot")
        body = retain(meta["raw_file"])
        if (
            meta["status"] != 200
            or len(body) != meta["bytes"]
            or hashlib.sha256(body).hexdigest() != meta["sha256"]
        ):
            raise ValueError("retained response status/hash/byte-count mismatch")
        captured = datetime.fromisoformat(meta["captured_at_utc"])
        if captured.utcoffset() is None:
            raise ValueError("retained capture time is naive")
        parsed = urlparse(meta["url"])
        if f"{parsed.scheme}://{parsed.netloc}" != contract["provider_base_url"]:
            raise ValueError("retained response is not from the verified provider")
        if meta["url"] != attempts[sequence]["url"] or attempts[sequence]["method"] != "GET":
            raise ValueError("retained request/response identity differs")
        payload = json.loads(body)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v2/matches":
            cid = int(query["competition"][0])
            if query.get("season") != [str(contract["provider_season_id"])]:
                raise ValueError("retained catalogue season differs")
            pages[cid].append((meta, payload))
        else:
            for endpoint, template in contract["endpoint_paths"].items():
                parts = parsed.path.split("/")
                if len(parts) == 6 and parts[-1] == endpoint and parts[-2].isdigit():
                    mid = int(parts[-2])
                    if parsed.path != template.format(match_id=mid) or query.get("match_id") != [
                        str(mid)
                    ]:
                        raise ValueError("retained endpoint identity differs")
                    key = (mid, endpoint)
                    if key in endpoint_responses:
                        raise ValueError("unexpected multiple retained endpoint versions")
                    endpoint_responses[key] = meta
                    break
            else:
                raise ValueError("unlicensed retained endpoint")
    if sequences != set(attempts):
        raise ValueError("retained request lacks a response")
    records: dict[int, dict[str, Any]] = {}
    metadata: dict[int, dict[str, Any]] = {}
    catalogue_counts: Counter[str] = Counter()
    if set(map(str, pages)) != set(contract["catalogue_counts"]):
        raise ValueError("retained competition catalogue set differs")
    for cid, chain in pages.items():
        next_cursor = None
        seen_cursors: set[str] = set()
        for index, (meta, payload) in enumerate(
            sorted(chain, key=lambda pair: pair[0]["sequence"])
        ):
            query = parse_qs(urlparse(meta["url"]).query)
            if query.get("_next", [None]) != [next_cursor]:
                raise ValueError("retained catalogue cursor chain is incomplete")
            for record in extract_items(payload):
                summary = parse_match_summary(record)
                if summary.match_id in records:
                    raise ValueError("duplicate catalogue match identity")
                if (
                    summary.season_id != contract["provider_season_id"]
                    or int(record["competitionId"]) != cid
                ):
                    raise ValueError("catalogue record competition/season differs")
                records[summary.match_id] = record
                metadata[summary.match_id] = dict(meta)
                catalogue_counts[str(cid)] += 1
            pagination = payload.get("pagination") if isinstance(payload, dict) else None
            if not isinstance(pagination, dict) or "_next" not in pagination:
                raise ValueError("retained catalogue termination is unproved")
            next_cursor = pagination["_next"] or None
            if next_cursor is not None:
                if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
                    raise ValueError("repeated/invalid catalogue cursor")
                seen_cursors.add(next_cursor)
            if index < len(chain) - 1 and next_cursor is None:
                raise ValueError("retained page follows terminal cursor")
        if next_cursor is not None:
            raise ValueError("retained catalogue final page is missing")
    pl = [parse_match_summary(r) for r in records.values() if int(r["competitionId"]) == 8]
    if any(r.home_team_id is None or r.away_team_id is None for r in pl):
        raise ValueError("PL catalogue has unresolved club identity")
    clubs = {team for r in pl for team in (r.home_team_id, r.away_team_id) if team is not None}
    if clubs != set(contract["provider_club_ids"]):
        raise ValueError("PL club provider identity set changed")
    selected = {}
    for mid, record in records.items():
        summary = parse_match_summary(record)
        if clubs.intersection((summary.home_team_id, summary.away_team_id)):
            if (
                summary.kickoff is None
                or summary.home_team_id is None
                or summary.away_team_id is None
            ):
                raise ValueError("selected match has unresolved kickoff/club identity")
            selected[mid] = record
    selected_counts = Counter(str(r["competitionId"]) for r in selected.values())
    checks = (
        (dict(catalogue_counts), contract["catalogue_counts"]),
        (dict(selected_counts), contract["selected_counts"]),
        (sum(map(len, pages.values())), contract["expected_metadata_pages"]),
        (len(records), contract["expected_catalogue_matches"]),
        (len(selected), contract["expected_selected_matches"]),
        (_hash([records[mid] for mid in sorted(records)]), contract["catalogue_records_sha256"]),
        (_hash(sorted(selected)), contract["selected_match_ids_sha256"]),
        (_hash(sorted(r.match_id for r in pl)), contract["pl_match_ids_sha256"]),
    )
    if any(actual != expected for actual, expected in checks):
        raise ValueError("frozen catalogue population/fingerprint differs")
    source_versions: dict[int, dict[str, Any]] = {}
    for result in [*report["matches"], *report["failures"]]:
        if "source_versions" in result:
            mid = result["sdp_match_id"]
            if mid in source_versions and source_versions[mid] != result["source_versions"]:
                raise ValueError("contradictory retained bundle provenance")
            source_versions[mid] = result["source_versions"]
    reused = {}
    for (mid, endpoint), meta in endpoint_responses.items():
        if mid not in selected or mid not in source_versions:
            raise ValueError("retained bundle absent from pinned selected inventory")
        bundle = json.loads(retain(f"capture-{mid}.json"))
        if (
            bundle["source_versions"] != source_versions[mid]
            or bundle["selected_match_record"] != selected[mid]
        ):
            raise ValueError("retained match manifest differs from pinned evidence")
        version = source_versions[mid][endpoint]
        if version["sha256"] != meta["sha256"] or version["bytes"] != meta["bytes"]:
            raise ValueError("retained payload and bundle version differ")
        reused[(mid, endpoint)] = {
            **version,
            "receipt": meta,
            "reused": True,
            "copied_raw_file": f"inputs/{meta['raw_file']}",
        }
    if (
        len(reused) != contract["expected_reused_endpoints"]
        or len({mid for mid, _ in reused}) != contract["expected_reused_matches"]
        or any(
            {e for match_id, e in reused if match_id == mid} != set(contract["endpoints"])
            for mid, _ in reused
        )
    ):
        raise ValueError("retained complete bundle population differs")
    missing = len(selected) * len(contract["endpoints"]) - len(reused)
    if (
        missing != contract["expected_missing_endpoints"]
        or missing > contract["maximum_distinct_provider_requests"]
    ):
        raise ValueError("missing endpoint count exceeds frozen budget")
    inventory = {
        "catalogue_counts": dict(catalogue_counts),
        "selected_counts": dict(selected_counts),
        "selected_matches": len(selected),
        "reused_endpoints": len(reused),
        "missing_endpoints": missing,
        "provider_club_ids": sorted(clubs),
        "selected_records": [selected[mid] for mid in sorted(selected)],
        "raw_status_counts": dict(
            Counter(f"{r.get('period')}:{r.get('resultType')}" for r in selected.values())
        ),
        "catalogue_vintage": "pinned_retained_pilot_complete_cursor_chains",
        "participation_validated": False,
    }
    return RetainedInputs(selected, metadata, reused, files, source_hashes, inventory)


def _source_fingerprints(root: Path) -> dict[str, str]:
    return {name: file_sha256(root / name) for name in SOURCE_FILES}


def _head(root: Path, contract: Mapping[str, Any]) -> str:
    head = git_clean_head(root)
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    if branch != contract["branch"]:
        raise ValueError("raw capture must remain on the V2 branch")
    return head


def collect(
    client: PlSdpClient,
    recorder: ResponseRecorder,
    inputs: RetainedInputs,
    contract: Mapping[str, Any],
    directory: Path,
    states: dict[tuple[int, str], dict[str, Any]],
) -> None:
    consecutive_failures = 0
    ordered = sorted(
        inputs.matches, key=lambda mid: (parse_match_summary(inputs.matches[mid]).kickoff, mid)
    )
    for mid in ordered:
        for endpoint in contract["endpoints"]:
            key = (mid, endpoint)
            if key in inputs.reused:
                continue
            call = (
                client.fetch_match_lineups if endpoint == "lineups" else client.fetch_match_events
            )
            try:
                raw = call(mid)
                receipt = next(
                    (
                        r
                        for r in reversed(recorder.responses)
                        if r["sha256"] == raw.sha256 and urlparse(r["url"]).path == raw.path
                    ),
                    None,
                )
                if receipt is None:
                    raise RuntimeError("successful endpoint lacks raw receipt")
                states[key] = {
                    "status": "received",
                    "source": {
                        **raw_identity(raw),
                        "receipt": receipt,
                        "reused": False,
                        "copied_raw_file": f"responses/{receipt['raw_file']}",
                    },
                }
                consecutive_failures = 0
            except EgressBlockedError as error:
                states[key] = {
                    "status": "egress_blocked",
                    "error_class": type(error).__name__,
                    "error": str(error),
                }
                raise
            except (ApiResponseError, SdpSchemaError) as error:
                states[key] = {
                    "status": "unavailable",
                    "error_class": type(error).__name__,
                    "error": str(error),
                }
                consecutive_failures += 1
                if consecutive_failures >= contract["maximum_consecutive_failed_endpoints"]:
                    raise RuntimeError("consecutive endpoint failure circuit breaker") from error
        publish_json(
            directory / f"capture-{mid}.json",
            {
                "sdp_match_id": mid,
                "selected_match_record": inputs.matches[mid],
                "metadata_receipt": inputs.metadata[mid],
                "endpoints": {
                    endpoint: states[(mid, endpoint)] for endpoint in contract["endpoints"]
                },
                "participation_validated": False,
            },
        )
        logger.info(
            "Raw match %s retained; %s/%s endpoint calls attempted",
            mid,
            len(recorder.urls),
            contract["expected_missing_endpoints"],
        )


def run(*, root: Path, retained: Path, results: Path) -> dict[str, Any]:
    root, retained, results = root.resolve(), retained.resolve(), results.resolve()
    contract = load_contract(root)
    head = _head(root, contract)
    if not retained.is_dir():
        raise ValueError("explicit original retained directory required")
    if results.exists() or results.is_symlink():
        raise FileExistsError("new output directory required; no overwrite/in-place resume")
    if results.is_relative_to(root) or results.is_relative_to(retained):
        raise ValueError("output must be external and outside preserved input directory")
    inputs = load_retained(root, retained, contract)
    source = load_sources().pl_sdp
    if source is None or source.base_url != contract["provider_base_url"]:
        raise ValueError("verified SDP source unavailable")
    for endpoint, template in contract["endpoint_paths"].items():
        if source.endpoints[f"match_{endpoint}"] != template:
            raise ValueError("configured endpoint differs from capture contract")
    fingerprints = _source_fingerprints(root)
    results.mkdir(parents=True, exist_ok=False)
    for name in ("inputs", "responses"):
        (results / name).mkdir()
    for name, content in inputs.files.items():
        publish_bytes(results / "inputs" / name, content)
    provenance = {
        "capture": NAME,
        "git_head": head,
        "clean_worktree": True,
        "config": contract,
        "source_sha256": fingerprints,
        "input_sha256": inputs.source_hashes,
        "retained_directory": str(retained),
        "results_directory": str(results),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "database_opened": False,
        "model_fitting": False,
        "participation_validated": False,
        "network_policy": source.model_dump(mode="json"),
    }
    publish_json(results / "provenance.json", provenance)
    publish_json(results / "inventory.json", inputs.inventory)
    recorder = ResponseRecorder(
        results / "responses",
        contract["maximum_distinct_provider_requests"],
        source.min_request_interval_seconds,
    )
    states: dict[tuple[int, str], dict[str, Any]] = {
        (mid, endpoint): {"status": "reused", "source": inputs.reused[(mid, endpoint)]}
        if (mid, endpoint) in inputs.reused
        else {"status": "not_attempted"}
        for mid in inputs.matches
        for endpoint in contract["endpoints"]
    }
    report: dict[str, Any] = {
        "completed": False,
        "capture_complete": False,
        "provenance": provenance,
    }
    try:
        with (
            httpx.Client(
                timeout=source.timeout_seconds,
                follow_redirects=True,
                event_hooks={"request": [recorder.request], "response": [recorder.response]},
            ) as http,
            PlSdpClient(config=source, client=http) as client,
        ):
            collect(client, recorder, inputs, contract, results, states)
        report["completed"] = True
    except Exception as error:
        report["execution_failure"] = {
            "class": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
    try:
        report["ending_git_head"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        report["ending_git_status"] = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        report["ending_worktree_clean"] = not report["ending_git_status"]
        unchanged = (
            _source_fingerprints(root) == fingerprints
            and all(file_sha256(Path(p)) == sha for p, sha in inputs.source_hashes.items())
            and all(
                file_sha256(results / "inputs" / name) == hashlib.sha256(content).hexdigest()
                for name, content in inputs.files.items()
            )
        )
        if not unchanged:
            raise RuntimeError("source/input/copy provenance changed during capture")
        report["postflight_unchanged"] = True
    except Exception as error:
        report["completed"] = False
        report["postflight_unchanged"] = False
        report["postflight_failure"] = {"class": type(error).__name__, "message": str(error)}
    counts = Counter(row["status"] for row in states.values())
    complete = sum(
        all(states[(mid, e)]["status"] in {"received", "reused"} for e in contract["endpoints"])
        for mid in inputs.matches
    )
    report.update(
        {
            "capture_complete": report["completed"] and complete == len(inputs.matches),
            "expected_matches": len(inputs.matches),
            "matches_with_both_endpoints_received": complete,
            "missing_or_failed_matches": len(inputs.matches) - complete,
            "endpoint_status_counts": dict(counts),
            "distinct_requests": len(recorder.urls),
            "http_attempts": recorder.attempts,
            "http_responses": recorder.responses,
            "response_status_counts": dict(Counter(str(r["status"]) for r in recorder.responses)),
            "endpoint_inventory": [
                {"sdp_match_id": mid, "endpoint": endpoint, **status}
                for (mid, endpoint), status in sorted(states.items())
            ],
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "participation_validated": False,
            "model_fitting": False,
            "database_opened": False,
            "promotion_permitted": False,
        }
    )
    publish_json(results / "result.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retained", type=Path, required=True, help="Original pinned pilot raw directory"
    )
    parser.add_argument(
        "--results", type=Path, required=True, help="New external persistent output directory"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    report = run(root=repo_root(), retained=args.retained, results=args.results)
    logger.info(
        "Raw capture complete=%s; participation remains unvalidated", report["capture_complete"]
    )
    return 0 if report["capture_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
