"""Offline, write-once source-structure audit. No prediction, fitting or database writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fpl.config import repo_root
from fpl.ingest.pl_sdp import extract_items, parse_match_summary
from fpl.jobs.capture_competitive_workload import load_contract, load_retained
from fpl.jobs.competitive_participation_pilot import file_sha256, publish_json
from fpl.storage.competitive_workload import canonical
from fpl.transform.player_role_source import available_before, parse_role_structure

CONFIG = "config/player_role_source_audit.yaml"
CONFIG_SHA256 = "a695452fbc12fd1d414d1d64b44c02addee53626c17cd06d4b66093ded7ead5a"
DATABASE_SHA256 = "538560454f551a48eeaf015c318f7dea0fc6a34fccc56ee7f0e2b117ef7330d6"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("timezone-aware receipt required")
    return parsed.astimezone(UTC)


def from_epoch(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000, UTC)


def checked_body(body: bytes, sha256: str, byte_count: int, status: int) -> Any:
    if status != 200 or len(body) != byte_count or hashlib.sha256(body).hexdigest() != sha256:
        raise ValueError("raw receipt status/bytes/hash mismatch")
    return json.loads(body)


def load_sample(root: Path, retained: Path, con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Original 13 bundles plus distinct latest whole operational source versions."""
    inputs = load_retained(root, retained, load_contract(root))
    sample: list[dict[str, Any]] = []
    for mid in sorted({mid for mid, _ in inputs.reused}):
        manifest = json.loads(inputs.files[f"capture-{mid}.json"])
        sources = {}
        payloads = {}
        for endpoint, version in manifest["source_versions"].items():
            receipt = next(
                row
                for row in json.loads(inputs.files["pilot-result.json"])["http_responses"]
                if row["sha256"] == version["sha256"]
            )
            payloads[endpoint] = checked_body(
                inputs.files[receipt["raw_file"]],
                receipt["sha256"],
                receipt["bytes"],
                receipt["status"],
            )
            sources[endpoint] = {
                **receipt,
                "raw_path": str(retained / receipt["raw_file"]),
                "retained_known_at": version["known_at"],
                "source_known_at": None,
            }
        sample.append(
            {
                "sample_group": "original_pilot",
                "season": "2025-26",
                "match": manifest["selected_match_record"],
                "lineups": payloads["lineups"],
                "events": payloads["events"],
                "sources": sources,
            }
        )
    records = con.execute(
        """SELECT CAST(record_json AS VARCHAR) FROM sdp_competitive_match_version
        QUALIFY row_number() OVER (
            PARTITION BY season,competition,provider_match_id ORDER BY known_at DESC,version_id
        )=1 ORDER BY season,competition,provider_match_id"""
    ).fetchall()
    for (body,) in records:
        record = json.loads(body)
        sources, payloads = {}, {}
        for endpoint, version in record["source_versions"].items():
            raw = con.execute(
                """SELECT CAST(payload AS VARCHAR),sha256,byte_count,status_code,
                epoch_us(fetched_at),request_path,params_json,endpoint,sdp_match_id,season
                FROM raw_pl_sdp_payload WHERE payload_id=?""",
                [version["payload_id"]],
            ).fetchone()
            if raw is None or raw[1] != version["sha256"] or raw[5] != version["path"]:
                raise ValueError("operational source reference mismatch")
            if any(
                instant(version[key]) != from_epoch(raw[4]) for key in ("known_at", "fetched_at")
            ):
                raise ValueError("operational source knowledge time mismatch")
            payloads[endpoint] = checked_body(raw[0].encode(), raw[1], raw[2], raw[3])
            expected = "competitive_matches" if endpoint == "metadata" else f"match_{endpoint}"
            if raw[7] != expected or raw[9] != record["season"]:
                raise ValueError("operational source endpoint/season mismatch")
            if endpoint != "metadata" and raw[8] != record["provider_match_id"]:
                raise ValueError("operational source match mismatch")
            sources[endpoint] = {
                **version,
                "source_known_at": None,
                "bytes": raw[2],
                "status": raw[3],
                "captured_at_utc": from_epoch(raw[4]).isoformat(),
                "endpoint": raw[7],
                "retained_known_at": from_epoch(raw[4]).isoformat(),
                "request_path": raw[5],
                "params": json.loads(raw[6]),
                "content_type": None,
                "content_type_note": "not retained by original operational raw-store schema",
            }
        if record["raw_metadata"] not in extract_items(payloads["metadata"]):
            raise ValueError("selected metadata absent from immutable catalogue")
        sample.append(
            {
                "sample_group": "operational",
                "season": record["season"],
                "match": record["raw_metadata"],
                "lineups": payloads["lineups"],
                "events": payloads["events"],
                "sources": sources,
                "retained_workload_version_id": record["version_id"],
            }
        )
    if Counter(row["sample_group"] for row in sample) != {"original_pilot": 13, "operational": 10}:
        raise ValueError("pinned bounded source population changed")
    return sample


