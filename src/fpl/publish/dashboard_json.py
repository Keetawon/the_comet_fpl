"""Per-page dashboard read models over the published BI Parquet export.

This is the P1.7a half of the dashboard boundary: it pre-shapes the joins the two
exploration pages need (fixture matrix and players) into application JSON, so the static
browser app only renders and ships no client-side query engine.  It reads ONLY the
immutable Parquet export published by :mod:`fpl.publish.export` -- never the production
DuckDB -- and publishes its own directory through the same atomic generation-swap
machinery, imported rather than duplicated.

Downstream transport only: nothing here changes a model, the composer, an optimizer
artifact, the scoring config, the semantic contract, or the Parquet export itself.
Failures raised as :class:`DashboardJsonError` come from this module; the reused publish
machinery surfaces its own :class:`fpl.publish.export.BiExportError` subclasses.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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
DASHBOARD_JSON_SCHEMA_VERSION: Final[int] = 1
FIXTURE_MATRIX_SCHEMA: Final[str] = "fpl.dashboard-fixture-matrix"
PLAYERS_SCHEMA: Final[str] = "fpl.dashboard-players"
MANIFEST_FILENAME: Final[str] = "manifest.json"
FIXTURE_MATRIX_FILENAME: Final[str] = "fixture_matrix.json"
PLAYERS_FILENAME: Final[str] = "players.json"

# Exactly the tables the read models read.  The source export is contract-complete, so a
# missing entry means the manifest was not produced by fpl.publish.export.
_READ_TABLES: Final[tuple[str, ...]] = (
    "dim_forecast_run",
    "dim_player_season",
    "dim_team_season",
    "dim_fixture",
    "fact_forecast_team_fixture",
    "fact_team_form",
    "fact_forecast_player_gameweek",
    "fact_player_form",
    "fact_forecast_player_fixture",
)
_WINDOW_LABELS: Final[tuple[str, ...]] = ("last_3", "last_5", "last_10", "season_to_date")
_FILE_LIST_KEY: Final[dict[str, str]] = {
    FIXTURE_MATRIX_FILENAME: "teams",
    PLAYERS_FILENAME: "players",
}
_FILE_SCHEMA: Final[dict[str, str]] = {
    FIXTURE_MATRIX_FILENAME: FIXTURE_MATRIX_SCHEMA,
    PLAYERS_FILENAME: PLAYERS_SCHEMA,
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
    """The derived, publishable content of both exploration read models."""

    runs: tuple[dict[str, Any], ...]
    teams: tuple[dict[str, Any], ...]
    players: tuple[dict[str, Any], ...]
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
    return DashboardReadModels(
        runs=runs,
        teams=teams,
        players=players,
        ease_index_formula_version=ease_version,
    )


def build_dashboard_read_models(export_dir: Path) -> DashboardReadModels:
    """Derive both read models from a published Parquet export without touching DuckDB."""
    source = Path(export_dir)
    return _build(source, _read_source_manifest(source))


def render_read_model_files(models: DashboardReadModels) -> dict[str, bytes]:
    """Deterministic strict-JSON bytes for both read models; identical models, identical bytes."""
    return {
        FIXTURE_MATRIX_FILENAME: _canonical_json_bytes(
            {
                "schema": FIXTURE_MATRIX_SCHEMA,
                "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
                "teams": list(models.teams),
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
    }


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
        if len(document[_FILE_LIST_KEY[filename]]) != entry["row_count"]:
            raise DashboardJsonError(f"{filename} row count does not match the manifest")
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
            for filename, payload in payloads.items():
                path = staging / filename
                path.write_bytes(payload)
                _fsync_file(path)
                files[filename] = {
                    "row_count": len(models.teams)
                    if filename == FIXTURE_MATRIX_FILENAME
                    else len(models.players),
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
    )


__all__ = [
    "DASHBOARD_JSON_SCHEMA",
    "DASHBOARD_JSON_SCHEMA_VERSION",
    "FIXTURE_MATRIX_FILENAME",
    "FIXTURE_MATRIX_SCHEMA",
    "MANIFEST_FILENAME",
    "PLAYERS_FILENAME",
    "PLAYERS_SCHEMA",
    "DashboardJsonError",
    "DashboardJsonResult",
    "DashboardReadModels",
    "build_dashboard_read_models",
    "export_dashboard_json",
    "render_read_model_files",
    "validate_dashboard_json",
]
