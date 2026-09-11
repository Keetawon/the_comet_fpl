"""Bounded raw-retaining participation pilot; reference DuckDB is always read-only.

    python -m fpl.jobs.competitive_participation_pilot --help

No forecasts, model fitting, staging, default database changes or schedule activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import httpx
import yaml

from fpl.config import PlSdpSource, load_sources, repo_root
from fpl.ingest.fpl_api import ApiResponseError, EgressBlockedError
from fpl.ingest.pl_sdp import PlSdpClient, RawPayload, extract_items, parse_match_summary
from fpl.storage.db import connect
from fpl.transform.competitive_participation import (
    ParticipationError,
    exact_crosswalk,
    parse_participation,
    uint,
)

CONFIG = "config/competitive_participation_pilot.yaml"
CONFIG_SHA256 = "d3bb9b7880db5d61cc1ee7c3b74aa86bf65e3d24bddb10ebfc8504b55c1047fa"
SOURCE_FILES = (
    CONFIG,
    "config/sources.yaml",
    "docs/competitive-participation-pilot.md",
    "src/fpl/jobs/competitive_participation_pilot.py",
    "src/fpl/transform/competitive_participation.py",
    "src/fpl/ingest/pl_sdp.py",
    "src/fpl/config.py",
    "src/fpl/storage/db.py",
    "src/fpl/storage/schema.sql",
    "tests/test_competitive_participation.py",
)
logger = logging.getLogger(__name__)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish_bytes(path: Path, payload: bytes) -> None:
    """Repository-standard fsync + exclusive hard-link publication; never overwrite."""
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_json(path: Path, value: object) -> None:
    publish_bytes(
        path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    )


def git_clean_head(root: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    if git("status", "--porcelain"):
        raise ParticipationError("pilot refuses dirty worktree; freeze implementation first")
    return git("rev-parse", "HEAD")


def load_contract(root: Path) -> dict[str, Any]:
    if file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ParticipationError("pilot contract differs from its supported frozen policy")
    contract = yaml.safe_load((root / CONFIG).read_bytes())
    if not isinstance(contract, dict):
        raise ParticipationError("pilot config must be a mapping")
    return dict(contract)


class ResponseRecorder:
    """Retain every HTTP attempt and response, including failed/retried revisions."""

    def __init__(
        self, directory: Path, maximum_requests: int, minimum_interval: float = 0.0
    ) -> None:
        self.directory = directory
        self.maximum_requests = maximum_requests
        self.minimum_interval = minimum_interval
        self.last_attempt: float | None = None
        self.urls: set[str] = set()
        self.attempts: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []

    def request(self, request: httpx.Request) -> None:
        url = str(request.url)
        if url not in self.urls and len(self.urls) >= self.maximum_requests:
            raise ParticipationError("distinct provider request bound exhausted")
        if self.last_attempt is not None:
            remaining = self.minimum_interval - (time.monotonic() - self.last_attempt)
            if remaining > 0:
                time.sleep(remaining)
        self.last_attempt = time.monotonic()
        self.urls.add(url)
        sequence = len(self.attempts) + 1
        request.extensions["pilot_sequence"] = sequence
        row = {
            "sequence": sequence,
            "url": url,
            "method": request.method,
            "attempted_at_utc": datetime.now(UTC).isoformat(),
        }
        publish_json(self.directory / f"request-{sequence:04d}.json", row)
        self.attempts.append(row)

    def response(self, response: httpx.Response) -> None:
        response.read()
        sequence = int(response.request.extensions["pilot_sequence"])
        digest = hashlib.sha256(response.content).hexdigest()
        name = f"response-{sequence:04d}-{digest}.raw"
        publish_bytes(self.directory / name, response.content)
        row = {
            "sequence": sequence,
            "url": str(response.url),
            "status": response.status_code,
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "sha256": digest,
            "bytes": len(response.content),
            "raw_file": name,
            "unchanged_from_prior_response_in_this_run": any(
                prior["url"] == str(response.url) and prior["sha256"] == digest
                for prior in self.responses
            ),
            "headers": {
                key: response.headers[key]
                for key in (
                    "content-type",
                    "cache-control",
                    "age",
                    "etag",
                    "last-modified",
                    "retry-after",
                    "via",
                    "server",
                    "x-cache",
                )
                if key in response.headers
            },
        }
        publish_json(self.directory / f"response-{sequence:04d}.json", row)
        self.responses.append(row)


def raw_identity(raw: RawPayload) -> dict[str, Any]:
    return {
        "endpoint": raw.endpoint,
        "path": raw.path,
        "params": dict(raw.params),
        "known_at": raw.fetched_at.isoformat(),
        "sha256": raw.sha256,
        "bytes": raw.byte_count,
        "status": raw.status_code,
    }


def discover(
    client: PlSdpClient, contract: Mapping[str, Any]
) -> tuple[list[tuple[dict[str, Any], RawPayload]], dict[str, Any]]:
    """Exhaust the observed cursor protocol; duplicate/no-progress pages are failures."""
    start = datetime.fromisoformat(contract["kickoff_from_utc"])
    end = datetime.fromisoformat(contract["kickoff_before_utc"])
    clubs = {row["provider_team_id"] for row in contract["clubs"]}
    seen: set[int] = set()
    cursors: set[str] = set()
    selected: list[tuple[dict[str, Any], RawPayload]] = []
    cursor = None
    pages = []
    for page in range(client.config.maximum_pages):
        raw = client.fetch_matches_page(season_id=contract["provider_season_id"], cursor=cursor)
        pages.append(raw_identity(raw))
        for item in extract_items(raw.payload):
            summary = parse_match_summary(item)
            if summary.match_id in seen:
                raise ParticipationError("duplicate match in discovery; no silent page termination")
            seen.add(summary.match_id)
            if (
                summary.season_id != contract["provider_season_id"]
                or uint(item.get("competitionId"), "competition") != client.config.competition
            ):
                raise ParticipationError("discovery competition/season contradiction")
            if summary.home_team_id is None or summary.away_team_id is None:
                raise ParticipationError("unknown discovery club identity")
            if clubs.intersection({summary.home_team_id, summary.away_team_id}):
                if summary.kickoff is None:
                    raise ParticipationError(
                        "unknown selected-club kickoff prevents coverage proof"
                    )
                if start <= summary.kickoff < end:
                    selected.append((dict(item), raw))
        pagination = raw.payload.get("pagination") if isinstance(raw.payload, dict) else None
        if not isinstance(pagination, dict) or "_next" not in pagination:
            raise ParticipationError("no verified cursor termination; discovery is incomplete")
        value = pagination["_next"]
        if value is None or value == "":
            return selected, {
                "complete": True,
                "pages": pages,
                "catalogue_matches": len(seen),
                "selected_match_ids": [int(row[0]["matchId"]) for row in selected],
            }
        if not isinstance(value, str) or value in cursors:
            raise ParticipationError("invalid/repeated discovery cursor")
        cursors.add(value)
        cursor = value
        logger.info("competition %s metadata page %s retained", client.config.competition, page + 1)
    raise ParticipationError("discovery exceeded existing provider page bound")


def reference_data(db: Path, season: str) -> dict[str, Any]:
    con = connect(db, read_only=True)
    try:
        registry = [
            {"season": season, "code": code, "opta_code": opta}
            for code, opta in con.execute(
                "SELECT code, opta_code FROM mart_dim_player WHERE season=?", [season]
            ).fetchall()
        ]
        facts = [
            dict(
                zip(
                    ("fixture", "code", "team_code", "minutes", "starts", "kickoff_utc"),
                    row,
                    strict=True,
                )
            )
            for row in con.execute(
                """SELECT f.fixture, f.code, t.team_code, f.minutes, f.starts,
                       CAST(f.kickoff_time AS VARCHAR)
               FROM mart_fact_player_fixture f JOIN mart_dim_team t
                 ON f.season=t.season AND f.team_id=t.team_id
               WHERE f.season=? ORDER BY f.kickoff_time, f.fixture, f.code""",
                [season],
            ).fetchall()
        ]
        crosswalk = {
            str(row[0]): dict(
                zip(
                    (
                        "fixture",
                        "method",
                        "kickoff_utc",
                        "home_team_code",
                        "away_team_code",
                        "home_score",
                        "away_score",
                    ),
                    row[1:],
                    strict=True,
                )
            )
            for row in con.execute(
                """SELECT x.sdp_match_id, x.fixture, x.match_method,
                          CAST(f.kickoff_time AS VARCHAR), h.team_code, a.team_code,
                          f.goals_for, f.goals_against
                   FROM stg_pl_sdp_fixture_crosswalk x
                   JOIN mart_fact_team_match f ON f.season=x.season AND f.fixture=x.fixture
                   JOIN mart_dim_team h ON h.season=f.season AND h.team_id=f.team_id
                   JOIN mart_dim_team a ON a.season=f.season AND a.team_id=f.opponent_team_id
                   WHERE x.season=? AND f.was_home AND x.corroborated_kickoff
                     AND x.corroborated_teams AND x.corroborated_score""",
                [season],
            ).fetchall()
        }
    finally:
        con.close()
    return {
        "season": season,
        "identity_observed_at_utc": datetime.now(UTC).isoformat(),
        "registry": registry,
        "facts": facts,
        "crosswalk": crosswalk,
    }


def validate_results(
    results: list[dict[str, Any]], reference: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Data-quality audit, retaining all denominators and paired player observations."""
    clubs = {row["team_code"] for row in contract["clubs"]}
    all_facts: list[dict[str, Any]] = reference["facts"]
    registry = reference["registry"]
    pairs: list[dict[str, Any]] = []
    errors: list[str] = []
    identity_total = identity_ok = starter_total = starter_ok = appearance_ok = 0
    for match in results:
        mid = match["sdp_match_id"]
        kickoff = datetime.fromisoformat(match["kickoff_utc"])
        for side in match["sides"]:
            errors.extend(f"match {mid}: {error}" for error in side["errors"])
            if side["provider_team_id"] not in clubs:
                continue
            ids = [row["provider_player_id"] for row in side["rows"]]
            crosswalk, missing = exact_crosswalk(ids, registry, season=contract["season"])
            errors.extend(f"match {mid}: {error}" for error in missing)
            identity_total += len(ids)
            identity_ok += sum(value is not None for value in crosswalk.values())
            for row in side["rows"]:
                code = crosswalk[row["provider_player_id"]]
                row["fpl_code"] = code
                row["fpl_opta_anchor"] = (
                    f"p{row['provider_player_id']}" if code is not None else None
                )
                row["identity_method"] = "exact_season_fpl_opta" if code is not None else None
                prior = [
                    f
                    for f in all_facts
                    if f["code"] == code and datetime.fromisoformat(f["kickoff_utc"]) < kickoff
                ]
                row["prior_fpl_team_code"] = prior[-1]["team_code"] if prior else None
                if prior and prior[-1]["team_code"] != side["provider_team_id"]:
                    errors.append(f"match {mid} code {code}: prior fixture club conflict")
            if match["provider_competition_id"] != 8:
                continue
            bridge = reference["crosswalk"].get(str(mid))
            if bridge is None:
                errors.append(f"PL match {mid}: missing corroborated fixture crosswalk")
                continue
            fpl = {
                f["code"]: f
                for f in all_facts
                if f["fixture"] == bridge["fixture"] and f["team_code"] == side["provider_team_id"]
            }
            sdp = {row["fpl_code"]: row for row in side["rows"] if row["fpl_code"] is not None}
            population = set(sdp) | {
                code for code, f in fpl.items() if (f["minutes"] or 0) > 0 or (f["starts"] or 0) > 0
            }
            for code in sorted(population):
                left, right = sdp.get(code), fpl.get(code)
                starter_total += 1
                starter_match = (
                    left is not None
                    and right is not None
                    and right["starts"] is not None
                    and left["started"] == (right["starts"] > 0)
                )
                appearance_match = (
                    left is not None
                    and right is not None
                    and right["minutes"] is not None
                    and left["appeared"] == (right["minutes"] > 0)
                )
                starter_ok += starter_match
                appearance_ok += appearance_match
                duration_population = bool(
                    (left is not None and left["appeared"])
                    or (right is not None and (right["minutes"] or 0) > 0)
                )
                difference = (
                    left["nominal_minutes"] - right["minutes"]
                    if left is not None
                    and right is not None
                    and left["nominal_minutes"] is not None
                    and right["minutes"] is not None
                    else None
                )
                pairs.append(
                    {
                        "sdp_match_id": mid,
                        "fixture": bridge["fixture"],
                        "team_code": side["provider_team_id"],
                        "code": code,
                        "starter_agreement": starter_match,
                        "appearance_agreement": appearance_match,
                        "duration_population": duration_population,
                        "difference_minutes": difference,
                        "nominal_minutes": left["nominal_minutes"] if left is not None else None,
                        "fpl_minutes": right["minutes"] if right is not None else None,
                    }
                )
    duration = [row for row in pairs if row["duration_population"]]
    diffs = [row["difference_minutes"] for row in duration if row["difference_minutes"] is not None]
    measured = len(diffs) / len(duration) if duration else 0.0
    within = sum(abs(value) <= 2 for value in diffs) / len(duration) if duration else 0.0
    mae = mean(abs(value) for value in diffs) if diffs else None
    checks = {
        "identity_complete": identity_total > 0 and identity_ok == identity_total,
        "no_required_errors": not errors,
        "pl_starters_exact": starter_total > 0 and starter_ok == starter_total,
        "pl_appearances_exact": starter_total > 0 and appearance_ok == starter_total,
        "pl_duration_complete": measured == 1.0,
        "pl_duration_within_two_minutes": within >= 0.95,
        "pl_duration_mae_at_most_one": mae is not None and mae <= 1.0,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "errors": errors,
        "identity_total": identity_total,
        "identity_resolved": identity_ok,
        "pl_comparison_rows": starter_total,
        "pl_starters_agree": starter_ok,
        "pl_appearances_agree": appearance_ok,
        "duration_rows": len(duration),
        "duration_measured_coverage": measured,
        "duration_within_two_minutes": within,
        "duration_mae": mae,
        "signed_difference_distribution": sorted(diffs),
        "pairs": pairs,
    }


