"""Forecast the football environment for future fixtures.

    python -m fpl.jobs.prospective_environment_v2 --gw-from 1 --gw-to 5

The football half of V2 run forward: fit the engine on everything known before a cutoff, then
predict a `FixtureEnvironment` per upcoming fixture. It emits the football layer only -- goal
distributions, shot and chance environments, clean-sheet probabilities -- and deliberately does
NOT emit player points.

**Why this is a separate job rather than a flag on `prospective_points_v1`.** V2's team
environment did not clear its pre-registered gate (`docs/v2-team-engine-development.md`:
+0.2867% against a 1% bar, with a 2021-22 regression). Wiring an ungated candidate into the
path that produces the owner's decision pack would change a forecast default on the strength of
a result that explicitly does not license it. The composer adapter
(`models/component_engine_v2.py`) means V2 CAN feed the composer whenever a gate is cleared;
until then this job produces the football forecast for analysis, and the prospective default is
untouched.

Point-in-time: `as_of` defaults to the current season's GW1 deadline and the engine is fitted
only on rows with `kickoff_time < as_of`. Upcoming fixtures come from the schedule, which
carries no outcome column.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fpl.artifacts.fixture_environment import FixtureEnvironment, summarise_coverage
from fpl.config import load_sources
from fpl.models.football_engine_v2 import DEFAULT_SIGNALS, MultiSignalTeamEngine
from fpl.storage.db import connect
from fpl.transform.pl_sdp import ARCHIVE_PROVIDER
from fpl.validate.v2_environment_harness import load_team_frame, promoted_team_codes

logger = logging.getLogger("fpl.prospective_environment_v2")

SCHEMA_VERSION = 1


def _upcoming_fixtures(
    con: Any, *, season: str, gw_from: int, gw_to: int, as_of: datetime
) -> pl.DataFrame:
    """Scheduled fixtures in the horizon, resolved to cross-season club identity.

    Read from the live fixture/team registry where it exists and the archive otherwise. The
    projection carries schedule metadata only -- no outcome column appears, so a future fixture
    cannot leak its result even in principle.
    """
    relation = con.execute(
        """
        WITH live AS (
            SELECT season, fixture, gw, kickoff_time, team_h, team_a,
                   row_number() OVER (
                       PARTITION BY season, fixture ORDER BY known_at DESC, capture_id DESC
                   ) AS version_rank
            FROM stg_live_fixture_version
            WHERE season = ? AND known_at <= ?
        ),
        latest AS (SELECT * FROM live WHERE version_rank = 1),
        teams AS (
            SELECT season, team_id, team_code, row_number() OVER (
                       PARTITION BY season, team_id ORDER BY known_at DESC, capture_id DESC
                   ) AS version_rank
            FROM stg_live_team_version WHERE season = ? AND known_at <= ?
        ),
        team_codes AS (SELECT * FROM teams WHERE version_rank = 1)
        SELECT l.season, l.fixture, l.gw, l.kickoff_time,
               h.team_code AS home_team_code, a.team_code AS away_team_code
        FROM latest AS l
        LEFT JOIN team_codes AS h ON h.season = l.season AND h.team_id = l.team_h
        LEFT JOIN team_codes AS a ON a.season = l.season AND a.team_id = l.team_a
        WHERE l.gw BETWEEN ? AND ?
          AND h.team_code IS NOT NULL AND a.team_code IS NOT NULL
        ORDER BY l.gw, l.kickoff_time, l.fixture
        """,
        [season, as_of, season, as_of, gw_from, gw_to],
    )
    return pl.from_arrow(relation.to_arrow_table())  # type: ignore[return-value]


def _serialise(environment: FixtureEnvironment) -> dict[str, Any]:
    def side(name: str) -> dict[str, Any]:
        block = asdict(getattr(environment, name))
        # The full pmf stays out of the wire payload for the same reason it does everywhere
        # else in this repository: consumers must not sum or re-derive probabilities. The
        # clean-sheet probability, which is the pmf's zero mass, is published explicitly.
        block.pop("goal_distribution", None)
        block["signal_coverage"] = dict(block.get("signal_coverage") or {})
        block["clean_sheet_probability"] = environment.clean_sheet_probability(
            getattr(environment, name).team_code
        )
        return block

    return {
        "season": environment.season,
        "fixture": environment.fixture,
        "gw": environment.gw,
        "kickoff_time": (
            environment.kickoff_time.isoformat() if environment.kickoff_time else None
        ),
        "rho": environment.rho,
        "engine": environment.engine,
        "home": side("home"),
        "away": side("away"),
    }


def run(
    *,
    db_path: Path | None = None,
    season: str | None = None,
    gw_from: int = 1,
    gw_to: int = 5,
    as_of: datetime | None = None,
    provider: str = ARCHIVE_PROVIDER,
    output: Path | None = None,
) -> dict[str, Any]:
    sources = load_sources()
    resolved_season = season or sources.current_season.season
    cutoff = as_of or sources.current_season.gw1_deadline

    con = connect(db_path, read_only=True)
    try:
        frame = load_team_frame(con, provider=provider)
        promoted = promoted_team_codes(con)
        upcoming = _upcoming_fixtures(
            con, season=resolved_season, gw_from=gw_from, gw_to=gw_to, as_of=cutoff
        )
    finally:
        con.close()

    training = frame.filter(pl.col("kickoff_time") < cutoff)
    if training.is_empty():
        raise RuntimeError(
            f"no team-match rows before {cutoff.isoformat()} for provider {provider!r}; "
            "the engine cannot be fitted"
        )
    engine = MultiSignalTeamEngine(signals=list(DEFAULT_SIGNALS))
    engine.set_promoted(promoted)
    engine.set_prediction_season(resolved_season)
    engine.fit(training)

    environments = [
        engine.predict_environment(
            season=str(row["season"]),
            fixture=int(row["fixture"]),
            home_team_code=int(row["home_team_code"]),
            away_team_code=int(row["away_team_code"]),
            gw=None if row["gw"] is None else int(row["gw"]),
            kickoff_time=row["kickoff_time"],
        )
        for row in upcoming.iter_rows(named=True)
    ]

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "development_only",
        "generated_at": datetime.now(UTC).isoformat(),
        "engine": engine.name,
        "provider": provider,
        "season": resolved_season,
        "as_of": cutoff.isoformat(),
        "horizon": {"gw_from": gw_from, "gw_to": gw_to},
        "training_rows": training.height,
        "parameters": engine.parameters.as_report(),
        "signal_coverage": summarise_coverage(environments),
        "not_a_forecast_default": (
            "The V2 team environment did not clear its pre-registered gate; see "
            "docs/v2-team-engine-development.md. This is the football forecast for analysis, "
            "not the prospective points default."
        ),
        "fixtures": [_serialise(environment) for environment in environments],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        logger.info("wrote %s", output)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forecast future fixture environments (V2).")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", default=None)
    parser.add_argument("--gw-from", type=int, default=1)
    parser.add_argument("--gw-to", type=int, default=5)
    parser.add_argument("--provider", default=ARCHIVE_PROVIDER)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    report = run(
        db_path=args.db,
        season=args.season,
        gw_from=args.gw_from,
        gw_to=args.gw_to,
        provider=args.provider,
        output=args.output,
    )
    print(
        f"{len(report['fixtures'])} fixture(s), engine {report['engine']}, "
        f"as_of {report['as_of']}, trained on {report['training_rows']} rows"
    )
    for fixture in report["fixtures"][:10]:
        home, away = fixture["home"], fixture["away"]
        print(
            f"  GW{fixture['gw']} fx{fixture['fixture']}: "
            f"{home['team_code']} {home['expected_goals']:.2f} - "
            f"{away['expected_goals']:.2f} {away['team_code']}  "
            f"CS(h)={home['clean_sheet_probability']:.3f} "
            f"SOTfaced(h)="
            + (
                f"{home['expected_shots_on_target_against']:.2f}"
                if home["expected_shots_on_target_against"] is not None
                else "n/a"
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
