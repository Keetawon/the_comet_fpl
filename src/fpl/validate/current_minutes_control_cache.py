"""Shared prequential CURRENT-selector proxy reference; no new candidate is fitted.

This is an explicit retrospective capability, not a prospective entry point. It
uses the actual prospective summary helpers and the unchanged incumbent V3 fit.
Archive target price is consulted only through the separately licensed boundary.
The cache contains distributions/lineage, not a new Stage B V3 evaluation.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fpl.config import load_phase2_evaluation, repo_root
from fpl.jobs.competitive_participation_pilot import (
    file_sha256,
    git_clean_head,
    publish_json,
)
from fpl.jobs.prospective_points_v1 import (
    last_team_code,
    prior_season_appearance_rate,
    trailing5_minute_bins,
)
from fpl.models.minutes_v3 import ConcentrationAdaptiveShrinkagePlayerMinutesV3
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.minutes_baselines import MinuteBins, TargetRow
from fpl.validate.minutes_harness import generate_minutes_folds, player_fixture_history
from fpl.validate.prospective_incumbent_adapter import (
    V3_NAME,
    DefaultMinutesInputs,
    RegistryEvidence,
)
from fpl.validate.retrospective_minutes_proxy import (
    EVIDENCE_CLASS,
    MISSING_PRICE,
    NAME,
    ArchiveFixturePrice,
    HistoricalPriceRoster,
    HistoricalRosterMember,
    reproduce_with_archive_cold_price_proxy,
)

CONFIG = "config/retrospective_minutes_control_cache.yaml"
CONFIG_SHA256 = "044a405c03fde988fc6035b97e028fe3f195fec20fae06d8dbad471d1f193cb9"
SOURCES = (
    CONFIG,
    "config/retrospective_current_minutes_proxy_v1.yaml",
    "config/phase2_evaluation.yaml",
    "src/fpl/validate/current_minutes_control_cache.py",
    "src/fpl/validate/retrospective_minutes_proxy.py",
    "src/fpl/validate/prospective_incumbent_adapter.py",
    "src/fpl/validate/minutes_baselines.py",
    "src/fpl/validate/minutes_harness.py",
    "src/fpl/validate/points_harness.py",
    "src/fpl/models/minutes_v1.py",
    "src/fpl/models/minutes_v2.py",
    "src/fpl/models/minutes_v3.py",
    "src/fpl/models/minutes_shrinkage.py",
    "src/fpl/models/price_starter_prior.py",
    "src/fpl/jobs/prospective_points_v1.py",
)
logger = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def target_roster(
    con: duckdb.DuckDBPyConnection, season: str, gw: int
) -> tuple[list[TargetRow], dict[int, int]]:
    """Existing nine-field roster proxy, never current-match outcomes or prices."""
    rows = con.execute(
        """SELECT f.season,f.gw,f.fixture,f.kickoff_time,f.code,f.position,
                  f.team_id,f.opponent_team_id,f.was_home,t.team_code
           FROM mart_fact_player_fixture f LEFT JOIN mart_dim_team t
             ON f.season=t.season AND f.team_id=t.team_id
           WHERE f.season=? AND f.gw=? AND f.minutes IS NOT NULL
           ORDER BY f.fixture,f.code""",
        [season, gw],
    ).pl()
    targets: list[TargetRow] = []
    clubs: dict[int, int] = {}
    positions: dict[int, Position] = {}
    for row in rows.iter_rows(named=True):
        if row["team_code"] is None:
            raise ValueError("unresolved season-qualified target club")
        code, club = int(row["code"]), int(row["team_code"])
        position = Position(str(row["position"]))
        if code in clubs and (clubs[code] != club or positions[code] != position):
            raise ValueError("same-GW target roster club/position ambiguity")
        clubs[code], positions[code] = club, position
        targets.append(
            TargetRow(
                season=season,
                gw=gw,
                fixture=int(row["fixture"]),
                kickoff_time=row["kickoff_time"],
                code=code,
                position=position,
                team_id=int(row["team_id"]),
                opponent_team_id=int(row["opponent_team_id"]),
                was_home=bool(row["was_home"]),
            )
        )
    if len({(r.fixture, r.code) for r in targets}) != len(targets):
        raise ValueError("duplicate target player-fixture")
    return targets, clubs


def archive_prices(
    con: duckdb.DuckDBPyConnection, *, season: str, gw: int, database_hash: str
) -> tuple[ArchiveFixturePrice, ...]:
    """EXPLICIT proxy-only target metadata read, no invented capture timestamp."""
    frame = con.execute(
        """SELECT f.season,f.gw,f.fixture,f.code,t.team_code,f.position,
                  f.kickoff_time,f.value
           FROM mart_fact_player_fixture f JOIN mart_dim_team t
             ON f.season=t.season AND f.team_id=t.team_id
           WHERE f.season=? AND f.gw=? AND f.minutes IS NOT NULL
           ORDER BY f.fixture,f.code""",
        [season, gw],
    ).pl()
    return tuple(
        ArchiveFixturePrice(
            season=season,
            gw=gw,
            fixture=int(r["fixture"]),
            code=int(r["code"]),
            team_code=int(r["team_code"]),
            position=Position(str(r["position"])),
            kickoff=r["kickoff_time"],
            value=None if r["value"] is None else int(r["value"]),
            source_identity=f"archive:{database_hash}:{season}:{r['fixture']}:{r['code']}:value",
            source_known_at=None,
        )
        for r in frame.iter_rows(named=True)
    )


def build_fold(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    gw: int,
    as_of: datetime,
    database_hash: str,
) -> dict[str, Any]:
    """One incumbent fit; target observations cannot enter this method's predictors."""
    targets, clubs = target_roster(con, season, gw)
    if not targets or min(r.kickoff_time for r in targets) != as_of:
        raise ValueError("cutoff does not equal the preregistered first-kickoff proxy")
    history = tuple(player_fixture_history(con, as_of=as_of))
    if any(r.kickoff_time >= as_of or (r.season, r.gw) == (season, gw) for r in history):
        raise ValueError("same-GW or future history in comparator fit")
    maximum = max((r.kickoff_time for r in history), default=None)
    last = last_team_code(con, as_of, current_club=clubs)
    prior = prior_season_appearance_rate(con, as_of, current_club=clubs)
    recent = trailing5_minute_bins(
        con, as_of, MinuteBins.from_config(load_phase2_evaluation()), current_club=clubs
    )
    source = f"archive:{database_hash}:{season}:GW{gw}:asof:{as_of.isoformat()}"
    members = {
        r.code: HistoricalRosterMember(
            code=r.code,
            team_code=clubs[r.code],
            position=r.position,
            eligible_history_present=r.code in last,
            prior_appearance=prior.get(r.code, (None, 0)),
            maximum_prior_event=maximum,
        )
        for r in targets
    }
    loaded: HistoricalPriceRoster | None = None

    def price_loader() -> HistoricalPriceRoster:
        nonlocal loaded
        if loaded is None:
            loaded = HistoricalPriceRoster(
                season=season,
                gw=gw,
                as_of=as_of,
                source_identity=source,
                database_sha256=database_hash,
                complete_for_declared_archive_population=True,
                members=tuple(members[code] for code in sorted(members)),
                prices=archive_prices(con, season=season, gw=gw, database_hash=database_hash),
            )
        return loaded

    model = ConcentrationAdaptiveShrinkagePlayerMinutesV3().fit(history, as_of=as_of)
    rows = []
    for target in targets:
        raw = model.predict(target)
        result = reproduce_with_archive_cold_price_proxy(
            DefaultMinutesInputs(
                target=target,
                as_of=as_of,
                raw_v3=raw,
                raw_v3_as_of=as_of,
                raw_v3_model_name=V3_NAME,
                current_team_code=clubs[target.code],
                eligible_history_present=target.code in last,
                trailing5=recent.get(target.code),
                prior_appearance=prior.get(target.code, (None, 0)),
                maximum_prior_event=maximum,
                prior_source_identity=source,
                registry=RegistryEvidence("archive_roster_proxy", source, None, False),
                price=MISSING_PRICE,
                established_price=MISSING_PRICE,
            ),
            load_archive=price_loader,
        )
        if result.selector.blockers or result.selector.distribution is None:
            raise ValueError(f"comparator unavailable for {target}: {result.selector.blockers}")
        rows.append(
            {
                "target": asdict(target),
                "team_code": clubs[target.code],
                "raw_v3_distribution": raw,
                "minutes_distribution": result.selector.distribution,
                "cold_start": result.cold_start,
                "price_proxy_dependent": result.proxy_dependent,
                "eligible_trailing_rows": recent.get(target.code, (raw, 0))[1],
                "prior_appearance": prior.get(target.code, (None, 0)),
                "last_eligible_team_code": last.get(target.code),
                "selector_provenance": asdict(result),
            }
        )
    return _jsonable(  # type: ignore[no-any-return]
        {
            "season": season,
            "gw": gw,
            "as_of": as_of,
            "rows": rows,
            "maximum_prior_kickoff": maximum,
            "training_rows": len(history),
            "selected_parameters": model.parameters(),
            "inner_metadata": asdict(model.metadata_v3()),
            "price_loader_used": loaded is not None,
            "same_gw_history_rows": 0,
            "future_history_rows": 0,
        }
    )


