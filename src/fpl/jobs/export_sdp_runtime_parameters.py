"""Copy terminal chronological Tactical/Chance parameters; never fit or score a model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fpl.config import repo_root


def export(root: Path) -> dict[str, Any]:
    path = root / "results/v2_chance_creation_development.json"
    body = path.read_bytes()
    result = json.loads(body)
    if not result["completed"] or result["verdict"] != "INCONCLUSIVE":
        raise ValueError("expected the complete frozen Phase A record")
    terminal = max(result["folds"], key=lambda row: row["as_of"])
    style = next(
        row
        for row in result["upstream_style_fit_provenance"]
        if (row["season"], row["gw"]) == (terminal["season"], terminal["gw"])
    )
    names = (
        "src/fpl/validate/tactical_state.py",
        "src/fpl/validate/tactical_matchup.py",
        "src/fpl/validate/tactical_math.py",
        "src/fpl/validate/chance_creation.py",
    )
    return {
        "schema_version": 1,
        "model_version": "sdp_v2_terminal_phase_a_parameters_v1",
        "selection_policy": "last_chronological_retained_fold_no_fit_no_score_selection",
        "known_at": result["completed_at_utc"],
        "source_result": path.relative_to(root).as_posix(),
        "source_result_sha256": hashlib.sha256(body).hexdigest(),
        "source_research_verdict": "INCONCLUSIVE",
        "historical_pit_claim": False,
        "frozen_source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names
        },
        "parameter_fold": {k: terminal[k] for k in ("season", "gw", "as_of")},
        "style_fits": style["style_fits"],
        "stage_fits": terminal["stage_fits"],
        "conversion_fit": terminal["conversion_fit"],
    }


if __name__ == "__main__":
    # Write-once even when invoked manually. A new snapshot needs a new explicit filename.
    destination = repo_root() / "config/sdp_v2_frozen_parameters.json"
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(export(repo_root()), handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
