"""Descriptive FPL archive xG supplements. Never supplies a model/SDP health input."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from fpl.config import load_data_quality
from fpl.features.pit import AsOf

TABLES = ("raw_merged_gw", "raw_players", "raw_fixtures", "raw_teams")


class FplXgSupplement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)
    value: float = Field(ge=0)
    source: Literal["fpl_archive_player_sum"] = "fpl_archive_player_sum"
    evidence_class: Literal["retrospective_descriptive"] = "retrospective_descriptive"
    season: str
    fixture: int = Field(gt=0)
    gw: int = Field(gt=0)
    kickoff_time: str
    subject_team_code: int = Field(gt=0)
    opponent_team_code: int = Field(gt=0)
    was_home: bool
    source_known_at: str
    player_rows: int = Field(ge=11)
    appeared_players: int = Field(ge=11)
    starters: Literal[11] = 11
    source_sha256: dict[str, str]
    records_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _id(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("invalid exact archive identity")
    return int(value)


def _number(value: Any) -> float:
    if value is None or value == "":
        raise ValueError("unmeasured archive value")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("invalid archive value")
    return parsed


def _index(rows: list[dict[str, Any]], key: str) -> dict[int, dict[str, Any]]:
    result = {_id(row[key]): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("contradictory archive identities")
    return result


def _source(
    con: duckdb.DuckDBPyConnection, season: str, cutoff: datetime
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], datetime]:
    tables: dict[str, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    stamps: list[datetime] = []
    for table in TABLES:  # Only these fixed identifiers enter SQL.
        count, first, last = con.execute(
            f"SELECT count(*),min(epoch_us(_ingested_at)),max(epoch_us(_ingested_at)) "
            f"FROM {table} WHERE season = ?",
            [season],
        ).fetchone() or (0, None, None)
        if not count or first != last or first is None:
            raise ValueError("missing or mixed archive capture")
        stamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(first))
        if stamp > cutoff:
            raise ValueError("archive capture is after dashboard cutoff")
        log = con.execute(
            "SELECT sha256,row_count FROM raw_ingest_log WHERE season=? "
            "AND source_table=? AND epoch_us(ingested_at)=?",
            [season, table, first],
        ).fetchall()
        if len(log) != 1 or log[0][1] != count or not re.fullmatch(r"[0-9a-f]{64}", log[0][0]):
            raise ValueError("archive source receipt does not reconcile")
        hashes[table] = log[0][0]
        stamps.append(stamp)
        # Exact duplicate source rows are safe to deduplicate; conflicting repeats are not.
        cursor = con.execute(
            f"SELECT DISTINCT * EXCLUDE (season,_ingested_at) FROM {table} WHERE season=?",
            [season],
        )
        columns = [item[0] for item in cursor.description]
        tables[table] = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    return tables, hashes, max(stamps)


def archive_team_xg(
    con: duckdb.DuckDBPyConnection, *, seasons: list[str], cutoff: datetime
) -> tuple[dict[tuple[str, int, int], dict[str, Any]], list[str]]:
    """Sum every recorded player row, including GK, after fixture-local validation.

    Eleven explicit starts plus all recorded rows measured is the coverage witness;
    this is not an independent witness of every substitute's presence in the archive.
    End-season roster club membership is deliberately never used for past fixtures.
    """
    result: dict[tuple[str, int, int], dict[str, Any]] = {}
    notes: list[str] = []
    cutoff = AsOf(cutoff).ts
    repairs = load_data_quality().nullify
    for season in sorted(set(seasons)):
        try:
            tables, hashes, stamp = _source(con, season, cutoff)
            players = _index(tables["raw_players"], "id")
            teams = _index(tables["raw_teams"], "id")
            fixtures = _index(tables["raw_fixtures"], "id")
            if len({_id(t["code"]) for t in teams.values()}) != len(teams):
                raise ValueError("duplicate stable team identity")
            player_codes = [_id(p["code"]) for p in players.values() if p["element_type"] != "5"]
            if len(set(player_codes)) != len(player_codes):
                raise ValueError("duplicate stable player identity")
            grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for row in tables["raw_merged_gw"]:
                grouped[_id(row["fixture"])].append(row)
        except (ValueError, KeyError, TypeError, duckdb.Error):
            notes.append(
                f"{season}: FPL archive xG supplement unavailable (source/identity/cutoff)."
            )
            continue
        rejected = 0
        for fixture_id, rows in sorted(grouped.items()):
            try:
                fixture = fixtures[fixture_id]
                gw = _id(fixture["event"])
                kickoff = AsOf(datetime.fromisoformat(fixture["kickoff_time"])).ts
                if (
                    kickoff >= cutoff
                    or kickoff > stamp
                    or str(fixture["finished"]).lower() != "true"
                ):
                    raise ValueError("unfinished/future fixture")
                if any(
                    r.season == season
                    and "expected_goals" in r.columns
                    and (r.gw_min is None or gw >= r.gw_min)
                    and (r.gw_max is None or gw <= r.gw_max)
                    for r in repairs
                ):
                    raise ValueError("declared unmeasured xG interval")
                home, away = _id(fixture["team_h"]), _id(fixture["team_a"])
                if home == away:
                    raise ValueError("same team on both sides")
                by_side: dict[int, list[dict[str, Any]]] = {home: [], away: []}
                seen: set[int] = set()
                for row in rows:
                    player = players[_id(row["element"])]
                    if player["element_type"] == "5":
                        continue
                    code = _id(player["code"])
                    if player["element_type"] not in ("1", "2", "3", "4") or code in seen:
                        raise ValueError("conflicting player fixture")
                    seen.add(code)
                    if str(row["was_home"]).lower() not in ("true", "false"):
                        raise ValueError("unresolved venue")
                    own, opponent = (
                        (home, away) if str(row["was_home"]).lower() == "true" else (away, home)
                    )
                    if (
                        _id(row["GW"]) != gw
                        or _id(row["opponent_team"]) != opponent
                        or row["team"] != teams[own]["name"]
                        or AsOf(datetime.fromisoformat(row["kickoff_time"])).ts != kickoff
                    ):
                        raise ValueError("fixture-time identity mismatch")
                    minutes, starts, xg = (
                        _number(row.get(k)) for k in ("minutes", "starts", "expected_goals")
                    )
                    if minutes > 120 or minutes != int(minutes) or starts not in (0, 1):
                        raise ValueError("invalid exposure")
                    if minutes == 0 and (starts != 0 or xg != 0):
                        raise ValueError("inconsistent zero-minute evidence")
                    by_side[own].append(
                        {"code": code, "minutes": minutes, "starts": starts, "xg": xg}
                    )
                pair: dict[tuple[str, int, int], dict[str, Any]] = {}
                for own, opponent in ((home, away), (away, home)):
                    members = sorted(by_side[own], key=lambda r: r["code"])
                    appeared = sum(r["minutes"] > 0 for r in members)
                    if appeared < 11 or sum(r["starts"] for r in members) != 11:
                        raise ValueError("incomplete explicit starters/exposure")
                    records = json.dumps(
                        members, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                    value = float(sum((Decimal(str(r["xg"])) for r in members), Decimal(0)))
                    supplement = FplXgSupplement(
                        value=value,
                        season=season,
                        fixture=fixture_id,
                        gw=gw,
                        kickoff_time=kickoff.isoformat(),
                        subject_team_code=_id(teams[own]["code"]),
                        opponent_team_code=_id(teams[opponent]["code"]),
                        was_home=own == home,
                        source_known_at=stamp.isoformat(),
                        player_rows=len(members),
                        appeared_players=appeared,
                        source_sha256=hashes,
                        records_sha256=hashlib.sha256(records).hexdigest(),
                    ).model_dump()
                    pair[season, fixture_id, supplement["subject_team_code"]] = supplement
                result.update(pair)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                rejected += 1
        notes.append(
            f"{season}: {len(grouped) - rejected}/{len(grouped)} FPL archive fixtures "
            "passed xG supplement checks."
        )
    return result, notes


def apply_team_xg_supplements(
    con: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]], *, cutoff: datetime, current: str
) -> list[str]:
    sources, notes = archive_team_xg(
        con, seasons=[r["season"] for r in rows if r["season"] != current], cutoff=cutoff
    )
    for row in rows:
        row["display_supplements"] = {}
        for metric, opponent in (("expected_goals", False), ("expected_goals_allowed", True)):
            code = row["opponent_team_code"] if opponent else row["team_code"]
            source = sources.get((row["season"], row["fixture"], code))
            if source is None or row["sdp"].get(metric) is not None:
                continue
            if (
                source["gw"] != row["gw"]
                or datetime.fromisoformat(source["kickoff_time"])
                != datetime.fromisoformat(row["kickoff_time"])
                or source["was_home"] != (not row["was_home"] if opponent else row["was_home"])
                or source["opponent_team_code"]
                != (row["team_code"] if opponent else row["opponent_team_code"])
            ):
                continue
            row["display_supplements"][metric] = source
            row["known_at"] = max(
                datetime.fromisoformat(row["known_at"]),
                datetime.fromisoformat(source["source_known_at"]),
            ).isoformat()
    return notes