def registries(con: duckdb.DuckDBPyConnection, interpreted_at: datetime) -> dict[str, Any]:
    historical = [
        dict(zip(("season", "code", "opta_code", "position", "web_name"), row, strict=True))
        for row in con.execute(
            """SELECT season,code,opta_code,position,web_name FROM mart_dim_player
        WHERE season='2025-26' ORDER BY code"""
        ).fetchall()
    ]
    snapshot = con.execute(
        """SELECT c.capture_id,epoch_us(c.captured_at),CAST(p.payload AS VARCHAR),
        p.sha256,p.byte_count FROM snapshot_capture c JOIN snapshot_payload p USING(capture_id)
        WHERE c.season='2026-27' AND p.endpoint='bootstrap-static'
        ORDER BY c.captured_at DESC,c.capture_id LIMIT 1"""
    ).fetchone()
    if snapshot is None:
        raise ValueError("required FPL bootstrap snapshot absent")
    capture, stamp, body, sha, size = snapshot
    bootstrap = checked_body(body.encode(), sha, size, 200)
    current = [
        {**row, "season": "2026-27", "position": POSITIONS[row["element_type"]]}
        for row in bootstrap["elements"]
        if row.get("element_type") in POSITIONS
    ]
    return {
        "2025-26": {
            "rows": historical,
            "known_at": interpreted_at.isoformat(),
            "provenance": {
                "source": "mart_dim_player",
                "season": "2025-26",
                "identity_and_registered_position_rechecked_at": interpreted_at.isoformat(),
                "historical_deadline_known_at": None,
                "sha256": hashlib.sha256(canonical(historical).encode()).hexdigest(),
            },
            "team_codes": [
                row[0]
                for row in con.execute(
                    "SELECT team_code FROM mart_dim_team WHERE season='2025-26' ORDER BY team_code"
                ).fetchall()
            ],
        },
        "2026-27": {
            "rows": current,
            "known_at": from_epoch(stamp).isoformat(),
            "teams": {int(t["id"]): int(t["code"]) for t in bootstrap["teams"]},
            "team_codes": sorted(int(t["code"]) for t in bootstrap["teams"]),
            "provenance": {
                "source": "snapshot_payload",
                "capture_id": capture,
                "sha256": sha,
                "known_at": from_epoch(stamp).isoformat(),
            },
        },
    }


