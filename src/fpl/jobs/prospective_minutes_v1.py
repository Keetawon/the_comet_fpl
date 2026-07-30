"""Prospective Stage B Candidate V1 minutes prediction (DEVELOPMENT-ONLY).

    python -m fpl.jobs.prospective_minutes_v1            # GW1 2026/27 at the deadline
    python -m fpl.jobs.prospective_minutes_v1 --as-of 2026-08-21T17:30:00Z --season 2026-27 --gw 1

This is Candidate V1 (`shrunk_trailing_5_player_minutes_v1`) applied **prospectively** to a
future gameweek. Candidate V1 is **development-only and unpromoted**: this output is NOT a
validated production forecast, and it claims no historical lift. It exists to exercise the
registered live/prospective path end to end -- the versioned player registry selects the roster,
the archive supplies trailing history, and the frozen closed form emits a four-bin distribution
-- so the procedure can be validated against 2026/27 outcomes as they accrue.

For a given ``as_of``:

  1. The target roster is selected from the versioned player registry with ``known_at <= as_of``
     (``PointInTimeView.player_registry``), BEFORE the model sees entity, position, or club.
  2. Each player's trailing-five prior player-fixture history is built under the strict cutoff
     ``kickoff_time < as_of`` (including zero-minute rows).
  3. Candidate V1's frozen closed form ``p_k = (c_k + alpha * q_k) / (n + alpha)`` is applied,
     with ``q`` the fold-local raw position prior and exactly ``q`` when ``n = 0``.
  4. The four-bin distribution is emitted per ``(code, fixture)``; double-gameweek fixtures are
     never collapsed (a player in two fixtures gets two rows -- identical distributions, by the
     contract's ``double_gameweek_same_distribution`` policy, but separate rows).

``alpha`` is selected by the **registered nested inner walk-forward**
(``ShrunkTrailing5PlayerMinutesV1.fit`` on the ``as_of`` history) -- not read from a frozen
development value -- and that fact is recorded in the output provenance. No new selection rule
is introduced. Availability (``status`` / chance-of-playing) is NOT an input here; consuming it
would require a separately named candidate under a contract amendment.

The archive is opened read-only. The output record carries provenance: ``as_of``, the registry
capture ids consumed, git HEAD, the config fingerprint, and the archive fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from fpl.config import Phase2EvaluationConfig, config_dir, load_phase2_evaluation, repo_root
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.models.minutes_v1 import ShrunkTrailing5PlayerMinutesV1
from fpl.storage.db import connect, default_db_path
from fpl.types import Position
from fpl.validate.minutes_baselines import TargetRow
from fpl.validate.minutes_harness import player_fixture_history

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger("fpl.jobs.prospective_minutes_v1")

# GW1 2026/27 reference instants (the contract's prospective confirmation set).
GW1_2026_27_DEADLINE = datetime.fromisoformat("2026-08-21T17:30:00+00:00")
GW1_2026_27_FIRST_KICKOFF = datetime.fromisoformat("2026-08-21T19:00:00+00:00")

_DISCLAIMER = (
    "DEVELOPMENT-ONLY: Candidate V1 is unpromoted. This is not a validated production forecast "
    "and claims no historical lift. The versioned registry and first-kickoff history make this "
    "point-in-time safe, but validity is established prospectively as 2026/27 accrues, not here."
)
_ALPHA_SOURCE = "registered nested inner walk-forward (ShrunkTrailing5PlayerMinutesV1.fit)"


@dataclass(frozen=True, slots=True)
class ProspectivePrediction:
    """One emitted four-bin distribution for one (code, fixture)."""

    season: str
    gw: int
    code: int
    fixture: int
    kickoff_time: datetime
    position: str
    team_id: int
    p_0: float
    p_1_59: float
    p_60_89: float
    p_90: float


@dataclass(frozen=True, slots=True)
class ProspectiveProvenance:
    as_of: datetime
    candidate: str
    contract_version: str
    seed: int
    alpha_source: str
    selected_alpha: float
    used_inner_holdout: bool
    inner_holdout_observed_gameweeks: int
    registry_capture_ids: tuple[str, ...]
    roster_size: int
    fixture_count: int
    row_count: int
    commit_sha: str | None
    config_sha256: str | None
    archive_sha256: str | None
    label: str


@dataclass(frozen=True, slots=True)
class ProspectiveResult:
    provenance: ProspectiveProvenance
    predictions: tuple[ProspectivePrediction, ...]
    # Aggregate mean of each bin across the emitted rows (a sanity quantity, not a forecast).
    bin_means: tuple[float, float, float, float]


def _git_head(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def predict_prospective_minutes(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str,
    gw: int,
    config: Phase2EvaluationConfig | None = None,
    db_path: Path | str | None = None,
    repo: Path | None = None,
) -> ProspectiveResult:
    """Apply Candidate V1 prospectively at ``as_of`` for one season/gameweek.

    ``con`` is opened read-only by the caller. ``db_path``/``repo`` enable the archive/config/git
    fingerprints in the provenance record; when omitted (e.g. an in-memory test database) those
    fields are ``None``.
    """
    resolved = config or load_phase2_evaluation()

    # 1. Roster from the versioned registry (known_at <= as_of), before the model sees anything.
    source = FeatureSource(con)
    view = PointInTimeView(source, AsOf(as_of))
    registry = view.player_registry()
    # polars returns native python values; typed Any so int()/str()/datetime flow through mypy.
    reg_codes: list[Any] = registry["code"].to_list()
    reg_positions: list[Any] = registry["position"].to_list()
    reg_teams: list[Any] = registry["team_id"].to_list()
    capture_ids_raw: list[Any] = registry["capture_id"].to_list() if registry.height else []
    capture_ids = tuple(sorted(set(capture_ids_raw)))

    # The target fixtures for this gameweek, from the versioned live schedule (known_at <= as_of).
    schedule = view.schedule(seasons=[season])
    gw_fixtures = schedule.filter(
        (pl.col("season") == pl.lit(season)) & (pl.col("gw") == pl.lit(gw))
    )
    gw_team: list[Any] = gw_fixtures["team_id"].to_list()
    gw_fixture: list[Any] = gw_fixtures["fixture"].to_list()
    gw_kickoff: list[Any] = gw_fixtures["kickoff_time"].to_list()
    gw_opponent: list[Any] = gw_fixtures["opponent_team_id"].to_list()
    gw_was_home: list[Any] = gw_fixtures["was_home"].to_list()
    # schedule() emits one row per team-side (home + away), so count distinct fixtures.
    fixture_count = int(gw_fixtures["fixture"].n_unique()) if gw_fixtures.height else 0
    fixtures_by_team: dict[int, list[tuple[int, datetime, int, bool]]] = {}
    for i in range(len(gw_fixture)):
        fixtures_by_team.setdefault(int(gw_team[i]), []).append(
            (int(gw_fixture[i]), gw_kickoff[i], int(gw_opponent[i]), bool(gw_was_home[i]))
        )

    # 2. Trailing history under the strict cutoff (labels included; this is training data).
    history = player_fixture_history(con, as_of=as_of)
    # 3. Fit Candidate V1 on the as_of history -- alpha comes from the registered nested
    #    inner walk-forward inside fit(), not from a frozen value.
    model = ShrunkTrailing5PlayerMinutesV1(config=resolved).fit(history, as_of=as_of)
    params = model.parameters()

    # 4. Emit per (code, fixture); double-gameweek fixtures are separate rows, never collapsed.
    predictions: list[ProspectivePrediction] = []
    for index in range(len(reg_codes)):
        code = int(reg_codes[index])
        position = Position(str(reg_positions[index]))
        team_id = int(reg_teams[index])
        for fixture_id, kickoff, opponent, was_home in fixtures_by_team.get(team_id, ()):
            target = TargetRow(
                season=season,
                gw=gw,
                fixture=fixture_id,
                kickoff_time=kickoff,
                code=code,
                position=position,
                team_id=team_id,
                opponent_team_id=opponent,
                was_home=was_home,
            )
            p0, p1, p2, p3 = model.predict(target)
            predictions.append(
                ProspectivePrediction(
                    season=season,
                    gw=gw,
                    code=code,
                    fixture=fixture_id,
                    kickoff_time=kickoff,
                    position=str(position),
                    team_id=team_id,
                    p_0=p0,
                    p_1_59=p1,
                    p_60_89=p2,
                    p_90=p3,
                )
            )

    bin_means = (
        sum(r.p_0 for r in predictions) / len(predictions) if predictions else 0.0,
        sum(r.p_1_59 for r in predictions) / len(predictions) if predictions else 0.0,
        sum(r.p_60_89 for r in predictions) / len(predictions) if predictions else 0.0,
        sum(r.p_90 for r in predictions) / len(predictions) if predictions else 0.0,
    )

    repo_path = repo or repo_root()
    config_path = config_dir() / "phase2_evaluation.yaml"
    provenance = ProspectiveProvenance(
        as_of=as_of,
        candidate=model.name,
        contract_version=resolved.contract_version,
        seed=resolved.training.seed,
        alpha_source=_ALPHA_SOURCE,
        selected_alpha=float(params["selected_alpha"]),
        used_inner_holdout=bool(params["used_inner_holdout"]),
        inner_holdout_observed_gameweeks=int(params["inner_holdout_observed_gameweeks"]),
        registry_capture_ids=capture_ids,
        roster_size=registry.height,
        fixture_count=fixture_count,
        row_count=len(predictions),
        commit_sha=_git_head(repo_path),
        config_sha256=_file_sha256(config_path),
        archive_sha256=_file_sha256(Path(db_path)) if db_path is not None else None,
        label=_DISCLAIMER,
    )
    return ProspectiveResult(
        provenance=provenance, predictions=tuple(predictions), bin_means=bin_means
    )


def result_to_record(result: ProspectiveResult) -> dict[str, object]:
    """A strict-JSON-serialisable view of the result (provenance + predictions + bin means)."""
    prov = result.provenance
    return {
        "schema": "stage_b_candidate_v1_prospective/v1",
        "status": "development_only_not_a_production_forecast",
        "label": prov.label,
        "provenance": {
            "as_of": prov.as_of.isoformat(),
            "candidate": prov.candidate,
            "contract_version": prov.contract_version,
            "seed": prov.seed,
            "alpha_source": prov.alpha_source,
            "selected_alpha": prov.selected_alpha,
            "used_inner_holdout": prov.used_inner_holdout,
            "inner_holdout_observed_gameweeks": prov.inner_holdout_observed_gameweeks,
            "registry_capture_ids": list(prov.registry_capture_ids),
            "roster_size": prov.roster_size,
            "fixture_count": prov.fixture_count,
            "row_count": prov.row_count,
            "commit_sha": prov.commit_sha,
            "config_sha256": prov.config_sha256,
            "archive_sha256": prov.archive_sha256,
        },
        "bin_means": {
            "0": result.bin_means[0],
            "1_59": result.bin_means[1],
            "60_89": result.bin_means[2],
            "90": result.bin_means[3],
        },
        "predictions": [
            {
                "season": p.season,
                "gw": p.gw,
                "code": p.code,
                "fixture": p.fixture,
                "kickoff_time": p.kickoff_time.isoformat(),
                "position": p.position,
                "team_id": p.team_id,
                "p_0": p.p_0,
                "p_1_59": p.p_1_59,
                "p_60_89": p.p_60_89,
                "p_90": p.p_90,
            }
            for p in result.predictions
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prospective Stage B Candidate V1 minutes prediction (DEVELOPMENT-ONLY)."
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--as-of", default=None, help="ISO 8601 as_of (default: GW1 2026/27 deadline)"
    )
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--gw", type=int, default=1)
    parser.add_argument("--output", type=Path, default=None, help="write JSON record to this path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else GW1_2026_27_DEADLINE
    db_path = args.db or default_db_path()
    repo = repo_root()

    con = connect(db_path, read_only=True)
    try:
        result = predict_prospective_minutes(
            con, as_of=as_of, season=args.season, gw=args.gw, db_path=db_path, repo=repo
        )
    finally:
        con.close()

    record = result_to_record(result)
    payload = json.dumps(record, indent=2, sort_keys=True, allow_nan=False)
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
        logger.info("wrote %d prediction(s) to %s", result.provenance.row_count, args.output)
    print(_DISCLAIMER)
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
