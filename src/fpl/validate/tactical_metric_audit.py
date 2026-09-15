"""Read-only, coverage-only audit of canonical SDP tactical payloads; never fit a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from fpl.config import SdpMetricType, load_sdp_metrics, repo_root
from fpl.ingest.pl_sdp import parse_team_stats
from fpl.storage.db import connect
from fpl.transform.pl_sdp import _coerce
from fpl.validate.retrospective_sdp import VERSION_SELECTION_POLICY, RetrospectiveBackfillView

OPTA_DEFINITIONS = "https://www.statsperform.com/opta-event-definitions/"
PL_CLARIFICATION = "https://www.premierleague.com/en/stats/clarification"
PROPOSED_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "attack_precision": ("ontargetScoringAtt", "totalScoringAtt"),
    "dangerous_territory": ("touchesInOppBox",),
    "control": ("possessionPercentage",),
    "directness": ("fwdPass", "totalPass"),
    "defensive_suppression": ("totalScoringAtt",),
}
_CAVEATS = {
    "ontargetScoringAtt": "Includes last-line blocks; differs from saves plus goals proxy.",
    "totalScoringAtt": "Includes blocked attempts; SOT/this field is not Opta shooting accuracy.",
    "touchesInOppBox": "Provider-labelled count, not unique possessions/entries or tracking data.",
    "possessionPercentage": "Provider-labelled 0..100 share; tracking-time method unverified.",
    "fwdPass": "Directional pass count; share is not sequence direct speed or pass length.",
    "totalPass": "Opta passes exclude crosses, keeper throws and throw-ins; volume not dominance.",
    "outfielderBlock": "Dictionary prose conflicts with Opta Block definition; excluded from V1.",
    "totalTackle": "Opta completed ground challenge; not every attempted tackle or pressure.",
    "possWonAtt3rd": "Zone regain count does not independently identify press intensity/success.",
    "possWonDef3rd": "Zone regain count does not independently identify low-block depth.",
    "penAreaEntries": "Provider-labelled; exact entry/deduplication definition uncorroborated.",
    "finalThirdEntries": "Provider-labelled; not interchangeable with final-third passes.",
    "ballRecovery": "Controlled possession change in open play; not every defensive action.",
}


def _file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_payloads(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Use the frozen complete-whole-payload policy, not latest reporting values.

    This coverage audit deliberately has no historical prediction cutoff. It is NOT a feature
    capability and must not be passed into a model. Times are never rewritten.
    """
    common = RetrospectiveBackfillView._common_ctes("")
    rows = con.execute(
        f"""{common}
        SELECT r.season, p.sdp_match_id, p.payload_id, epoch_us(p.fetched_at),
               p.sha256, r.payload, r.byte_count, x.fixture,
               x.corroborated_kickoff, x.corroborated_teams, x.corroborated_score
        FROM selected_payload AS p
        JOIN raw_pl_sdp_payload AS r ON r.payload_id = p.payload_id
        LEFT JOIN stg_pl_sdp_fixture_crosswalk AS x ON x.sdp_match_id = p.sdp_match_id
        ORDER BY r.season, p.sdp_match_id
        """,
        [datetime(2100, 1, 1, tzinfo=UTC)],
    ).fetchall()
    result: list[dict[str, Any]] = []
    for season, match_id, capture, micros, sha, payload, size, fixture, kick, teams, score in rows:
        raw = str(payload).encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != sha or len(raw) != size:
            raise ValueError(f"raw byte/hash mismatch: {capture}")
        if fixture is None or not kick or not teams:
            raise ValueError(f"uncorroborated fixture identity: {season}/{match_id}")
        parsed = parse_team_stats(json.loads(payload), match_id=match_id)
        if len(parsed) != 2 or {side.side for side in parsed} != {"home", "away"}:
            raise ValueError(f"not two reciprocal provider sides: {capture}")
        result.append(
            {
                "season": season,
                "sdp_match_id": match_id,
                "fixture": fixture,
                "capture_id": capture,
                "source_known_at_epoch_us": micros,
                "payload_sha256": sha,
                "byte_count": size,
                "score_corroborated": score,
                "sides": parsed,
            }
        )
    return result


