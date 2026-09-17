"""Optional, pointer-last publication of validated public dashboard generations to R2."""

from __future__ import annotations

import gzip
import hashlib
import io
import logging
import re
import stat
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlsplit

from fpl.config import repo_root
from fpl.publish.competitive_schedule import validate_competitive_schedule
from fpl.publish.dashboard_json import validate_dashboard_json
from fpl.publish.dashboard_refresh import check_observed_freshness, publication_status
from fpl.publish.export import _canonical_json_bytes, _strict_json_loads
from fpl.publish.public_dashboard import (
    _ARCHIVE_FILENAMES,
    _assert_public_safe,
    package_public_dashboard,
)
from fpl.publish.sdp_stats import validate_sdp_stats

PUBLIC_FILES = frozenset(
    [f"data/{name}" for name in _ARCHIVE_FILENAMES]
    + [f"sdp/{name}.json" for name in ("sdp_stats", "competitive_schedule", "publication_status")]
)
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


@dataclass(frozen=True)
class R2Config:
    bucket: str
    endpoint_url: str
    public_base_url: str
    credentials_file: Path
    profile: str = "comet-r2"


def _inside_git(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in path.resolve().parents)


def _has_reparse_ancestor(path: Path) -> bool:
    for node in (path.absolute(), *path.absolute().parents):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or node.is_symlink()
        ):
            return True
    return False


def load_config(path: Path) -> R2Config:
    """Read only non-secret configuration; credential material stays in the SDK file."""
    if _has_reparse_ancestor(path):
        raise ValueError("R2 config path cannot contain symlinks or reparse points")
    if _inside_git(path) or path.resolve().is_relative_to(repo_root().resolve()):
        raise ValueError("R2 config must be stored outside the repository")
    value = _strict_json_loads(path.read_text(encoding="utf-8"))
    if set(value) != {"bucket", "endpoint_url", "public_base_url", "credentials_file", "profile"}:
        raise ValueError("R2 config must contain only the five documented non-secret fields")
    if any(not isinstance(v, str) or not v.strip() for v in value.values()):
        raise ValueError("R2 config fields must be nonempty strings")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value["bucket"]):
        raise ValueError("invalid R2 bucket name")
    for field in ("endpoint_url", "public_base_url"):
        url = urlsplit(value[field])
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.port not in (None, 443)
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError("R2 URLs must be HTTPS origins without credentials or paths")
        if field == "endpoint_url" and not re.fullmatch(
            r"[a-z0-9.-]+\.r2\.cloudflarestorage\.com", url.hostname
        ):
            raise ValueError("R2 endpoint must be an official Cloudflare S3 origin")
    if value["profile"] != "comet-r2":
        raise ValueError("R2 must use the dedicated comet-r2 credentials profile")
    credentials = Path(value["credentials_file"])
    if not credentials.is_absolute():
        raise ValueError("R2 credentials_file must be an absolute local path")
    if credentials.anchor.startswith("\\\\") or _has_reparse_ancestor(credentials):
        raise ValueError("R2 credentials path must be local without symlinks or reparse points")
    credentials = credentials.resolve()
    if (
        _inside_git(credentials)
        or credentials.is_relative_to(repo_root().resolve())
        or not credentials.is_file()
    ):
        raise ValueError("R2 credentials must exist outside the repository")
    return R2Config(
        value["bucket"],
        value["endpoint_url"].rstrip("/"),
        value["public_base_url"].rstrip("/"),
        credentials,
        value["profile"],
    )


