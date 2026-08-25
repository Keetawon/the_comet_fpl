"""Per-page dashboard read models over the published BI Parquet export.

This is the dashboard data boundary: it pre-shapes the joins all dashboard pages
need (fixture matrix, players, summary, next gameweek, forecast versus actual, optimizer
audit) into application JSON, so the static browser app only renders and ships no
client-side query engine.  It reads ONLY the
immutable Parquet export published by :mod:`fpl.publish.export` -- never the production
DuckDB -- and publishes its own directory through the same atomic generation-swap
machinery, imported rather than duplicated.

Downstream transport only: nothing here changes a model, the composer, an optimizer
artifact, the scoring config, the semantic contract, or the Parquet export itself.
Failures raised as :class:`DashboardJsonError` come from this module; the reused publish
machinery surfaces its own :class:`fpl.publish.export.BiExportError` subclasses.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import polars as pl

# The atomic-publish machinery (lock, generation swap, no-clobber, fsync) and the strict
# JSON helpers are shared with the Parquet exporter; import rather than fork a second copy.
from fpl.publish.export import (
    BI_EXPORT_SCHEMA,
    BI_EXPORT_SCHEMA_VERSION,
    BiExportError,
    _canonical_json_bytes,
    _export_lock,
    _fsync_directory,
    _fsync_file,
    _isoformat,
    _publish_generation,
    _published_snapshot,
    _resolve_output_dir,
    _sha256_bytes,
    _sha256_file,
    _strict_json_loads,
    _strict_manifest_content_sha256,
)

DASHBOARD_JSON_SCHEMA: Final[str] = "fpl.dashboard-read-models"
# v2: the manifest gains the summary, next-gameweek, forecast-vs-actual and
# optimizer-audit read models alongside v1's fixture-matrix and players files; the v1
# record shapes are unchanged.
# v3: optimizer plans carry an explicit platform/default/diagnostic/user classification,
# a display label, and the compact owner policy needed by the plan-builder result view.
# v4: each player carries cumulative-horizon xP and threshold probabilities derived here
# from the published player-gameweek PMFs.  The browser selects these values; it never
# sums probabilities or reconstructs them from per-gameweek primitives.
DASHBOARD_JSON_SCHEMA_VERSION: Final[int] = 4
FIXTURE_MATRIX_SCHEMA: Final[str] = "fpl.dashboard-fixture-matrix"
PLAYERS_SCHEMA: Final[str] = "fpl.dashboard-players"
PLAYER_HORIZONS_SCHEMA: Final[str] = "fpl.dashboard-player-horizons"
SUMMARY_SCHEMA: Final[str] = "fpl.dashboard-summary"
NEXT_GW_SCHEMA: Final[str] = "fpl.dashboard-next-gw"
FORECAST_VS_ACTUAL_SCHEMA: Final[str] = "fpl.dashboard-forecast-vs-actual"
OPTIMIZER_AUDIT_SCHEMA: Final[str] = "fpl.dashboard-optimizer-audit"
MANIFEST_FILENAME: Final[str] = "manifest.json"
FIXTURE_MATRIX_FILENAME: Final[str] = "fixture_matrix.json"
PLAYERS_FILENAME: Final[str] = "players.json"
PLAYER_HORIZONS_FILENAME: Final[str] = "player_horizons.json"
SUMMARY_FILENAME: Final[str] = "summary.json"
NEXT_GW_FILENAME: Final[str] = "next_gw.json"
FORECAST_VS_ACTUAL_FILENAME: Final[str] = "forecast_vs_actual.json"
OPTIMIZER_AUDIT_FILENAME: Final[str] = "optimizer_audit.json"

# Exactly the tables the read models read.  The source export is contract-complete, so a
# missing entry means the manifest was not produced by fpl.publish.export.
_READ_TABLES: Final[tuple[str, ...]] = (
    "dim_forecast_run",
    "dim_player_season",
    "dim_team_season",
    "dim_fixture",
    "dim_gameweek",
    "fact_forecast_team_fixture",
    "fact_team_form",
    "fact_forecast_player_gameweek",
    "fact_player_form",
    "fact_forecast_player_fixture",
    "fact_optimizer_plan",
    "fact_player_fixture_actual",
    "dim_optimizer_run",
)
_WINDOW_LABELS: Final[tuple[str, ...]] = ("last_3", "last_5", "last_10", "season_to_date")
_HORIZON_THRESHOLDS: Final[tuple[int, ...]] = (2, 4, 6, 10, 15)
_HORIZON_FIELDS: Final[tuple[str, ...]] = (
    "gw_to",
    "xp",
    "p_le_2",
    "p_ge_2",
    "p_ge_4",
    "p_ge_6",
    "p_ge_10",
    "p_ge_15",
)
_HORIZON_VALUE_DECIMAL_PLACES: Final[int] = 6
_PMF_ABSOLUTE_TOLERANCE: Final[float] = 1e-9
_EXPECTED_POINTS_ABSOLUTE_TOLERANCE: Final[float] = 1e-10
_HORIZON_WIRE_ABSOLUTE_TOLERANCE: Final[float] = 10**-_HORIZON_VALUE_DECIMAL_PLACES
# Which top-level array of each file the manifest row_count counts.  summary.json is a
# single object, so its row count is 1.
_FILE_LIST_KEY: Final[dict[str, str | None]] = {
    FIXTURE_MATRIX_FILENAME: "teams",
    PLAYERS_FILENAME: "players",
    PLAYER_HORIZONS_FILENAME: "players",
    NEXT_GW_FILENAME: "plans",
    SUMMARY_FILENAME: None,
    FORECAST_VS_ACTUAL_FILENAME: "runs",
    OPTIMIZER_AUDIT_FILENAME: "plans",
}
_FILE_SCHEMA: Final[dict[str, str]] = {
    FIXTURE_MATRIX_FILENAME: FIXTURE_MATRIX_SCHEMA,
    PLAYERS_FILENAME: PLAYERS_SCHEMA,
    PLAYER_HORIZONS_FILENAME: PLAYER_HORIZONS_SCHEMA,
    NEXT_GW_FILENAME: NEXT_GW_SCHEMA,
    SUMMARY_FILENAME: SUMMARY_SCHEMA,
    FORECAST_VS_ACTUAL_FILENAME: FORECAST_VS_ACTUAL_SCHEMA,
    OPTIMIZER_AUDIT_FILENAME: OPTIMIZER_AUDIT_SCHEMA,
}
_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "json_schema_version",
        "generated_at",
        "source",
        "runs",
        "run_ids",
        "ease_index_formula_version",
        "files",
        "content_sha256",
    }
)


class DashboardJsonError(RuntimeError):
    """The dashboard read models cannot truthfully be built or published."""


@dataclass(frozen=True, slots=True)
class DashboardReadModels:
    """The derived, publishable content of every dashboard read model."""

    runs: tuple[dict[str, Any], ...]
    teams: tuple[dict[str, Any], ...]
    schedule: dict[str, Any]
    players: tuple[dict[str, Any], ...]
    player_horizons: tuple[dict[str, Any], ...]
    summary: dict[str, Any]
    next_gw: dict[str, Any]
    forecast_vs_actual: dict[str, Any]
    optimizer_audit: dict[str, Any]
    ease_index_formula_version: str | None


@dataclass(frozen=True, slots=True)
class DashboardJsonResult:
    """The published endpoint and the immutable facts recorded in its manifest."""

    output_dir: Path
    manifest_path: Path
    content_sha256: str
    run_ids: tuple[str, ...]
    fixture_matrix_rows: int
    players_rows: int
    player_horizon_rows: int
    next_gw_plans: int


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise DashboardJsonError(
            f"expected a timezone-aware datetime in the source export, found {type(value).__name__}"
        )
    return _isoformat(value)


def _read_source_manifest(export_dir: Path) -> dict[str, Any]:
    path = export_dir / MANIFEST_FILENAME
    try:
        manifest = _strict_json_loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DashboardJsonError(f"cannot read source export manifest {path}: {exc}") from exc
    except BiExportError as exc:
        raise DashboardJsonError(
            f"source export manifest {path} is not strict JSON: {exc}"
        ) from exc
    if manifest.get("schema") != BI_EXPORT_SCHEMA or manifest.get("schema_version") != (
        BI_EXPORT_SCHEMA_VERSION
    ):
        raise DashboardJsonError(
            f"{path} is not a {BI_EXPORT_SCHEMA} version {BI_EXPORT_SCHEMA_VERSION} export"
        )
    tables = manifest.get("tables")
    if not isinstance(tables, dict):
        raise DashboardJsonError(f"{path} has no tables object")
    missing = [name for name in _READ_TABLES if name not in tables]
    if missing:
        raise DashboardJsonError(f"source export does not carry required table(s) {missing}")
    if manifest.get("content_sha256") != _strict_manifest_content_sha256(manifest):
        raise DashboardJsonError(f"{path} content_sha256 does not verify")
    return manifest


def _read_source_table(export_dir: Path, manifest: Mapping[str, Any], name: str) -> pl.DataFrame:
    entry = manifest["tables"][name]
    path = export_dir / f"{name}.parquet"
    if not path.is_file():
        raise DashboardJsonError(f"source export is missing {path.name}")
    if _sha256_file(path) != entry.get("sha256"):
        raise DashboardJsonError(f"{name}.parquet does not match the source manifest SHA-256")
    frame = pl.read_parquet(path)
    if frame.height != entry.get("row_count"):
        raise DashboardJsonError(f"{name}.parquet row count does not match the source manifest")
    return frame


def _require_no_nulls(frame: pl.DataFrame, columns: tuple[str, ...], message: str) -> None:
    for name in columns:
        if frame.get_column(name).null_count():
            raise DashboardJsonError(message)


def _horizon_projection(runs: pl.DataFrame) -> pl.DataFrame:
    return runs.select(
        pl.col("run_id"),
        pl.col("season").alias("run_season"),
        pl.col("gw_from"),
        pl.col("gw_to"),
    )


def _kickoff_projection(dim_fixture: pl.DataFrame) -> pl.DataFrame:
    return dim_fixture.select("season", "fixture", pl.col("kickoff_time").alias("_kickoff"))


def _opponent_projection(team_season: pl.DataFrame) -> pl.DataFrame:
    return team_season.select(
        pl.col("season"),
        pl.col("team_id").alias("_opponent_id"),
        pl.col("team_code").alias("opponent_team_code"),
        pl.col("short_name").alias("opponent_short_name"),
    )


def _require_within_run(frame: pl.DataFrame, subject: str) -> None:
    """Every forecast row must belong to its run's season and gameweek horizon."""
    _require_no_nulls(
        frame,
        ("run_season",),
        f"a {subject} row references a run absent from dim_forecast_run",
    )
    outside = frame.filter(
        (pl.col("season") != pl.col("run_season"))
        | (pl.col("gw") < pl.col("gw_from"))
        | (pl.col("gw") > pl.col("gw_to"))
    )
    if outside.height:
        raise DashboardJsonError(
            f"{outside.height} {subject} rows fall outside their run's season or "
            f"gw_from..gw_to horizon; refusing to reshape them"
        )