def _counts(values: list[float | None], mirrors: list[float | None]) -> dict[str, Any]:
    if len(values) != len(mirrors) or not values:
        raise ValueError("coverage denominators must be equal and nonempty")
    measured = [value for value in values if value is not None]
    n = len(values)
    both = sum(a is not None and b is not None for a, b in zip(values, mirrors, strict=True))
    zeros = sum(value == 0 for value in measured)
    return {
        "team_sides": n,
        "measured": len(measured),
        "coverage_pct": 100 * len(measured) / n,
        "explicit_zero": zeros,
        "zero_pct_all_sides": 100 * zeros / n,
        "zero_pct_measured": 100 * zeros / len(measured) if measured else None,
        "missing_or_non_numeric": n - len(measured),
        "missing_pct": 100 * (n - len(measured)) / n,
        "opponent_measured": sum(value is not None for value in mirrors),
        "both_sides_measured": both,
        "both_sides_coverage_pct": 100 * both / n,
        "minimum": min(measured) if measured else None,
        "maximum": max(measured) if measured else None,
    }


def eligible_seasons(joint: dict[str, dict[str, Any]], complete: set[str]) -> list[str]:
    """Coverage only: >=95% joint reciprocal availability and an earlier complete season."""
    return [
        season
        for season in sorted(joint)
        if season in complete
        and any(previous < season for previous in complete)
        and joint[season]["joint_both_raw_coverage_pct"] >= 95.0
    ]


def self_check() -> None:
    """Hand-computable null/zero, reciprocal coverage and selection regression checks."""
    counts = _counts([None, 0.0, 3.0], [2.0, None, 0.0])
    assert counts["measured"] == 2
    assert counts["explicit_zero"] == 1
    assert counts["missing_or_non_numeric"] == 1
    assert counts["both_sides_measured"] == 1
    joint = {
        "2021-22": {"joint_both_raw_coverage_pct": 100.0},
        "2022-23": {"joint_both_raw_coverage_pct": 94.99},
        "2023-24": {"joint_both_raw_coverage_pct": 95.0},
        "2024-25": {"joint_both_raw_coverage_pct": 100.0},
    }
    assert eligible_seasons(joint, {"2021-22", "2022-23", "2023-24"}) == ["2023-24"]
    assert eligible_seasons(joint, {"2023-24"}) == []


