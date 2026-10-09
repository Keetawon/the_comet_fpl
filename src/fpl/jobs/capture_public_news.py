"""Capture optional public news privately; no forecasts or operational databases touched."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
import yaml
from pydantic import ValidationError

from fpl.ingest.public_news import NewsCaptureConfig, capture_fpl_snapshot, run_capture
from fpl.storage.public_news import NewsStore


def _news_environment(path: Path, *, required: bool) -> dict[str, str]:
    """Read two literal credentials privately; the process environment takes precedence."""
    keys = {"OPENAI_API_KEY", "X_BEARER_TOKEN"}
    if any(part.lower() in {"public", "dist", "dashboard"} for part in path.resolve().parts):
        raise ValueError("news credentials must stay outside dashboard/publication directories")
    try:
        with path.open("rb") as handle:
            raw = handle.read(16_385)
        if len(raw) > 16_384:
            raise ValueError("news credential file exceeds 16 KiB")
        text = raw.decode("utf-8-sig")
    except FileNotFoundError:
        if required:
            raise ValueError("explicit news credential file is missing") from None
        text = ""
    except (OSError, UnicodeError):
        raise ValueError("news credential file cannot be read as UTF-8") from None
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in keys or key in values:
            raise ValueError("invalid or duplicate news credential assignment")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("invalid news credential quoting")
            value = value[1:-1]
        if any(ord(char) < 33 or ord(char) > 126 for char in value) or any(
            marker in value for marker in ("'", '"', "${", "$(")
        ):
            raise ValueError("news credentials must be single-line literal tokens")
        values[key] = value
    # Do not mutate os.environ or expose unrelated process secrets to the adapter.
    values.update({key: os.environ[key] for key in keys if key in os.environ})
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New private capture receipt; write once"
    )
    parser.add_argument("--fpl-snapshot", type=Path)
    parser.add_argument("--season")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Private UTF-8 credential file; defaults to .env beside --store (no parent search)",
    )
    args = parser.parse_args(argv)
    if args.store.suffix.lower() not in {".sqlite", ".sqlite3"}:
        parser.error("--store must be a separate private .sqlite or .sqlite3 file")
    if any(part.lower() in {"public", "dist", "dashboard"} for part in args.store.resolve().parts):
        parser.error("private news store must be outside dashboard/publication directories")
    if args.fpl_snapshot and not args.season:
        parser.error("--fpl-snapshot requires its explicit --season")
    if args.output.exists():
        parser.error("capture receipt already exists; use a new output identity")
    try:
        config = NewsCaptureConfig.model_validate(
            yaml.safe_load(args.config.read_text(encoding="utf-8"))
        )
    except (ValidationError, yaml.YAMLError):
        parser.error("invalid news configuration; use process environment or a private --env-file")
    try:
        environment = _news_environment(
            args.env_file if args.env_file is not None else args.store.parent / ".env",
            required=args.env_file is not None,
        )
    except ValueError as exc:
        # These messages are fixed strings: never echo file contents, paths or credential values.
        parser.error(str(exc))
    store = NewsStore(args.store)
    statuses = []
    if args.fpl_snapshot:
        statuses.append(capture_fpl_snapshot(args.fpl_snapshot, store, season=args.season))
    with httpx.Client(trust_env=False) as client:
        statuses.extend(run_capture(config, store, client=client, env=environment))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {"schema_version": 1, "sources": [s.model_dump(mode="json") for s in statuses]},
            handle,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        handle.write("\n")
    print(
        json.dumps(
            {
                "sources": len(statuses),
                "network_enabled": config.enabled,
                "statuses": {s.source_id: s.status for s in statuses},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
