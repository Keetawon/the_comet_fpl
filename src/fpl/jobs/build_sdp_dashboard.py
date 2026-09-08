"""Build a public descriptive dashboard generation using the existing publishers.

The documented Windows before_publish hook retains validated copies if the OS
denies symlink publication. That limitation is reported, never called a passed gate.
No capture, inference, optimizer solve or remote deployment happens here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fpl.publish.dashboard_json import export_dashboard_json, validate_dashboard_json
from fpl.publish.export import export_bi, validate_bi_export
from fpl.publish.public_dashboard import package_public_dashboard
from fpl.publish.sdp_stats import export_sdp_stats
from fpl.storage.db import connect


def retain_validated_generation(
    publisher: Callable[..., Any], source: Path, endpoint: Path, retained: Path
) -> bool:
    """Preserve only a generation that reached the existing pre-publication gate."""

    def retain() -> None:
        candidates = list(endpoint.parent.glob(f".{endpoint.name}.*.tmp"))
        if len(candidates) != 1:
            raise ValueError("ambiguous staged dashboard generation")
        shutil.copytree(candidates[0], retained)

    try:
        publisher(source, endpoint, before_publish=retain)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314 or not retained.is_dir():
            raise
        return False
    return True


def install_preview(generation: Path, public: Path) -> None:
    """Copy only public JSON exports to the existing Vite public directory."""
    for relative in ("data", "sdp"):
        destination = public / relative
        destination.mkdir(parents=True, exist_ok=True)
        for source in sorted((generation / "public" / relative).glob("*.json")):
            temporary = destination / f".{source.name}.new"
            with temporary.open("xb") as handle:
                handle.write(source.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination / source.name)


def build(
    db: Path,
    output: Path,
    *,
    preview_public: Path | None = None,
    base_dashboard: Path | None = None,
) -> dict[str, Any]:
    if not db.is_file():
        raise ValueError("explicit existing operational database required")
    output.mkdir(parents=True, exist_ok=False)
    stamp = datetime.now(UTC)
    # Keep a read lease throughout the export; a writer must not mix generations.
    with connect(db, read_only=True):
        bi_published = retain_validated_generation(
            export_bi, db, output / "bi-endpoint", output / "bi-retained"
        )
        validate_bi_export(output / "bi-retained")
        dashboard_published = retain_validated_generation(
            export_dashboard_json,
            output / "bi-retained",
            output / "dashboard-endpoint",
            output / "dashboard-retained",
        )
        validate_dashboard_json(output / "dashboard-retained")
        # An operational DB can intentionally contain no optimizer plans. A caller
        # may explicitly retain an existing complete dashboard generation instead
        # of running inference/optimization merely to satisfy the public packager.
        base = base_dashboard if base_dashboard is not None else output / "dashboard-retained"
        base_manifest = validate_dashboard_json(base)
        package = package_public_dashboard(
            base,
            output / "public" / "data",
            output / "dashboard-public-data.zip",
        )
        sidecar = export_sdp_stats(db, output / "public" / "sdp" / "sdp_stats.json", as_of=stamp)
    report = {
        "schema": "fpl.sdp-dashboard-generation/v1",
        "started_at": stamp.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "bi_atomic_publish": bi_published,
        "dashboard_atomic_publish": dashboard_published,
        "publication_limitation": None
        if bi_published and dashboard_published
        else "Windows symlink privilege unavailable; validated before_publish copies retained",
        "public_package": package.metadata(),
        "base_dashboard": {
            "mode": "retained_existing_generation"
            if base_dashboard is not None
            else "refreshed_operational_generation",
            "generated_at": base_manifest["generated_at"],
            "manifest_content_sha256": base_manifest["content_sha256"],
            "statistics_sidecar_refreshed_independently": True,
        },
        "sdp_sidecar": sidecar,
        "forecast_regenerated": False,
        "remote_deployed": False,
        "preview_assets_installed": preview_public is not None,
    }
    if preview_public is not None:
        install_preview(output, preview_public)
    (output / "receipt.json").write_text(
        json.dumps(report, allow_nan=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New retained generation directory"
    )
    parser.add_argument("--preview-public", type=Path, help="Existing dashboard/public directory")
    parser.add_argument(
        "--base-dashboard",
        type=Path,
        help="Explicit existing validated dashboard base; keeps its original forecast vintage",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build(
                args.db,
                args.output,
                preview_public=args.preview_public,
                base_dashboard=args.base_dashboard,
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
