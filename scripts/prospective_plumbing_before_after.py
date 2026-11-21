"""Before/after regeneration report for the prospective live data-plumbing repairs.

    python scripts/prospective_plumbing_before_after.py --db data/fpl.duckdb --output REPORT.json

Runs the prospective forecast twice at the next deadline's cutoff on the SAME database:

* BEFORE -- the pre-repair behaviour, reconstructed by monkeypatching in this harness only:
  the finalized-live Stage A training rows are suppressed and the not-available-to-the-club
  prior rule is disabled (`_PRIOR_SEASON_MIN_APPEARANCES = 0`, which is exactly the old
  `if values` filter).
* AFTER -- the repaired code path unchanged.

Nothing in `src/` is modified; the patches live and die with this process. The report
covers the four required diffs: team lambdas, the SDP/incumbent fallback share, the xP of
the Defect-1 population (players with >=4 of GW6-10 at 60+ minutes and a 2025-26 archive
appearance rate below 0.6 over n >= 35 rows), and every change of the top-20 player rank
by position. Read-only over the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl.jobs import prospective_points_v1 as prospective
from fpl.jobs.prospective_points_v1 import predict_prospective_points
from fpl.storage.db import connect

_EMPTY_FRAME: pl.DataFrame | None = None


def _next_deadline(con: Any, season: str, as_of_floor: datetime) -> tuple[int, datetime]:
    bootstrap = prospective.live_bootstrap_snapshot(con, season, as_of_floor)
    events = sorted(bootstrap.data["events"], key=lambda e: int(e["id"]))
    for event in events:
        if not event.get("finished", False):
            deadline = datetime.fromisoformat(str(event["deadline_time"]).replace("Z", "+00:00"))
            return int(event["id"]), deadline
    raise ValueError("no unfinished gameweek in the bootstrap payload")


def _defect1_population(con: Any, as_of: datetime) -> list[dict[str, Any]]:
    """The 26-player scope: >=4 of GW6-10 with 60+ minutes, prior-2025-26 rate < 0.6, n >= 35."""
    rows = con.execute(
        """
        WITH prior AS (
            SELECT code, avg(CASE WHEN minutes >= 1 THEN 1.0 ELSE 0.0 END) AS rate, count(*) AS n
            FROM mart_fact_player_fixture
            WHERE season = '2025-26' AND minutes IS NOT NULL AND kickoff_time < ?
            GROUP BY code
        ),
        current AS (
            SELECT code, count(*) FILTER (WHERE minutes >= 60) AS big
            FROM mart_fact_player_fixture_live
            WHERE season = '2026-27' AND gw BETWEEN 6 AND 10
              AND minutes IS NOT NULL AND kickoff_time < ?
            GROUP BY code
        )
        SELECT c.code, p.rate, p.n, c.big
        FROM current AS c JOIN prior AS p USING (code)
        WHERE c.big >= 4 AND p.rate < 0.6 AND p.n >= 35
        ORDER BY c.code
        """,
        [as_of, as_of],
    ).fetchall()
    return [
        {"code": int(code), "prior_rate": float(rate), "prior_n": int(n), "big": int(big)}
        for code, rate, n, big in rows
    ]


def _arm(con: Any, *, as_of: datetime, season: str, gw_from: int, gw_to: int, before: bool) -> Any:
    restore_frame = prospective.live_finalized_team_match_rows
    restore_min = prospective._PRIOR_SEASON_MIN_APPEARANCES
    if before:
        empty = pl.DataFrame(
            schema={
                "season": pl.String,
                "gw": pl.Int32,
                "fixture": pl.Int32,
                "was_home": pl.Boolean,
                "team_code": pl.Int32,
                "opponent_team_code": pl.Int32,
                "goals_for": pl.Int32,
                "goals_against": pl.Int32,
                "team_xg": pl.Float64,
                "team_xgc": pl.Float64,
                "fdr": pl.Int32,
                "kickoff_time": pl.Datetime(time_zone="UTC"),
            }
        )
        prospective.live_finalized_team_match_rows = lambda _con, _as_of: empty
        prospective._PRIOR_SEASON_MIN_APPEARANCES = 0
    try:
        return predict_prospective_points(
            con,
            as_of=as_of,
            season=season,
            gw_from=gw_from,
            gw_to=gw_to,
            db_path=None,
            repo=None,
        )
    finally:
        prospective.live_finalized_team_match_rows = restore_frame
        prospective._PRIOR_SEASON_MIN_APPEARANCES = restore_min


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--gw-to", type=int, default=None, help="horizon end (default: gw_from+4)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    con = connect(args.db, read_only=True)
    try:
        floor = datetime.now(UTC)
        gw_from, deadline = _next_deadline(con, args.season, floor)
        gw_to = args.gw_to or (gw_from + 4)
        print(f"next deadline: {args.season} GW{gw_from} at {deadline.isoformat()}")
        population = _defect1_population(con, deadline)
        print(f"defect-1 population: {len(population)} players")
        before = _arm(
            con, as_of=deadline, season=args.season, gw_from=gw_from, gw_to=gw_to, before=True
        )
        after = _arm(
            con, as_of=deadline, season=args.season, gw_from=gw_from, gw_to=gw_to, before=False
        )

        # 1. Team lambdas.
        before_teams = {
            (r.gw, r.fixture, r.team_code): (r.lambda_for, r.lambda_against)
            for r in before.team_records
        }
        after_teams = {
            (r.gw, r.fixture, r.team_code): (r.lambda_for, r.lambda_against)
            for r in after.team_records
        }
        assert before_teams.keys() == after_teams.keys()
        changed = [
            {
                "gw": gw,
                "fixture": fixture,
                "team_code": code,
                "lambda_for_before": before_teams[(gw, fixture, code)][0],
                "lambda_for_after": after_teams[(gw, fixture, code)][0],
                "lambda_against_before": before_teams[(gw, fixture, code)][1],
                "lambda_against_after": after_teams[(gw, fixture, code)][1],
            }
            for gw, fixture, code in sorted(before_teams)
            if abs(before_teams[(gw, fixture, code)][0] - after_teams[(gw, fixture, code)][0])
            > 1e-9
            or abs(before_teams[(gw, fixture, code)][1] - after_teams[(gw, fixture, code)][1])
            > 1e-9
        ]
        print(f"team-fixture lambda rows changed: {len(changed)} of {len(before_teams)}")

        # 2. Fallback share.
        def _selector_share(result: Any) -> dict[str, Any]:
            provenance = result.football_environment_provenance
            if provenance is None:
                return {"mode": "incumbent_only"}
            return {
                "mode": "sdp_v2_with_incumbent_fallback",
                "selector_counts_team_predictions": provenance.get(
                    "selector_counts_team_predictions"
                ),
                "health": provenance.get("health", {}).get("matches_using_fallback"),
            }

        share_before = _selector_share(before)
        share_after = _selector_share(after)
        league_avg_before = sum(1 for r in before.team_records if r.stage_a_league_average_team)
        league_avg_after = sum(1 for r in after.team_records if r.stage_a_league_average_team)

        # 3. Defect-1 players' xP.
        codes = [p["code"] for p in population]
        totals_before = {t.code: t for t in before.player_totals}
        totals_after = {t.code: t for t in after.player_totals}
        defect1_xp = [
            {
                **p,
                "xp_before": totals_before[c].expected_points if c in totals_before else None,
                "xp_after": totals_after[c].expected_points if c in totals_after else None,
            }
            for p, c in zip(population, codes, strict=True)
        ]
        for row in defect1_xp:
            if row["xp_before"] is not None and row["xp_after"] is not None:
                row["delta"] = row["xp_after"] - row["xp_before"]

        # 4. Top-20 rank changes by position.
        def _ranks(result: Any) -> dict[str, dict[int, int]]:
            by_pos: dict[str, list[Any]] = {}
            for t in result.player_totals:
                by_pos.setdefault(t.position, []).append(t)
            return {
                pos: {
                    t.code: rank
                    for rank, t in enumerate(
                        sorted(rows, key=lambda t: (-t.expected_points, t.code))[:20], start=1
                    )
                }
                for pos, rows in by_pos.items()
            }

        ranks_before = _ranks(before)
        ranks_after = _ranks(after)
        rank_changes = []
        for pos in sorted(set(ranks_before) | set(ranks_after)):
            entered = [
                {"code": c, "rank": r}
                for c, r in ranks_after.get(pos, {}).items()
                if c not in ranks_before.get(pos, {})
            ]
            exited = [
                {"code": c, "rank": r}
                for c, r in ranks_before.get(pos, {}).items()
                if c not in ranks_after.get(pos, {})
            ]
            moved = [
                {"code": c, "before": ranks_before[pos][c], "after": ranks_after[pos][c]}
                for c in ranks_before.get(pos, {})
                if c in ranks_after.get(pos, {}) and ranks_before[pos][c] != ranks_after[pos][c]
            ]
            if entered or exited or moved:
                rank_changes.append(
                    {"position": pos, "entered": entered, "exited": exited, "moved": moved}
                )

        report = {
            "schema": "prospective_plumbing_before_after/v1",
            "as_of": deadline.isoformat(),
            "season": args.season,
            "gw_from": gw_from,
            "gw_to": gw_to,
            "team_lambda_rows_changed": len(changed),
            "team_lambda_changes": changed,
            "fallback_share": {"before": share_before, "after": share_after},
            "stage_a_league_average_team_rows": {
                "before": league_avg_before,
                "after": league_avg_after,
            },
            "defect1_population": population,
            "defect1_xp": defect1_xp,
            "top20_rank_changes_by_position": rank_changes,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
        print(f"fallback share before={share_before} after={share_after}")
        lifted = [r for r in defect1_xp if r.get("delta", 0) > 0.05]
        print(f"defect-1 players with xP lift > 0.05: {len(lifted)} of {len(defect1_xp)}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