def fixture_identity(
    con: duckdb.DuckDBPyConnection, entry: dict[str, Any], registry: dict[str, Any]
) -> tuple[int | None, dict[str, Any]]:
    match = parse_match_summary(entry["match"])
    if int(entry["match"]["competitionId"]) != 8:
        return None, {"method": "no_fpl_fixture_for_other_competition", "known_at": None}
    cross = con.execute(
        """SELECT fixture FROM stg_pl_sdp_fixture_crosswalk WHERE season=? AND sdp_match_id=?
        AND corroborated_kickoff AND corroborated_teams AND corroborated_score""",
        [entry["season"], match.match_id],
    ).fetchall()
    if len(cross) != 1:
        raise ValueError("no unique corroborated fixture crosswalk")
    fixture = int(cross[0][0])
    if entry["season"] == "2025-26":
        witness = con.execute(
            """SELECT epoch_us(f.kickoff_time),h.team_code,a.team_code,
            f.team_h_score,f.team_a_score FROM stg_fixture f JOIN mart_dim_team h
            ON f.season=h.season AND f.team_h=h.team_id JOIN mart_dim_team a
            ON f.season=a.season AND f.team_a=a.team_id WHERE f.season=? AND f.fixture=?""",
            [entry["season"], fixture],
        ).fetchone()
        provenance = {
            "method": "existing_corroborated_crosswalk_and_archive_fixture",
            "known_at": registry["known_at"],
            "historical_deadline_known_at": None,
        }
    else:
        witness = con.execute(
            """SELECT epoch_us(kickoff_time),team_h,team_a,team_h_score,team_a_score,capture_id
            FROM stg_live_fixture_version WHERE season=? AND fixture=?
            ORDER BY known_at DESC,capture_id LIMIT 1""",
            [entry["season"], fixture],
        ).fetchone()
        if witness is not None:
            raw = con.execute(
                """SELECT CAST(p.payload AS VARCHAR),p.sha256,p.byte_count,epoch_us(c.captured_at)
                FROM snapshot_payload p JOIN snapshot_capture c USING(capture_id)
                WHERE p.capture_id=? AND p.endpoint='fixtures'""",
                [witness[5]],
            ).fetchone()
            if raw is None:
                raise ValueError("FPL fixture raw snapshot missing")
            candidates = [
                r
                for r in checked_body(raw[0].encode(), raw[1], raw[2], 200)
                if r.get("id") == fixture
            ]
            if len(candidates) != 1:
                raise ValueError("FPL fixture raw identity not unique")
            evidence = candidates[0]
            if (
                instant(evidence["kickoff_time"]),
                evidence["team_h"],
                evidence["team_a"],
                evidence["team_h_score"],
                evidence["team_a_score"],
            ) != (from_epoch(witness[0]), *witness[1:5]):
                raise ValueError("FPL fixture staged/raw mismatch")
            provenance = {
                "method": "existing_corroborated_crosswalk_and_raw_fpl_fixture",
                "capture_id": witness[5],
                "sha256": raw[1],
                "known_at": from_epoch(raw[3]).isoformat(),
            }
            witness = (
                witness[0],
                registry["teams"][witness[1]],
                registry["teams"][witness[2]],
                *witness[3:5],
            )
    if witness is None or (from_epoch(witness[0]), *witness[1:]) != (
        match.kickoff,
        match.home_team_id,
        match.away_team_id,
        match.home_score,
        match.away_score,
    ):
        raise ValueError("fixture crosswalk independent identity contradiction")
    return fixture, {
        "fixture": fixture,
        "provider_match_id": match.match_id,
        "home_provider_team_id": match.home_team_id,
        "home_fpl_team_code": witness[1],
        "away_provider_team_id": match.away_team_id,
        "away_fpl_team_code": witness[2],
        **provenance,
    }


def schema_inventory(sample: list[dict[str, Any]]) -> dict[str, Any]:
    """Presence denominator counts actual parent objects; no absent rows are invented."""
    objects: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            objects[path].append(value)
            for key, child in value.items():
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for child in value:
                visit(child, path + "[]")

    for entry in sample:
        visit(entry["match"], "match")
        objects["lineup.root"].append(entry["lineups"])
        objects["event.root"].append(entry["events"])
        for label, node in (("home", "homeTeam"), ("away", "awayTeam")):
            visit(entry["lineups"][label + "_team"], "lineup.side")
            visit(entry["events"][node], "event.side")
    result = {}
    for path, parents in sorted(objects.items()):
        fields = {}
        for key in sorted(set().union(*(row.keys() for row in parents))):
            values = [row[key] for row in parents if key in row]
            fields[key] = {
                "present": len(values),
                "missing": len(parents) - len(values),
                "null": sum(v is None for v in values),
                "types": dict(sorted(Counter(type(v).__name__ for v in values).items())),
            }
        result[path] = {"objects": len(parents), "fields": fields}
    return result