def s3_client(config: R2Config) -> Any:
    """Use the optional official SDK with only the explicit shared-credentials profile."""
    boto3 = import_module("boto3")
    config_type = import_module("botocore.config").Config
    credential_provider = import_module("botocore.credentials").SharedCredentialProvider

    for name in ("boto3", "botocore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    credentials = credential_provider(
        creds_filename=str(config.credentials_file), profile_name=config.profile
    ).load()
    if credentials is None:
        raise ValueError("R2 shared-credentials profile is unavailable")
    session = boto3.Session(
        aws_access_key_id=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        aws_session_token=credentials.token,
        region_name="auto",
    )
    return session.client(
        "s3",
        endpoint_url=config.endpoint_url,
        config=config_type(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=60,
            retries={"mode": "standard", "total_max_attempts": 3},
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def inventory_hash(files: dict[str, Any]) -> str:
    return _sha(_canonical_json_bytes(files))


def _validate_sdp_public_safe(document: dict[str, Any]) -> None:
    """Scan schema-validated public correction timestamps without changing their transport."""
    validate_sdp_stats(document)
    scanned = deepcopy(document)
    for row in scanned["team_matches"]:
        for correction in row["display_corrections"].values():
            # The SDP schema permits exactly this public timestamp at this path.
            # Rename its key only in the scan copy; every value still gets scanned.
            correction["confirmation_recorded_at"] = correction.pop(
                "owner_confirmation_recorded_at"
            )
    _assert_public_safe(scanned)


def prepare_generation(generation: Path, output: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Return verified compressed bytes; disposable copies use the system temporary disk."""
    # Keep the public API/output receipt location; staging must not accumulate there.
    with TemporaryDirectory(prefix="comet-r2-") as directory:
        return _prepare_generation(generation, Path(directory))


def _prepare_generation(generation: Path, staging: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Re-sanitize inside our owned temporary directory, cleaned on success or failure."""
    receipt = _strict_json_loads((generation / "receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "fpl.sdp-dashboard-generation/v1" or not receipt.get(
        "completed_at"
    ):
        raise ValueError("R2 publication requires a completed dashboard generation")
    completed = datetime.fromisoformat(receipt["completed_at"])
    if completed.tzinfo is None or completed.utcoffset() is None or completed > datetime.now(UTC):
        raise ValueError("R2 generation completion time is invalid")
    source_manifest = validate_dashboard_json(generation / "public/data")
    if source_manifest["content_sha256"] != receipt.get("public_package", {}).get(
        "manifest_content_sha256"
    ):
        raise ValueError("R2 source dashboard does not match its completed generation receipt")
    package_public_dashboard(
        generation / "public/data", staging / "sanitized-data", staging / "sanitized-data.zip"
    )
    documents = {}
    for name, validate, receipt_key, size_key in (
        ("sdp_stats", _validate_sdp_public_safe, "sdp_sidecar", "byte_count"),
        ("competitive_schedule", validate_competitive_schedule, "competitive_schedule", "bytes"),
    ):
        body = (generation / f"public/sdp/{name}.json").read_bytes()
        pin = receipt.get(receipt_key, {})
        if pin.get("sha256") != _sha(body) or pin.get(size_key) != len(body):
            raise ValueError("R2 companion does not match its completed generation receipt")
        document = _strict_json_loads(body.decode("utf-8"))
        validate(document)
        if name != "sdp_stats":
            _assert_public_safe(document)
        documents[f"sdp/{name}.json"] = document
    check_observed_freshness(staging / "sanitized-data", documents["sdp/sdp_stats.json"])
    documents["sdp/publication_status.json"] = publication_status(
        staging / "sanitized-data", documents["sdp/sdp_stats.json"]
    )
    _assert_public_safe(documents["sdp/publication_status.json"])
    compressed: dict[str, bytes] = {}
    inventory: dict[str, Any] = {}
    for relative in sorted(PUBLIC_FILES):
        if relative.startswith("data/"):
            body = (staging / "sanitized-data" / relative.removeprefix("data/")).read_bytes()
        else:
            body = _canonical_json_bytes(documents[relative], indent=2)
        inventory[relative] = {"sha256": _sha(body), "size_bytes": len(body)}
        stream = io.BytesIO()
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as zipped:
            zipped.write(body)
        compressed[relative] = stream.getvalue()
    return compressed, inventory


def validate_pointer(value: dict[str, Any]) -> None:
    if (
        set(value)
        != {"schema", "schema_version", "generation_sha256", "base_path", "published_at", "files"}
        or value["schema"] != "fpl.public-dashboard-current"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or not isinstance(value["files"], dict)
        or set(value["files"]) != PUBLIC_FILES
    ):
        raise ValueError("invalid R2 current pointer contract")
    for entry in value["files"].values():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"sha256", "size_bytes"}
            or not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            or type(entry["size_bytes"]) is not int
            or entry["size_bytes"] <= 0
        ):
            raise ValueError("invalid R2 pointer file inventory")
    digest = inventory_hash(value["files"])
    if value["generation_sha256"] != digest or value["base_path"] != f"generations/{digest}":
        raise ValueError("R2 pointer generation identity mismatch")
    stamp = datetime.fromisoformat(value["published_at"])
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("R2 pointer publication timestamp must be timezone-aware")
    _assert_public_safe(value)


def _read(client: Any, bucket: str, key: str, limit: int) -> tuple[bytes, dict[str, Any]] | None:
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") in (
            "NoSuchKey",
            "404",
            "NotFound",
        ):
            return None
        raise RuntimeError("R2 object read failed") from None
    stream = response["Body"]
    try:
        body = stream.read(limit + 1)
    finally:
        stream.close()
    if not isinstance(body, bytes) or len(body) > limit:
        raise ValueError("R2 object exceeds its declared bound")
    return body, response


def _keys(client: Any, bucket: str, prefix: str) -> set[str]:
    listing = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
    if listing.get("IsTruncated"):
        raise ValueError("R2 generation contains more than the public file allowlist")
    return {entry["Key"] for entry in listing.get("Contents", [])}


def _verify(body: bytes, metadata: dict[str, Any], expected: bytes, entry: dict[str, Any]) -> None:
    if (
        body != expected
        or metadata.get("ContentEncoding") != "gzip"
        or metadata.get("ContentType") != "application/json"
        or metadata.get("CacheControl") != _IMMUTABLE_CACHE
    ):
        raise ValueError("R2 immutable object content or metadata mismatch")
    decoded = gzip.decompress(body)
    if _sha(decoded) != entry["sha256"] or len(decoded) != entry["size_bytes"]:
        raise ValueError("R2 decoded object does not match its public inventory")


def publish_r2_dashboard(
    generation: Path,
    config_path: Path,
    output: Path,
    *,
    client: Any = None,
    published_at: datetime | None = None,
) -> dict[str, Any]:
    """Caller holds the existing refresh lock; every failure has a non-secret receipt."""
    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {"status": "FAILED", "pointer_update_attempted": False}
    try:
        config = load_config(config_path)
        encoded, inventory = prepare_generation(generation, output)
        digest = inventory_hash(inventory)
        stamp = published_at or datetime.now(UTC)
        pointer = {
            "schema": "fpl.public-dashboard-current",
            "schema_version": 1,
            "generation_sha256": digest,
            "base_path": f"generations/{digest}",
            "published_at": stamp.isoformat(),
            "files": inventory,
        }
        validate_pointer(pointer)
        pointer_body = _canonical_json_bytes(pointer, indent=2)
        (output / "proposed-current.json").write_bytes(pointer_body)
        report.update(
            {
                "generation_sha256": digest,
                "files": len(inventory),
                "public_base_url": config.public_base_url,
            }
        )
        if client is None:
            client = s3_client(config)
        previous = _read(client, config.bucket, "current.json", 65536)
        previous_body = previous[0] if previous else None
        (output / "previous-current.json").write_bytes(previous_body or b"null\n")
        report["previous_pointer_sha256"] = _sha(previous_body) if previous_body else None
        if previous:
            validate_pointer(_strict_json_loads(previous[0].decode("utf-8")))
            if not isinstance(previous[1].get("ETag"), str):
                raise ValueError("R2 previous pointer lacks an ETag")
            if (
                previous[1].get("CacheControl") != "no-store"
                or previous[1].get("ContentType") != "application/json"
            ):
                raise ValueError("R2 previous pointer has unsafe cache or content metadata")
        prefix = f"generations/{digest}/"
        expected_keys = {prefix + relative for relative in inventory}
        if _keys(client, config.bucket, prefix) - expected_keys:
            raise ValueError("R2 immutable generation contains unrecognized objects")
        for relative, body in encoded.items():
            key = prefix + relative
            existing = _read(client, config.bucket, key, len(body))
            if existing is None:
                client.put_object(
                    Bucket=config.bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/json",
                    ContentEncoding="gzip",
                    CacheControl=_IMMUTABLE_CACHE,
                    IfNoneMatch="*",
                )
                existing = _read(client, config.bucket, key, len(body))
            if existing is None:
                raise ValueError("R2 uploaded object is missing")
            _verify(existing[0], existing[1], body, inventory[relative])
        if _keys(client, config.bucket, prefix) != expected_keys:
            raise ValueError("R2 uploaded generation inventory is incomplete")
        if (
            previous
            and _strict_json_loads(previous[0].decode("utf-8"))["generation_sha256"] == digest
        ):
            report["status"] = "COMPLETE"
            report["already_current"] = True
        else:
            condition = {"IfMatch": previous[1]["ETag"]} if previous else {"IfNoneMatch": "*"}
            report["pointer_update_attempted"] = True
            client.put_object(
                Bucket=config.bucket,
                Key="current.json",
                Body=pointer_body,
                ContentType="application/json",
                CacheControl="no-store",
                **condition,
            )
            report["status"] = "COMPLETE"
            report["already_current"] = False
    except Exception as exc:
        # SDK exceptions may contain request/credential context. Never serialize or log them.
        report["error_type"] = type(exc).__name__
        report["error"] = (
            "R2 publication failed; inspect configuration and retained public inventory"
        )
        if report["pointer_update_attempted"]:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in (
                "PreconditionFailed",
                "ConditionalRequestConflict",
                "412",
                "409",
            ):
                report["error"] = "Pointer changed concurrently; conditional publication rejected"
            else:
                report["status"] = "UNKNOWN"
                report["error"] = "Pointer write unconfirmed; verify current.json before retrying"
    report["finished_at"] = datetime.now(UTC).isoformat()
    (output / "receipt.json").write_bytes(_canonical_json_bytes(report, indent=2))
    return report
