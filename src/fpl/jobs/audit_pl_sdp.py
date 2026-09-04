"""Premier League SDP audit: identity, coverage, and reconciliation. Coverage-first.

    python -m fpl.jobs.audit_pl_sdp                 # audit what is already captured
    python -m fpl.jobs.audit_pl_sdp --stage         # restage from raw first
    python -m fpl.jobs.audit_pl_sdp --probe         # discover provider season ids (network)

Writes three reports under `results/`:

    pl_sdp_identity_audit.json     is pulse_id the SDP matchId? MEASURED, not assumed.
    pl_sdp_coverage.json           per metric, per season: what exists and from when.
    pl_sdp_reconciliation.json     SDP values against the FPL-derived values of the same thing.

The order is deliberate and is the rule the V2 roadmap calls coverage-first: no model may be
fitted on a metric before this job has said how far back it exists and how it compares with
what this repository already had. A metric absent from a season is reported absent -- it is
never zero-filled, because a zero is a measurement claim.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fpl.config import load_sdp_metrics, load_sources, repo_root
from fpl.ingest.fpl_api import EgressBlockedError
from fpl.ingest.pl_sdp import PlSdpClient, extract_items, parse_match_summary
from fpl.storage.db import connect, initialise, table_exists
from fpl.transform import pl_sdp as sdp_transform

logger = logging.getLogger("fpl.audit_pl_sdp")

RESULTS_DIR = "results"
IDENTITY_REPORT = "pl_sdp_identity_audit.json"
COVERAGE_REPORT = "pl_sdp_coverage.json"
RECONCILIATION_REPORT = "pl_sdp_reconciliation.json"


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False: a NaN in a coverage report would serialise as invalid JSON that most
    # parsers silently accept, and an unreadable number must fail here rather than downstream.
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------------------


def build_coverage(con: Any) -> dict[str, Any]:
    """Per metric, per season: how much of it exists, and over what range.

    Runs over `mart_fact_team_match_stats_v2` so it covers every provider on one grain, which
    is what makes "SDP has no xGOT before season X" and "the archive never had it at all"
    distinguishable statements rather than one undifferentiated gap.
    """
    dictionary = load_sdp_metrics()
    generated_at = datetime.now(UTC)
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at,
        "metric_dictionary_version": dictionary.schema_version,
        "note": (
            "coverage_pct is over team-rows present in mart_fact_team_match_stats_v2 for that "
            "provider and season. An absent metric is reported absent and is never zero-filled."
        ),
        "providers": {},
    }
    if not table_exists(con, "mart_fact_team_match_stats_v2"):
        report["providers"] = {}
        report["warning"] = "mart_fact_team_match_stats_v2 does not exist; nothing to report"
        return report

    populations = con.execute(
        """
        SELECT provider, season,
               count(*) AS team_rows,
               count(DISTINCT fixture) AS fixtures,
               min(kickoff_time) AS first_kickoff,
               max(kickoff_time) AS last_kickoff
        FROM mart_fact_team_match_stats_v2
        GROUP BY provider, season ORDER BY provider, season
        """
    ).fetchall()
    if not populations:
        return report

    expected = {
        (str(season),): (int(rows), int(fixtures))
        for season, rows, fixtures in con.execute(
            """
            SELECT season, count(*), count(DISTINCT fixture)
            FROM mart_fact_team_match GROUP BY season
            """
        ).fetchall()
    }

    fields = [metric.local_field for metric in dictionary.all_fields()]
    mirrors = list(dictionary.mirror_fields().values())
    columns = [*fields, *mirrors]
    for provider, season, team_rows, fixtures, first_kickoff, last_kickoff in populations:
        provider_block = report["providers"].setdefault(str(provider), {})
        expected_rows, expected_fixtures = expected.get((str(season),), (0, 0))
        season_block: dict[str, Any] = {
            "team_rows_available": int(team_rows),
            "team_rows_expected": expected_rows,
            "fixtures_available": int(fixtures),
            "fixtures_expected": expected_fixtures,
            "first_kickoff": first_kickoff,
            "last_kickoff": last_kickoff,
            "metrics": {},
        }
        selects = ", ".join(
            f'count("{column}") AS n_{index}, min("{column}") AS lo_{index}, '
            f'max("{column}") AS hi_{index}, avg("{column}") AS mu_{index}'
            for index, column in enumerate(columns)
        )
        row = con.execute(
            f"""
            SELECT {selects} FROM mart_fact_team_match_stats_v2
            WHERE provider = ? AND season = ?
            """,
            [provider, season],
        ).fetchone()
        assert row is not None
        declared = dictionary.by_local_field()
        for index, column in enumerate(columns):
            non_null, low, high, average = row[index * 4 : index * 4 + 4]
            metric = declared.get(column)
            season_block["metrics"][column] = {
                "non_null": int(non_null),
                "coverage_pct": (
                    round(100.0 * int(non_null) / int(team_rows), 4) if team_rows else 0.0
                ),
                "min": low,
                "max": high,
                "mean": round(float(average), 6) if average is not None else None,
                "group": metric.group if metric is not None else "mirror",
                "verified_semantics": (metric.verified_semantics if metric is not None else False),
                "definition": (
                    metric.description if metric is not None else "opponent mirror of a metric"
                ),
            }
        provider_block[str(season)] = season_block
    return report


# --------------------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------------------


def build_reconciliation(con: Any) -> dict[str, Any]:
    """SDP values against the FPL-derived values of the same quantity, on identical rows.

    Differences are REPORTED, never repaired. Where two providers measure the same concept by
    different routes -- SDP's xG against the sum of FPL's per-player xG, SDP's shots on target
    allowed against the goalkeeper saves-plus-conceded proxy -- disagreement is information
    about the sources, and forcing them to agree would destroy it.
    """
    generated_at = datetime.now(UTC)
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at,
        "note": "differences are reported, never reconciled away; both values are retained",
        "comparisons": [],
        "crosswalk": {},
    }
    if not table_exists(con, "mart_fact_team_match_stats_v2"):
        report["warning"] = "mart_fact_team_match_stats_v2 does not exist"
        return report

    # (label, sdp column, archive column) triples measuring the same concept two ways.
    pairs = [
        ("expected_goals", "expected_goals", "expected_goals"),
        ("goals", "goals", "goals"),
        (
            "shots_on_target_allowed_vs_gk_proxy",
            "shots_on_target_allowed",
            "shots_on_target_allowed_proxy",
        ),
        (
            "expected_goals_allowed_vs_measured_xgc",
            "expected_goals_allowed",
            "expected_goals_conceded_measured",
        ),
    ]
    for label, sdp_column, archive_column in pairs:
        row = con.execute(
            f"""
            SELECT count(*) AS rows_compared,
                   avg(s."{sdp_column}") AS sdp_mean,
                   avg(a."{archive_column}") AS archive_mean,
                   avg(s."{sdp_column}" - a."{archive_column}") AS mean_difference,
                   max(abs(s."{sdp_column}" - a."{archive_column}")) AS max_absolute_difference,
                   sum(CASE WHEN s."{sdp_column}" = a."{archive_column}" THEN 1 ELSE 0 END)
                       AS exact_agreements
            FROM mart_fact_team_match_stats_v2 AS s
            JOIN mart_fact_team_match_stats_v2 AS a
              ON a.season = s.season AND a.fixture = s.fixture AND a.team_id = s.team_id
             AND a.provider = ?
            WHERE s.provider = ? AND s."{sdp_column}" IS NOT NULL
              AND a."{archive_column}" IS NOT NULL
            """,
            [sdp_transform.ARCHIVE_PROVIDER, sdp_transform.PROVIDER],
        ).fetchone()
        assert row is not None
        report["comparisons"].append(
            {
                "label": label,
                "sdp_column": sdp_column,
                "archive_column": archive_column,
                "rows_compared": int(row[0]),
                "sdp_mean": None if row[1] is None else round(float(row[1]), 6),
                "archive_mean": None if row[2] is None else round(float(row[2]), 6),
                "mean_difference": None if row[3] is None else round(float(row[3]), 6),
                "max_absolute_difference": None if row[4] is None else round(float(row[4]), 6),
                "exact_agreements": int(row[5] or 0),
            }
        )

    if table_exists(con, "stg_pl_sdp_fixture_crosswalk"):
        rows = con.execute(
            """
            SELECT match_method, count(*),
                   sum(CASE WHEN corroborated_kickoff THEN 1 ELSE 0 END),
                   sum(CASE WHEN corroborated_teams THEN 1 ELSE 0 END),
                   sum(CASE WHEN corroborated_score THEN 1 ELSE 0 END)
            FROM stg_pl_sdp_fixture_crosswalk GROUP BY match_method
            """
        ).fetchall()
        report["crosswalk"] = {
            str(method): {
                "fixtures": int(count),
                "kickoff_corroborated": int(kickoff or 0),
                "teams_corroborated": int(teams or 0),
                "score_corroborated": int(score or 0),
            }
            for method, count, kickoff, teams, score in rows
        }
    return report


# --------------------------------------------------------------------------------------
# Season-id probe (the one mode that needs the network)
# --------------------------------------------------------------------------------------


def probe_season_ids(
    *, client: PlSdpClient | None = None, candidates: list[int] | None = None
) -> dict[str, Any]:
    """Discover which provider season id corresponds to which season label.

    The mapping is not documented anywhere and this repository refuses to guess it, so the
    provider is asked. Two routes are tried in order: the configured `seasons` endpoint, and
    -- if that is absent or unrecognisable -- probing candidate ids and inferring the label
    from the earliest kickoff a season's matches carry. A season starting in August of year Y
    is labelled `Y-(Y+1)`, which is the FPL archive's own convention.
    """
    sources = load_sources()
    if sources.pl_sdp is None:
        raise RuntimeError("config/sources.yaml carries no `pl_sdp` block")
    owned = client is None
    sdp = client or PlSdpClient(config=sources.pl_sdp)
    discovered: dict[str, int] = {}
    notes: list[str] = []
    try:
        try:
            raw = sdp.fetch_seasons()
            for record in extract_items(raw.payload):
                if not isinstance(record, dict):
                    continue
                identifier = record.get("id") or record.get("seasonId")
                label = record.get("label") or record.get("name") or record.get("season")
                if isinstance(identifier, int) and isinstance(label, str):
                    discovered[_normalise_season_label(label)] = identifier
            notes.append(f"seasons endpoint returned {len(discovered)} labelled season(s)")
        except Exception as error:
            notes.append(f"seasons endpoint unusable ({error}); falling back to id probing")

        if not discovered:
            pool = candidates or list(
                range(
                    sources.pl_sdp.probe_season_id_minimum,
                    sources.pl_sdp.probe_season_id_maximum + 1,
                )
            )
            for season_id in pool:
                try:
                    raw = sdp.fetch_matches_page(season_id=season_id, page=0)
                    summaries = [
                        parse_match_summary(record) for record in extract_items(raw.payload)
                    ]
                except Exception:
                    continue
                kickoffs = [s.kickoff for s in summaries if s.kickoff is not None]
                if not kickoffs:
                    continue
                first = min(kickoffs)
                start_year = first.year if first.month >= 7 else first.year - 1
                discovered[f"{start_year}-{str(start_year + 1)[2:]}"] = season_id
    finally:
        if owned:
            sdp.close()
    return {"season_ids": dict(sorted(discovered.items())), "notes": notes}


def _normalise_season_label(label: str) -> str:
    """Provider season labels to this repository's `YYYY-YY` convention."""
    text = label.strip().replace("/", "-").replace(" ", "")
    parts = text.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        start = int(parts[0])
        end = parts[1] if len(parts[1]) == 2 else str(int(parts[1]))[2:]
        return f"{start}-{end.zfill(2)}"
    return text


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Premier League SDP data.")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--stage", action="store_true", help="restage from raw before auditing")
    parser.add_argument("--probe", action="store_true", help="discover season ids (needs network)")
    parser.add_argument(
        "--allow-identity-failures",
        action="store_true",
        help="record ambiguities/contradictions instead of failing closed",
    )
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    results = args.results or repo_root() / RESULTS_DIR

    if args.probe:
        try:
            discovered = probe_season_ids()
        except EgressBlockedError as error:
            logger.error("%s", error)
            logger.error("run --probe where premierleague.com is reachable")
            return 3
        logger.info("discovered %d season id(s)", len(discovered["season_ids"]))
        print(json.dumps(discovered, indent=2, sort_keys=True))
        print(
            "\n# paste under `pl_sdp:` in config/sources.yaml\n  season_ids:\n"
            + "\n".join(
                f'    "{label}": {value}' for label, value in discovered["season_ids"].items()
            )
        )
        return 0

    con = initialise(args.db) if args.stage else connect(args.db, read_only=True)
    try:
        identity: dict[str, Any]
        if args.stage:
            sources = load_sources()
            labels = (
                {value: key for key, value in sources.pl_sdp.season_ids.items()}
                if sources.pl_sdp
                else {}
            )
            match_report = sdp_transform.stage_matches(con, season_labels=labels)
            stats_report = sdp_transform.stage_team_stats(con)
            logger.info(
                "staged %d match row(s), %d team side(s), %d metric row(s)",
                match_report.matches_staged,
                stats_report.team_sides_staged,
                stats_report.metric_rows_staged,
            )
            for failure in (*match_report.schema_failures, *stats_report.schema_failures):
                logger.warning("staging: %s", failure)
            audit = sdp_transform.resolve_crosswalk(
                con,
                team_name_codes=sdp_transform.team_name_code_map(con),
                strict=not args.allow_identity_failures,
            )
            identity = {
                "schema_version": 1,
                "generated_at": datetime.now(UTC),
                "fpl_fixtures": audit.fpl_fixtures,
                "sdp_matches": audit.sdp_matches,
                "matched_by_pulse_id": audit.matched_by_pulse_id,
                "matched_by_identity_fallback": audit.matched_by_identity_fallback,
                "unmatched_fpl_fixtures": audit.unmatched_fpl_fixtures,
                "unmatched_sdp_matches": audit.unmatched_sdp_matches,
                "pulse_id_present": audit.pulse_id_present,
                "pulse_id_exact_matches": audit.pulse_id_exact_matches,
                "pulse_id_match_rate": audit.pulse_id_match_rate,
                "kickoff_corroborated": audit.kickoff_corroborated,
                "teams_corroborated": audit.teams_corroborated,
                "score_corroborated": audit.score_corroborated,
                "ambiguities": audit.ambiguities,
                "contradictions": audit.contradictions,
                "by_season": audit.by_season,
                "unmapped_provider_fields": list(stats_report.unmapped_provider_fields),
            }
        else:
            identity = {
                "schema_version": 1,
                "generated_at": datetime.now(UTC),
                "note": "run with --stage to recompute identity from raw payloads",
            }
        _write(results / IDENTITY_REPORT, identity)
        _write(results / COVERAGE_REPORT, build_coverage(con))
        _write(results / RECONCILIATION_REPORT, build_reconciliation(con))
    finally:
        con.close()
    logger.info("wrote %s, %s, %s", IDENTITY_REPORT, COVERAGE_REPORT, RECONCILIATION_REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
