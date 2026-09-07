"""Read-only card semantics/coverage audit; no forecasts or model scoring."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from fpl.config import load_scoring_rules, repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256, publish_json
from fpl.models.disciplinary_development import scored_card_state
from fpl.storage.db import connect

RULES_URL = "https://www.premierleague.com/es/news/4661029"


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    exceptions: list[dict[str, Any]] = []
    for row in rows:
        counts["rows"] += 1
        season = row["season"]
        counts[f"{season}:rows"] += 1
        state = scored_card_state(row["yellow_cards"], row["red_cards"])
        key = "unmeasured" if state is None else ("none", "yellow", "red")[state]
        counts[f"{season}:{key}"] += 1
        counts[key] += 1
        if state not in (None, 0) and row["minutes"] == 0:
            exceptions.append(row)
    return {"counts": dict(counts), "zero_minute_card_rows": exceptions}


def run(*, db: Path, output: Path) -> dict[str, Any]:
    root = repo_root()
    db, output = db.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root.resolve()):
        raise ValueError("requires a new external evidence directory")
    if not db.is_file() or Path(str(db) + ".wal").exists():
        raise ValueError("source database missing or unresolved WAL")
    database_hash = file_sha256(db)
    output.mkdir(parents=True, exist_ok=False)
    with connect(db, read_only=True) as con:
        frame = con.execute(
            """SELECT f.season,f.gw,f.fixture,f.code,p.web_name,f.position,
                      f.minutes,f.yellow_cards,f.red_cards
               FROM mart_fact_player_fixture f LEFT JOIN mart_dim_player p
               ON f.season=p.season AND f.code=p.code
               ORDER BY f.season,f.fixture,f.code"""
        ).pl()
        audit = summarise(frame.to_dicts())
        rules = load_scoring_rules("2026_27")
        started = datetime.now(UTC).isoformat()
        source: dict[str, Any] = {"url": RULES_URL, "requested_at": started}
        # One ordinary official source request. Never bypass refusal; no SDP traffic.
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(RULES_URL)
            with (output / "official-rules.raw").open("xb") as handle:
                handle.write(response.content)
            source.update(
                {
                    "status": response.status_code,
                    "final_url": str(response.url),
                    "content_type": response.headers.get("content-type"),
                    "known_at": datetime.now(UTC).isoformat(),
                    "sha256": file_sha256(output / "official-rules.raw"),
                    "bytes": len(response.content),
                    "raw_file": "official-rules.raw",
                    "red_includes_yellow_text_present": "Red card deductions include"
                    in response.text,
                    "zero_minutes_card_appearance_text_present": "receiving a yellow"
                    in response.text,
                }
            )
        except httpx.HTTPError as error:
            source.update({"error_class": type(error).__name__, "error": str(error)})
        report = {
            "identity": "fpl_scored_disciplinary_target_audit_v1",
            "model_evaluation": False,
            "evidence_class": "historical_recorded_targets_not_deadline_predictions",
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "git_status": subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True
            ),
            "database_path": str(db),
            "database_sha256": database_hash,
            "source_sha256": file_sha256(Path(__file__)),
            "rules_sha256": file_sha256(root / "config/scoring_2026_27.yaml"),
            "scoring_constants": {"yellow": rules.yellow_cards, "red": rules.red_cards},
            "physical_second_yellow_identifiable_from_archive": False,
            "states": [[0, 0], [1, 0], [0, 1]],
            "official_source": source,
            **audit,
        }
        if file_sha256(db) != database_hash or Path(str(db) + ".wal").exists():
            raise ValueError("source database changed during audit")
        publish_json(output / "result.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(db=args.db, output=args.output)
    print(json.dumps({"counts": report["counts"], "source": report["official_source"]}))


if __name__ == "__main__":
    main()
