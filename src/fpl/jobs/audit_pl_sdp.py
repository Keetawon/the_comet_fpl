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
from fpl.ingest.fpl_api import ApiResponseError, EgressBlockedError
from fpl.ingest.pl_sdp import PlSdpClient, SdpSchemaError, extract_items, parse_match_summary
from fpl.storage.db import connect, initialise, table_exists
from fpl.transform import football_v2
from fpl.transform import pl_sdp as sdp_transform

logger = logging.getLogger("fpl.audit_pl_sdp")

RESULTS_DIR = "results"
IDENTITY_REPORT = "pl_sdp_identity_audit.json"
COVERAGE_REPORT = "pl_sdp_coverage.json"
RECONCILIATION_REPORT = "pl_sdp_reconciliation.json"
METRIC_INVENTORY_REPORT = "pl_sdp_metric_inventory.json"


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

    expected_fixtures_by_season: dict[str, int] = {}
    for fixture in sdp_transform._fixture_identities(con, None):
        expected_fixtures_by_season[fixture.season] = (
            expected_fixtures_by_season.get(fixture.season, 0) + 1
        )

    fields = [metric.local_field for metric in dictionary.all_fields()]
    mirrors = list(dictionary.mirror_fields().values())
    columns = [*fields, *mirrors]
    for provider, season, team_rows, fixtures, first_kickoff, last_kickoff in populations:
        provider_block = report["providers"].setdefault(str(provider), {})
        expected_fixtures = expected_fixtures_by_season.get(str(season), 0)
        expected_rows = 2 * expected_fixtures
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
            f'max("{column}") AS hi_{index}, avg("{column}") AS mu_{index}, '
            f'min(CASE WHEN "{column}" IS NOT NULL THEN kickoff_time END) AS first_{index}, '
            f'max(CASE WHEN "{column}" IS NOT NULL THEN kickoff_time END) AS last_{index}'
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
            non_null, low, high, average, first_measured, last_measured = row[
                index * 6 : index * 6 + 6
            ]
            metric = declared.get(column)
            season_block["metrics"][column] = {
                "non_null": int(non_null),
                "coverage_pct": (
                    round(100.0 * int(non_null) / int(team_rows), 4) if team_rows else 0.0
                ),
                "coverage_pct_expected": (
                    round(100.0 * int(non_null) / expected_rows, 4) if expected_rows else None
                ),
                "min": low,
                "max": high,
                "mean": round(float(average), 6) if average is not None else None,
                "first_measured_kickoff": first_measured,
                "last_measured_kickoff": last_measured,
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


def _quantile(values: list[float], probability: float) -> float:
    """Linear-interpolated quantile for the small audit populations."""
    if not values:
        raise ValueError("a quantile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _difference_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "rows": 0,
            "mean": None,
            "mean_absolute": None,
            "quantiles": {},
        }
    quantiles = {
        label: round(float(_quantile(values, probability)), 6)
        for label, probability in (
            ("p00", 0.0),
            ("p10", 0.1),
            ("p25", 0.25),
            ("p50", 0.5),
            ("p75", 0.75),
            ("p90", 0.9),
            ("p100", 1.0),
        )
    }
    return {
        "rows": len(values),
        "mean": round(sum(values) / len(values), 6),
        "mean_absolute": round(sum(abs(value) for value in values) / len(values), 6),
        "quantiles": quantiles,
    }


def _score_reconciliation(con: Any) -> dict[str, Any]:
    if not (
        table_exists(con, "stg_pl_sdp_fixture_crosswalk") and table_exists(con, "stg_pl_sdp_match")
    ):
        return {"rows_compared": 0, "note": "required identity tables are unavailable"}
    provider_rows = con.execute(
        """
        WITH latest_match AS (
            SELECT * EXCLUDE (ordinal)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY sdp_match_id ORDER BY known_at DESC, payload_id DESC
                ) AS ordinal
                FROM stg_pl_sdp_match
            )
            WHERE ordinal = 1
        )
        SELECT c.season, c.fixture, c.sdp_match_id, m.home_score, m.away_score
        FROM stg_pl_sdp_fixture_crosswalk AS c
        JOIN latest_match AS m ON m.sdp_match_id = c.sdp_match_id
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY c.season, c.fixture
        """
    ).fetchall()
    fixtures = {
        (fixture.season, fixture.fixture): fixture
        for fixture in sdp_transform._fixture_identities(con, None)
    }
    rows = [
        (*row, fixture.home_score, fixture.away_score)
        for row in provider_rows
        if (fixture := fixtures.get((str(row[0]), int(row[1])))) is not None
        and fixture.home_score is not None
        and fixture.away_score is not None
    ]
    mismatches = [
        {
            "season": str(season),
            "fixture": int(fixture),
            "sdp_match_id": int(match_id),
            "sdp_score": f"{int(sdp_home)}-{int(sdp_away)}",
            "fpl_score": f"{int(fpl_home)}-{int(fpl_away)}",
        }
        for season, fixture, match_id, sdp_home, sdp_away, fpl_home, fpl_away in rows
        if (sdp_home, sdp_away) != (fpl_home, fpl_away)
    ]
    home_differences = [float(row[3] - row[5]) for row in rows]
    away_differences = [float(row[4] - row[6]) for row in rows]
    return {
        "rows_compared": len(rows),
        "exact_agreements": len(rows) - len(mismatches),
        "match_rate": None if not rows else (len(rows) - len(mismatches)) / len(rows),
        "home_goal_difference": _difference_summary(home_differences),
        "away_goal_difference": _difference_summary(away_differences),
        "exceptions": mismatches,
    }


def build_reconciliation(con: Any) -> dict[str, Any]:
    """SDP values against the FPL-derived values of the same quantity, on identical rows.

    Differences are REPORTED, never repaired. Where two providers measure the same concept by
    different routes -- SDP's xG against the sum of FPL's per-player xG, SDP's shots on target
    allowed against the goalkeeper saves-plus-conceded proxy -- disagreement is information
    about the sources, and forcing them to agree would destroy it.
    """
    generated_at = datetime.now(UTC)
    report: dict[str, Any] = {
        "schema_version": 2,
        "generated_at": generated_at,
        "note": "differences are reported, never reconciled away; both values are retained",
        "score": _score_reconciliation(con),
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
        rows = con.execute(
            f"""
            SELECT s.season, s.fixture, s.team_id,
                   s."{sdp_column}", a."{archive_column}",
                   s."{sdp_column}" - a."{archive_column}" AS difference
            FROM mart_fact_team_match_stats_v2 AS s
            JOIN mart_fact_team_match_stats_v2 AS a
              ON a.season = s.season AND a.fixture = s.fixture AND a.team_id = s.team_id
             AND a.provider = ?
            WHERE s.provider = ? AND s."{sdp_column}" IS NOT NULL
              AND a."{archive_column}" IS NOT NULL
            ORDER BY s.season, s.fixture, s.team_id
            """,
            [sdp_transform.ARCHIVE_PROVIDER, sdp_transform.PROVIDER],
        ).fetchall()
        differences = [float(row[5]) for row in rows]
        by_season: dict[str, list[float]] = {}
        for row in rows:
            by_season.setdefault(str(row[0]), []).append(float(row[5]))
        notable = sorted(rows, key=lambda row: abs(float(row[5])), reverse=True)[:10]
        report["comparisons"].append(
            {
                "label": label,
                "sdp_column": sdp_column,
                "archive_column": archive_column,
                "rows_compared": len(rows),
                "sdp_mean": (
                    None if not rows else round(sum(float(row[3]) for row in rows) / len(rows), 6)
                ),
                "archive_mean": (
                    None if not rows else round(sum(float(row[4]) for row in rows) / len(rows), 6)
                ),
                "exact_agreements": sum(row[3] == row[4] for row in rows),
                "difference": _difference_summary(differences),
                "by_season": {
                    season: _difference_summary(season_values)
                    for season, season_values in sorted(by_season.items())
                },
                "largest_absolute_differences": [
                    {
                        "season": str(row[0]),
                        "fixture": int(row[1]),
                        "team_id": int(row[2]),
                        "sdp_value": float(row[3]),
                        "archive_value": float(row[4]),
                        "difference": float(row[5]),
                    }
                    for row in notable
                ],
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
# Provider-field inventory
# --------------------------------------------------------------------------------------


def build_metric_inventory(con: Any) -> dict[str, Any]:
    """Enumerate every latest provider field, including unmapped numeric fields."""
    dictionary = load_sdp_metrics()
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC),
        "metric_dictionary_version": dictionary.schema_version,
        "note": (
            "Observed field names and values are provider evidence. A mapping's semantic "
            "verification remains controlled by config/pl_sdp_metrics.yaml."
        ),
        "provider_fields": [],
        "unmapped_numeric_fields": [],
    }
    if not table_exists(con, "stg_pl_sdp_team_match_metric"):
        report["warning"] = "stg_pl_sdp_team_match_metric does not exist"
        return report
    rows = con.execute(
        """
        WITH latest_stats AS (
            SELECT * EXCLUDE (ordinal)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY sdp_match_id, side
                    ORDER BY known_at DESC, payload_id DESC
                ) AS ordinal
                FROM stg_pl_sdp_team_match_stats
            )
            WHERE ordinal = 1
        ), latest AS (
            SELECT m.*, s.known_at
            FROM stg_pl_sdp_team_match_metric AS m
            JOIN latest_stats AS s
              ON s.sdp_match_id = m.sdp_match_id AND s.side = m.side
             AND s.payload_id = m.payload_id
        )
        SELECT provider_field, min(local_field) AS local_field,
               count(*) AS team_sides, count(DISTINCT sdp_match_id) AS matches,
               count(value_numeric) AS numeric_values, count(value_text) AS text_values,
               first(value_numeric ORDER BY known_at DESC)
                   FILTER (WHERE value_numeric IS NOT NULL) AS example_numeric,
               first(value_text ORDER BY known_at DESC)
                   FILTER (WHERE value_text IS NOT NULL) AS example_text
        FROM latest
        GROUP BY provider_field
        ORDER BY provider_field
        """
    ).fetchall()
    declared = dictionary.by_local_field()
    fields: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for (
        provider_field,
        local_field,
        team_sides,
        matches,
        numeric_values,
        text_values,
        example_numeric,
        example_text,
    ) in rows:
        metric = declared.get(str(local_field)) if local_field is not None else None
        example_value = example_numeric if example_numeric is not None else example_text
        field = {
            "provider_field": str(provider_field),
            "example_value": example_value,
            "mapped_local_field": None if local_field is None else str(local_field),
            "verified_semantics": metric.verified_semantics if metric is not None else False,
            "reason": metric.description if metric is not None else "no local mapping declared",
            "evidence": (
                f"observed on {int(team_sides)} latest team-side rows across "
                f"{int(matches)} match(es)"
            ),
            "notes": (
                "semantic meaning verified under the metric dictionary contract"
                if metric is not None and metric.verified_semantics
                else "field existence is verified; semantic meaning remains unverified"
            ),
            "numeric_values": int(numeric_values),
            "text_values": int(text_values),
        }
        fields.append(field)
        if local_field is None and int(numeric_values) > 0:
            unmapped.append(
                {
                    "provider_field": str(provider_field),
                    "example_value": example_numeric,
                    "numeric_values": int(numeric_values),
                    "matches": int(matches),
                }
            )
    report["provider_fields"] = fields
    report["unmapped_numeric_fields"] = unmapped
    report["summary"] = {
        "provider_fields": len(fields),
        "mapped_fields": sum(field["mapped_local_field"] is not None for field in fields),
        "unmapped_numeric_fields": len(unmapped),
    }
    return report


def build_identity_details(con: Any) -> dict[str, Any]:
    """Concrete unmatched and agreement rows to accompany aggregate identity counts."""
    if not (
        table_exists(con, "stg_fixture")
        and table_exists(con, "stg_pl_sdp_match")
        and table_exists(con, "stg_pl_sdp_fixture_crosswalk")
    ):
        return {}
    resolved = con.execute(
        """
        SELECT count(*),
               sum(CASE WHEN match_method = ? THEN 1 ELSE 0 END),
               sum(CASE WHEN corroborated_kickoff IS TRUE THEN 1 ELSE 0 END),
               sum(CASE WHEN corroborated_teams IS TRUE THEN 1 ELSE 0 END),
               sum(CASE WHEN corroborated_score IS TRUE THEN 1 ELSE 0 END)
        FROM stg_pl_sdp_fixture_crosswalk
        """,
        [sdp_transform.MATCH_METHOD_PULSE_ID],
    ).fetchone()
    assert resolved is not None
    resolved_keys = {
        (str(season), int(fixture))
        for season, fixture in con.execute(
            "SELECT season, fixture FROM stg_pl_sdp_fixture_crosswalk"
        ).fetchall()
    }
    unmatched_fpl = [
        fixture
        for fixture in sdp_transform._fixture_identities(con, None)
        if (fixture.season, fixture.fixture) not in resolved_keys
    ]
    unmatched_sdp = con.execute(
        """
        WITH latest AS (
            SELECT * EXCLUDE (ordinal)
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY sdp_match_id ORDER BY known_at DESC, payload_id DESC
                ) AS ordinal
                FROM stg_pl_sdp_match
            )
            WHERE ordinal = 1
        )
        SELECT m.season, m.sdp_match_id, m.kickoff_time,
               m.home_team_name, m.away_team_name, m.home_score, m.away_score
        FROM latest AS m
        LEFT JOIN stg_pl_sdp_fixture_crosswalk AS c ON c.sdp_match_id = m.sdp_match_id
        WHERE c.sdp_match_id IS NULL
        ORDER BY m.season, m.sdp_match_id
        """
    ).fetchall()
    duplicates = con.execute(
        """
        SELECT sdp_match_id, count(*)
        FROM stg_pl_sdp_fixture_crosswalk
        GROUP BY sdp_match_id HAVING count(*) > 1
        ORDER BY sdp_match_id
        """
    ).fetchall()
    return {
        "resolved_fixtures": int(resolved[0]),
        "valid_pulse_id_resolutions": int(resolved[1] or 0),
        "kickoff_agreements": int(resolved[2] or 0),
        "home_away_agreements": int(resolved[3] or 0),
        "score_agreements": int(resolved[4] or 0),
        "duplicate_sdp_claims": [
            {"sdp_match_id": int(match_id), "claims": int(count)} for match_id, count in duplicates
        ],
        "unmatched_fpl": [
            {
                "season": fixture.season,
                "fixture": fixture.fixture,
                "pulse_id": fixture.pulse_id,
                "kickoff": fixture.kickoff_time,
            }
            for fixture in unmatched_fpl
        ],
        "unmatched_sdp": [
            {
                "season": str(season),
                "sdp_match_id": int(match_id),
                "kickoff": kickoff,
                "home": home,
                "away": away,
                "score": (
                    None
                    if home_score is None or away_score is None
                    else f"{int(home_score)}-{int(away_score)}"
                ),
            }
            for season, match_id, kickoff, home, away, home_score, away_score in unmatched_sdp
        ],
    }


# --------------------------------------------------------------------------------------
# Season-id probe (the one mode that needs the network)
# --------------------------------------------------------------------------------------


def probe_season_ids(
    *, client: PlSdpClient | None = None, candidates: list[int] | None = None
) -> dict[str, Any]:
    """Discover which provider season id corresponds to which season label.

    The mapping is not documented anywhere and this repository refuses to guess it, so the
    provider is asked. The configured `seasons` route is tried first. If the provider disables
    that route, only explicitly supplied or already configured ids are verified against real
    Premier League match identities. The broad configured numeric range is deliberately never
    swept: a blocked/disabled route must not become hundreds of guessed requests.
    """
    sources = load_sources()
    if sources.pl_sdp is None:
        raise RuntimeError("config/sources.yaml carries no `pl_sdp` block")
    owned = client is None
    sdp = client or PlSdpClient(config=sources.pl_sdp)
    discovered: dict[str, int] = {}
    notes: list[str] = []
    try:
        seasons_error: Exception | None = None
        try:
            raw = sdp.fetch_seasons()
            for record in extract_items(raw.payload):
                if not isinstance(record, dict):
                    continue
                identifier = record.get("id") or record.get("seasonId")
                label = record.get("label") or record.get("name") or record.get("season")
                if isinstance(identifier, bool) or not isinstance(identifier, (int, str)):
                    continue
                try:
                    numeric_identifier = int(identifier)
                except (TypeError, ValueError):
                    continue
                if isinstance(label, str):
                    discovered[_normalise_season_label(label)] = numeric_identifier
            notes.append(f"seasons endpoint returned {len(discovered)} labelled season(s)")
        except EgressBlockedError:
            raise
        except (ApiResponseError, SdpSchemaError) as error:
            seasons_error = error
            notes.append(f"seasons endpoint unusable ({error})")

        if not discovered:
            configured = sorted(set(sources.pl_sdp.season_ids.values()))
            pool = sorted(set(candidates if candidates is not None else configured))
            if not pool:
                raise ApiResponseError(
                    "seasons endpoint returned no usable catalogue and no explicit/configured "
                    "season ids are available; refusing to scan the numeric id range"
                ) from seasons_error
            configured_labels = {
                identifier: label for label, identifier in sources.pl_sdp.season_ids.items()
            }
            for season_id in pool:
                raw = sdp.fetch_matches_page(season_id=season_id, page=0)
                records = extract_items(raw.payload)
                summaries = [parse_match_summary(record) for record in records]
                kickoffs = [s.kickoff for s in summaries if s.kickoff is not None]
                if not kickoffs:
                    raise ApiResponseError(
                        f"provider season id {season_id} returned no match kickoff to verify"
                    )
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    competition_id = record.get("competitionId")
                    competition_name = record.get("competition")
                    if competition_id is not None and str(competition_id) != str(
                        sources.pl_sdp.competition
                    ):
                        raise ApiResponseError(
                            f"provider season id {season_id} returned competitionId "
                            f"{competition_id!r}, expected {sources.pl_sdp.competition}"
                        )
                    if competition_name is not None and str(competition_name) != "Premier League":
                        raise ApiResponseError(
                            f"provider season id {season_id} returned competition "
                            f"{competition_name!r}, expected 'Premier League'"
                        )
                    reported_season = record.get("season")
                    if reported_season is not None and str(reported_season) != str(season_id):
                        raise ApiResponseError(
                            f"provider query season {season_id} returned season {reported_season!r}"
                        )
                first = min(kickoffs)
                start_year = first.year if first.month >= 7 else first.year - 1
                inferred_label = f"{start_year}-{str(start_year + 1)[2:]}"
                configured_label = configured_labels.get(season_id)
                if configured_label is not None and configured_label != inferred_label:
                    raise ApiResponseError(
                        f"configured {configured_label} -> {season_id}, but the provider's "
                        f"earliest returned kickoff implies {inferred_label}"
                    )
                if inferred_label in discovered and discovered[inferred_label] != season_id:
                    raise ApiResponseError(
                        f"provider ids {discovered[inferred_label]} and {season_id} both imply "
                        f"season label {inferred_label}; refusing an ambiguous mapping"
                    )
                discovered[inferred_label] = season_id
                sample = summaries[0]
                notes.append(
                    f"verified {inferred_label} -> {season_id} from Premier League match "
                    f"{sample.match_id} at {sample.kickoff}"
                )
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
        "--probe-season-id",
        action="append",
        type=int,
        default=None,
        help=(
            "explicit provider season id to verify when its catalogue route is disabled; "
            "repeatable, and never expanded into a numeric sweep"
        ),
    )
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
            discovered = probe_season_ids(candidates=args.probe_season_id)
        except EgressBlockedError as error:
            logger.error("%s", error)
            logger.error("run --probe where premierleague.com is reachable")
            return 3
        except (ApiResponseError, SdpSchemaError) as error:
            logger.error("provider season discovery failed: %s", error)
            return 4
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
            con.execute("BEGIN TRANSACTION")
            try:
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
                football_counts = football_v2.build_all(con)
            except Exception:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")
            logger.info(
                "rebuilt V2 marts: %d team-match row(s), %d tactical row(s), providers=%s",
                football_counts.team_match_stats_rows,
                football_counts.tactical_form_rows,
                ",".join(football_counts.providers),
            )
            identity = {
                "schema_version": 2,
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
                "valid_pulse_id_match_rate": (
                    None
                    if audit.pulse_id_present == 0
                    else audit.matched_by_pulse_id / audit.pulse_id_present
                ),
                "kickoff_corroborated": audit.kickoff_corroborated,
                "teams_corroborated": audit.teams_corroborated,
                "score_corroborated": audit.score_corroborated,
                "ambiguities": audit.ambiguities,
                "contradictions": audit.contradictions,
                "by_season": audit.by_season,
                "unmapped_provider_fields": list(stats_report.unmapped_provider_fields),
                "details": build_identity_details(con),
                "v2_mart_rows": football_counts.team_match_stats_rows,
                "tactical_form_rows": football_counts.tactical_form_rows,
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
        _write(results / METRIC_INVENTORY_REPORT, build_metric_inventory(con))
    finally:
        con.close()
    logger.info(
        "wrote %s, %s, %s, %s",
        IDENTITY_REPORT,
        COVERAGE_REPORT,
        RECONCILIATION_REPORT,
        METRIC_INVENTORY_REPORT,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