def summarize(matches: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    rows = []
    history: dict[int, list[dict[str, Any]]] = defaultdict(list)
    order: Counter[str] = Counter()
    profiles: dict[str, Counter[str]] = defaultdict(Counter)
    for match in matches:
        for side in match["sides"]:
            population = side["rows"]
            for row in population:
                row["team_name"] = match["team_names"][side["side"]]
                rows.append(row)
                history[row["provider_player_id"]].append(row)
            formation = (side["formation"] or {}).get("formation")
            for row in population:
                if row["formation_line_index"] is not None:
                    profiles[f"{formation}:line:{row['formation_line_index']}"][
                        str(row.get("provider_broad_position"))
                    ] += 1
            for key in (
                "overall",
                "season:" + match["season"],
                "competition:" + str(match["provider_competition_id"]),
                "team:" + str(side["provider_team_id"]),
                "formation:" + str(formation),
            ):
                group = groups[key]
                group["sides"] += 1
                group["explicit_formation"] += side["formation_lineup"] is not None
                group["annotation_consistent"] += side["formation_annotation_matches"] is True
                group["exact_xi"] += sum(r["started"] is True for r in population) == 11
                group["bench_recoverable"] += bool(side["membership_policy"])
                group["unassigned_roster"] += len(side["unassigned_roster_ids"])
                group["roster_rows"] += len(population)
                group["mapped_rows"] += sum(r["fpl_code"] is not None for r in population)
                group["unmapped_rows"] += sum(r["fpl_code"] is None for r in population)
                group["starters"] += sum(r["started"] is True for r in population)
                group["bench_players"] += sum(r["on_bench"] is True for r in population)
                group["broad_position"] += sum(
                    r.get("provider_broad_position") is not None for r in population
                )
                group["formation_band"] += sum(r["formation_band"] is not None for r in population)
                group["within_line_index_available"] += sum(
                    r["formation_member_index"] is not None for r in population
                )
                group["within_line_semantics_validated"] += 0
                group["substitution_events"] += len(side["substitutions"])
                group["promoted_club_roster_rows"] += sum(
                    r.get("promoted_club_sample") is True for r in population
                )
                group["no_prior_season_registry_witness"] += sum(
                    r.get("no_previous_season_fpl_registry_row") is True for r in population
                )
            for line in side["formation_lineup"] or []:
                if len(line) > 1:
                    ids = list(map(int, line))
                    order["multiple_member_lines"] += 1
                    order["numeric_id_sorted"] += ids == sorted(ids)
    controls = []
    seen = set()
    for row in sorted(
        rows,
        key=lambda r: (
            r["season"],
            r["provider_match_id"],
            r["provider_team_id"],
            r["provider_player_id"],
        ),
    ):
        if row["started"] is True and row["fpl_code"] is not None and row["fpl_code"] not in seen:
            controls.append(row)
            seen.add(row["fpl_code"])
            if len(controls) == 6:
                break
    movements = []
    for pid, observations in sorted(history.items()):
        starters = [r for r in observations if r["formation_line_index"] is not None]
        lines = {r["formation_line_index"] for r in starters}
        if len(lines) > 1:
            movements.append(
                {
                    "provider_player_id": pid,
                    "line_indices": sorted(lines),
                    "observations": [
                        {
                            k: r[k]
                            for k in (
                                "season",
                                "provider_match_id",
                                "provider_team_id",
                                "formation",
                                "formation_line_index",
                                "formation_member_index",
                                "provider_position",
                            )
                        }
                        for r in starters
                    ],
                }
            )
    # Name matching selects requested display cases only AFTER frozen generic classification.
    # It never creates an identity join or participates in the role/OOP classifier.
    aliases = {"O'Reilly": "oreilly", "Hume": "hume", "De Cuyper": "decuyper"}
    cases: dict[str, Any] = {}
    for label, token in aliases.items():
        selected = []
        for row in rows:
            name = "".join(c for c in str(row.get("fpl_web_name", "")).casefold() if c.isalpha())
            if row["fpl_code"] is not None and name == token:
                selected.append(row)
        cases[label] = {"status": "OBSERVED" if selected else "NOT OBSERVED", "rows": selected}
    club_changes = [
        {
            "provider_player_id": pid,
            "observed_provider_team_ids": sorted({r["provider_team_id"] for r in observations}),
            "registration_interval_or_transfer_date": None,
            "observations": [
                {
                    k: r[k]
                    for k in (
                        "season",
                        "provider_match_id",
                        "kickoff",
                        "provider_team_id",
                        "fpl_code",
                        "capture_known_at",
                    )
                }
                for r in observations
            ],
        }
        for pid, observations in sorted(history.items())
        if len({r["provider_team_id"] for r in observations}) > 1
    ]
    return {
        "coverage": {key: dict(value) for key, value in sorted(groups.items())},
        "unique_provider_players": len(history),
        "order_diagnostics": dict(order),
        "broad_positions_by_formation_line": {
            key: dict(value) for key, value in sorted(profiles.items())
        },
        "identity": {
            "mapped_rows": sum(r["fpl_code"] is not None for r in rows),
            "unmapped_rows": sum(r["fpl_code"] is None for r in rows),
            "mapped_unique_provider_ids": len(
                {r["provider_player_id"] for r in rows if r["fpl_code"] is not None}
            ),
            "unmapped_unique_provider_ids": len(
                {r["provider_player_id"] for r in rows if r["fpl_code"] is None}
            ),
            "contradictory_provider_code_mappings": [
                pid
                for pid, observations in sorted(history.items())
                if len({r["fpl_code"] for r in observations if r["fpl_code"] is not None}) > 1
            ],
            "reverse_duplicate_code_mappings": sorted(
                code
                for code in {r["fpl_code"] for r in rows}
                if code is not None
                and len({r["provider_player_id"] for r in rows if r["fpl_code"] == code}) > 1
            ),
            "rows_with_identity_errors": [
                {
                    k: r[k]
                    for k in (
                        "season",
                        "provider_match_id",
                        "provider_player_id",
                        "identity_errors",
                    )
                }
                for r in rows
                if r["identity_errors"]
            ],
        },
        "line_movements": movements,
        "observed_club_changes": club_changes,
        "case_studies": cases,
        "source_determined_controls": controls,
        "oop_counts": dict(Counter(row["oop_diagnostic"] for row in rows)),
        "all_target_pre_kickoff_checks_rejected": all(
            not available_before(row, instant(row["kickoff"])) for row in rows
        ),
    }


def run(
    *, root: Path, retained: Path, database: Path, output: Path, replay_of: Path | None = None
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("source audit output is immutable")
    if file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("pre-case generic source rules changed")
    if Path(str(database) + ".wal").exists() or file_sha256(database) != DATABASE_SHA256:
        raise ValueError("explicit immutable forecast-source database fingerprint required")
    config = yaml.safe_load((root / CONFIG).read_bytes())
    interpreted_at = datetime.now(UTC)
    prior = None
    if replay_of is not None:
        prior = json.loads(replay_of.read_bytes())
        interpreted_at = instant(prior["interpretation_known_at"])
    if interpreted_at < instant(config["rules_frozen_at"]):
        raise ValueError("interpretation cannot predate the frozen source rules")
    files = [
        CONFIG,
        "src/fpl/jobs/audit_player_role_source.py",
        "src/fpl/transform/player_role_source.py",
        "src/fpl/transform/competitive_participation.py",
        "src/fpl/transform/competitive_participation_v2.py",
        "src/fpl/jobs/capture_competitive_workload.py",
        "src/fpl/ingest/pl_sdp.py",
    ]
    hashes = {name: file_sha256(root / name) for name in files}
    with duckdb.connect(str(database), read_only=True) as con:
        sample = load_sample(root, retained, con)
        registry = registries(con, interpreted_at)
        club_witnesses: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
        for candidate in sample:
            if int(candidate["match"]["competitionId"]) != 8:
                continue
            try:
                _, witness = fixture_identity(con, candidate, registry[candidate["season"]])
            except ValueError:
                # The fixture itself is explicitly quarantined below; it supplies no club anchor.
                continue
            for label in ("home", "away"):
                pid, code = witness[f"{label}_provider_team_id"], witness[f"{label}_fpl_team_code"]
                club_witnesses[candidate["season"]].setdefault(
                    pid, {"provider_team_id": pid, "team_code": code, "fixture_identity": witness}
                )
        matches, failures = [], []
        for entry in sample:
            identity = registry[entry["season"]]
            capture = max(
                instant(source[key])
                for source in entry["sources"].values()
                for key in ("captured_at_utc", "retained_known_at")
            )
            provenance = {
                "sources": entry["sources"],
                "identity": identity["provenance"],
                "source_database_sha256": DATABASE_SHA256,
                "rule_sha256": CONFIG_SHA256,
                "club_identity_witnesses": [
                    club_witnesses[entry["season"]].get(int(entry["match"][node]["id"]))
                    for node in ("homeTeam", "awayTeam")
                ],
            }
            try:
                fixture, fixture_provenance = fixture_identity(con, entry, identity)
                provenance["fixture_identity"] = fixture_provenance
                identity_time = max(
                    instant(identity["known_at"]),
                    instant(fixture_provenance["known_at"])
                    if fixture_provenance["known_at"]
                    else instant(identity["known_at"]),
                    *(
                        instant(w["fixture_identity"]["known_at"])
                        for w in provenance["club_identity_witnesses"]
                        if w is not None
                    ),
                )
                result = parse_role_structure(
                    entry["match"],
                    entry["lineups"],
                    entry["events"],
                    season=entry["season"],
                    fixture=fixture,
                    registry=identity["rows"],
                    source_known_at=None,
                    capture_known_at=capture,
                    interpretation_known_at=interpreted_at,
                    identity_known_at=identity_time,
                    provenance=provenance,
                    event_capture_known_at=instant(entry["sources"]["events"]["retained_known_at"]),
                )
                result["sample_group"] = entry["sample_group"]
                result["team_names"] = {
                    label: entry["match"][node]["name"]
                    for label, node in (("home", "homeTeam"), ("away", "awayTeam"))
                }
                for side in result["sides"]:
                    team = side["provider_team_id"]
                    club = club_witnesses[entry["season"]].get(team)
                    for row in side["rows"]:
                        row["team_code"] = club["team_code"] if club is not None else None
                        row["promoted_club_sample"] = (
                            club["team_code"] not in registry["2025-26"]["team_codes"]
                            if entry["season"] == "2026-27" and club is not None
                            else None
                        )
                        row["no_previous_season_fpl_registry_row"] = (
                            row["fpl_code"] not in {r["code"] for r in registry["2025-26"]["rows"]}
                            if entry["season"] == "2026-27" and row["fpl_code"] is not None
                            else None
                        )
                matches.append(result)
            except (ValueError, KeyError, TypeError) as error:
                failures.append(
                    {
                        "provider_match_id": entry["match"]["matchId"],
                        "reason": str(error),
                        "provenance": provenance,
                    }
                )
        report = {
            "contract": config,
            "interpretation_known_at": interpreted_at.isoformat(),
            "development_only": True,
            "network_requests": 0,
            "model_fitting": False,
            "production_mutations": False,
            "database": str(database),
            "database_sha256": DATABASE_SHA256,
            "source_sha256": hashes,
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "sample_matches": len(sample),
            "interpreted_matches": len(matches),
            "schema_inventory": schema_inventory(sample),
            "matches": matches,
            "failures": failures,
            "summary": summarize(matches),
        }
        if file_sha256(database) != DATABASE_SHA256 or hashes != {
            name: file_sha256(root / name) for name in files
        }:
            raise ValueError("read-only source/config/implementation changed during audit")
        # Re-read retained bytes to verify immutability, without reinterpreting any frozen result.
        if canonical(load_sample(root, retained, con)) != canonical(sample):
            raise ValueError("raw source state changed during audit")
    if prior is not None and canonical(report) != canonical(prior):
        raise ValueError("identical-input source audit replay differed")
    publish_json(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-of", type=Path)
    args = parser.parse_args(argv)
    report = run(
        root=repo_root(),
        retained=args.retained.resolve(),
        database=args.db.resolve(),
        output=args.output.resolve(),
        replay_of=args.replay_of,
    )
    print(
        json.dumps(
            {
                "sample": report["sample_matches"],
                "interpreted": report["interpreted_matches"],
                "failures": len(report["failures"]),
                "coverage": report["summary"]["coverage"]["overall"],
            }
        )
    )
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
