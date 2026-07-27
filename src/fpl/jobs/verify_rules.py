"""Verify a scoring ruleset against a real `game_config.scoring` payload.

    python -m fpl.jobs.verify_rules --ruleset 2026_27 --payload <bootstrap-static.json>
    python -m fpl.jobs.verify_rules --ruleset 2026_27 --payload <path> --write

R2 makes the rules configuration; this job is what stops that configuration being merely
*asserted*. Three outcomes per field, and only the first marks it confirmed:

  confirmed    the payload carries the field and the value agrees
  unconfirmed  no key in the payload matches it, under any known layout
  MISMATCH     the payload carries it and disagrees

A mismatch exits non-zero and never rewrites the config. An upstream rule change is a
decision for a human -- silently adopting it would let FPL change our model's targets.

FPL has moved these constants between `game_config.scoring` and flat `scoring_*` keys on
`game_settings` over the years, and per-position values have appeared keyed both by
element-type id and by short name. Rather than commit to one layout, each field lists
candidate paths and the first hit wins. A field no candidate matches is reported
unconfirmed, never guessed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import yaml

from fpl.config import ScoringRules, config_dir, load_scoring_rules
from fpl.types import Position

logger = logging.getLogger("fpl.verify_rules")

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_NO_PAYLOAD = 2

# Position -> the keys FPL has used for it in per-position scoring maps.
_POSITION_KEYS: Final[dict[Position, tuple[str, ...]]] = {
    Position.GK: ("1", "GKP", "GK"),
    Position.DEF: ("2", "DEF"),
    Position.MID: ("3", "MID"),
    Position.FWD: ("4", "FWD"),
}


@dataclass(frozen=True, slots=True)
class FieldCheck:
    """One YAML field, and what the payload said about it."""

    path: str
    expected: object
    observed: object | None
    matched_key: str | None

    @property
    def status(self) -> str:
        if self.matched_key is None:
            return "unconfirmed"
        return "confirmed" if self.observed == self.expected else "MISMATCH"


def _lookup(scoring: dict[str, Any], candidates: Sequence[str]) -> tuple[str | None, object | None]:
    """First candidate key present in the payload wins. Supports `a.b` paths."""
    for candidate in candidates:
        node: Any = scoring
        for part in candidate.split("."):
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if node is not None:
            return candidate, node
    return None, None


def _positional(
    scoring: dict[str, Any], bases: Sequence[str], position: Position
) -> tuple[str | None, object | None]:
    """Resolve a per-position value under any of `bases`, by any key spelling."""
    for base in bases:
        _, node = _lookup(scoring, [base])
        if isinstance(node, dict):
            for key in _POSITION_KEYS[position]:
                if key in node:
                    return f"{base}.{key}", node[key]
        elif node is not None:
            # A scalar under a per-position base means the value is position-independent.
            return base, node
    return None, None


def _unit_points(
    scoring: dict[str, Any], bases: Sequence[str], positions: frozenset[Position]
) -> tuple[str | None, object | None]:
    """Normalise a scalar unit score or a position map to the configured unit score.

    The 2026/27 payload changed `goals_conceded` and `defensive_contribution` from
    scalars to maps. A map confirms the scalar config only when every enabled position
    has the same value and every explicitly listed disabled position has zero.
    """
    for base in bases:
        matched, node = _lookup(scoring, [base])
        if node is None:
            continue
        if not isinstance(node, dict):
            return matched, node
        enabled: list[object] = []
        for position in positions:
            _, value = _positional(scoring, [base], position)
            if value is None:
                return base, node
            enabled.append(value)
        for position in set(Position) - set(positions):
            _, value = _positional(scoring, [base], position)
            if value not in {None, 0}:
                return base, node
        if enabled and all(value == enabled[0] for value in enabled):
            return base, enabled[0]
        return base, node
    return None, None


def check_ruleset(rules: ScoringRules, scoring: dict[str, Any]) -> list[FieldCheck]:
    """Compare every scoring field in `rules` against the payload."""
    checks: list[FieldCheck] = []

    def add(path: str, expected: object, resolved: tuple[str | None, object | None]) -> None:
        key, observed = resolved
        checks.append(FieldCheck(path, expected, observed, key))

    add(
        "appearance.long_play_points",
        rules.appearance.long_play_points,
        _lookup(scoring, ["long_play", "scoring_long_play"]),
    )
    add(
        "appearance.short_play_points",
        rules.appearance.short_play_points,
        _lookup(scoring, ["short_play", "scoring_short_play"]),
    )
    add(
        "appearance.long_play_minutes",
        rules.appearance.long_play_minutes,
        _lookup(scoring, ["long_play_limit", "scoring_long_play_limit"]),
    )
    add("assists", rules.assists, _lookup(scoring, ["assists", "scoring_assists"]))

    for position, value in sorted(rules.goals_scored.items()):
        add(
            f"goals_scored.{position.value}",
            value,
            _positional(scoring, ["goals_scored", "scoring_goals_scored"], position),
        )
    for position, value in sorted(rules.clean_sheets.points.items()):
        add(
            f"clean_sheets.points.{position.value}",
            value,
            _positional(scoring, ["clean_sheets", "scoring_clean_sheets"], position),
        )
    add(
        "clean_sheets.minimum_minutes",
        rules.clean_sheets.minimum_minutes,
        _lookup(scoring, ["clean_sheets_limit", "scoring_clean_sheets_limit"]),
    )

    add(
        "goals_conceded.points_per_unit",
        rules.goals_conceded.points_per_unit,
        _unit_points(
            scoring,
            ["goals_conceded", "scoring_goals_conceded"],
            rules.goals_conceded.positions,
        ),
    )
    add(
        "goals_conceded.unit",
        rules.goals_conceded.unit,
        _lookup(scoring, ["goals_conceded_limit", "scoring_concede_limit"]),
    )
    add(
        "saves.points_per_unit",
        rules.saves.points_per_unit,
        _lookup(scoring, ["saves", "scoring_saves"]),
    )
    add(
        "saves.unit",
        rules.saves.unit,
        _lookup(scoring, ["saves_limit", "scoring_saves_limit"]),
    )
    for field_name in (
        "penalties_saved",
        "penalties_missed",
        "own_goals",
        "yellow_cards",
        "red_cards",
    ):
        add(
            field_name,
            getattr(rules, field_name),
            _lookup(scoring, [field_name, f"scoring_{field_name}"]),
        )

    add(
        "defensive_contribution.points",
        rules.defensive_contribution.points,
        _unit_points(
            scoring,
            ["defensive_contribution", "scoring_defensive_contribution"],
            frozenset(rules.defensive_contribution.thresholds),
        ),
    )
    for position, threshold in sorted(rules.defensive_contribution.thresholds.items()):
        add(
            f"defensive_contribution.thresholds.{position.value}",
            threshold,
            _positional(
                scoring,
                ["defensive_contribution_limit", "scoring_defensive_contribution_limit"],
                position,
            ),
        )
    return checks


# Never marked confirmed, whatever a payload says. A payload confirms the number FPL
# publishes; it cannot confirm the calculator handles it.
_NEVER_CONFIRMED: Final[dict[str, str]] = {
    "goals_scored.GK": (
        "Untested either way. No goalkeeper scored in the validation data -- measured 0 GK "
        "goals across 29,747 rows of 2025-26 -- so no replay can exercise this value. A "
        "payload confirms the number FPL publishes, not that the calculator handles it."
    ),
    "clean_sheets.points.FWD": (
        "Zero-valued, so a correct 0 is indistinguishable from an omitted rule."
    ),
}


def verify(ruleset_id: str, payload_path: Path, *, write: bool) -> tuple[int, list[FieldCheck]]:
    payload = json.loads(payload_path.read_text("utf-8"))
    is_placeholder = isinstance(payload, dict) and "_PLACEHOLDER" in payload
    rules = load_scoring_rules(ruleset_id)

    from fpl.ingest.fpl_api import BootstrapStatic

    scoring = BootstrapStatic.model_validate(payload).scoring_block()
    if not scoring:
        logger.error("no scoring block found in %s", payload_path)
        return EXIT_NO_PAYLOAD, []

    checks = check_ruleset(rules, scoring)
    confirmed = [c for c in checks if c.status == "confirmed" and c.path not in _NEVER_CONFIRMED]
    unconfirmed = [c for c in checks if c.status == "unconfirmed"]
    mismatched = [c for c in checks if c.status == "MISMATCH"]

    for check in checks:
        logger.info(
            "%-48s %-12s expected=%r observed=%r via=%s",
            check.path,
            check.status,
            check.expected,
            check.observed,
            check.matched_key,
        )

    logger.info(
        "%d confirmed, %d unconfirmed, %d mismatched",
        len(confirmed),
        len(unconfirmed),
        len(mismatched),
    )

    if mismatched:
        for check in mismatched:
            logger.error(
                "MISMATCH %s: config says %r, payload says %r (key %s)",
                check.path,
                check.expected,
                check.observed,
                check.matched_key,
            )
        logger.error("refusing to rewrite config -- an upstream rule change needs a human decision")
        return EXIT_MISMATCH, checks

    if is_placeholder:
        logger.warning(
            "%s carries a _PLACEHOLDER key: it is not a real capture, so nothing is marked "
            "confirmed. Replace it with a real bootstrap-static response.",
            payload_path,
        )
        return EXIT_OK, checks

    if write:
        _rewrite_verification(ruleset_id, payload_path, confirmed, unconfirmed)
        logger.info("rewrote the verification block of scoring_%s.yaml", ruleset_id)
    return EXIT_OK, checks


def _rewrite_verification(
    ruleset_id: str,
    payload_path: Path,
    confirmed: list[FieldCheck],
    unconfirmed: list[FieldCheck],
) -> None:
    path = config_dir() / f"scoring_{ruleset_id}.yaml"
    document = yaml.safe_load(path.read_text("utf-8"))
    verification = document.setdefault("verification", {})
    payload = json.loads(payload_path.read_text("utf-8"))
    capture = payload.get("_CAPTURE", {}) if isinstance(payload, dict) else {}
    captured_at = capture.get("captured_at") if isinstance(capture, dict) else None
    if captured_at is None:
        captured_at = datetime.now(UTC).isoformat()
    verification["payload_captured_at"] = captured_at
    verification["payload_sha256"] = _canonical_text_sha256(payload_path)
    verification["payload_confirmed"] = sorted(check.path for check in confirmed)

    authoritative = {
        path
        for source in verification.get("authoritative_sources", [])
        if isinstance(source, dict)
        for path in source.get("confirmed", [])
        if isinstance(path, str)
    }
    notes = dict(_NEVER_CONFIRMED)
    for check in unconfirmed:
        if check.path in authoritative:
            continue
        notes.setdefault(
            check.path,
            "No key in the captured payload matched this field under any known layout, so "
            "the published value could not be confirmed.",
        )
    verification["unverified"] = notes
    path.write_text(yaml.safe_dump(document, sort_keys=False, width=88), "utf-8")


def _canonical_text_sha256(path: Path) -> str:
    """Hash textual evidence independently of Git's platform line-ending checkout."""
    canonical = path.read_text("utf-8").replace("\r\n", "\n").encode()
    return hashlib.sha256(canonical).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify scoring config against a real payload.")
    parser.add_argument("--ruleset", default="2026_27")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument(
        "--write", action="store_true", help="rewrite the config's verification block"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.payload.is_file():
        logger.error("no such payload: %s", args.payload)
        return EXIT_NO_PAYLOAD
    code, _ = verify(args.ruleset, args.payload, write=args.write)
    return code


if __name__ == "__main__":
    sys.exit(main())
