"""Republish only the provisional preview of the live dashboard generation.

Read-only against the published site and the committed capture; it writes one staging
directory and, with an explicit R2 config, one new immutable generation plus the pointer.
No database in this repository is opened for writing and no forecast is regenerated.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from fpl.config import repo_root
from fpl.publish.provisional_republish import (
    ProvisionalRepublishError,
    build_restatement,
    fetch_published_generation,
    https_reader,
    restate_generation,
)
from fpl.publish.r2_dashboard import publish_r2_dashboard

DEFAULT_BASE_URL = "https://data.thecometfpl.com"


def latest_capture(root: Path, season: str | None) -> Path:
    """The newest committed completed-match capture, chosen by its directory identity."""
    base = root / "snapshots" / "player-history-provisional"
    seasons = sorted(p for p in base.glob("*") if p.is_dir())
    if season is not None:
        seasons = [p for p in seasons if p.name == season]
    if not seasons:
        raise ProvisionalRepublishError("no committed provisional capture season is present")
    packages = sorted(
        (package for current in seasons for package in current.glob("gw-*/*/manifest.json")),
        key=lambda path: path.parent.name,
    )
    if not packages:
        raise ProvisionalRepublishError("no committed provisional capture package is present")
    return packages[-1].parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Staging directory to create")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--capture", type=Path, help="Capture package; default is the newest")
    parser.add_argument("--season", help="Restrict the default capture search to one season")
    parser.add_argument(
        "--r2-config",
        type=Path,
        help="External non-secret R2 config. Without it the restatement is staged only.",
    )
    args = parser.parse_args(argv)

    stamp = datetime.now(UTC)
    args.out.mkdir(parents=True, exist_ok=False)
    root = repo_root()
    capture = args.capture or latest_capture(root, args.season)
    resolved = capture.resolve()
    label = (
        str(resolved.relative_to(root.resolve()))
        if resolved.is_relative_to(root.resolve())
        else str(resolved)
    )
    generation = fetch_published_generation(args.base_url, read=https_reader())
    restatement = build_restatement(capture, generation, scratch=args.out / "capture")
    receipt = restate_generation(generation, restatement, args.out / "generation", as_of=stamp)
    report: dict[str, object] = {
        "schema": "fpl.provisional-republish/v1",
        "started_at": stamp.isoformat(),
        "capture": label,
        "base_generation_sha256": generation.generation_sha256,
        "restated_files": receipt["restated_files"],
        "capture_evidence": receipt["capture"],
        "published": False,
    }
    if not receipt["restated_files"]:
        report["reason"] = "the published preview already matches this capture"
    elif args.r2_config is not None:
        publication = publish_r2_dashboard(
            args.out / "generation",
            args.r2_config,
            args.out / "r2",
            published_at=stamp,
            expected_base_generation=generation.generation_sha256,
        )
        report["published"] = publication["status"] == "COMPLETE"
        report["r2"] = {
            key: publication.get(key)
            for key in ("status", "generation_sha256", "files", "already_current", "error_type")
        }
    else:
        report["reason"] = "no R2 config supplied; restatement staged and verified only"
    report["completed_at"] = datetime.now(UTC).isoformat()
    (args.out / "republish-receipt.json").write_text(
        json.dumps(report, allow_nan=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, allow_nan=False, sort_keys=True, indent=2))
    failed = (
        args.r2_config is not None and bool(receipt["restated_files"]) and not report["published"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