def collect(
    http: httpx.Client,
    source: PlSdpSource,
    contract: Mapping[str, Any],
    reference: Mapping[str, Any],
    directory: Path,
) -> dict[str, Any]:
    selected: dict[int, tuple[dict[str, Any], RawPayload]] = {}
    inventory: dict[str, Any] = {}
    for competition in contract["competitions"]:
        cid = competition["provider_competition_id"]
        with PlSdpClient(
            config=source.model_copy(update={"competition": cid}), client=http
        ) as client:
            matches, evidence = discover(client, contract)
        inventory[str(cid)] = evidence
        for match, raw in matches:
            mid = uint(match["matchId"], "match id")
            if mid in selected:
                raise ParticipationError("selected match claimed by multiple competitions")
            selected[mid] = (match, raw)
        if len(selected) > contract["maximum_selected_matches"]:
            raise ParticipationError("selected match bound exceeded")
    actual_pl = {
        mid
        for mid, (match, _) in selected.items()
        if uint(match["competitionId"], "competition") == 8
    }
    if (
        actual_pl != set(contract["expected_pl_match_ids"])
        or len(actual_pl) < contract["minimum_pl_matches"]
    ):
        raise ParticipationError("PL inventory differs from frozen eight-match reference")
    publish_json(directory / "inventory.json", inventory)
    for mid in sorted(actual_pl):
        summary = parse_match_summary(selected[mid][0])
        bridge = reference["crosswalk"].get(str(mid))
        if bridge is None or (
            summary.kickoff != datetime.fromisoformat(bridge["kickoff_utc"])
            or summary.home_team_id != bridge["home_team_code"]
            or summary.away_team_id != bridge["away_team_code"]
            or summary.home_score != bridge["home_score"]
            or summary.away_score != bridge["away_score"]
        ):
            raise ParticipationError(f"PL match {mid}: fresh metadata contradicts reference")
    results = []
    failures = []
    with PlSdpClient(config=source, client=http) as client:
        for mid, (match, metadata) in sorted(selected.items()):
            logger.info("collecting selected match %s (%s matches total)", mid, len(selected))
            payloads = {}
            for name, call in (
                ("lineups", client.fetch_match_lineups),
                ("events", client.fetch_match_events),
            ):
                try:
                    payloads[name] = call(mid)
                except EgressBlockedError:
                    raise
                except ApiResponseError as error:
                    failures.append(
                        {
                            "sdp_match_id": mid,
                            "endpoint": name,
                            "error_class": type(error).__name__,
                            "error": str(error),
                        }
                    )
            bundle = {
                "metadata": raw_identity(metadata),
                **{name: raw_identity(raw) for name, raw in payloads.items()},
            }
            publish_json(
                directory / f"capture-{mid}.json",
                {
                    "sdp_match_id": mid,
                    "selected_match_record": match,
                    "source_versions": bundle,
                    "both_endpoints_captured": len(payloads) == 2,
                    "identity_evidence_observed_at_utc": reference["identity_observed_at_utc"],
                    "original_historical_identity_known_at": None,
                },
            )
            if len(payloads) != 2:
                continue
            try:
                known_at = max(
                    metadata.fetched_at,
                    *(raw.fetched_at for raw in payloads.values()),
                    datetime.fromisoformat(reference["identity_observed_at_utc"]),
                )
                parsed = parse_participation(
                    match,
                    payloads["lineups"].payload,
                    payloads["events"].payload,
                    known_at=known_at,
                    event_known_at=payloads["events"].fetched_at,
                )
                parsed["source_versions"] = bundle
                results.append(parsed)
            except (ParticipationError, KeyError, TypeError, ValueError) as error:
                failures.append(
                    {
                        "sdp_match_id": mid,
                        "endpoint": "interpretation",
                        "error_class": type(error).__name__,
                        "error": str(error),
                        "source_versions": bundle,
                    }
                )
    validation = validate_results(results, reference, contract)
    complete = not failures and len(results) == len(selected)
    return {
        "inventory": inventory,
        "selected_matches": len(selected),
        "pl_matches": len(actual_pl),
        "parsed_matches": len(results),
        "capture_complete": complete,
        "failures": failures,
        "validation": validation,
        "passed": complete and validation["passed"],
        "matches": results,
    }


