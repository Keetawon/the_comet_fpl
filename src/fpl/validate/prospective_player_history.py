"""One cutoff-selected player history for prospective component consumers.

Archive evidence keeps its existing retrospective-prior contract. Live observations
are selected by the existing PIT reader, never by the latest reporting mart.
This module does not alter an estimator or a historical evaluation adapter.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

import duckdb
import polars as pl

from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.models.bps_bonus import PlayerRow

HISTORY_CONTRACT = "prospective_archive_live_player_history/v1"
IDENTITY = ["season", "code", "fixture"]
ORDER = ["kickoff_time", "season", "fixture", "code"]


def load_player_history(con: duckdb.DuckDBPyConnection, as_of: datetime) -> pl.DataFrame:
    """Whole-row live revisions take precedence over overlapping archive identities.

    Deduplicate before removing unknown minutes: a newer NULL must not resurrect
    an old measurement. Stable club identity is season-qualified and cutoff-known.
    """
    frame = PointInTimeView(FeatureSource(con), AsOf(as_of)).observed_player_fixtures()
    frame = frame.unique(subset=IDENTITY, keep="last", maintain_order=True).with_columns(
        pl.col("kickoff_time").dt.convert_time_zone("UTC")
    )
    teams = con.execute(
        """
        SELECT season, team_id, team_code FROM mart_dim_team
        UNION ALL
        SELECT season, team_id, team_code FROM stg_live_team_version
        WHERE known_at <= ?
        QUALIFY row_number() OVER (
            PARTITION BY season, team_id ORDER BY known_at DESC, capture_id DESC
        ) = 1
        """,
        [as_of],
    ).pl()
    # A season-local ID cannot identify two clubs. No name matching or current-club
    # substitution for historical fixture membership is allowed.
    conflicts = (
        teams.drop_nulls("team_code")
        .group_by("season", "team_id")
        .agg(pl.col("team_code").n_unique().alias("codes"))
    )
    if conflicts.filter(pl.col("codes") > 1).height:
        raise ValueError("contradictory season-qualified player-history club identity")
    teams = teams.unique(subset=["season", "team_id"], keep="last", maintain_order=True)
    return (
        frame.join(teams, on=["season", "team_id"], how="left", validate="m:1")
        .filter(pl.col("minutes").is_not_null())
        .sort(ORDER, maintain_order=True)
    )


def history_provenance(
    con: duckdb.DuckDBPyConnection,
    frame: pl.DataFrame,
    as_of: datetime,
    *,
    trailing: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """Bind consumed observations, live versions and latest-five fixture identities."""
    live = (
        con.execute(
            """
        SELECT season, code, fixture, capture_id, known_at, kickoff_time
        FROM mart_fact_player_fixture_live WHERE known_at <= ?
        QUALIFY row_number() OVER (
            PARTITION BY season, code, fixture ORDER BY known_at DESC, capture_id DESC
        ) = 1
        """,
            [as_of],
        )
        .pl()
        .with_columns(pl.col("kickoff_time", "known_at").dt.convert_time_zone("UTC"))
        .filter(pl.col("kickoff_time") < as_of.astimezone(UTC))
    )
    live = live.join(frame.select(IDENTITY), on=IDENTITY, how="semi").sort(ORDER)
    versions = live.select("season", "code", "fixture", "capture_id", "known_at")
    recent: dict[str, list[dict[str, Any]]] = {}
    appeared: dict[str, list[dict[str, Any]]] = {}
    selected = frame if trailing is None else trailing
    for row in selected.select(*IDENTITY, "gw", "minutes").iter_rows(named=True):
        history = recent.setdefault(str(row["code"]), [])
        history.append(row)
        del history[:-5]
        if row["minutes"] > 0:
            history = appeared.setdefault(str(row["code"]), [])
            history.append(row)
            del history[:-5]
    return {
        "contract": HISTORY_CONTRACT,
        "as_of": as_of.isoformat(),
        "row_count": frame.height,
        "observations_sha256": hashlib.sha256(frame.write_json().encode()).hexdigest(),
        "live_row_count": live.height,
        "live_versions_sha256": hashlib.sha256(versions.write_json().encode()).hexdigest(),
        "live_captures": sorted(set(live["capture_id"].to_list())),
        "latest_live_known_at": (
            None if live.is_empty() else cast(datetime, live["known_at"].max()).isoformat()
        ),
        "by_season_gw": frame.group_by("season", "gw").len().sort("season", "gw").to_dicts(),
        "trailing_latest_five_fixtures": recent,
        "trailing_latest_five_appearances": appeared,
        "prior_season_appearance": "archive-only completed-season prior; unchanged",
    }


def canonical_provenance(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def residual_training_rows(frame: pl.DataFrame) -> list[PlayerRow]:
    """The existing BPS row projection over the shared history, without NULL filling."""
    required = [
        "minutes",
        "goals_scored",
        "assists",
        "clean_sheets",
        "penalties_saved",
        "influence",
        "creativity",
        "bps",
        "bonus",
    ]
    rows: list[PlayerRow] = []
    for r in frame.drop_nulls(required).iter_rows(named=True):
        if r["position"] not in {"GK", "DEF", "MID", "FWD"}:
            continue
        cbi = r["clearances_blocks_interceptions"]
        rows.append(
            PlayerRow(
                code=int(r["code"]),
                position=str(r["position"]),
                minutes=int(r["minutes"]),
                goals_scored=int(r["goals_scored"]),
                assists=int(r["assists"]),
                clean_sheets=int(r["clean_sheets"]),
                penalties_saved=int(r["penalties_saved"]),
                clearances_blocks_interceptions=None if cbi is None else int(cbi),
                influence=float(r["influence"]),
                creativity=float(r["creativity"]),
                bps=int(r["bps"]),
                bonus=int(r["bonus"]),
                order_key=(r["kickoff_time"].timestamp(), str(r["season"]), int(r["fixture"])),
            )
        )
    return rows