def run(*, db: Path, output: Path, root: Path) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    if branch != "claude/comet-fpl-v2-architecture-mqrj8f":
        raise ValueError("reference cache must run on the V2 branch")
    if file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("reference cache contract differs from preregistration")
    config = yaml.safe_load((root / CONFIG).read_bytes())
    proxy = yaml.safe_load(
        (root / "config/retrospective_current_minutes_proxy_v1.yaml").read_bytes()
    )
    if config["comparator"] != NAME or config["evidence_class"] != EVIDENCE_CLASS:
        raise ValueError("reference comparator identity/evidence class differs")
    for name, expected in proxy["unchanged_source_sha256"].items():
        if file_sha256(root / name) != expected:
            raise ValueError(f"unchanged prospective source differs: {name}")
    db, output = db.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root.resolve()):
        raise ValueError("cache requires a NEW external persistent directory")
    if not db.is_file() or Path(str(db) + ".wal").exists():
        raise ValueError("reference database absent or unresolved WAL")
    database_hash = file_sha256(db)
    if database_hash != config["database_sha256"]:
        raise ValueError("reference database differs from preregistered historical source")
    fingerprint = {name: file_sha256(root / name) for name in SOURCES}
    frozen = {str(p.relative_to(root)): file_sha256(p) for p in (root / "results").glob("*.json")}
    output.mkdir(parents=True, exist_ok=False)
    provenance = {
        "identity": config["identity"],
        "comparator": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "git_head": head,
        "branch": branch,
        "worktree_clean": True,
        "config": config,
        "source_sha256": fingerprint,
        "frozen_results_sha256": frozen,
        "database_path": str(db),
        "database_sha256": database_hash,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "new_model_candidate_scoring": False,
        "historical_deadline_validity": False,
    }
    publish_json(output / "provenance.json", provenance)
    folds: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    con = connect(db, read_only=True)
    try:
        for fold in generate_minutes_folds(con):
            if fold.season not in config["seasons"]:
                continue
            logger.info(
                "incumbent reference %s GW%s (%s/114)", fold.season, fold.gw, len(folds) + 1
            )
            result = build_fold(
                con, season=fold.season, gw=fold.gw, as_of=fold.as_of, database_hash=database_hash
            )
            name = f"{fold.season}-gw{fold.gw:02d}.json"
            publish_json(output / name, result)
            counts["rows"] += len(result["rows"])
            counts["price_proxy_rows"] += sum(r["price_proxy_dependent"] for r in result["rows"])
            counts[fold.season] += len(result["rows"])
            folds.append(
                {
                    "file": name,
                    "sha256": file_sha256(output / name),
                    "season": fold.season,
                    "gw": fold.gw,
                    "rows": len(result["rows"]),
                }
            )
        if (len(folds), counts["rows"], counts["price_proxy_rows"]) != (
            config["expected_folds"],
            config["expected_rows"],
            config["expected_direct_proxy_rows"],
        ):
            raise ValueError(f"population/proxy coverage drift: {dict(counts)}")
        if git_clean_head(root) != head or any(
            file_sha256(root / n) != h for n, h in fingerprint.items()
        ):
            raise ValueError("code/provenance changed during comparator build")
        if file_sha256(db) != database_hash or Path(str(db) + ".wal").exists():
            raise ValueError("source database changed during reference build")
        if any(file_sha256(root / n) != h for n, h in frozen.items()):
            raise ValueError("frozen result changed")
        report = {
            "completed": True,
            "provenance": provenance,
            "counts": dict(counts),
            "folds": folds,
            "ended_at_utc": datetime.now(UTC).isoformat(),
        }
        publish_json(output / "manifest.json", report)
        return report
    except Exception as error:
        publish_json(
            output / "failure.json",
            {
                "completed": False,
                "class": type(error).__name__,
                "message": str(error),
                "retained_folds": folds,
                "provenance": provenance,
            },
        )
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = run(db=args.db, output=args.output, root=repo_root())
    print(json.dumps({"completed": report["completed"], "counts": report["counts"]}))


if __name__ == "__main__":
    main()
