"""Current descriptive club form from the same ended fixtures as dashboard logs.

This is publication arithmetic, never a forecast input. Callers supply validated
finalized/provisional read models; archival form marts are not a live fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any


def refresh_team_forms(
    teams: Sequence[dict[str, Any]],
    finalized: Sequence[dict[str, Any]],
    provisional: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    by_team: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for status, records in (("provisional", provisional), ("finalized", finalized)):
        for record in records:
            fixtures = by_team.setdefault((record["season"], record["team_code"]), {})
            for row in record["actuals"]:
                prior = fixtures.get(row["fixture"])
                if prior is not None:
                    if prior["outcome_status"] == status:
                        raise ValueError("duplicate team form fixture")
                    for field in ("gw", "kickoff_time", "opponent_team_code", "was_home"):
                        if prior[field] != row[field]:
                            raise ValueError("team form fixture identity mismatch")
                fixtures[row["fixture"]] = {**row, "outcome_status": status}
    forms: dict[tuple[str, int], dict[str, Any]] = {}
    for identity, fixtures in by_team.items():
        rows = sorted(
            fixtures.values(),
            key=lambda r: (datetime.fromisoformat(r["kickoff_time"]), r["fixture"]),
            reverse=True,
        )
        if not rows:
            continue
        windows: dict[str, Any] = {}
        for name, limit in (
            ("last_3", 3),
            ("last_5", 5),
            ("last_10", 10),
            ("season_to_date", None),
        ):
            selected = rows[:limit]
            count = len(selected)
            gf = sum(r["goals_for"] for r in selected)
            ga = sum(r["goals_against"] for r in selected)
            window: dict[str, Any] = {
                "matches_played": count,
                "goals_for": gf,
                "goals_against": ga,
                "clean_sheets": sum(r["goals_against"] == 0 for r in selected),
                "wins": sum(r["goals_for"] > r["goals_against"] for r in selected),
                "draws": sum(r["goals_for"] == r["goals_against"] for r in selected),
                "losses": sum(r["goals_for"] < r["goals_against"] for r in selected),
                "goals_for_per_match": gf / count,
                "goals_against_per_match": ga / count,
                "observations": {
                    "fixture_ids": [r["fixture"] for r in selected],
                    "gw_from": min(r["gw"] for r in selected),
                    "gw_to": max(r["gw"] for r in selected),
                    "provisional_matches": sum(
                        r["outcome_status"] == "provisional" for r in selected
                    ),
                },
            }
            for metric in ("team_xg", "team_xgc"):
                values = [r[metric] for r in selected if r[metric] is not None]
                window[metric] = sum(values) if values else None
                window[f"{metric}_per_match"] = sum(values) / len(values) if values else None
                window["observations"][f"{metric}_matches"] = len(values)
            windows[name] = window
        forms[identity] = {
            "season": identity[0],
            "as_at_gw": max(r["gw"] for r in rows),
            "source": "published_team_actuals",
            "windows": windows,
        }
    return tuple({**team, "form": forms.get((team["season"], team["team_code"]))} for team in teams)