def _latest_form_windows(form: pl.DataFrame, key: str) -> dict[int, dict[str, Any]]:
    """Latest observed (season, gw) anchor per identity, all four windows, NULLs intact.

    ``key`` is the cross-season identity column (team_code or code), so the anchor may
    legitimately fall in a completed prior season when the forecast season has no finished
    matches.  The anchor season and gameweek are returned beside the windows so the UI can
    label how old the form is.
    """
    if form.height == 0:
        return {}
    measures = [name for name in form.columns if name not in {"season", "gw", key, "window"}]
    latest_season = form.group_by(key).agg(pl.col("season").max().alias("_anchor_season"))
    in_latest_season = form.join(latest_season, on=key).filter(
        pl.col("season") == pl.col("_anchor_season")
    )
    latest_gw = in_latest_season.group_by(key).agg(pl.col("gw").max().alias("_anchor_gw"))
    anchored = in_latest_season.join(latest_gw, on=key).filter(pl.col("gw") == pl.col("_anchor_gw"))
    result: dict[int, dict[str, Any]] = {}
    for row in anchored.sort([key, "window"]).iter_rows(named=True):
        identity = int(row[key])
        entry = result.get(identity)
        if entry is None:
            entry = {"season": row["season"], "as_at_gw": int(row["gw"]), "windows": {}}
            result[identity] = entry
        entry["windows"][row["window"]] = {measure: row[measure] for measure in measures}
    for identity, entry in result.items():
        missing = [label for label in _WINDOW_LABELS if label not in entry["windows"]]
        if missing:
            raise DashboardJsonError(
                f"form anchor for {key} {identity} at {entry['season']} GW{entry['as_at_gw']} "
                f"is missing window(s) {missing}"
            )
    return result


