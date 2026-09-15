"""Exclusive claims shared by every linked worktree in this development program."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fpl.jobs.competitive_participation_pilot import publish_json


def reserve_program_claim(root: Path, candidate: str, provenance: Mapping[str, Any]) -> Path:
    if re.fullmatch(r"[a-z][a-z0-9_]+", candidate) is None:
        raise ValueError("candidate identity must be a fixed safe filename")
    old = root / "data" / "evaluation-claims" / f"{candidate}.json"
    if old.exists() or old.is_symlink():
        raise FileExistsError("previous worktree-local candidate claim must remain frozen")
    common = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"], cwd=root, text=True
        ).strip()
    )
    if not common.is_absolute():
        common = root / common
    common = common.resolve(strict=True)
    directory = common / "development-evaluation-claims"
    if directory.is_symlink():
        raise ValueError("shared claim directory must not be a symlink")
    directory.mkdir(exist_ok=True)
    path = directory / f"{candidate}.json"
    publish_json(
        path,
        {
            "candidate": candidate,
            "claimed_at_utc": datetime.now(UTC).isoformat(),
            "provenance": dict(provenance),
            "resume_permitted": False,
            "shared_git_common_dir": str(common),
        },
    )
    return path
