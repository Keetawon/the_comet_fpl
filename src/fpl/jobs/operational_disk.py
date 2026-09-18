"""Bounded local disk preflight for operational allocations; never deletes data."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)
GIB = 1 << 30
WARNING_FREE_BYTES = 30 * GIB
MINIMUM_FREE_BYTES = 20 * GIB


def check_disk_space(destination: Path, required_bytes: int) -> dict[str, int | str]:
    """Warn below 30 GiB projected free; refuse an allocation leaving under 20 GiB.

    The check reserves the full new allocation even when the destination already exists.
    It is a preflight, not a reservation against unrelated processes using the same drive.
    """
    if (
        isinstance(required_bytes, bool)
        or not isinstance(required_bytes, int)
        or required_bytes < 0
    ):
        raise ValueError("required_bytes must be a nonnegative integer")
    destination = destination.resolve()
    disk_path = destination if destination.is_dir() else destination.parent
    while not disk_path.exists():
        disk_path = disk_path.parent
    free_bytes = shutil.disk_usage(disk_path).free
    projected_free_bytes = free_bytes - required_bytes
    if projected_free_bytes < MINIMUM_FREE_BYTES:
        raise RuntimeError(
            f"insufficient disk space for {destination}: {free_bytes / GIB:.2f} GiB free, "
            f"{required_bytes / GIB:.2f} GiB required, "
            f"{projected_free_bytes / GIB:.2f} GiB projected free; "
            "minimum is 20 GiB; allocation blocked, no data deleted"
        )
    status = "WARNING" if projected_free_bytes < WARNING_FREE_BYTES else "OK"
    if status == "WARNING":
        logger.warning(
            "Low disk space for %s: %.2f GiB free, %.2f GiB projected after allocation "
            "(warning threshold 30 GiB; minimum 20 GiB)",
            destination,
            free_bytes / GIB,
            projected_free_bytes / GIB,
        )
    return {
        "destination": str(destination),
        "disk_path": str(disk_path),
        "free_bytes": free_bytes,
        "required_bytes": required_bytes,
        "projected_free_bytes": projected_free_bytes,
        "warning_free_bytes": WARNING_FREE_BYTES,
        "minimum_free_bytes": MINIMUM_FREE_BYTES,
        "status": status,
    }