def _build_teams(
    team_fixture: pl.DataFrame,
    dim_fixture: pl.DataFrame,
    team_season: pl.DataFrame,
    runs: pl.DataFrame,
    team_form: pl.DataFrame,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    versions = team_fixture.get_column("ease_index_formula_version").unique().to_list()
    if len(versions) > 1:
        raise DashboardJsonError(f"source export mixes ease formula versions {versions}")

    own = team_season.select(
        pl.col("season"),
        pl.col("team_id").alias("_own_id"),
        pl.col("team_name"),
        pl.col("short_name"),
    )
    enriched = (
        team_fixture.join(_horizon_projection(runs), on="run_id", how="left")
        .join(_kickoff_projection(dim_fixture), on=["season", "fixture"], how="left")
        .join(own, left_on=["season", "team_id"], right_on=["season", "_own_id"], how="left")
        .join(
            _opponent_projection(team_season),
            left_on=["season", "opponent_team_id"],
            right_on=["season", "_opponent_id"],
            how="left",
        )
    )
    _require_within_run(enriched, "team-fixture")
    _require_no_nulls(
        enriched,
        ("team_name", "short_name", "opponent_team_code", "opponent_short_name"),
        "a team-fixture club or opponent label failed to resolve season-safely; refusing to "
        "publish an unlabelled read model",
    )

    ordered = enriched.sort(
        ["run_id", "season", "team_code", "gw", "_kickoff", "fixture"], nulls_last=True
    )
    fixtures: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    labels: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in ordered.iter_rows(named=True):
        identity = (row["run_id"], row["season"], int(row["team_code"]))
        if identity not in labels:
            labels[identity] = {
                "as_of": _iso_or_none(row["as_of"]),
                "team_name": row["team_name"],
                "short_name": row["short_name"],
            }
            fixtures[identity] = []
        fixtures[identity].append(
            {
                "gw": row["gw"],
                "fixture": row["fixture"],
                "kickoff_time": _iso_or_none(row["_kickoff"]),
                "opponent_team_code": row["opponent_team_code"],
                "opponent_short_name": row["opponent_short_name"],
                "was_home": row["was_home"],
                "lambda_for": row["lambda_for"],
                "lambda_against": row["lambda_against"],
                "probability_clean_sheet": row["probability_clean_sheet"],
                "attack_ease_index": row["attack_ease_index"],
                "defence_ease_index": row["defence_ease_index"],
                "overall_ease_index": row["overall_ease_index"],
                "ease_index_formula_version": row["ease_index_formula_version"],
                "official_fdr": row["official_fdr"],
                "stage_a_league_average_team": row["stage_a_league_average_team"],
            }
        )

    windows = _latest_form_windows(team_form, "team_code")
    teams: list[dict[str, Any]] = []
    for identity in sorted(fixtures):
        run_id, season, team_code = identity
        label = labels[identity]
        teams.append(
            {
                "run_id": run_id,
                "as_of": label["as_of"],
                "season": season,
                "team_code": team_code,
                "team_name": label["team_name"],
                "short_name": label["short_name"],
                "form": windows.get(team_code),
                "fixtures": fixtures[identity],
            }
        )
    return tuple(teams), (versions[0] if versions else None)


def _build_current_schedule(
    dim_fixture: pl.DataFrame,
    team_season: pl.DataFrame,
    runs: pl.DataFrame,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a current-at-export schedule overlay, deliberately outside forecast vintages.

    The overlay contains the complete scheduled season for every season represented by an
    exported forecast run. It is never joined to a run and carries no forecast or ease fields.
    Official FDR is carried as a current schedule property; consumers must not mistake a later
    schedule amendment or display proxy for point-in-time forecast input.
    """
    export_created_at = manifest.get("created_at")
    database_sha256 = manifest.get("database_sha256")
    if not isinstance(export_created_at, str) or not export_created_at:
        raise DashboardJsonError("source export created_at is missing or invalid")
    if (
        not isinstance(database_sha256, str)
        or len(database_sha256) != 64
        or any(character not in "0123456789abcdef" for character in database_sha256)
    ):
        raise DashboardJsonError("source export database_sha256 is missing or invalid")

    run_seasons = sorted(
        {str(season) for season in runs.get_column("season").to_list() if season is not None}
    )
    if not run_seasons:
        return {
            "schema_version": 2,
            "semantics": "current_at_export_not_forecast_vintage",
            "export_created_at": export_created_at,
            "database_sha256": database_sha256,
            "teams": [],
        }

    scheduled = dim_fixture.filter(pl.col("season").is_in(run_seasons) & pl.col("gw").is_not_null())
    _require_no_nulls(
        scheduled,
        (
            "season",
            "fixture",
            "gw",
            "home_team_id",
            "away_team_id",
            "home_team_code",
            "away_team_code",
        ),
        "a scheduled fixture is missing its season, gameweek, fixture, or club identity",
    )

    duplicate_fixtures = scheduled.group_by(["season", "fixture"]).len().filter(pl.col("len") != 1)
    if duplicate_fixtures.height:
        raise DashboardJsonError(
            "the current schedule has duplicate (season, fixture) rows; refusing an ambiguous "
            "schedule overlay"
        )

    season_labels = team_season.filter(pl.col("season").is_in(run_seasons))
    duplicate_team_ids = (
        season_labels.group_by(["season", "team_id"]).len().filter(pl.col("len") != 1)
    )
    duplicate_team_codes = (
        season_labels.group_by(["season", "team_code"]).len().filter(pl.col("len") != 1)
    )
    if duplicate_team_ids.height or duplicate_team_codes.height:
        raise DashboardJsonError(
            "dim_team_season is not unique by season-qualified team id and code"
        )

    labels: dict[tuple[str, int], dict[str, Any]] = {}
    for row in season_labels.sort(["season", "team_id"]).iter_rows(named=True):
        if any(row[name] is None for name in ("team_id", "team_code", "team_name", "short_name")):
            raise DashboardJsonError(
                "a current-schedule club label is incomplete in dim_team_season"
            )
        labels[(str(row["season"]), int(row["team_id"]))] = {
            "team_code": int(row["team_code"]),
            "team_name": row["team_name"],
            "short_name": row["short_name"],
        }

    fixture_sides: dict[tuple[str, int], list[tuple[int, dict[str, Any]]]] = {}
    team_fixtures: dict[tuple[str, int], list[dict[str, Any]]] = {}
    team_labels: dict[tuple[str, int], dict[str, Any]] = {}
    side_keys: set[tuple[str, int, int]] = set()
    ordered = scheduled.sort(["season", "gw", "kickoff_time", "fixture"], nulls_last=True)
    for row in ordered.iter_rows(named=True):
        season = str(row["season"])
        fixture = int(row["fixture"])
        home_id = int(row["home_team_id"])
        away_id = int(row["away_team_id"])
        if home_id == away_id:
            raise DashboardJsonError("a current-schedule fixture names the same club on both sides")
        try:
            home = labels[(season, home_id)]
            away = labels[(season, away_id)]
        except KeyError as exc:
            raise DashboardJsonError(
                "a current-schedule club failed to resolve through dim_team_season on "
                "(season, team_id)"
            ) from exc
        if (
            int(row["home_team_code"]) != home["team_code"]
            or int(row["away_team_code"]) != away["team_code"]
        ):
            raise DashboardJsonError(
                "a current-schedule team_code disagrees with its season-qualified club label"
            )

        for own, opponent, was_home, official_fdr in (
            (home, away, True, row["home_official_fdr"]),
            (away, home, False, row["away_official_fdr"]),
        ):
            own_code = int(own["team_code"])
            side_key = (season, own_code, fixture)
            if side_key in side_keys:
                raise DashboardJsonError(
                    "the current schedule has a duplicate (season, team_code, fixture) side"
                )
            side_keys.add(side_key)
            identity = (season, own_code)
            team_labels[identity] = own
            side = {
                "gw": int(row["gw"]),
                "fixture": fixture,
                "kickoff_time": _iso_or_none(row["kickoff_time"]),
                "opponent_team_code": int(opponent["team_code"]),
                "opponent_short_name": opponent["short_name"],
                "was_home": was_home,
                "official_fdr": int(official_fdr) if official_fdr is not None else None,
            }
            team_fixtures.setdefault(identity, []).append(side)
            fixture_sides.setdefault((season, fixture), []).append((own_code, side))

    for sides in fixture_sides.values():
        if len(sides) != 2:
            raise DashboardJsonError(
                "a current-schedule fixture does not have exactly two reciprocal club sides"
            )
        (first_code, first), (second_code, second) = sides
        if (
            first["opponent_team_code"] != second_code
            or second["opponent_team_code"] != first_code
            or first["was_home"] == second["was_home"]
        ):
            raise DashboardJsonError("a current-schedule fixture has non-reciprocal club sides")

    teams: list[dict[str, Any]] = []
    for identity in sorted(team_fixtures):
        season, team_code = identity
        label = team_labels[identity]
        teams.append(
            {
                "season": season,
                "team_code": team_code,
                "team_name": label["team_name"],
                "short_name": label["short_name"],
                "fixtures": team_fixtures[identity],
            }
        )
    return {
        "schema_version": 2,
        "semantics": "current_at_export_not_forecast_vintage",
        "export_created_at": export_created_at,
        "database_sha256": database_sha256,
        "teams": teams,
    }


def _avg_minutes_last_5(form: dict[str, Any] | None) -> float | None:
    """Minutes per ROSTERED fixture over the last-5 window: per-match average, DNPs included."""
    if form is None:
        return None
    window = form["windows"].get("last_5")
    if window is None:
        return None
    minutes = window.get("minutes")
    rostered = window.get("rostered_fixtures")
    if not isinstance(minutes, (int, float)) or not isinstance(rostered, int) or not rostered:
        return None  # zero denominator is unmeasured here, never 0.0
    return float(minutes) / rostered


def _validated_horizon_pmf(raw: object, subject: str) -> tuple[float, ...]:
    """Parse one published player-gameweek PMF without weakening its artifact contract."""
    if not isinstance(raw, str):
        raise DashboardJsonError(f"{subject} distribution must be a JSON string")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DashboardJsonError(f"{subject} distribution is not JSON: {exc}") from exc
    if not isinstance(parsed, list) or not parsed:
        raise DashboardJsonError(f"{subject} distribution must be a non-empty JSON array")
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0.0
        for value in parsed
    ):
        raise DashboardJsonError(
            f"{subject} distribution masses must be finite, non-negative numbers"
        )
    probabilities = tuple(float(value) for value in parsed)
    total = math.fsum(probabilities)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=_PMF_ABSOLUTE_TOLERANCE):
        raise DashboardJsonError(f"{subject} distribution sums to {total!r}, expected 1")
    return probabilities


def _convolve_pmfs(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    """Discrete convolution over the complete integer support, with no truncation."""
    products: list[list[float]] = [[] for _ in range(len(left) + len(right) - 1)]
    for left_index, left_mass in enumerate(left):
        for right_index, right_mass in enumerate(right):
            products[left_index + right_index].append(left_mass * right_mass)
    return tuple(math.fsum(cell) for cell in products)


def _bounded_probability(value: float, subject: str) -> float:
    if value < -_PMF_ABSOLUTE_TOLERANCE or value > 1.0 + _PMF_ABSOLUTE_TOLERANCE:
        raise DashboardJsonError(f"{subject} probability {value!r} falls outside [0, 1]")
    # Floating convolution can miss a boundary by a few ulps. Clamp only inside the same
    # tolerance used to validate the source PMFs.
    return min(1.0, max(0.0, value))


def _build_player_horizons(
    player_gameweek: pl.DataFrame, runs: pl.DataFrame
) -> tuple[dict[str, Any], ...]:
    """Convolve each player's gameweek PMFs from ``gw_from`` through every ``gw_to``.

    Expected points are included beside the threshold probabilities for one coherent
    distribution summary.  The weekly published means are independently reconciled with
    their PMFs, and missing weeks fail closed rather than producing a partial horizon.
    """
    bounded = player_gameweek.join(_horizon_projection(runs), on="run_id", how="left")
    _require_within_run(bounded, "player-gameweek")

    actual_by_run = {
        str(row["run_id"]): (int(row["rows"]), int(row["players"]))
        for row in bounded.group_by("run_id")
        .agg(pl.len().alias("rows"), pl.col("code").n_unique().alias("players"))
        .iter_rows(named=True)
    }
    for run in runs.iter_rows(named=True):
        run_id = str(run["run_id"])
        gw_from, gw_to = run["gw_from"], run["gw_to"]
        row_count, roster_size = run.get("row_count"), run.get("roster_size")
        if (
            not isinstance(gw_from, int)
            or not isinstance(gw_to, int)
            or not isinstance(row_count, int)
            or not isinstance(roster_size, int)
            or roster_size <= 0
            or row_count <= 0
        ):
            raise DashboardJsonError(
                f"dim_forecast_run {run_id} is missing its positive integer "
                "horizon/population contract"
            )
        expected_rows = roster_size * (gw_to - gw_from + 1)
        if row_count != expected_rows:
            raise DashboardJsonError(
                f"dim_forecast_run {run_id} row_count {row_count} does not equal "
                f"roster_size*horizon {expected_rows}"
            )
        actual_rows, actual_players = actual_by_run.get(run_id, (0, 0))
        if actual_rows != row_count or actual_players != roster_size:
            raise DashboardJsonError(
                f"dim_forecast_run {run_id} declares {row_count} rows/{roster_size} players "
                f"but the published player-gameweek table has {actual_rows}/{actual_players}"
            )

    duplicate = (
        bounded.group_by(["run_id", "season", "code", "gw"]).len().filter(pl.col("len") != 1)
    )
    if duplicate.height:
        raise DashboardJsonError(
            "player-gameweek forecast rows are not unique at (run_id, season, code, gw)"
        )

    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in bounded.sort(["run_id", "season", "code", "gw"]).iter_rows(named=True):
        key = (str(row["run_id"]), str(row["season"]), int(row["code"]))
        grouped.setdefault(key, []).append(row)

    result: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        run_id, season, code = key
        gw_from = rows[0]["gw_from"]
        gw_to = rows[0]["gw_to"]
        if not isinstance(gw_from, int) or not isinstance(gw_to, int):
            raise DashboardJsonError(f"player {code} references an invalid run horizon")
        actual_gws = [int(row["gw"]) for row in rows]
        expected_gws = list(range(gw_from, gw_to + 1))
        if actual_gws != expected_gws:
            raise DashboardJsonError(
                f"player {code} in {run_id}/{season} has gameweeks {actual_gws}, expected "
                f"the complete horizon {expected_gws}"
            )

        cumulative: tuple[float, ...] = (1.0,)
        published_xp: list[float] = []
        normalised_xp: list[float] = []
        horizons: list[dict[str, float | int]] = []
        for row in rows:
            gw = int(row["gw"])
            subject = f"player {code} in {run_id}/{season} GW{gw}"
            raw_expected = row["expected_points"]
            if (
                not isinstance(raw_expected, (int, float))
                or isinstance(raw_expected, bool)
                or not math.isfinite(raw_expected)
            ):
                raise DashboardJsonError(f"{subject} expected_points must be finite")
            weekly_raw = _validated_horizon_pmf(row["distribution"], subject)
            weekly_xp = math.fsum(index * mass for index, mass in enumerate(weekly_raw))
            if not math.isclose(
                float(raw_expected),
                weekly_xp,
                rel_tol=0.0,
                abs_tol=_EXPECTED_POINTS_ABSOLUTE_TOLERANCE,
            ):
                raise DashboardJsonError(
                    f"{subject} expected_points {raw_expected!r} does not match its "
                    f"distribution mean {weekly_xp!r}"
                )

            # Upstream permits at most 1e-9 serialisation drift in total mass. Preserve the
            # stored xP above, but remove that accepted drift before repeated convolution so
            # a valid near-unit PMF cannot make cumulative tails shrink or exceed one.
            weekly_mass = math.fsum(weekly_raw)
            weekly = tuple(mass / weekly_mass for mass in weekly_raw)
            normalised_xp.append(math.fsum(index * mass for index, mass in enumerate(weekly)))
            cumulative = _convolve_pmfs(cumulative, weekly)
            cumulative_mass = math.fsum(cumulative)
            if not math.isclose(
                cumulative_mass,
                1.0,
                rel_tol=0.0,
                abs_tol=_PMF_ABSOLUTE_TOLERANCE,
            ):
                raise DashboardJsonError(
                    f"{subject} cumulative distribution sums to {cumulative_mass!r}, expected 1"
                )
            published_xp.append(float(raw_expected))
            cumulative_xp = math.fsum(index * mass for index, mass in enumerate(cumulative))
            summed_xp = math.fsum(published_xp)
            summed_normalised_xp = math.fsum(normalised_xp)
            if not math.isclose(
                cumulative_xp,
                summed_normalised_xp,
                rel_tol=0.0,
                abs_tol=_EXPECTED_POINTS_ABSOLUTE_TOLERANCE,
            ):
                raise DashboardJsonError(
                    f"{subject} cumulative distribution mean {cumulative_xp!r} does not "
                    f"match its normalised gameweek means {summed_normalised_xp!r}"
                )

            horizon: dict[str, float | int] = {
                "gw_to": gw,
                "xp": summed_xp,
                "p_le_2": _bounded_probability(
                    math.fsum(cumulative[:3]), f"{subject} P(points <= 2)"
                ),
            }
            for threshold in _HORIZON_THRESHOLDS:
                horizon[f"p_ge_{threshold}"] = _bounded_probability(
                    math.fsum(cumulative[threshold:]),
                    f"{subject} P(points >= {threshold})",
                )
            horizons.append(horizon)
        result.append(
            {
                "run_id": run_id,
                "season": season,
                "code": code,
                "horizons": horizons,
            }
        )
    return tuple(result)


def _build_players(
    player_gameweek: pl.DataFrame,
    player_fixture: pl.DataFrame,
    team_fixture: pl.DataFrame,
    player_season: pl.DataFrame,
    team_season: pl.DataFrame,
    dim_fixture: pl.DataFrame,
    runs: pl.DataFrame,
    player_form: pl.DataFrame,
) -> tuple[dict[str, Any], ...]:
    # Identity comes from each player's FIRST forecast gameweek: the deadline-known price,
    # ownership and reported availability of the vintage.
    first_gw = player_gameweek.group_by(["run_id", "season", "code"]).agg(
        pl.col("gw").min().alias("_first_gw")
    )
    club = team_season.select(
        pl.col("season"),
        pl.col("team_id").alias("_club_id"),
        pl.col("team_code").alias("_club_code"),
        pl.col("short_name").alias("team_short_name"),
    )
    identity = (
        player_gameweek.join(first_gw, on=["run_id", "season", "code"])
        .filter(pl.col("gw") == pl.col("_first_gw"))
        .join(player_season.select("season", "code", "web_name"), on=["season", "code"], how="left")
        .join(club, left_on=["season", "team_id"], right_on=["season", "_club_id"], how="left")
        .with_columns(pl.col("team_code").fill_null(pl.col("_club_code")).alias("team_code"))
    )
    _require_no_nulls(
        identity,
        ("web_name", "team_code", "team_short_name"),
        "a player identity failed to resolve web_name or club season-safely; refusing to "
        "publish an unlabelled read model",
    )

    # The fixture chips need the player's own club ease for the same fixture, joined on the
    # season-qualified fixture-team key.  A marker column distinguishes a missing team row
    # (an internal inconsistency) from legitimately NULL ease/FDR values.
    ease = team_fixture.select(
        "run_id",
        "season",
        "fixture",
        "team_id",
        pl.lit(True).alias("_team_row_present"),
        pl.col("attack_ease_index").alias("team_attack_ease_index"),
        pl.col("defence_ease_index").alias("team_defence_ease_index"),
        pl.col("overall_ease_index").alias("team_overall_ease_index"),
        pl.col("official_fdr").alias("team_official_fdr"),
        # The club primitives behind the player chip's colour, so the expanded player row
        # can show raw lambdas and the team clean sheet beside the ease indices.
        pl.col("lambda_for").alias("team_lambda_for"),
        pl.col("lambda_against").alias("team_lambda_against"),
        pl.col("probability_clean_sheet").alias("team_probability_clean_sheet"),
    )
    enriched = (
        player_fixture.join(_horizon_projection(runs), on="run_id", how="left")
        .join(_kickoff_projection(dim_fixture), on=["season", "fixture"], how="left")
        .join(
            _opponent_projection(team_season),
            left_on=["season", "opponent_team_id"],
            right_on=["season", "_opponent_id"],
            how="left",
        )
        .join(ease, on=["run_id", "season", "fixture", "team_id"], how="left")
    )
    _require_within_run(enriched, "player-fixture")
    _require_no_nulls(
        enriched,
        ("opponent_team_code", "opponent_short_name", "_team_row_present"),
        "a player-fixture opponent label or team-ease row failed to resolve; refusing to "
        "publish a mislabelled read model",
    )

    ordered = enriched.sort(
        ["run_id", "season", "code", "gw", "_kickoff", "fixture"], nulls_last=True
    )
    fixtures: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in ordered.iter_rows(named=True):
        player_key = (row["run_id"], row["season"], int(row["code"]))
        fixtures.setdefault(player_key, []).append(
            {
                "gw": row["gw"],
                "fixture": row["fixture"],
                "kickoff_time": _iso_or_none(row["_kickoff"]),
                "opponent_team_code": row["opponent_team_code"],
                "opponent_short_name": row["opponent_short_name"],
                "was_home": row["was_home"],
                "expected_points": row["expected_points"],
                "probability_appears": row["probability_appears"],
                "probability_sixty_minutes": row["probability_sixty_minutes"],
                "expected_goals": row["expected_goals"],
                "expected_assists": row["expected_assists"],
                "probability_clean_sheet": row["probability_clean_sheet"],
                "team_attack_ease_index": row["team_attack_ease_index"],
                "team_defence_ease_index": row["team_defence_ease_index"],
                "team_overall_ease_index": row["team_overall_ease_index"],
                "team_official_fdr": row["team_official_fdr"],
                "team_lambda_for": row["team_lambda_for"],
                "team_lambda_against": row["team_lambda_against"],
                "team_probability_clean_sheet": row["team_probability_clean_sheet"],
            }
        )

    identities = {
        (row["run_id"], row["season"], int(row["code"])): row
        for row in identity.sort(["run_id", "season", "code"]).iter_rows(named=True)
    }
    orphans = sorted(set(fixtures) - set(identities))
    if orphans:
        raise DashboardJsonError(
            f"player-fixture rows exist with no player-gameweek identity: {orphans[:3]}"
        )
    roster_codes = {key[2] for key in identities}
    windows = _latest_form_windows(
        player_form.filter(pl.col("code").is_in(sorted(roster_codes))), "code"
    )

    players: list[dict[str, Any]] = []
    for key in sorted(identities):
        run_id, season, code = key
        row = identities[key]
        players.append(
            {
                "run_id": run_id,
                "as_of": _iso_or_none(row["as_of"]),
                "season": season,
                "code": code,
                "web_name": row["web_name"],
                "position": row["position"],
                "team_code": row["team_code"],
                "team_short_name": row["team_short_name"],
                "now_cost": row["now_cost"],
                "selected_by_percent": row["selected_by_percent"],
                "availability_status": row["availability_status"],
                "chance_of_playing": row["chance_of_playing"],
                "availability_multiplier": row["availability_multiplier"],
                # Availability is a reported overlay valid for the first forecast gameweek;
                # the ledger repeats it for later ones.  Passed through, never folded in.
                "form": windows.get(code),
                "avg_minutes_last_5": _avg_minutes_last_5(windows.get(code)),
                "fixtures": fixtures.get(key, []),
            }
        )
    return tuple(players)


def _component_modes(runs: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """run_id -> parsed component modes; the ledger stores them as sorted-key JSON."""
    result: dict[str, dict[str, Any]] = {}
    for row in runs.iter_rows(named=True):
        raw = row.get("component_modes")
        if not isinstance(raw, str):
            raise DashboardJsonError(
                f"dim_forecast_run {row['run_id']} has malformed component_modes"
            )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DashboardJsonError(
                f"dim_forecast_run {row['run_id']} component_modes is not JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise DashboardJsonError(
                f"dim_forecast_run {row['run_id']} component_modes is not an object"
            )
        result[row["run_id"]] = parsed
    return result


def _short_name_maps(
    team_season: pl.DataFrame,
) -> tuple[dict[tuple[str, int], str], dict[tuple[str, int], tuple[int, str]]]:
    by_code: dict[tuple[str, int], str] = {}
    by_id: dict[tuple[str, int], tuple[int, str]] = {}
    for row in team_season.iter_rows(named=True):
        key = (row["season"], int(row["team_code"]))
        by_code[key] = row["short_name"]
        by_id[(row["season"], int(row["team_id"]))] = (int(row["team_code"]), row["short_name"])
    return by_code, by_id


def _player_identity_maps(
    player_season: pl.DataFrame,
) -> tuple[dict[tuple[str, int], tuple[str, str]], tuple[str, ...]]:
    names: dict[tuple[str, int], tuple[str, str]] = {}
    for row in player_season.iter_rows(named=True):
        names[(row["season"], int(row["code"]))] = (row["web_name"], row["position"])
    positions = ("GK", "DEF", "MID", "FWD")
    return names, positions


def _build_next_gw(
    plans_frame: pl.DataFrame,
    dim_optimizer_run: pl.DataFrame,
    runs: pl.DataFrame,
    player_gameweek: pl.DataFrame,
    player_season: pl.DataFrame,
    team_season: pl.DataFrame,
) -> dict[str, Any]:
    """next_gw.json: every optimizer plan in the source export, joined season-safely to the
    forecast's per-gameweek EV, ownership/availability overlay, and flags.

    The default-vs-diagnostic diff is *not* precomputed here: both plans ship complete, and
    the set operations (squad/XI overlap, captain agreement, unique players) are derived in
    the UI from the same records.  ``component_modes`` travels with each plan so the UI can
    label which architecture produced it without guessing.
    """
    if plans_frame.height == 0:
        return {"plans": ()}

    modes = _component_modes(runs)
    plan_metadata = _optimizer_plan_metadata(dim_optimizer_run, runs)
    horizon = {row["run_id"]: row for row in _horizon_projection(runs).iter_rows(named=True)}
    names, _ = _player_identity_maps(player_season)
    by_code, by_id = _short_name_maps(team_season)

    # EV keyed (forecast run, gw, code); team_code resolved season-safely (the raw forecast
    # row's team_code may be NULL and fall back to (season, team_id)).
    ev: dict[tuple[str, int, int], float | None] = {}
    run_team_code: dict[tuple[str, int, int], int] = {}
    for row in player_gameweek.iter_rows(named=True):
        key = (row["run_id"], int(row["gw"]), int(row["code"]))
        ev[key] = row["expected_points"]
        team_code = row["team_code"]
        if team_code is None:
            resolved = by_id.get((row["season"], int(row["team_id"])))
            team_code = resolved[0] if resolved is not None else None
        if team_code is None:
            raise DashboardJsonError(
                f"forecast row {row['run_id']} GW{row['gw']} code {row['code']} has a club "
                "that fails to resolve season-safely"
            )
        run_team_code[key] = int(team_code)
    first_gw = (
        player_gameweek.group_by(["run_id", "code"])
        .agg(pl.col("gw").min().alias("_first_gw"))
        .join(player_gameweek, on=["run_id", "code"])
        .filter(pl.col("gw") == pl.col("_first_gw"))
    )
    context: dict[tuple[str, int], dict[str, Any]] = {}
    for row in first_gw.iter_rows(named=True):
        context[(row["run_id"], int(row["code"]))] = {
            "selected_by_percent": row["selected_by_percent"],
            "availability_status": row["availability_status"],
            "chance_of_playing": row["chance_of_playing"],
            "availability_multiplier": row["availability_multiplier"],
            "cold_start_player": row["cold_start_player"],
            "stage_a_league_average_team": row["stage_a_league_average_team"],
            "attacking_signal_cold_start": row["attacking_signal_cold_start"],
            "assist_signal_cold_start": row["assist_signal_cold_start"],
            "transferred_no_rescale": row["transferred_no_rescale"],
        }

    role_rank = {"starting_xi": 0, "bench_goalkeeper": 1, "bench_outfield": 2}
    plans: list[dict[str, Any]] = []
    for optimizer_run_id in sorted(plans_frame.get_column("optimizer_run_id").unique().to_list()):
        sub = plans_frame.filter(pl.col("optimizer_run_id") == optimizer_run_id)
        forecast_run_ids = sub.get_column("forecast_run_id").unique().to_list()
        if len(forecast_run_ids) != 1:
            raise DashboardJsonError(
                f"optimizer run {optimizer_run_id} spans {len(forecast_run_ids)} forecast runs"
            )
        forecast_run_id = forecast_run_ids[0]
        run = horizon.get(forecast_run_id)
        if run is None:
            raise DashboardJsonError(
                f"optimizer run {optimizer_run_id} references forecast run absent from "
                "dim_forecast_run"
            )
        metadata = plan_metadata.get(optimizer_run_id)
        if metadata is None:
            raise DashboardJsonError(
                f"optimizer run {optimizer_run_id} is absent from dim_optimizer_run; "
                "cannot classify a plan without its search policy"
            )
        seasons = sub.get_column("season").unique().to_list()
        if seasons != [run["run_season"]]:
            raise DashboardJsonError(
                f"optimizer run {optimizer_run_id} season {seasons} disagrees with its "
                f"forecast run's {run['run_season']}"
            )
        decision_shas = sub.get_column("decision_sha256").unique().to_list()
        if len(decision_shas) != 1:
            raise DashboardJsonError(f"optimizer run {optimizer_run_id} mixes decisions")
        outside = sub.filter((pl.col("gw") < run["gw_from"]) | (pl.col("gw") > run["gw_to"]))
        if outside.height:
            raise DashboardJsonError(
                f"optimizer run {optimizer_run_id} has weeks outside its forecast horizon"
            )

        weeks: list[dict[str, Any]] = []
        for gw in sorted(sub.get_column("gw").unique().to_list()):
            week_rows = sorted(
                sub.filter(pl.col("gw") == gw).iter_rows(named=True),
                key=lambda row: (
                    role_rank.get(str(row["role"]), 3),
                    row["bench_order_index"] if row["bench_order_index"] is not None else 0,
                    int(row["code"]),
                ),
            )
            hits = {row["hit_points_this_gw"] for row in week_rows}
            if len(hits) != 1:
                raise DashboardJsonError(
                    f"optimizer run {optimizer_run_id} GW{gw} has inconsistent hit points"
                )
            captains = [
                row for row in week_rows if row["is_captain"] and row["role"] == "starting_xi"
            ]
            vices = [
                row for row in week_rows if row["is_vice_captain"] and row["role"] == "starting_xi"
            ]
            if len(captains) != 1 or len(vices) != 1:
                raise DashboardJsonError(
                    f"optimizer run {optimizer_run_id} GW{gw} needs exactly one captain and "
                    "one vice-captain in the XI"
                )
            players: list[dict[str, Any]] = []
            for row in week_rows:
                code = int(row["code"])
                identity = names.get((run["run_season"], code))
                if identity is None:
                    raise DashboardJsonError(
                        f"optimizer run {optimizer_run_id} names code {code} with no "
                        "dim_player_season row; refusing an unlabelled plan"
                    )
                team_code = run_team_code.get((forecast_run_id, gw, code))
                if team_code is None:
                    raise DashboardJsonError(
                        f"optimizer run {optimizer_run_id} GW{gw} names code {code} absent "
                        "from its forecast; refusing a plan the forecast never rated"
                    )
                short = by_code.get((run["run_season"], team_code))
                if short is None:
                    raise DashboardJsonError(
                        f"plan player code {code} has a team_code that fails to resolve"
                    )
                players.append(
                    {
                        "code": code,
                        "web_name": identity[0],
                        "position": identity[1],
                        "team_code": team_code,
                        "team_short_name": short,
                        "now_cost": row["now_cost"],
                        "role": row["role"],
                        "bench_order_index": row["bench_order_index"],
                        "is_captain": bool(row["is_captain"]),
                        "is_vice_captain": bool(row["is_vice_captain"]),
                        "transferred_in": bool(row["transferred_in"]),
                        "transferred_out": bool(row["transferred_out"]),
                        "expected_points": ev[(forecast_run_id, gw, code)],
                    }
                )
            weeks.append(
                {
                    "gw": gw,
                    "hit_points": next(iter(hits)),
                    "squad_cost": sum(
                        player["now_cost"] for player in players if player["now_cost"] is not None
                    ),
                    "captain_code": int(captains[0]["code"]),
                    "vice_captain_code": int(vices[0]["code"]),
                    "players": players,
                }
            )

        squad_codes = sorted(
            {int(code) for week in weeks for code in (player["code"] for player in week["players"])}
        )
        player_xp: dict[str, dict[str, float | None]] = {}
        for code in squad_codes:
            by_gw: dict[str, float | None] = {}
            for gw in range(run["gw_from"], run["gw_to"] + 1):
                by_gw[str(gw)] = ev.get((forecast_run_id, gw, code))
            player_xp[str(code)] = by_gw
        plans.append(
            {
                "optimizer_run_id": optimizer_run_id,
                "decision_sha256": decision_shas[0],
                "forecast_run_id": forecast_run_id,
                "as_of": _iso_or_none(next(iter(sub.get_column("as_of")))),
                "season": run["run_season"],
                "gw_from": run["gw_from"],
                "gw_to": run["gw_to"],
                "component_modes": modes.get(forecast_run_id),
                "plan_kind": metadata["plan_kind"],
                "display_label": metadata["display_label"],
                "policy": metadata["compact_policy"],
                "weeks": weeks,
                "player_xp": player_xp,
                "squad_context": {
                    str(code): context.get((forecast_run_id, code)) for code in squad_codes
                },
            }
        )
    return {"plans": tuple(plans)}


def _summary_player_rows(
    rows: list[dict[str, Any]],
    season: str,
    names: Mapping[tuple[str, int], tuple[str, str]],
    by_code: Mapping[tuple[str, int], str],
    by_id: Mapping[tuple[str, int], tuple[int, str]],
) -> list[dict[str, Any]]:
    summary_rows: list[dict[str, Any]] = []
    for row in rows:
        code = int(row["code"])
        identity = names.get((season, code), (None, None))
        team_code = row.get("team_code")
        if team_code is None and row.get("team_id") is not None:
            resolved = by_id.get((season, int(row["team_id"])))
            team_code = resolved[0] if resolved is not None else None
        summary_rows.append(
            {
                "code": code,
                "web_name": identity[0],
                "position": identity[1],
                "team_short_name": by_code.get((season, team_code)) if team_code else None,
                "expected_points": row["expected_points"],
            }
        )
    return summary_rows


def _build_summary(
    runs: pl.DataFrame,
    player_gameweek: pl.DataFrame,
    team_fixture: pl.DataFrame,
    dim_gameweek: pl.DataFrame,
    player_season: pl.DataFrame,
    team_season: pl.DataFrame,
    plans_frame: pl.DataFrame,
    dim_optimizer_run: pl.DataFrame,
    ease_version: str | None,
) -> dict[str, Any]:
    """summary.json: the landing snapshot -- latest run, roster coverage, headline EV and
    risk, the next gameweek's first kickoff (deadlines are not sourced, never fabricated),
    and the optimizer plans present in the export."""
    by_code, by_id = _short_name_maps(team_season)
    names, _ = _player_identity_maps(player_season)

    if runs.height == 0:
        return {
            "latest_run": None,
            "roster": {"players": 0, "teams": 0},
            "next_gameweek": None,
            "top_xp": [],
            "horizon_top_xp": [],
            "flagged_top_xp": [],
            "easiest_fixtures": [],
            "hardest_fixtures": [],
            "optimizer_plans": [],
            "ease_index_formula_version": ease_version,
        }

    ordered = runs.sort(["created_at", "run_id"], nulls_last=True)
    latest = ordered.rows(named=True)[-1]
    run_id = latest["run_id"]
    season = latest["season"]
    gw_from, gw_to = latest["gw_from"], latest["gw_to"]
    modes = _component_modes(runs)[run_id]

    run_gw = player_gameweek.filter(pl.col("run_id") == run_id)
    first_rows = (
        run_gw.filter(pl.col("gw") == gw_from)
        .sort("expected_points", descending=True, nulls_last=True)
        .head(5)
        .to_dicts()
    )
    flagged_rows = (
        run_gw.filter(
            (pl.col("gw") == gw_from)
            & pl.col("availability_status").is_not_null()
            & (pl.col("availability_status") != "a")
        )
        .sort("expected_points", descending=True, nulls_last=True)
        .head(5)
        .to_dicts()
    )
    horizon_rows = (
        run_gw.filter((pl.col("gw") >= gw_from) & (pl.col("gw") <= gw_to))
        .group_by("code")
        .agg(
            pl.col("team_code").first(),
            pl.col("team_id").first(),
            pl.col("expected_points").sum().alias("expected_points"),
        )
        .sort("expected_points", descending=True, nulls_last=True)
        .head(5)
        .to_dicts()
    )

    run_fixtures = team_fixture.filter(
        (pl.col("run_id") == run_id)
        & (pl.col("gw") == gw_from)
        & pl.col("overall_ease_index").is_not_null()
    )
    fixture_rows = []
    for row in run_fixtures.iter_rows(named=True):
        opponent = by_id.get((season, int(row["opponent_team_id"])))
        fixture_rows.append(
            {
                "team_short_name": by_code.get((season, int(row["team_code"]))),
                "opponent_short_name": opponent[1] if opponent else None,
                "was_home": row["was_home"],
                "overall_ease_index": row["overall_ease_index"],
                "official_fdr": row["official_fdr"],
            }
        )
    fixture_rows.sort(
        key=lambda row: (
            -(row["overall_ease_index"] if row["overall_ease_index"] is not None else 0.0)
        )
    )

    gw_row = (
        dim_gameweek.filter((pl.col("season") == season) & (pl.col("gw") == gw_from))
        .sort("gw")
        .rows(named=True)
    )
    next_gameweek = (
        {
            "gw": gw_from,
            "first_kickoff": _iso_or_none(gw_row[0]["first_kickoff"]),
            "last_kickoff": _iso_or_none(gw_row[0]["last_kickoff"]),
            "fixture_count": gw_row[0]["fixture_count"],
        }
        if gw_row
        else None
    )

    optimizer_plans = []
    if plans_frame.height:
        plan_modes = _component_modes(runs)
        plan_metadata = _optimizer_plan_metadata(dim_optimizer_run, runs)
        seen: dict[str, dict[str, Any]] = {}
        for row in plans_frame.iter_rows(named=True):
            metadata = plan_metadata.get(row["optimizer_run_id"])
            if metadata is None:
                raise DashboardJsonError(
                    f"optimizer run {row['optimizer_run_id']} is absent from "
                    "dim_optimizer_run; cannot classify a plan without its search policy"
                )
            seen[row["optimizer_run_id"]] = {
                "optimizer_run_id": row["optimizer_run_id"],
                "decision_sha256": row["decision_sha256"],
                "forecast_run_id": row["forecast_run_id"],
                "component_modes": plan_modes.get(row["forecast_run_id"]),
                "plan_kind": metadata["plan_kind"],
                "display_label": metadata["display_label"],
            }
        optimizer_plans = [seen[key] for key in sorted(seen)]

    return {
        "latest_run": {
            "run_id": run_id,
            "as_of": _iso_or_none(latest["as_of"]),
            "created_at": _iso_or_none(latest["created_at"]),
            "season": season,
            "gw_from": gw_from,
            "gw_to": gw_to,
            "status": latest["status"],
            "component_modes": modes,
        },
        "roster": {
            "players": player_gameweek.filter(pl.col("run_id") == run_id)
            .get_column("code")
            .n_unique(),
            "teams": team_fixture.filter(pl.col("run_id") == run_id)
            .get_column("team_code")
            .n_unique(),
        },
        "next_gameweek": next_gameweek,
        "top_xp": _summary_player_rows(first_rows, season, names, by_code, by_id),
        "horizon_top_xp": _summary_player_rows(horizon_rows, season, names, by_code, by_id),
        "flagged_top_xp": _summary_player_rows(flagged_rows, season, names, by_code, by_id),
        "easiest_fixtures": fixture_rows[:3],
        "hardest_fixtures": list(reversed(fixture_rows[-3:])),
        "optimizer_plans": optimizer_plans,
        "ease_index_formula_version": ease_version,
    }


def _discrete_crps(probabilities: list[float], actual: float) -> float | None:
    """CRPS of an integer-indexed pmf against an observation, by the double-sum identity.

    Returns None when the pmf is malformed (negative mass, or weights that are not finite);
    the caller reports such a row as unmeasured rather than inventing a score.
    """
    support = list(range(len(probabilities)))
    if any((not (p >= 0.0)) or p > 1.0 for p in probabilities):
        return None
    first = sum(p * abs(x - actual) for x, p in zip(support, probabilities, strict=True))
    second = 0.0
    for i, p_i in enumerate(probabilities):
        for j, p_j in enumerate(probabilities):
            second += p_i * p_j * abs(i - j)
    return first - 0.5 * second


_CALIBRATION_BUCKETS: Final[tuple[tuple[str, float, float], ...]] = (
    ("0.0-0.1", 0.0, 0.1),
    ("0.1-0.3", 0.1, 0.3),
    ("0.3-0.5", 0.3, 0.5),
    ("0.5-0.7", 0.5, 0.7),
    ("0.7-1.0", 0.7, 1.01),
)
_CALIBRATION_THRESHOLD: Final[int] = 2


def _parse_distribution(raw: object) -> list[float] | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise DashboardJsonError(
            f"forecast distribution must be a JSON string, found {type(raw).__name__}"
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DashboardJsonError(f"forecast distribution is not JSON: {exc}") from exc
    if not isinstance(parsed, list) or not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) for value in parsed
    ):
        raise DashboardJsonError("forecast distribution must be a JSON array of numbers")
    return [float(value) for value in parsed]


def _score_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean EV / actual / bias / MAE / CRPS over scored rows; None when nothing scored."""
    if not rows:
        return {
            "rows": 0,
            "mean_ev": None,
            "mean_actual": None,
            "bias": None,
            "mae": None,
            "crps": None,
        }
    count = len(rows)
    mean_ev = sum(row["ev"] for row in rows) / count
    mean_actual = sum(row["actual"] for row in rows) / count
    mae = sum(abs(row["actual"] - row["ev"]) for row in rows) / count
    crps_values = [row["crps"] for row in rows if row["crps"] is not None]
    return {
        "rows": count,
        "mean_ev": mean_ev,
        "mean_actual": mean_actual,
        "bias": mean_actual - mean_ev,
        "mae": mae,
        "crps": sum(crps_values) / len(crps_values) if crps_values else None,
    }


def _build_forecast_vs_actual(
    player_gameweek: pl.DataFrame,
    player_fixture_actual: pl.DataFrame,
    runs: pl.DataFrame,
) -> dict[str, Any]:
    """forecast_vs_actual.json: each vintage scored against its own season's finalised
    outcomes, at player-gameweek grain, under the ``points_under_rules_2026_27`` measure.

    The join is read-time only: forecast rows keep their ``run_id``, outcome rows keep
    none, and they meet on ``(season, gw, code)``. With no finalised outcomes inside any
    vintage's horizon (the 2026-27 GW1 state), ``has_outcomes`` is false and every block
    is empty -- the UI shows the framework and says why, never zero-filled numbers.
    """
    horizon = {row["run_id"]: row for row in _horizon_projection(runs).iter_rows(named=True)}
    # Finalised points per (season, gw, code): unmeasured (NULL) points stay out, never 0.
    actual_points: dict[tuple[str, int, int], float] = {}
    if player_fixture_actual.height:
        measured = player_fixture_actual.filter(pl.col("points_under_rules_2026_27").is_not_null())
        grouped = measured.group_by(["season", "gw", "code"]).agg(
            pl.col("points_under_rules_2026_27").sum().alias("actual")
        )
        for row in grouped.iter_rows(named=True):
            actual_points[(row["season"], int(row["gw"]), int(row["code"]))] = float(row["actual"])

    scored_by_run: dict[str, list[dict[str, Any]]] = {}
    for row in player_gameweek.iter_rows(named=True):
        run = horizon.get(row["run_id"])
        if run is None:
            raise DashboardJsonError(
                f"forecast row references run {row['run_id']} absent from dim_forecast_run"
            )
        actual = actual_points.get((row["season"], int(row["gw"]), int(row["code"])))
        if actual is None or row["expected_points"] is None:
            continue  # no finalised outcome (yet) for this player-gameweek: unscored, not zero
        distribution = _parse_distribution(row.get("distribution"))
        probabilities_ge_threshold = None
        crps = None
        if distribution is not None:
            total = sum(distribution)
            if total > 0.0:
                probabilities_ge_threshold = sum(distribution[_CALIBRATION_THRESHOLD:]) / total
            crps = _discrete_crps(distribution, actual)
        scored_by_run.setdefault(row["run_id"], []).append(
            {
                "gw": int(row["gw"]),
                "code": int(row["code"]),
                "position": row["position"],
                "ev": float(row["expected_points"]),
                "actual": actual,
                "p_ge_threshold": probabilities_ge_threshold,
                "crps": crps,
            }
        )

    run_records: list[dict[str, Any]] = []
    for run_id in sorted(scored_by_run):
        rows = scored_by_run[run_id]
        run = horizon[run_id]
        by_position = []
        for position in sorted({row["position"] for row in rows}):
            block = _score_block([row for row in rows if row["position"] == position])
            by_position.append({"position": position, **block})
        by_gw = []
        for gw in sorted({row["gw"] for row in rows}):
            block = _score_block([row for row in rows if row["gw"] == gw])
            by_gw.append({"gw": gw, **block})
        calibration = []
        for label, low, high in _CALIBRATION_BUCKETS:
            bucket = [
                row
                for row in rows
                if row["p_ge_threshold"] is not None and low <= row["p_ge_threshold"] < high
            ]
            if not bucket:
                continue
            calibration.append(
                {
                    "bucket": label,
                    "threshold_points": _CALIBRATION_THRESHOLD,
                    "rows": len(bucket),
                    "predicted_mean": sum(row["p_ge_threshold"] for row in bucket) / len(bucket),
                    "observed_rate": sum(
                        1.0 for row in bucket if row["actual"] >= _CALIBRATION_THRESHOLD
                    )
                    / len(bucket),
                }
            )
        run_records.append(
            {
                "run_id": run_id,
                "season": run["run_season"],
                "gw_from": run["gw_from"],
                "gw_to": run["gw_to"],
                **_score_block(rows),
                "by_position": by_position,
                "by_gw": by_gw,
                "calibration": calibration,
            }
        )
    return {"has_outcomes": bool(run_records), "runs": run_records}


def _parse_json_column(raw: object, subject: str) -> Any:
    """Parse one of dim_optimizer_run's deterministic JSON columns, failing closed."""
    if raw is None:
        raise DashboardJsonError(f"{subject} is NULL; the optimizer-run dimension is incomplete")
    if not isinstance(raw, str):
        raise DashboardJsonError(f"{subject} must be a JSON string, found {type(raw).__name__}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DashboardJsonError(f"{subject} is not JSON: {exc}") from exc


def _policy_codes(policy: Mapping[str, Any], key: str, subject: str) -> list[int]:
    raw = policy.get(key, [])
    if not isinstance(raw, list) or any(
        isinstance(code, bool) or not isinstance(code, int) for code in raw
    ):
        raise DashboardJsonError(f"{subject} {key} must be a JSON array of player codes")
    if len(set(raw)) != len(raw):
        raise DashboardJsonError(f"{subject} {key} must contain distinct player codes")
    return sorted(raw)


def _architecture_label(modes: Mapping[str, Any]) -> str:
    attacking = modes.get("attacking_mode")
    assists = modes.get("assists_mode")
    return f"{attacking} goals / {assists} assists"


def _optimizer_plan_metadata(
    dim_optimizer_run: pl.DataFrame, runs: pl.DataFrame
) -> dict[str, dict[str, Any]]:
    """Classify optimizer decisions from explicit provenance, never row/hash ordering."""
    if dim_optimizer_run.height == 0:
        return {}
    modes = _component_modes(runs)
    metadata: dict[str, dict[str, Any]] = {}
    for row in dim_optimizer_run.sort("optimizer_run_id").iter_rows(named=True):
        optimizer_run_id = row["optimizer_run_id"]
        if optimizer_run_id in metadata:
            raise DashboardJsonError(f"duplicate dim_optimizer_run row {optimizer_run_id}")
        run_modes = modes.get(row["forecast_run_id"])
        if run_modes is None:
            raise DashboardJsonError(
                f"optimizer run {optimizer_run_id} references forecast run absent from "
                "dim_forecast_run"
            )
        subject = f"optimizer run {optimizer_run_id} policy"
        policy = _parse_json_column(row["search_policy"], subject)
        if not isinstance(policy, dict):
            raise DashboardJsonError(f"{subject} is not an object")
        locked_codes = _policy_codes(policy, "locked_codes", subject)
        excluded_codes = _policy_codes(policy, "excluded_codes", subject)
        threshold = policy.get("min_bench_appearance", 0.0)
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0.0 <= float(threshold) <= 1.0
        ):
            raise DashboardJsonError(f"{subject} min_bench_appearance must be within [0, 1]")
        explicit_origin = policy.get("plan_origin")
        origin = explicit_origin
        if origin is None:
            origin = (
                "user_custom"
                if locked_codes or excluded_codes or float(threshold) > 0.0
                else "platform"
            )
        if origin not in {"platform", "user_custom"}:
            raise DashboardJsonError(
                f"{subject} plan_origin must be platform or user_custom, found {origin!r}"
            )
        is_default = (
            run_modes.get("attacking_mode") == "v3" and run_modes.get("assists_mode") == "coupled"
        )
        if origin == "user_custom":
            plan_kind = "user_custom"
            label_prefix = "Your plan"
        elif is_default:
            plan_kind = "platform_default"
            label_prefix = "Platform default"
        else:
            plan_kind = "platform_diagnostic"
            label_prefix = "Diagnostic sensitivity"
        normalized_policy = dict(policy)
        normalized_policy["plan_origin"] = origin
        metadata[optimizer_run_id] = {
            "plan_kind": plan_kind,
            "display_label": f"{label_prefix} \u2014 {_architecture_label(run_modes)}",
            "compact_policy": {
                "locked_codes": locked_codes,
                "excluded_codes": excluded_codes,
                "min_bench_appearance": float(threshold),
            },
            "search_policy": normalized_policy,
        }
    return metadata


def _build_optimizer_audit(dim_optimizer_run: pl.DataFrame, runs: pl.DataFrame) -> dict[str, Any]:
    """optimizer_audit.json: the full provenance behind each optimizer decision -- solver
    identity and status, Git heads, squad-rule snapshot (the constraints), bounded-search
    policy, and explicit assumptions.  The squad and transfer path themselves are NOT
    duplicated here: next_gw.json already carries them, and the audit page reads both."""
    modes = _component_modes(runs) if dim_optimizer_run.height else {}
    plan_metadata = _optimizer_plan_metadata(dim_optimizer_run, runs)
    if dim_optimizer_run.height == 0:
        return {"plans": []}
    plans: list[dict[str, Any]] = []
    for row in dim_optimizer_run.sort("optimizer_run_id").iter_rows(named=True):
        optimizer_run_id = row["optimizer_run_id"]
        subject = f"optimizer run {optimizer_run_id}"
        metadata = plan_metadata[optimizer_run_id]
        if row["forecast_run_id"] not in modes:
            raise DashboardJsonError(
                f"{subject} references forecast run absent from dim_forecast_run"
            )
        plans.append(
            {
                "optimizer_run_id": optimizer_run_id,
                "decision_sha256": row["decision_sha256"],
                "forecast_run_id": row["forecast_run_id"],
                "component_modes": modes[row["forecast_run_id"]],
                "plan_kind": metadata["plan_kind"],
                "display_label": metadata["display_label"],
                "as_of": _iso_or_none(row["as_of"]),
                "season": row["season"],
                "gw_from": row["gw_from"],
                "gw_to": row["gw_to"],
                "provenance": {
                    "optimizer_commit_sha": row["optimizer_commit_sha"],
                    "optimizer_worktree_clean": row["optimizer_worktree_clean"],
                    "forecast_artifact_sha256": row["forecast_artifact_sha256"],
                    "forecast_commit_sha": row["forecast_commit_sha"],
                    "squad_rules_path": row["squad_rules_path"],
                    "squad_rules_contract_version": row["squad_rules_contract_version"],
                    "squad_rules_sha256": row["squad_rules_sha256"],
                },
                "solver": {
                    "name": row["solver_name"],
                    "package": row["solver_package"],
                    "package_version": row["solver_package_version"],
                    "binary_version": row["solver_binary_version"],
                    "options": _parse_json_column(row["solver_options"], f"{subject} options"),
                    "seed": row["solver_seed"],
                    "status": row["solver_status"],
                },
                "search_policy": metadata["search_policy"],
                "rules_snapshot": _parse_json_column(row["rules_snapshot"], f"{subject} rules"),
                "assumptions": _parse_json_column(row["assumptions"], f"{subject} assumptions"),
                "status": row["status"],
            }
        )
    return {"plans": plans}


def _run_records(runs: pl.DataFrame, manifest: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for row in runs.sort("run_id").iter_rows(named=True):
        gw_from, gw_to = row["gw_from"], row["gw_to"]
        if not isinstance(gw_from, int) or not isinstance(gw_to, int) or gw_from > gw_to:
            raise DashboardJsonError(
                f"dim_forecast_run {row['run_id']} has an invalid horizon {gw_from}..{gw_to}"
            )
        records.append(
            {
                "run_id": row["run_id"],
                "as_of": _iso_or_none(row["as_of"]),
                "season": row["season"],
                "gw_from": gw_from,
                "gw_to": gw_to,
                "horizon_gameweeks": gw_to - gw_from + 1,
            }
        )
    declared = manifest.get("exported_run_ids")
    if declared != [record["run_id"] for record in records]:
        raise DashboardJsonError(
            "dim_forecast_run run ids disagree with the source manifest exported_run_ids"
        )
    return tuple(records)


def _build(export_dir: Path, manifest: Mapping[str, Any]) -> DashboardReadModels:
    frames = {name: _read_source_table(export_dir, manifest, name) for name in _READ_TABLES}
    runs = _run_records(frames["dim_forecast_run"], manifest)
    teams, ease_version = _build_teams(
        frames["fact_forecast_team_fixture"],
        frames["dim_fixture"],
        frames["dim_team_season"],
        frames["dim_forecast_run"],
        frames["fact_team_form"],
    )
    schedule = _build_current_schedule(
        frames["dim_fixture"],
        frames["dim_team_season"],
        frames["dim_forecast_run"],
        manifest,
    )
    players = _build_players(
        frames["fact_forecast_player_gameweek"],
        frames["fact_forecast_player_fixture"],
        frames["fact_forecast_team_fixture"],
        frames["dim_player_season"],
        frames["dim_team_season"],
        frames["dim_fixture"],
        frames["dim_forecast_run"],
        frames["fact_player_form"],
    )
    player_horizons = _build_player_horizons(
        frames["fact_forecast_player_gameweek"], frames["dim_forecast_run"]
    )
    player_keys = {(row["run_id"], row["season"], int(row["code"])) for row in players}
    horizon_keys = {(row["run_id"], row["season"], int(row["code"])) for row in player_horizons}
    if player_keys != horizon_keys:
        raise DashboardJsonError(
            "player horizon summaries do not reconcile with player identities: "
            f"missing={sorted(player_keys - horizon_keys)[:3]}, "
            f"orphan={sorted(horizon_keys - player_keys)[:3]}"
        )
    next_gw = _build_next_gw(
        frames["fact_optimizer_plan"],
        frames["dim_optimizer_run"],
        frames["dim_forecast_run"],
        frames["fact_forecast_player_gameweek"],
        frames["dim_player_season"],
        frames["dim_team_season"],
    )
    summary = _build_summary(
        frames["dim_forecast_run"],
        frames["fact_forecast_player_gameweek"],
        frames["fact_forecast_team_fixture"],
        frames["dim_gameweek"],
        frames["dim_player_season"],
        frames["dim_team_season"],
        frames["fact_optimizer_plan"],
        frames["dim_optimizer_run"],
        ease_version,
    )
    forecast_vs_actual = _build_forecast_vs_actual(
        frames["fact_forecast_player_gameweek"],
        frames["fact_player_fixture_actual"],
        frames["dim_forecast_run"],
    )
    optimizer_audit = _build_optimizer_audit(
        frames["dim_optimizer_run"], frames["dim_forecast_run"]
    )
    return DashboardReadModels(
        runs=runs,
        teams=teams,
        schedule=schedule,
        players=players,
        player_horizons=player_horizons,
        summary=summary,
        next_gw=next_gw,
        forecast_vs_actual=forecast_vs_actual,
        optimizer_audit=optimizer_audit,
        ease_index_formula_version=ease_version,
    )


def build_dashboard_read_models(export_dir: Path) -> DashboardReadModels:
    """Derive all read models from a published Parquet export without touching DuckDB."""
    source = Path(export_dir)
    return _build(source, _read_source_manifest(source))


def _player_horizon_semantics() -> dict[str, Any]:
    return {
        "grain": ["run_id", "season", "code", "gw_to"],
        "cumulative_from": "dim_forecast_run.gw_from",
        "distribution_combination": "independent-gameweek-convolution-v1",
        "availability": "raw-model-distribution-unadjusted",
        "value_decimal_places": _HORIZON_VALUE_DECIMAL_PLACES,
        "probability_boundary_policy": "preserve-exact-zero-one-v1",
        "thresholds": {
            "p_le": [2],
            "p_ge": list(_HORIZON_THRESHOLDS),
        },
    }


def _player_horizon_wire_players(models: DashboardReadModels) -> list[dict[str, Any]]:
    """Compact named internal values into versioned positional rows for transport."""
    quantum = 10**-_HORIZON_VALUE_DECIMAL_PLACES
    players: list[dict[str, Any]] = []
    for player in models.player_horizons:
        rows: list[list[int | float]] = []
        for horizon in player["horizons"]:
            values: list[int | float] = [int(horizon["gw_to"])]
            for field in _HORIZON_FIELDS[1:]:
                raw_value = float(horizon[field])
                rounded = round(raw_value, _HORIZON_VALUE_DECIMAL_PLACES)
                if field.startswith("p_"):
                    # Quantisation must not relabel possible/impossible or certain/uncertain.
                    # Reserve exact 0 and 1 for source values at those exact boundaries.
                    if raw_value > 0.0 and rounded == 0.0:
                        rounded = quantum
                    elif raw_value < 1.0 and rounded == 1.0:
                        rounded = 1.0 - quantum
                values.append(0.0 if rounded == 0.0 else rounded)
            rows.append(values)
        players.append(
            {
                "run_id": player["run_id"],
                "season": player["season"],
                "code": player["code"],
                "horizons": rows,
            }
        )
    return players


def render_read_model_files(models: DashboardReadModels) -> dict[str, bytes]:
    """Deterministic strict-JSON bytes for all read models; identical models, identical bytes."""
    return {
        FIXTURE_MATRIX_FILENAME: _canonical_json_bytes(
            {
                "schema": FIXTURE_MATRIX_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                "teams": list(models.teams),
                "schedule": models.schedule,
            },
            indent=2,
        ),
        PLAYERS_FILENAME: _canonical_json_bytes(
            {
                "schema": PLAYERS_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                "players": list(models.players),
            },
            indent=2,
        ),
        PLAYER_HORIZONS_FILENAME: _canonical_json_bytes(
            {
                "schema": PLAYER_HORIZONS_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                "semantics": _player_horizon_semantics(),
                "horizon_fields": list(_HORIZON_FIELDS),
                "players": _player_horizon_wire_players(models),
            }
        ),
        NEXT_GW_FILENAME: _canonical_json_bytes(
            {
                "schema": NEXT_GW_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                "plans": list(models.next_gw["plans"]),
            },
            indent=2,
        ),
        SUMMARY_FILENAME: _canonical_json_bytes(
            {
                "schema": SUMMARY_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                **models.summary,
            },
            indent=2,
        ),
        FORECAST_VS_ACTUAL_FILENAME: _canonical_json_bytes(
            {
                "schema": FORECAST_VS_ACTUAL_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                **models.forecast_vs_actual,
            },
            indent=2,
        ),
        OPTIMIZER_AUDIT_FILENAME: _canonical_json_bytes(
            {
                "schema": OPTIMIZER_AUDIT_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                **models.optimizer_audit,
            },
            indent=2,
        ),
    }


def _validate_player_horizon_document(document: Mapping[str, Any]) -> None:
    if set(document) != {
        "schema",
        "json_schema_version",
        "semantics",
        "horizon_fields",
        "players",
    }:
        raise DashboardJsonError("player_horizons.json has a malformed schema envelope")
    if document.get("semantics") != _player_horizon_semantics():
        raise DashboardJsonError("player_horizons.json lost its versioned probability semantics")
    if document.get("horizon_fields") != list(_HORIZON_FIELDS):
        raise DashboardJsonError("player_horizons.json lost its positional horizon field contract")
    players = document.get("players")
    if not isinstance(players, list):
        raise DashboardJsonError("player_horizons.json players must be an array")
    player_keys: set[tuple[str, str, int]] = set()
    expected_player_keys = {"run_id", "season", "code", "horizons"}
    probability_keys = _HORIZON_FIELDS[2:]
    for player in players:
        if not isinstance(player, dict) or set(player) != expected_player_keys:
            raise DashboardJsonError("player_horizons.json has a malformed player record")
        run_id, season, code = player["run_id"], player["season"], player["code"]
        if (
            not isinstance(run_id, str)
            or not run_id
            or not isinstance(season, str)
            or not season
            or not isinstance(code, int)
            or isinstance(code, bool)
            or code <= 0
        ):
            raise DashboardJsonError("player_horizons.json has an invalid player identity")
        player_key = (run_id, season, code)
        if player_key in player_keys:
            raise DashboardJsonError(f"player_horizons.json repeats player identity {player_key}")
        player_keys.add(player_key)
        horizons = player["horizons"]
        if not isinstance(horizons, list) or not horizons:
            raise DashboardJsonError(f"player_horizons.json {player_key} has no horizons")
        previous_gw = 0
        previous_xp = -math.inf
        previous_le_2 = math.inf
        previous_ge = dict.fromkeys(probability_keys[1:], -math.inf)
        for raw_horizon in horizons:
            if not isinstance(raw_horizon, list) or len(raw_horizon) != len(_HORIZON_FIELDS):
                raise DashboardJsonError(f"player_horizons.json {player_key} has a malformed row")
            horizon = dict(zip(_HORIZON_FIELDS, raw_horizon, strict=True))
            gw_to, xp = horizon["gw_to"], horizon["xp"]
            if (
                not isinstance(gw_to, int)
                or isinstance(gw_to, bool)
                or gw_to <= previous_gw
                or not isinstance(xp, (int, float))
                or isinstance(xp, bool)
                or not math.isfinite(xp)
                or xp < 0.0
                or xp < previous_xp - _HORIZON_WIRE_ABSOLUTE_TOLERANCE
                or float(xp) != round(float(xp), _HORIZON_VALUE_DECIMAL_PLACES)
            ):
                raise DashboardJsonError(
                    f"player_horizons.json {player_key} horizons are not ordered cumulative values"
                )
            for key in probability_keys:
                value = horizon[key]
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or not 0.0 <= value <= 1.0
                    or float(value) != round(float(value), _HORIZON_VALUE_DECIMAL_PLACES)
                ):
                    raise DashboardJsonError(
                        f"player_horizons.json {player_key} {key} is not a probability"
                    )
            if horizon["p_le_2"] > previous_le_2 + _HORIZON_WIRE_ABSOLUTE_TOLERANCE or any(
                horizon[key] < previous_ge[key] - _HORIZON_WIRE_ABSOLUTE_TOLERANCE
                for key in probability_keys[1:]
            ):
                raise DashboardJsonError(
                    f"player_horizons.json {player_key} probabilities are not cumulative"
                )
            if any(
                horizon[left] < horizon[right] - _HORIZON_WIRE_ABSOLUTE_TOLERANCE
                for left, right in pairwise(probability_keys[1:])
            ):
                raise DashboardJsonError(
                    f"player_horizons.json {player_key} threshold tails are not ordered"
                )
            if horizon["p_le_2"] + horizon["p_ge_2"] < 1.0 - _HORIZON_WIRE_ABSOLUTE_TOLERANCE:
                raise DashboardJsonError(
                    f"player_horizons.json {player_key} violates inclusive score-2 overlap"
                )
            previous_gw = gw_to
            previous_xp = float(xp)
            previous_le_2 = float(horizon["p_le_2"])
            previous_ge = {key: float(horizon[key]) for key in probability_keys[1:]}


def _validate_player_horizon_generation(
    documents: Mapping[str, Mapping[str, Any]], manifest: Mapping[str, Any]
) -> None:
    """Reconcile the additive horizon file with its generation, not just itself."""
    player_rows = documents[PLAYERS_FILENAME].get("players")
    horizon_rows = documents[PLAYER_HORIZONS_FILENAME].get("players")
    runs = manifest.get("runs")
    if not isinstance(player_rows, list) or not isinstance(horizon_rows, list):
        raise DashboardJsonError("player read models lost their top-level player arrays")
    if not isinstance(runs, list):
        raise DashboardJsonError("read-model manifest runs must be an array")

    run_horizons: dict[tuple[str, str], tuple[int, int]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise DashboardJsonError("read-model manifest has a malformed run record")
        run_id, season = run.get("run_id"), run.get("season")
        gw_from, gw_to = run.get("gw_from"), run.get("gw_to")
        horizon_gameweeks = run.get("horizon_gameweeks")
        if (
            not isinstance(run_id, str)
            or not run_id
            or not isinstance(season, str)
            or not season
            or not isinstance(gw_from, int)
            or isinstance(gw_from, bool)
            or not isinstance(gw_to, int)
            or isinstance(gw_to, bool)
            or gw_from <= 0
            or gw_from > gw_to
            or not isinstance(horizon_gameweeks, int)
            or isinstance(horizon_gameweeks, bool)
            or horizon_gameweeks != gw_to - gw_from + 1
        ):
            raise DashboardJsonError("read-model manifest has an invalid run horizon")
        run_key = (run_id, season)
        if run_key in run_horizons:
            raise DashboardJsonError("read-model manifest repeats a run horizon")
        run_horizons[run_key] = (gw_from, gw_to)

    player_keys: set[tuple[str, str, int]] = set()
    for player in player_rows:
        if not isinstance(player, dict):
            raise DashboardJsonError("players.json has a malformed player record")
        run_id, season, code = player.get("run_id"), player.get("season"), player.get("code")
        if (
            not isinstance(run_id, str)
            or not isinstance(season, str)
            or not isinstance(code, int)
            or isinstance(code, bool)
        ):
            raise DashboardJsonError("players.json has an invalid player identity")
        player_key = (run_id, season, code)
        if player_key in player_keys:
            raise DashboardJsonError(f"players.json repeats player identity {player_key}")
        player_keys.add(player_key)

    horizon_keys: set[tuple[str, str, int]] = set()
    for player in horizon_rows:
        # The file-local validator has already established the exact record shape.
        horizon_key = (player["run_id"], player["season"], player["code"])
        horizon_keys.add(horizon_key)
        run_horizon = run_horizons.get((horizon_key[0], horizon_key[1]))
        if run_horizon is None:
            raise DashboardJsonError(
                f"player_horizons.json {horizon_key} references a run absent from the manifest"
            )
        expected_gws = list(range(run_horizon[0], run_horizon[1] + 1))
        actual_gws = [row[0] for row in player["horizons"]]
        if actual_gws != expected_gws:
            raise DashboardJsonError(
                f"player_horizons.json {horizon_key} has endpoints {actual_gws}, expected "
                f"{expected_gws}"
            )
    if player_keys != horizon_keys:
        raise DashboardJsonError(
            "player_horizons.json does not reconcile with players.json: "
            f"missing={sorted(player_keys - horizon_keys)[:3]}, "
            f"orphan={sorted(horizon_keys - player_keys)[:3]}"
        )
    player_runs = {(run_id, season) for run_id, season, _code in player_keys}
    if set(run_horizons) != player_runs:
        raise DashboardJsonError(
            "player_horizons.json does not cover every manifest run: "
            f"missing={sorted(set(run_horizons) - player_runs)[:3]}, "
            f"orphan={sorted(player_runs - set(run_horizons))[:3]}"
        )


def _file_row_count(document: Mapping[str, Any], filename: str) -> int:
    """Rows the manifest counts for one file: its top-level array, or 1 for an object."""
    if filename == PLAYER_HORIZONS_FILENAME:
        players = document["players"]
        return sum(len(player["horizons"]) for player in players)
    list_key = _FILE_LIST_KEY[filename]
    if list_key is None:
        return 1
    return len(document[list_key])


def _manifest_content_sha256(manifest: Mapping[str, Any]) -> str:
    content = dict(manifest)
    content.pop("generated_at", None)
    content.pop("content_sha256", None)
    return _sha256_bytes(_canonical_json_bytes(content))


def _validate_directory(
    directory: Path, expected_files: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    actual = {path.name for path in directory.iterdir()}
    expected_names = {MANIFEST_FILENAME, *expected_files}
    if actual != expected_names:
        raise DashboardJsonError(
            f"read-model directory must contain exactly {sorted(expected_names)}; found "
            f"{sorted(actual)}"
        )
    documents: dict[str, Mapping[str, Any]] = {}
    for filename, entry in sorted(expected_files.items()):
        payload = (directory / filename).read_bytes()
        if _sha256_bytes(payload) != entry["sha256"]:
            raise DashboardJsonError(f"{filename} does not match the manifest SHA-256")
        document = _strict_json_loads(payload.decode("utf-8"))
        if (
            document.get("schema") != _FILE_SCHEMA[filename]
            or document.get("json_schema_version") != DASHBOARD_JSON_SCHEMA_VERSION
        ):
            raise DashboardJsonError(f"{filename} lost its schema envelope")
        if filename == PLAYER_HORIZONS_FILENAME:
            _validate_player_horizon_document(document)
        if _file_row_count(document, filename) != entry["row_count"]:
            raise DashboardJsonError(f"{filename} row count does not match the manifest")
        documents[filename] = document
    manifest = _strict_json_loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    if set(manifest) != _MANIFEST_KEYS:
        raise DashboardJsonError("read-model manifest fields drifted")
    if (
        manifest["schema"] != DASHBOARD_JSON_SCHEMA
        or manifest["json_schema_version"] != DASHBOARD_JSON_SCHEMA_VERSION
    ):
        raise DashboardJsonError("read-model manifest schema/version does not match this emitter")
    if manifest["files"] != dict(expected_files):
        raise DashboardJsonError("read-model manifest files block does not match the directory")
    if manifest["content_sha256"] != _manifest_content_sha256(manifest):
        raise DashboardJsonError("read-model manifest content_sha256 does not verify")
    run_ids = manifest["run_ids"]
    if run_ids != [record["run_id"] for record in manifest["runs"]]:
        raise DashboardJsonError("read-model manifest run_ids disagree with its runs records")
    if run_ids != sorted(run_ids):
        raise DashboardJsonError("read-model manifest run ids are not deterministically ordered")
    _validate_player_horizon_generation(documents, manifest)
    return manifest


def validate_dashboard_json(output_dir: Path) -> dict[str, Any]:
    """Re-open and validate a published read-model directory without touching DuckDB."""
    directory = Path(output_dir)
    try:
        manifest = _strict_json_loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    except OSError as exc:
        raise DashboardJsonError(f"cannot read read-model manifest: {exc}") from exc
    except BiExportError as exc:
        raise DashboardJsonError(f"read-model manifest is not strict JSON: {exc}") from exc
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_FILE_LIST_KEY):
        raise DashboardJsonError("read-model manifest files block is malformed")
    return _validate_directory(directory, files)


def export_dashboard_json(
    export_dir: Path,
    output_dir: Path,
    *,
    generated_at: datetime | None = None,
    before_publish: Callable[[], None] | None = None,
) -> DashboardJsonResult:
    """Build, validate, and atomically publish the dashboard read models.

    ``before_publish`` runs after the staged directory validates and immediately before the
    atomic swap, for concurrency testing exactly as in :func:`fpl.publish.export.export_bi`.
    """
    source = Path(export_dir)
    target = _resolve_output_dir(Path(output_dir))
    stamp = generated_at or datetime.now(UTC)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    stamp = stamp.astimezone(UTC)

    with _export_lock(target):
        original = _published_snapshot(target)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        )
        try:
            source_manifest = _read_source_manifest(source)
            models = _build(source, source_manifest)
            payloads = render_read_model_files(models)

            files: dict[str, dict[str, Any]] = {}
            row_counts = {
                FIXTURE_MATRIX_FILENAME: len(models.teams),
                PLAYERS_FILENAME: len(models.players),
                PLAYER_HORIZONS_FILENAME: sum(
                    len(player["horizons"]) for player in models.player_horizons
                ),
                NEXT_GW_FILENAME: len(models.next_gw["plans"]),
                SUMMARY_FILENAME: 1,
                FORECAST_VS_ACTUAL_FILENAME: len(models.forecast_vs_actual["runs"]),
                OPTIMIZER_AUDIT_FILENAME: len(models.optimizer_audit["plans"]),
            }
            for filename, payload in payloads.items():
                path = staging / filename
                path.write_bytes(payload)
                _fsync_file(path)
                files[filename] = {
                    "row_count": row_counts[filename],
                    "sha256": _sha256_bytes(payload),
                }
            manifest: dict[str, Any] = {
                "schema": DASHBOARD_JSON_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                "generated_at": _isoformat(stamp),
                "source": {
                    "export_schema": source_manifest["schema"],
                    "export_schema_version": source_manifest["schema_version"],
                    "semantic_contract_version": source_manifest["semantic_contract_version"],
                    "export_content_sha256": source_manifest["content_sha256"],
                    "export_created_at": source_manifest["created_at"],
                    "database_sha256": source_manifest["database_sha256"],
                },
                "runs": [dict(record) for record in models.runs],
                "run_ids": [record["run_id"] for record in models.runs],
                "ease_index_formula_version": models.ease_index_formula_version,
                "files": files,
            }
            manifest["content_sha256"] = _manifest_content_sha256(manifest)
            manifest_path = staging / MANIFEST_FILENAME
            manifest_path.write_bytes(_canonical_json_bytes(manifest, indent=2))
            _fsync_file(manifest_path)
            _fsync_directory(staging)
            _validate_directory(staging, files)
            if before_publish is not None:
                before_publish()
            _publish_generation(output_dir=target, temporary_dir=staging, original=original)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    return DashboardJsonResult(
        output_dir=target,
        manifest_path=target / MANIFEST_FILENAME,
        content_sha256=str(manifest["content_sha256"]),
        run_ids=tuple(str(record["run_id"]) for record in models.runs),
        fixture_matrix_rows=len(models.teams),
        players_rows=len(models.players),
        player_horizon_rows=sum(len(player["horizons"]) for player in models.player_horizons),
        next_gw_plans=len(models.next_gw["plans"]),
    )


__all__ = [
    "DASHBOARD_JSON_SCHEMA",
    "DASHBOARD_JSON_SCHEMA_VERSION",
    "FIXTURE_MATRIX_FILENAME",
    "FIXTURE_MATRIX_SCHEMA",
    "FORECAST_VS_ACTUAL_FILENAME",
    "FORECAST_VS_ACTUAL_SCHEMA",
    "MANIFEST_FILENAME",
    "NEXT_GW_FILENAME",
    "NEXT_GW_SCHEMA",
    "PLAYERS_FILENAME",
    "PLAYERS_SCHEMA",
    "PLAYER_HORIZONS_FILENAME",
    "PLAYER_HORIZONS_SCHEMA",
    "SUMMARY_FILENAME",
    "SUMMARY_SCHEMA",
    "DashboardJsonError",
    "DashboardJsonResult",
    "DashboardReadModels",
    "build_dashboard_read_models",
    "export_dashboard_json",
    "render_read_model_files",
    "validate_dashboard_json",
]
