"""Write-once CURRENT component reference, shared by development experiments.

No challenger fit, minutes refit or Monte Carlo points draw. Retain all inputs
to the current joint composer once per GW, with exact typed read-back checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import subprocess
import traceback
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fpl.config import repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256, git_clean_head, publish_json
from fpl.models.points_composition import ComponentDistributions, FixturePlayer
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.development_reference_components import (
    EXPECTED_COUNTS,
    DevelopmentReferenceComponents,
    ReferencePlayerComponents,
    ValidatedMinutesControlFold,
    build_reference_components,
    component_source_fingerprints,
    read_minutes_control_cache,
)
from fpl.validate.development_reference_components import (
    MANIFEST_SHA256 as MINUTES_MANIFEST_SHA256,
)
from fpl.validate.development_reference_components import (
    NAME as REFERENCE,
)
from fpl.validate.minutes_baselines import TargetRow
from fpl.validate.retrospective_minutes_proxy import EVIDENCE_CLASS

NAME = "retrospective_current_component_proxy_cache_v1"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
logger = logging.getLogger(__name__)


def source_pins(root: Path) -> dict[str, str]:
    pins = component_source_fingerprints(root)
    for name in (
        "src/fpl/validate/current_component_reference_cache.py",
        "docs/current-component-reference-cache.md",
    ):
        pins[name] = file_sha256(root / name)
    return pins


def snapshot(root: Path, db: Path) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    if branch != BRANCH or not db.is_file() or Path(str(db) + ".wal").exists():
        raise ValueError("clean exact V2 branch and original database without WAL required")
    return {
        "git_head": head,
        "branch": branch,
        "worktree_clean": True,
        "identity": NAME,
        "reference": REFERENCE,
        "evidence_class": EVIDENCE_CLASS,
        "database_path": str(db),
        "database_sha256": file_sha256(db),
        "minutes_manifest_sha256": MINUTES_MANIFEST_SHA256,
        "source_sha256": source_pins(root),
        "minutes_refitted": False,
        "challenger_fitted": False,
        "points_monte_carlo_drawn": False,
        "historical_deadline_validity": False,
        "promotion_permitted": False,
    }


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("reference timestamp must retain its timezone")
    return result


def _object(raw: Any, cls: type[Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {f.name for f in fields(cls)}:
        raise ValueError(f"exact {cls.__name__} predictor fields required; no target labels")
    return cast(dict[str, Any], raw)


def _finite_tree(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("reference JSON contains a nonfinite numeric value")
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite_tree(item)


def _pmf(raw: Any, size: int | None = None) -> tuple[float, ...]:
    if not isinstance(raw, (list, tuple)) or not raw or (size is not None and len(raw) != size):
        raise ValueError("reference PMF support differs")
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
        for v in raw
    ):
        raise ValueError("reference PMF must be finite and nonnegative")
    if not math.isclose(math.fsum(raw), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("reference PMF mass differs from one")
    return tuple(raw)


def decode_reference(raw: Any) -> DevelopmentReferenceComponents:
    """Explicit dataclass/enum/tuple decoding; never pickle, eval or opaque objects."""
    _finite_tree(raw)
    data = dict(_object(raw, DevelopmentReferenceComponents))
    if (
        data["identity"] != REFERENCE
        or data["evidence_class"] != EVIDENCE_CLASS
        or data["promotion_permitted"] is not False
    ):
        raise ValueError("only the exact current unpromoted reference is accepted")
    data["as_of"] = _time(data["as_of"])
    rows = []
    for item in data["rows"]:
        row = dict(_object(item, ReferencePlayerComponents))
        target = dict(_object(row["target"], TargetRow))
        target["kickoff_time"] = _time(target["kickoff_time"])
        target["position"] = Position(target["position"])
        row["target"] = TargetRow(**target)
        player = dict(_object(row["player"], FixturePlayer))
        components = dict(_object(player["components"], ComponentDistributions))
        if components["disciplinary"] is not None:
            raise ValueError("current default reference must retain absent disciplinary component")
        components["position"] = Position(components["position"])
        components["minutes"] = _pmf(components["minutes"], 4)
        for name in ("goals", "assists", "team_goals_conceded"):
            components[name] = _pmf(components[name], 11 if name in ("goals", "assists") else None)
        if components["saves"] is not None:
            components["saves"] = _pmf(components["saves"])
        if not 0 <= components["dc_hit_probability"] <= 1:
            raise ValueError("DC probability outside [0,1]")
        player["components"] = ComponentDistributions(**components)
        if any(
            not isinstance(player[k], (float, int))
            or isinstance(player[k], bool)
            or not math.isfinite(player[k])
            for k in ("residual_mean", "residual_sigma")
        ):
            raise ValueError("BPS residual mean/sigma must be finite")
        if player["residual_sigma"] < 0:
            raise ValueError("BPS residual sigma must be nonnegative")
        row["player"] = FixturePlayer(**player)
        if player["code"] != target["code"] or components["position"] != target["position"]:
            raise ValueError("component player identity/position differs from declared target")
        for key in ("team_price_proxy_codes", "fixture_price_proxy_codes"):
            row[key] = tuple(row[key])
        for key in (
            "raw_goal_signal",
            "raw_assist_signal",
            "resolved_goal_signal",
            "resolved_assist_signal",
            "unconditional_goal_rate",
            "unconditional_assist_rate",
        ):
            if row[key] is not None and (
                isinstance(row[key], bool) or not math.isfinite(row[key]) or row[key] < 0
            ):
                raise ValueError(
                    "reference signal/rate must be measured nonnegative or unavailable"
                )
        rows.append(ReferencePlayerComponents(**row))
    data["rows"] = tuple(rows)
    data["team_scored"] = tuple(
        (fixture, team, _pmf(pmf)) for fixture, team, pmf in data["team_scored"]
    )
    for key in ("diagnostics_json", "provenance_json"):
        if not isinstance(data[key], str) or not isinstance(json.loads(data[key]), dict):
            raise ValueError("reference must retain original diagnostic/provenance JSON")
        _finite_tree(json.loads(data[key]))
    return DevelopmentReferenceComponents(**data)


def encode_reference(value: DevelopmentReferenceComponents) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(asdict(value), default=str, allow_nan=False)))


def validate_reference(
    value: DevelopmentReferenceComponents, fold: ValidatedMinutesControlFold
) -> None:
    if (value.season, value.gw, value.as_of) != (fold.season, fold.gw, fold.as_of):
        raise ValueError("reference batch identity/cutoff differs")
    if len(value.rows) != len(fold.rows):
        raise ValueError("reference row count differs from the complete minutes roster")
    for row, control in zip(value.rows, fold.rows, strict=True):
        if (
            row.target != control.target
            or row.team_code != control.team_code
            or row.player.components.minutes != control.minutes
            or row.cold_start is not control.cold_start
            or row.direct_price_proxy is not control.price_proxy_dependent
            or row.selector_provenance_json != control.selector_provenance_json
        ):
            raise ValueError("reference target/minutes/price lineage differs from exact cache row")
    provenance = json.loads(value.provenance_json)
    if (
        provenance["minutes_manifest_sha256"] != fold.manifest_sha256
        or provenance["minutes_fold_sha256"] != fold.fold_sha256
        or provenance["database_sha256"] != fold.database_sha256
    ):
        raise ValueError("reference original database/minutes fingerprints differ")
    diagnostics = json.loads(value.diagnostics_json)
    maximum = diagnostics["maximum_prior_kickoff"]
    if (
        diagnostics["minutes_refitted"] is not False
        or diagnostics["same_gw_history_rows"] != 0
        or (maximum is not None and _time(maximum) >= fold.as_of)
    ):
        raise ValueError("reference changed minutes or violated pre-GW event isolation")
    if len({(f, t) for f, t, _ in value.team_scored}) != len(value.team_scored):
        raise ValueError("duplicate fixture/team PMF")


def build_cache(*, root: Path, db: Path, minutes_cache: Path, output: Path) -> dict[str, Any]:
    root, db, output = root.resolve(), db.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("new external write-once cache directory required")
    # Read lease spans all hashing, baseline fits and final publication.
    with connect(db, read_only=True) as con:
        provenance = snapshot(root, db)
        minutes = read_minutes_control_cache(minutes_cache, db=db, root=root)
        claim = reserve_program_claim(root, NAME, provenance)
        output.mkdir(parents=True, exist_ok=False)
        publish_json(output / "provenance.json", provenance)
        completed = []
        started = datetime.now(UTC).isoformat()
        try:
            for fold in minutes.folds:
                reference = build_reference_components(con, fold)
                encoded = encode_reference(reference)
                decoded = decode_reference(encoded)
                if decoded != reference:
                    raise ValueError(
                        "full typed comparator round-trip changed its mathematical inputs"
                    )
                validate_reference(decoded, fold)
                name = f"{fold.season}-gw{fold.gw:02d}.json"
                publish_json(output / name, encoded)
                completed.append(
                    {
                        "season": fold.season,
                        "gw": fold.gw,
                        "file": name,
                        "sha256": file_sha256(output / name),
                        "rows": len(reference.rows),
                    }
                )
                logger.info(
                    "current components %s GW%s complete: %s rows (%s/114)",
                    fold.season,
                    fold.gw,
                    len(reference.rows),
                    len(completed),
                )
            if snapshot(root, db) != provenance:
                raise ValueError("reference cache source/HEAD/database changed during generation")
            if read_minutes_control_cache(minutes_cache, db=db, root=root) != minutes:
                raise ValueError("external minutes cache changed during reference generation")
            result = {
                "completed": True,
                "identity": NAME,
                "reference": REFERENCE,
                "provenance": provenance,
                "counts": EXPECTED_COUNTS,
                "folds": completed,
                "claim_path": str(claim),
                "started_at_utc": started,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "typed_round_trip_exact": True,
                "points_monte_carlo_drawn": False,
            }
            publish_json(output / "manifest.json", result)
            return result
        except BaseException as error:
            publish_json(
                output / "failure.json",
                {
                    "completed": False,
                    "identity": NAME,
                    "error_class": type(error).__name__,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                    "completed_folds": completed,
                    "claim_preserved": True,
                    "retry_permitted": False,
                    "provenance": provenance,
                },
            )
            raise


def load_component_reference_cache(
    directory: Path,
    *,
    root: Path,
    db: Path,
    minutes_cache: Path,
    expected_manifest_sha256: str,
) -> tuple[DevelopmentReferenceComponents, ...]:
    """Read all exact current components; no model is refitted or rescored."""
    directory, root, db = directory.resolve(), root.resolve(), db.resolve()
    manifest_path = directory / "manifest.json"
    if file_sha256(manifest_path) != expected_manifest_sha256:
        raise ValueError("component reference manifest hash differs from preregistration")
    raw = json.loads(manifest_path.read_bytes())
    provenance = raw["provenance"]
    if (
        raw["completed"] is not True
        or raw["identity"] != NAME
        or raw["reference"] != REFERENCE
        or raw["typed_round_trip_exact"] is not True
        or raw["points_monte_carlo_drawn"] is not False
        or raw["counts"] != EXPECTED_COUNTS
        or provenance["evidence_class"] != EVIDENCE_CLASS
        or provenance["worktree_clean"] is not True
        or provenance["promotion_permitted"] is not False
        or provenance["minutes_refitted"] is not False
        or provenance["challenger_fitted"] is not False
    ):
        raise ValueError("reference cache identity/status/evidence differs")
    if json.loads((directory / "provenance.json").read_bytes()) != provenance:
        raise ValueError("reference separate provenance receipt differs")
    if source_pins(root) != provenance["source_sha256"]:
        raise ValueError("transitive CURRENT component source changed")
    if Path(str(db) + ".wal").exists() or file_sha256(db) != provenance["database_sha256"]:
        raise ValueError("reference database changed or has unresolved WAL")
    minutes = read_minutes_control_cache(minutes_cache, db=db, root=root)
    if len(raw["folds"]) != len(minutes.folds) or len(minutes.folds) != 114:
        raise ValueError("reference must contain exactly all114 retained minutes folds")
    result = []
    for item, fold in zip(raw["folds"], minutes.folds, strict=True):
        path = (directory / item["file"]).resolve()
        if (
            path.parent != directory
            or path.name != f"{fold.season}-gw{fold.gw:02d}.json"
            or (item["season"], item["gw"], item["rows"]) != (fold.season, fold.gw, len(fold.rows))
        ):
            raise ValueError("reference fold path/identity/population differs")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("reference fold content SHA differs")
        decoded = decode_reference(json.loads(body))
        validate_reference(decoded, fold)
        result.append(decoded)
    return tuple(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--minutes-cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = build_cache(
        root=repo_root(), db=args.db, minutes_cache=args.minutes_cache, output=args.output
    )
    print(
        json.dumps(
            {
                "completed": result["completed"],
                "folds": len(result["folds"]),
                "counts": result["counts"],
            }
        )
    )


if __name__ == "__main__":
    main()
