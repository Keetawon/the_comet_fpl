"""Canonical audit transport v2; the invalid V1 encoder remains reproducible.

JSON keys are strings. Accept string/integer audit keys, normalize before sorting,
and reject collisions. Values retain JSON semantics, tuples become arrays and
datetimes retain the original ISO representation. UTF-8, ASCII escapes, compact
separators, one LF and finite JSON numbers are fixed transport policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime


def _normalise(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) and type(key) is not int:
                raise TypeError("audit JSON mapping keys must be strings or integers")
            name = str(key)
            if name in result:
                raise ValueError(f"ambiguous audit JSON mapping key: {name!r}")
            result[name] = _normalise(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def canonical(value: object) -> bytes:
    """Idempotent under JSON decode/re-encode, including nested integer-key maps."""
    return (
        json.dumps(
            _normalise(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