def build_audit(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Enumerate every retained numeric key, without model scores or zero interpretation."""
    payloads = canonical_payloads(con)
    dictionary = load_sdp_metrics()
    aliases = dictionary.alias_index()
    declarations = dictionary.by_local_field()
    seasons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    names: set[str] = set()
    raw_presence: Counter[str] = Counter()
    raw_nulls: Counter[str] = Counter()
    non_numeric: Counter[str] = Counter()
    manifest = []
    for payload in payloads:
        manifest.append({key: value for key, value in payload.items() if key != "sides"})
        for side in payload["sides"]:
            numeric = {}
            for key, raw_value in side.stats.items():
                raw_presence[key] += 1
                if raw_value is None:
                    raw_nulls[key] += 1
                value, _ = _coerce(raw_value, SdpMetricType.FLOAT)
                if value is not None and math.isfinite(value):
                    numeric[key] = value
                    names.add(key)
                elif raw_value is not None:
                    non_numeric[key] += 1
            seasons[payload["season"]].append(
                {"match_id": payload["sdp_match_id"], "side": side.side, "numeric": numeric}
            )
    fields = []
    for field in sorted(names):
        local = aliases.get(field)
        declaration = declarations.get(local or "")
        verified = bool(
            declaration is not None
            and declaration.verified_semantics
            and hasattr(declaration, "provider_fields")
            and declaration.provider_fields[0] == field
        )
        confidence = (
            "independently_corroborated"
            if verified
            else "provider_labelled_dictionary_definition_conflict"
            if field == "outfielderBlock"
            else "provider_labelled_documented_concept"
            if local
            else "unmapped_unverified"
        )
        per_season = {}
        for season, rows in sorted(seasons.items()):
            by_side = {(row["match_id"], row["side"]): row["numeric"] for row in rows}
            own = [row["numeric"].get(field) for row in rows]
            opponent = [
                by_side[(row["match_id"], "away" if row["side"] == "home" else "home")].get(field)
                for row in rows
            ]
            per_season[season] = _counts(own, opponent)
        fields.append(
            {
                "local_field": local,
                "provider_field": field,
                "semantic_confidence": confidence,
                "verified_semantics_unchanged": verified,
                "description_in_dictionary": declaration.description if declaration else None,
                "declared_opponent_mirror": declaration.mirror if declaration else None,
                "caveat": _CAVEATS.get(field),
                "intended_dimension": [
                    dim for dim, keys in PROPOSED_DIMENSIONS.items() if field in keys
                ],
                "direction": (
                    "opponent value reversed for suppression; own value attack volume"
                    if field == "totalScoringAtt"
                    else "higher is more of the provider-labelled quantity, not inherently better"
                ),
                "seasons_available": [
                    season for season, counts in per_season.items() if counts["measured"] > 0
                ],
                "raw_key_present": raw_presence[field],
                "raw_explicit_null": raw_nulls[field],
                "raw_non_numeric_or_non_finite": non_numeric[field],
                "by_season": per_season,
            }
        )
    joint = {}
    needed = set().union(*PROPOSED_DIMENSIONS.values())
    for season, rows in sorted(seasons.items()):
        by_side = {(row["match_id"], row["side"]): row["numeric"] for row in rows}
        own_ok = []
        paired_ok = []
        for row in rows:
            own = row["numeric"]
            opp = by_side[(row["match_id"], "away" if row["side"] == "home" else "home")]
            valid_own = needed <= own.keys() and own["totalScoringAtt"] > 0 and own["totalPass"] > 0
            valid_opp = needed <= opp.keys() and opp["totalScoringAtt"] > 0 and opp["totalPass"] > 0
            own_ok.append(valid_own)
            paired_ok.append(valid_own and valid_opp)
        joint[season] = {
            "team_sides": len(rows),
            "joint_own_raw_measured": sum(own_ok),
            "joint_own_raw_coverage_pct": 100 * sum(own_ok) / len(rows),
            "joint_both_raw_measured": sum(paired_ok),
            "joint_both_raw_coverage_pct": 100 * sum(paired_ok) / len(rows),
        }
    archive_counts = dict(
        con.execute(
            """SELECT season, count(*) FROM mart_fact_team_match_stats_v2
            WHERE provider='fpl_archive' AND goals IS NOT NULL AND goals_allowed IS NOT NULL
            AND gw IS NOT NULL GROUP BY season ORDER BY season"""
        ).fetchall()
    )
    complete = {season for season, count in archive_counts.items() if count == 760}
    selected = eligible_seasons(joint, complete)
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": 1,
        "evidence_class": "retrospective_backfill_development",
        "purpose": "coverage_only_pre_model_audit_no_goal_model_fitting_or_scoring",
        "version_selection_policy": VERSION_SELECTION_POLICY,
        "canonical_match_captures": len(payloads),
        "canonical_team_sides": sum(len(rows) for rows in seasons.values()),
        "provider_numeric_field_count": len(names),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "capture_manifest": manifest,
        "coverage_denominator": "captured reciprocal team sides; not all scheduled fixtures",
        "metric_fields": fields,
        "non_numeric_only_fields": sorted(raw_presence.keys() - names),
        "proposed_dimensions": {key: list(value) for key, value in PROPOSED_DIMENSIONS.items()},
        "joint_proposed_raw_coverage": joint,
        "season_eligibility_decision": {
            "rule": "joint_both_raw_coverage_pct >=95; complete760side historical PL season; "
            "at least one earlier complete season for warmup",
            "selected_seasons": selected,
            "archive_completed_target_rows": archive_counts,
            "outer_prediction_team_sides": sum(archive_counts[season] for season in selected),
            "score_population": "all archive sides in eligible seasons, including missing target "
            "tactical stats; no target-stat-based scored-row exclusion",
            "training_population": "prior event-time eligible measured historical observations; "
            "outer-ineligible seasons may supply training/warmup",
        },
        "source_definitions": [OPTA_DEFINITIONS, PL_CLARIFICATION],
        "missing_policy": "missing/null/non-numeric never filled with zero or a mean",
    }


def main() -> None:
    self_check()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"audit output is write-once: {args.output}")
    before = _file_sha(args.db)
    with connect(args.db, read_only=True) as con:
        report = build_audit(con)
    if _file_sha(args.db) != before:
        raise RuntimeError("read-only audit database hash changed")
    report["provenance"] = {
        "database_path": str(args.db.resolve()),
        "database_sha256": before,
        "database_unchanged": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root(), text=True
        ).strip(),
        "audit_source_sha256": _file_sha(Path(__file__)),
        "dictionary_sha256": _file_sha(repo_root() / "config/pl_sdp_metrics.yaml"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "canonical_match_captures",
                    "canonical_team_sides",
                    "provider_numeric_field_count",
                    "joint_proposed_raw_coverage",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
