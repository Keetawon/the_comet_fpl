"""Read-only attacking-usage source inventory; no score, fitting or evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fpl.config import repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256, publish_json

POSITIONS = ("DEF", "MID", "FWD")
FIELDS = (
    "minutes",
    "starts",
    "expected_goals",
    "expected_assists",
    "threat",
    "creativity",
    "shots",
    "shots_on_target",
    "non_penalty_expected_goals",
    "key_passes",
    "chances_created",
    "box_touches",
    "penalty_area_entries",
    "crosses",
)


def instant(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.utcoffset() is None:
        raise ValueError("timezone-aware knowledge and event times required")
    return parsed.astimezone(UTC)


def epoch_instant(value: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)


def numeric_valid(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def select_history(
    records: list[dict[str, Any]],
    *,
    as_of: datetime,
    target_batch: tuple[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Cutoff-select whole versions before event/whole-GW exclusion, without filling NULLs."""
    cutoff = instant(as_of)
    latest: dict[tuple[str, int, int], dict[str, Any]] = {}
    versions: set[tuple[str, int, int, str]] = set()
    identities: dict[tuple[str, int, str], int] = {}
    for row in records:
        if row.get("known_at") is None or instant(row["known_at"]) > cutoff:
            continue
        if row.get("available_at") is not None and instant(row["available_at"]) > cutoff:
            continue
        key = (str(row["season"]), int(row["code"]), int(row["fixture"]))
        capture = str(row["capture_id"])
        version = (*key, capture)
        if version in versions:
            raise ValueError("duplicate source player-fixture version")
        versions.add(version)
        if row.get("element") is not None:
            identity = (key[0], int(row["element"]), capture)
            if identity in identities and identities[identity] != key[1]:
                raise ValueError("contradictory season-qualified player identity")
            identities[identity] = key[1]
        old = latest.get(key)
        if old is None or (instant(row["known_at"]), capture) > (
            instant(old["known_at"]),
            str(old["capture_id"]),
        ):
            latest[key] = row
    return [
        row
        for _, row in sorted(latest.items())
        if row.get("source_available", True) is True
        and ("available_at" not in row or row["available_at"] is not None)
        and instant(row["kickoff_time"]) < cutoff
        and (target_batch is None or (row["season"], row["gw"]) != target_batch)
    ]


def coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Observed coverage only; absent/null/invalid measurements are counted separately."""
    fields: dict[str, Any] = {}
    for field in FIELDS:
        values = [row[field] for row in records if field in row and row[field] is not None]
        valid = [v for v in values if numeric_valid(v)]
        fields[field] = {
            "field_present_rows": sum(field in row for row in records),
            "measured_valid_rows": len(valid),
            "null_or_absent_rows": len(records) - len(values),
            "invalid_numeric_rows": len(values) - len(valid),
        }
    return {
        "rows": len(records),
        "players": len({r["code"] for r in records}),
        "fixtures": len({(r["season"], r["fixture"]) for r in records}),
        "gameweeks": len({(r["season"], r["gw"]) for r in records}),
        "appeared_rows": sum(numeric_valid(r.get("minutes")) and r["minutes"] > 0 for r in records),
        "total_measured_minutes": sum(
            r["minutes"] for r in records if numeric_valid(r.get("minutes"))
        )
        if any(numeric_valid(r.get("minutes")) for r in records)
        else None,
        "fields": fields,
    }


def grouped_coverage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[row["season"], row["position"]].append(row)
    return [
        {"season": s, "position": p, **coverage(rows)} for (s, p), rows in sorted(groups.items())
    ]


def query(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = con.execute(sql)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def player_rows(con: duckdb.DuckDBPyConnection, table: str) -> list[dict[str, Any]]:
    if table not in {"mart_fact_player_fixture", "stg_live_player_fixture_version"}:
        raise ValueError("unsupported inventory table")
    columns = {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}
    selected = ["season", "gw", "fixture", "code", "position", "team_id"]
    selected += [field for field in FIELDS if field in columns]
    selected += [
        f"epoch_us({field}) AS {field}"
        for field in ("kickoff_time", "known_at")
        if field in columns
    ]
    selected += [field for field in ("capture_id", "element") if field in columns]
    rows = query(con, f"SELECT {','.join(selected)} FROM {table} ORDER BY season,code,fixture")
    for row in rows:
        for field in ("kickoff_time", "known_at"):
            if field in row:
                row[field] = epoch_instant(row[field])
    return [row for row in rows if row["position"] in POSITIONS]


def exposure_bins(records: list[dict[str, Any]]) -> dict[str, int]:
    minutes: dict[int, int] = defaultdict(int)
    for row in records:
        if numeric_valid(row.get("minutes")):
            minutes[row["code"]] += row["minutes"]
    return {
        f"players_with_at_least_{bound}_minutes": sum(v >= bound for v in minutes.values())
        for bound in (90, 180, 360, 720)
    }


def raw_inventory(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    fields: Counter[str] = Counter()
    source_hashes: list[tuple[str, str, str]] = []
    history_rows = 0
    for capture, parameter, body, sha in con.execute(
        """SELECT capture_id,parameter,CAST(payload AS VARCHAR),sha256 FROM snapshot_payload
        WHERE endpoint='element-summary' ORDER BY capture_id,parameter"""
    ).fetchall():
        source_hashes.append((capture, parameter, sha))
        for row in json.loads(body).get("history", []):
            fields.update(row.keys())
            history_rows += 1
    team_fields: Counter[str] = Counter()
    endpoints: Counter[str] = Counter()
    team_sides = 0
    player_attacking_objects = 0
    sdp_hashes: list[tuple[str, str]] = []
    for payload_id, endpoint, body, sha in con.execute(
        """SELECT payload_id,endpoint,CAST(payload AS VARCHAR),sha256 FROM raw_pl_sdp_payload
        ORDER BY payload_id"""
    ).fetchall():
        endpoints[endpoint] += 1
        sdp_hashes.append((payload_id, sha))
        if endpoint != "match_stats":
            continue
        payload = json.loads(body)
        if not isinstance(payload, list):
            raise ValueError("retained SDP team-stat envelope changed")
        for side in payload:
            if not isinstance(side.get("stats"), dict) or "teamId" not in side:
                raise ValueError("retained SDP team identity/stat shape changed")
            team_sides += 1
            team_fields.update(side["stats"].keys())
            player_attacking_objects += sum(
                isinstance(value, (list, dict)) and key != "fastestPlayer"
                for key, value in side["stats"].items()
            )
    if player_attacking_objects:
        raise ValueError("new nested SDP statistics need a separate grain audit")
    return {
        "archive_raw_player_columns": [
            r[0] for r in con.execute("DESCRIBE raw_merged_gw").fetchall()
        ],
        "archive_mart_player_columns": [
            r[0] for r in con.execute("DESCRIBE mart_fact_player_fixture").fetchall()
        ],
        "fpl_element_summary_payloads": len(source_hashes),
        "fpl_history_versions_all_positions": history_rows,
        "fpl_history_field_presence": dict(sorted(fields.items())),
        "fpl_source_versions_sha256": digest(source_hashes),
        "sdp_endpoint_versions": dict(sorted(endpoints.items())),
        "sdp_team_stat_sides": team_sides,
        "sdp_team_stat_field_presence": dict(sorted(team_fields.items())),
        "sdp_non_speed_nested_stat_objects": player_attacking_objects,
        "sdp_player_attacking_stat_grain_available": False,
        "sdp_source_versions_sha256": digest(sdp_hashes),
        "team_statistics_must_not_be_substituted_for_player_statistics": True,
        "player_open_play_set_piece_separation_available": False,
    }


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def deadline_coverage(
    con: duckdb.DuckDBPyConnection,
    archive: list[dict[str, Any]],
    live: list[dict[str, Any]],
    latest: list[dict[str, Any]],
    archive_known_at: datetime,
) -> list[dict[str, Any]]:
    """Coverage witnesses only: target labels never define a forecasting roster or features."""
    deadlines: dict[tuple[str, int], tuple[datetime, datetime, str]] = {}
    for season, stamp, capture, body in con.execute(
        """SELECT c.season,epoch_us(c.captured_at),c.capture_id,CAST(p.payload AS VARCHAR)
        FROM snapshot_capture c JOIN snapshot_payload p USING(capture_id)
        WHERE p.endpoint='bootstrap-static' ORDER BY c.captured_at,c.capture_id"""
    ).fetchall():
        known = epoch_instant(stamp)
        for event in json.loads(body)["events"]:
            deadline = instant(event["deadline_time"])
            if known <= deadline:
                deadlines[season, event["id"]] = (deadline, known, capture)
    registry = query(
        con,
        """SELECT season,code,position,team_id,capture_id,
        epoch_us(known_at) AS known_at FROM stg_live_player_version
        ORDER BY known_at,capture_id,season,code""",
    )
    team_versions = query(
        con,
        """SELECT season,team_id,team_code,capture_id,
        epoch_us(known_at) AS known_at FROM stg_live_team_version
        ORDER BY known_at,capture_id,season,team_id""",
    )
    archive_teams = {
        (r[0], r[1]): r[2]
        for r in con.execute("SELECT season,team_id,team_code FROM mart_dim_team").fetchall()
    }
    results = []
    for season, gw in sorted({(r["season"], r["gw"]) for r in latest}):
        cutoff, deadline_known, deadline_capture = deadlines[season, gw]
        roster = {
            r["code"]: r
            for r in registry
            if r["season"] == season and epoch_instant(r["known_at"]) <= cutoff
        }
        teams = {
            (r["season"], r["team_id"]): r["team_code"]
            for r in team_versions
            if epoch_instant(r["known_at"]) <= cutoff
        }
        target = [r for r in latest if (r["season"], r["gw"]) == (season, gw)]
        absent = [r for r in target if r["code"] not in roster]
        mismatch = [
            r
            for r in target
            if r["code"] in roster
            and any(r[key] != roster[r["code"]][key] for key in ("position", "team_id"))
        ]
        eligible = [r for r in target if r not in absent and r not in mismatch]
        history = select_history(live, as_of=cutoff, target_batch=(season, gw))
        archive_history = [
            r
            for r in archive
            if archive_known_at <= cutoff
            and r["kickoff_time"] < cutoff
            and (r["season"], r["gw"]) != (season, gw)
        ]
        by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in archive_history + history:
            by_player[row["code"]].append(row)
        measured = {
            code: [
                r
                for r in rows
                if numeric_valid(r["minutes"])
                and r["minutes"] > 0
                and numeric_valid(r["expected_goals"])
                and numeric_valid(r["expected_assists"])
            ]
            for code, rows in by_player.items()
        }
        exposures = [sum(r["minutes"] for r in measured.get(t["code"], [])) for t in eligible]
        by_position: dict[str, Counter[str]] = {p: Counter() for p in POSITIONS}
        for target_row in eligible:
            code = target_row["code"]
            counts = by_position[target_row["position"]]
            prior = by_player.get(code, [])
            paired = measured.get(code, [])
            current = [r for r in history if r["code"] == code]
            current_measured = [
                r
                for r in current
                if numeric_valid(r["minutes"])
                and r["minutes"] > 0
                and numeric_valid(r["expected_goals"])
                and numeric_valid(r["expected_assists"])
            ]
            counts["eligible_target_rows"] += 1
            counts["prior_paired_measured_rows"] += len(paired)
            counts["prior_paired_measured_minutes"] += sum(r["minutes"] for r in paired)
            counts["prior_measured_starts"] += sum(
                r["starts"] for r in paired if numeric_valid(r.get("starts"))
            )
            counts["current_season_prior_rows_present"] += bool(current)
            counts["current_season_prior_appearance_present"] += bool(current_measured)
            counts["cold_no_retained_history"] += not prior
            counts["cold_no_positive_measured_history"] += not paired
            for name, subset in (("prior", paired), ("current_season", current_measured)):
                minutes = sum(r["minutes"] for r in subset)
                for bound in (90, 180, 360, 720):
                    counts[f"{name}_measured_minutes_ge_{bound}"] += minutes >= bound
            target_club = teams.get((season, target_row["team_id"]))
            for name, subset in (("retained", prior), ("measured", paired)):
                if not subset:
                    continue
                last = max(subset, key=lambda r: (r["kickoff_time"], r["season"], r["fixture"]))
                mapping = teams if "capture_id" in last else archive_teams
                club = mapping.get((last["season"], last["team_id"]))
                if club is not None and target_club is not None:
                    counts[f"last_{name}_club_differs_from_cutoff_club"] += club != target_club
                if name == "measured":
                    counts["last_measured_position_differs_from_cutoff_position"] += (
                        last["position"] != target_row["position"]
                    )
        results.append(
            {
                "season": season,
                "gw": gw,
                "prediction_as_of": cutoff.isoformat(),
                "deadline_snapshot_known_at": deadline_known.isoformat(),
                "deadline_snapshot_capture_id": deadline_capture,
                "observed_target_rows": len(target),
                "missing_cutoff_registry": len(absent),
                "cutoff_registry_identity_mismatch": len(mismatch),
                "identity_eligible_observed_target_rows": len(eligible),
                "identity_eligible_by_position": dict(
                    sorted(Counter(r["position"] for r in eligible).items())
                ),
                "prior_archive_outfield_rows": len(archive_history),
                "prior_live_outfield_rows": len(history),
                "prior_live_gameweeks": len({(r["season"], r["gw"]) for r in history}),
                "cold_no_retained_history": sum(not by_player.get(r["code"]) for r in eligible),
                "cold_no_positive_measured_history": sum(value == 0 for value in exposures),
                "measured_history_exposure_bins": {
                    str(bound): sum(v >= bound for v in exposures) for bound in (90, 180, 360, 720)
                },
                "history_support_by_position": {
                    p: dict(sorted(c.items())) for p, c in by_position.items()
                },
                "identity_exclusions": [
                    {
                        "season": r["season"],
                        "fixture": r["fixture"],
                        "code": r["code"],
                        "reason": reason,
                    }
                    for reason, subset in (
                        ("NO_CUTOFF_REGISTRY", absent),
                        ("CUTOFF_REGISTRY_IDENTITY_MISMATCH", mismatch),
                    )
                    for r in subset
                ],
                "observed_identity_crosscheck_only_not_a_target_derived_prediction_roster": True,
            }
        )
    return results


def audit(database: Path, role_result: Path, config: Path) -> dict[str, Any]:
    contract = yaml.safe_load(config.read_bytes())
    if contract["evidence_policy"] != "strict_known_at":
        raise ValueError("this inventory cannot substitute event time for knowledge time")
    cutoff = instant(contract["inventory_as_of"])
    paths = {
        "database": database,
        "role_result": role_result,
        "config": config,
        "auditor": Path(__file__),
        "publication_helpers": Path(__file__).with_name("competitive_participation_pilot.py"),
    }
    hashes = {name: file_sha256(path) for name, path in paths.items()}
    if (
        hashes["database"] != contract["database_sha256"]
        or hashes["role_result"] != contract["role_result_sha256"]
        or Path(str(database) + ".wal").exists()
    ):
        raise ValueError("immutable source pin/WAL check failed")
    role = json.loads(role_result.read_bytes())
    with duckdb.connect(str(database), read_only=True) as con:
        con.execute("SET TimeZone='UTC'")
        archive = player_rows(con, "mart_fact_player_fixture")
        live = player_rows(con, "stg_live_player_fixture_version")
        latest = select_history(live, as_of=cutoff)
        archive_times = query(
            con,
            """SELECT season,source_table,
            min(epoch_us(ingested_at)) AS first_ingested_at_us,
            max(epoch_us(ingested_at)) AS last_ingested_at_us,
            count(DISTINCT sha256) AS distinct_source_hashes
            FROM raw_ingest_log GROUP BY season,source_table ORDER BY season,source_table""",
        )
        raw_current = query(
            con,
            """SELECT max(epoch_us(_ingested_at)) AS stamp FROM (
            SELECT _ingested_at FROM raw_merged_gw UNION ALL SELECT _ingested_at FROM raw_players
            UNION ALL SELECT _ingested_at FROM raw_teams
            UNION ALL SELECT _ingested_at FROM raw_fixtures
            )""",
        )[0]["stamp"]
        archive_known = epoch_instant(raw_current)
        batches = deadline_coverage(con, archive, live, latest, archive_known)
        result = {
            "study_id": contract["study_id"],
            "contract_version": contract["contract_version"],
            "inventory_as_of": cutoff.isoformat(),
            "source_sha256": hashes,
            "git_head": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root(),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
            "development_only": True,
            "formal_evaluation": False,
            "model_fitting": False,
            "network_requests": 0,
            "production_mutations": False,
            "archive": {
                "overall": coverage(archive),
                "by_season_position": grouped_coverage(archive),
                "ingest_receipts": archive_times,
                "conservative_current_raw_known_at": archive_known.isoformat(),
                "historical_deadline_known_evidence": False,
            },
            "live": {
                "overall": coverage(latest),
                "by_season_position": grouped_coverage(latest),
                "latest_current_season_exposure_bins": exposure_bins(latest),
                "completed_gameweek_batches": batches,
                "first_known_at_by_gameweek": query(
                    con,
                    """SELECT season,gw,
                    count(DISTINCT (season,code,fixture)) AS player_fixture_rows,
                    min(epoch_us(known_at)) AS first_known_at_us
                    FROM stg_live_player_fixture_version WHERE position IN ('DEF','MID','FWD')
                    GROUP BY season,gw ORDER BY season,gw""",
                ),
                "snapshot_captures": query(
                    con,
                    """SELECT season,count(*) AS captures,
                    min(epoch_us(captured_at)) AS earliest_capture_at_us,
                    max(epoch_us(captured_at)) AS latest_capture_at_us FROM snapshot_capture
                    GROUP BY season ORDER BY season""",
                ),
            },
            "raw_inventory": raw_inventory(con),
            "formation_support": {
                "retained_sample_matches": role["sample_matches"],
                "interpretation_known_at": role["interpretation_known_at"],
                "optional_not_a_prerequisite": True,
                "eligible_in_completed_live_batches": sum(
                    instant(role["interpretation_known_at"]) <= instant(row["prediction_as_of"])
                    for row in batches
                ),
            },
            "feasibility": {
                "status": contract["decision"],
                "verdict": "D. INSUFFICIENT DATA",
                "review_not_a_numeric_promotion_gate": True,
                "completed_strict_deadline_batches": len(batches),
                "batches_with_prior_current_season_history": sum(
                    r["prior_live_gameweeks"] > 0 for r in batches
                ),
                "review_limitation": "Only three completed deadline batches and two "
                "current-season updates; longitudinal usage-change validity is unassessed.",
                "optional_context_absence_alone_is_failure": False,
                "historical_archive_has_real_capture_but_not_earlier_deadline_knowledge": True,
                "numerical_promotion_threshold": None,
                "attacking_role_premium": None,
                "shrinkage_strength": None,
                "regime_shift_count": None,
                "predictive_metrics": None,
                "formation_incremental_value": None,
                "named_case_classification": None,
            },
        }
    if (
        any(file_sha256(path) != hashes[name] for name, path in paths.items())
        or Path(str(database) + ".wal").exists()
    ):
        raise ValueError("source changed during read-only inventory")
    result["source_hashes_unchanged"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--role-result", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit(args.db, args.role_result, args.config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    publish_json(args.output, result)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": file_sha256(args.output),
                "status": result["feasibility"]["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