def run(*, root: Path, db: Path, results: Path) -> dict[str, Any]:
    contract = load_contract(root)
    head = git_clean_head(root)
    db = db.resolve()
    results = results.resolve()
    if not db.is_file() or Path(str(db) + ".wal").exists():
        raise ParticipationError("explicit read-only reference DB required, with no unresolved WAL")
    if results.exists():
        raise ParticipationError("results directory already exists; no overwrite or resume")
    if results.is_relative_to(root.resolve()):
        raise ParticipationError("pilot output must be a new external operational directory")
    source = load_sources().pl_sdp
    if source is None:
        raise ParticipationError("SDP provider unconfigured")
    fingerprint = {name: file_sha256(root / name) for name in SOURCE_FILES}
    database_hash = file_sha256(db)
    reference = reference_data(db, contract["season"])
    results.mkdir(parents=True, exist_ok=False)
    recorder = ResponseRecorder(
        results, contract["maximum_distinct_provider_requests"], source.min_request_interval_seconds
    )
    provenance = {
        "git_head": head,
        "clean_worktree": True,
        "source_sha256": fingerprint,
        "database": str(db),
        "database_sha256": database_hash,
        "reference_identity_observed_at_utc": reference["identity_observed_at_utc"],
        "original_historical_identity_known_at": None,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "config": contract,
        "database_read_only": True,
        "model_fitting": False,
    }
    publish_json(results / "provenance.json", provenance)
    report: dict[str, Any] = {"completed": False, "passed": False, "provenance": provenance}
    try:
        with httpx.Client(
            timeout=source.timeout_seconds,
            follow_redirects=True,
            event_hooks={"request": [recorder.request], "response": [recorder.response]},
        ) as http:
            report.update(collect(http, source, contract, reference, results))
        report["completed"] = True
    except Exception as error:
        report["passed"] = False
        report["execution_failure"] = {
            "class": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
    try:
        postflight = {
            "git_unchanged_and_clean": git_clean_head(root) == head,
            "database_sha256": file_sha256(db),
            "no_unresolved_wal": not Path(str(db) + ".wal").exists(),
            "source_sha256": {name: file_sha256(root / name) for name in SOURCE_FILES},
        }
        report["postflight"] = postflight
        if (
            not postflight["git_unchanged_and_clean"]
            or not postflight["no_unresolved_wal"]
            or postflight["database_sha256"] != database_hash
            or postflight["source_sha256"] != fingerprint
        ):
            raise ParticipationError("postflight source/database provenance changed")
    except Exception as error:
        report["completed"] = report["passed"] = False
        report["postflight_failure"] = {"class": type(error).__name__, "message": str(error)}
    report.update(
        {
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "http_attempts": recorder.attempts,
            "http_responses": recorder.responses,
            "distinct_requests": len(recorder.urls),
            "response_statuses": [row["status"] for row in recorder.responses],
        }
    )
    publish_json(results / "result.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="read-only historical reference DB")
    parser.add_argument(
        "--results",
        required=True,
        type=Path,
        help="new external timestamped directory; must not exist",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run(root=repo_root(), db=args.db, results=args.results)
    logger.info(
        "pilot completed=%s passed=%s; %s", result["completed"], result["passed"], args.results
    )
    return 0 if result["completed"] and result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
