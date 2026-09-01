"""Build a public-safe package from one validated dashboard JSON generation.

The normal dashboard generation is an internal immutable read model.  It may include
browser-specific ``user_custom`` optimizer plans and an absolute local path to the squad
rules file.  Those values must never leak into the static public deployment.  This module
is a narrow transport boundary: it validates the source generation, removes only custom
plans, normalizes the one provenance path, reseals the dashboard manifest, validates the
result, and emits a deterministic ZIP containing the complete read-model generation at
its root.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

from fpl.publish.dashboard_json import (
    FIXTURE_MATRIX_FILENAME,
    MANIFEST_FILENAME,
    NEXT_GW_FILENAME,
    OPTIMIZER_AUDIT_FILENAME,
    PLAYER_ACTUALS_FILENAME,
    PLAYER_FORECAST_VS_ACTUAL_FILENAME,
    PLAYER_HORIZONS_FILENAME,
    PLAYER_PROVISIONAL_ACTUALS_FILENAME,
    PLAYERS_FILENAME,
    SUMMARY_FILENAME,
    TEAM_ACTUALS_FILENAME,
    TEAM_FORECAST_VS_ACTUAL_FILENAME,
    TEAM_PROVISIONAL_ACTUALS_FILENAME,
    DashboardJsonError,
    _file_row_count,
    _manifest_content_sha256,
    validate_dashboard_json,
)
from fpl.publish.export import (
    BiExportError,
    _canonical_json_bytes,
    _sha256_bytes,
    _sha256_file,
    _strict_json_loads,
)

PUBLIC_DASHBOARD_PACKAGE_SCHEMA: Final[str] = "fpl.public-dashboard-package"
PUBLIC_DASHBOARD_PACKAGE_SCHEMA_VERSION: Final[int] = 1
PUBLIC_SQUAD_RULES_PATH: Final[str] = "config/squad_2026_27.yaml"

_READ_MODEL_FILENAMES: Final[tuple[str, ...]] = tuple(
    sorted(
        (
            FIXTURE_MATRIX_FILENAME,
            PLAYER_HORIZONS_FILENAME,
            PLAYER_ACTUALS_FILENAME,
            PLAYER_PROVISIONAL_ACTUALS_FILENAME,
            TEAM_ACTUALS_FILENAME,
            TEAM_PROVISIONAL_ACTUALS_FILENAME,
            PLAYERS_FILENAME,
            SUMMARY_FILENAME,
            NEXT_GW_FILENAME,
            PLAYER_FORECAST_VS_ACTUAL_FILENAME,
            TEAM_FORECAST_VS_ACTUAL_FILENAME,
            OPTIMIZER_AUDIT_FILENAME,
        )
    )
)
_ARCHIVE_FILENAMES: Final[tuple[str, ...]] = tuple(
    sorted((*_READ_MODEL_FILENAMES, MANIFEST_FILENAME))
)
_FORMAL_PLAN_KINDS: Final[frozenset[str]] = frozenset({"platform_default", "platform_diagnostic"})
_ALL_PLAN_KINDS: Final[frozenset[str]] = frozenset({*_FORMAL_PLAN_KINDS, "user_custom"})
_SENSITIVE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "access_key",
        "account_id",
        "api_key",
        "apikey",
        "entry",
        "auth",
        "authorization",
        "client_secret",
        "entry_id",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
        "user_id",
    }
)
_SENSITIVE_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "cookie",
        "credential",
        "email",
        "manager",
        "owner",
        "passwd",
        "password",
        "secret",
        "session",
        "token",
    }
)
_PRIVATE_STRING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"(?i)(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[a-z0-9-]+"
        r"(?:\.[a-z0-9-]+)+(?![\w.-])"
    ),
    re.compile(r"(?i)\b(?:manager|owner|entry|user)(?:[\s_:#-]*(?:id)?[\s_:#-]*)?\d+\b"),
    re.compile(r"(?i)\buser[_ -]?custom\b"),
)
_FORMAL_FORBIDDEN_POLICY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "bank",
        "bank_tenths",
        "budget",
        "budget_millions",
        "budget_tenths",
        "current_squad",
        "current_squad_codes",
        "initial_squad",
        "initial_squad_codes",
        "purchase_prices",
        "selling_prices",
        "team_value",
    }
)
_DOCUMENT_TOP_LEVEL_KEYS: Final[dict[str, frozenset[str]]] = {
    FIXTURE_MATRIX_FILENAME: frozenset({"schema", "json_schema_version", "teams", "schedule"}),
    PLAYERS_FILENAME: frozenset({"schema", "json_schema_version", "players"}),
    PLAYER_ACTUALS_FILENAME: frozenset({"schema", "json_schema_version", "players"}),
    PLAYER_PROVISIONAL_ACTUALS_FILENAME: frozenset(
        {"schema", "json_schema_version", "captured_at", "players"}
    ),
    TEAM_ACTUALS_FILENAME: frozenset({"schema", "json_schema_version", "teams"}),
    TEAM_PROVISIONAL_ACTUALS_FILENAME: frozenset(
        {"schema", "json_schema_version", "captured_at", "teams"}
    ),
    PLAYER_HORIZONS_FILENAME: frozenset(
        {"schema", "json_schema_version", "semantics", "horizon_fields", "players"}
    ),
    NEXT_GW_FILENAME: frozenset({"schema", "json_schema_version", "plans"}),
    SUMMARY_FILENAME: frozenset(
        {
            "schema",
            "json_schema_version",
            "latest_run",
            "roster",
            "next_gameweek",
            "top_xp",
            "horizon_top_xp",
            "flagged_top_xp",
            "easiest_fixtures",
            "hardest_fixtures",
            "optimizer_plans",
            "ease_index_formula_version",
        }
    ),
    PLAYER_FORECAST_VS_ACTUAL_FILENAME: frozenset(
        {"schema", "json_schema_version", "semantics", "runs", "has_outcomes"}
    ),
    TEAM_FORECAST_VS_ACTUAL_FILENAME: frozenset(
        {"schema", "json_schema_version", "semantics", "runs", "has_outcomes"}
    ),
    OPTIMIZER_AUDIT_FILENAME: frozenset({"schema", "json_schema_version", "plans"}),
}
_PLAN_LISTS: Final[tuple[tuple[str, str], ...]] = (
    (NEXT_GW_FILENAME, "plans"),
    (SUMMARY_FILENAME, "optimizer_plans"),
    (OPTIMIZER_AUDIT_FILENAME, "plans"),
)
_FIXED_ZIP_TIMESTAMP: Final[tuple[int, int, int, int, int, int]] = (1980, 1, 1, 0, 0, 0)


class PublicDashboardPackageError(RuntimeError):
    """The source cannot be represented as a safe, complete public package."""


@dataclass(frozen=True, slots=True)
class PublicDashboardPackageResult:
    """Paths and immutable identities emitted for a deployment workflow."""

    output_dir: Path
    archive_path: Path
    archive_sha256: str
    archive_size_bytes: int
    manifest_content_sha256: str

    def metadata(self) -> dict[str, str | int]:
        """Machine-readable output; release tag/repository remain CI-owned fields."""
        return {
            "schema": PUBLIC_DASHBOARD_PACKAGE_SCHEMA,
            "schema_version": PUBLIC_DASHBOARD_PACKAGE_SCHEMA_VERSION,
            "output_dir": str(self.output_dir),
            "asset_path": str(self.archive_path),
            "asset_name": self.archive_path.name,
            "asset_sha256": self.archive_sha256,
            "asset_size_bytes": self.archive_size_bytes,
            "manifest_content_sha256": self.manifest_content_sha256,
        }


@dataclass(frozen=True, slots=True)
class _PlanIdentity:
    """Stable fields that must describe one optimizer run identically in every file."""

    plan_kind: str
    decision_sha256: str
    forecast_run_id: str
    component_modes_json: bytes
    display_label: str


def _load_document(path: Path) -> dict[str, Any]:
    try:
        return _strict_json_loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PublicDashboardPackageError(f"cannot read {path}: {exc}") from exc
    except BiExportError as exc:
        raise PublicDashboardPackageError(f"{path} is not strict JSON: {exc}") from exc


def _require_string(plan: Mapping[str, Any], key: str, subject: str) -> str:
    value = plan.get(key)
    if not isinstance(value, str) or not value:
        raise PublicDashboardPackageError(f"{subject} {key} must be a non-empty string")
    return value


def _require_mapping(plan: Mapping[str, Any], key: str, subject: str) -> Mapping[str, Any]:
    value = plan.get(key)
    if not isinstance(value, dict):
        raise PublicDashboardPackageError(f"{subject} {key} must be an object")
    return value


def _require_list(plan: Mapping[str, Any], key: str, subject: str) -> list[Any]:
    value = plan.get(key)
    if not isinstance(value, list):
        raise PublicDashboardPackageError(f"{subject} {key} must be an array")
    return value


def _validate_common_plan_shape(plan: Mapping[str, Any], subject: str) -> tuple[str, _PlanIdentity]:
    optimizer_run_id = _require_string(plan, "optimizer_run_id", subject)
    forecast_run_id = _require_string(plan, "forecast_run_id", subject)
    decision_sha256 = _require_string(plan, "decision_sha256", subject)
    if len(decision_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in decision_sha256
    ):
        raise PublicDashboardPackageError(f"{subject} decision_sha256 is not a SHA-256")
    plan_kind = _require_string(plan, "plan_kind", subject)
    if plan_kind not in _ALL_PLAN_KINDS:
        raise PublicDashboardPackageError(f"{subject} has unknown plan_kind {plan_kind!r}")
    display_label = _require_string(plan, "display_label", subject)
    component_modes = _require_mapping(plan, "component_modes", subject)
    return optimizer_run_id, _PlanIdentity(
        plan_kind=plan_kind,
        decision_sha256=decision_sha256,
        forecast_run_id=forecast_run_id,
        component_modes_json=_canonical_json_bytes(component_modes),
        display_label=display_label,
    )


def _validate_file_specific_plan_shape(
    plan: Mapping[str, Any], *, filename: str, subject: str
) -> None:
    if filename == NEXT_GW_FILENAME:
        _require_mapping(plan, "policy", subject)
        weeks = _require_list(plan, "weeks", subject)
        if not weeks or any(not isinstance(week, dict) for week in weeks):
            raise PublicDashboardPackageError(
                f"{subject} weeks must contain at least one gameweek object"
            )
        _require_mapping(plan, "player_xp", subject)
        _require_mapping(plan, "squad_context", subject)
    elif filename == SUMMARY_FILENAME:
        pass
    elif filename == OPTIMIZER_AUDIT_FILENAME:
        _require_mapping(plan, "provenance", subject)
        _require_mapping(plan, "solver", subject)
        _require_mapping(plan, "search_policy", subject)
        _require_mapping(plan, "rules_snapshot", subject)
        _require_list(plan, "assumptions", subject)
    else:  # pragma: no cover - closed internal tuple
        raise AssertionError(f"unsupported plan file {filename}")


def _require_formal_policy_defaults(
    plan: Mapping[str, Any], *, filename: str, subject: str
) -> None:
    if filename == NEXT_GW_FILENAME:
        policy = _require_mapping(plan, "policy", subject)
    elif filename == OPTIMIZER_AUDIT_FILENAME:
        policy = _require_mapping(plan, "search_policy", subject)
        if policy.get("plan_origin") != "platform":
            raise PublicDashboardPackageError(
                f"{subject} formal search_policy.plan_origin must be platform"
            )
    else:
        return

    forbidden_fields = sorted(_FORMAL_FORBIDDEN_POLICY_FIELDS.intersection(policy))
    if forbidden_fields:
        raise PublicDashboardPackageError(
            f"{subject} formal policy contains owner-specific fields: {forbidden_fields}"
        )

    for key in ("locked_codes", "excluded_codes"):
        raw_codes = policy.get(key)
        if not isinstance(raw_codes, list):
            raise PublicDashboardPackageError(f"{subject} formal {key} must be an array")
        if raw_codes:
            raise PublicDashboardPackageError(
                f"{subject} formal {key} must be empty; user-specific locks/exclusions "
                "cannot be published as a platform plan"
            )
    threshold = policy.get("min_bench_appearance")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise PublicDashboardPackageError(f"{subject} formal min_bench_appearance must be numeric")
    if float(threshold) != 0.0:
        raise PublicDashboardPackageError(f"{subject} formal min_bench_appearance must be 0.0")


def _sanitize_plan_list(
    document: dict[str, Any], *, filename: str, list_key: str
) -> dict[str, _PlanIdentity]:
    raw_plans = document.get(list_key)
    if not isinstance(raw_plans, list):
        raise PublicDashboardPackageError(f"{filename} {list_key} must be an array")

    identities: dict[str, _PlanIdentity] = {}
    sanitized: list[dict[str, Any]] = []
    formal_counts = dict.fromkeys(_FORMAL_PLAN_KINDS, 0)
    for index, raw_plan in enumerate(raw_plans):
        subject = f"{filename} {list_key}[{index}]"
        if not isinstance(raw_plan, dict):
            raise PublicDashboardPackageError(f"{subject} must be an object")
        optimizer_run_id, identity = _validate_common_plan_shape(raw_plan, subject)
        plan_kind = identity.plan_kind
        _validate_file_specific_plan_shape(raw_plan, filename=filename, subject=subject)
        if optimizer_run_id in identities:
            raise PublicDashboardPackageError(
                f"{filename} repeats optimizer_run_id {optimizer_run_id}"
            )
        identities[optimizer_run_id] = identity

        if filename == OPTIMIZER_AUDIT_FILENAME:
            search_policy = _require_mapping(raw_plan, "search_policy", subject)
            expected_origin = "user_custom" if plan_kind == "user_custom" else "platform"
            if search_policy.get("plan_origin") != expected_origin:
                raise PublicDashboardPackageError(
                    f"{subject} search_policy.plan_origin disagrees with plan_kind"
                )

        if plan_kind == "user_custom":
            continue
        _require_formal_policy_defaults(raw_plan, filename=filename, subject=subject)
        formal_counts[plan_kind] += 1
        if filename == OPTIMIZER_AUDIT_FILENAME:
            provenance = raw_plan["provenance"]
            assert isinstance(provenance, dict)  # narrowed by the shape validator above
            if not isinstance(provenance.get("squad_rules_path"), str):
                raise PublicDashboardPackageError(
                    f"{subject} provenance.squad_rules_path must be a string"
                )
            provenance["squad_rules_path"] = PUBLIC_SQUAD_RULES_PATH
        sanitized.append(raw_plan)

    invalid_counts = {kind: count for kind, count in formal_counts.items() if count != 1}
    if invalid_counts:
        raise PublicDashboardPackageError(
            f"{filename} must contain exactly one platform_default and exactly one "
            f"platform_diagnostic plan; found {dict(sorted(formal_counts.items()))}"
        )
    document[list_key] = sanitized
    return identities


def _sanitize_plans(documents: Mapping[str, dict[str, Any]]) -> None:
    identities: list[tuple[str, dict[str, _PlanIdentity]]] = []
    for filename, list_key in _PLAN_LISTS:
        identities.append(
            (
                filename,
                _sanitize_plan_list(documents[filename], filename=filename, list_key=list_key),
            )
        )
    reference_filename, reference = identities[0]
    for filename, current in identities[1:]:
        if current != reference:
            raise PublicDashboardPackageError(
                f"optimizer plan stable identities disagree between {reference_filename} "
                f"and {filename}"
            )


def _is_absolute_path(value: str) -> bool:
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()


def _is_sensitive_field(key: str) -> bool:
    snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", snake_case).strip("_")
    tokens = frozenset(part for part in normalized.split("_") if part)
    return normalized in _SENSITIVE_FIELD_NAMES or bool(tokens & _SENSITIVE_KEY_TOKENS)


def _assert_public_safe(value: object, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "user_custom" or _is_absolute_path(key) or _is_sensitive_field(key):
                raise PublicDashboardPackageError(
                    f"public package contains unsafe object key at {location}: {key!r}"
                )
            _assert_public_safe(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_public_safe(child, f"{location}[{index}]")
    elif isinstance(value, str):
        if value == "user_custom":
            raise PublicDashboardPackageError(
                f"public package retains custom-plan ownership at {location}"
            )
        if _is_absolute_path(value):
            raise PublicDashboardPackageError(
                f"public package retains an absolute path at {location}: {value!r}"
            )
        if any(pattern.search(value) for pattern in _PRIVATE_STRING_PATTERNS):
            raise PublicDashboardPackageError(
                f"public package contains private-looking text at {location}"
            )


def _validate_document_envelopes(documents: Mapping[str, dict[str, Any]]) -> None:
    for filename, allowed_keys in _DOCUMENT_TOP_LEVEL_KEYS.items():
        actual_keys = frozenset(documents[filename])
        if actual_keys != allowed_keys:
            raise PublicDashboardPackageError(
                f"{filename} has unsupported top-level field drift; expected "
                f"{sorted(allowed_keys)}, found {sorted(actual_keys)}"
            )


def _render_sanitized_generation(
    source: Path, staging: Path, source_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    documents = {filename: _load_document(source / filename) for filename in _READ_MODEL_FILENAMES}
    _validate_document_envelopes(documents)
    _sanitize_plans(documents)
    for filename, document in documents.items():
        _assert_public_safe(document, f"{filename}:$")

    files: dict[str, dict[str, Any]] = {}
    for filename in _READ_MODEL_FILENAMES:
        document = documents[filename]
        # Keep the high-cardinality positional horizon transport compact after the
        # public-safety pass. Re-expanding it here would more than double the served
        # payload and undo the schema-v4 wire-format budget.
        payload = _canonical_json_bytes(
            document,
            indent=None if filename == PLAYER_HORIZONS_FILENAME else 2,
        )
        (staging / filename).write_bytes(payload)
        files[filename] = {
            "row_count": _file_row_count(document, filename),
            "sha256": _sha256_bytes(payload),
        }

    manifest = dict(source_manifest)
    manifest["files"] = files
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    _assert_public_safe(manifest, f"{MANIFEST_FILENAME}:$")
    (staging / MANIFEST_FILENAME).write_bytes(_canonical_json_bytes(manifest, indent=2))
    return manifest


def _write_deterministic_zip(source: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for filename in _ARCHIVE_FILENAMES:
            info = zipfile.ZipInfo(filename=filename, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                (source / filename).read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def _validate_archive(directory: Path, archive_path: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            if tuple(archive.namelist()) != _ARCHIVE_FILENAMES:
                raise PublicDashboardPackageError(
                    "public dashboard archive must contain exactly the declared read-model "
                    "files and manifest at its root in deterministic order"
                )
            for filename in _ARCHIVE_FILENAMES:
                info = archive.getinfo(filename)
                if info.date_time != _FIXED_ZIP_TIMESTAMP or info.is_dir():
                    raise PublicDashboardPackageError(
                        f"public dashboard archive metadata drifted for {filename}"
                    )
                if archive.read(filename) != (directory / filename).read_bytes():
                    raise PublicDashboardPackageError(
                        f"public dashboard archive payload disagrees for {filename}"
                    )
    except (OSError, zipfile.BadZipFile) as exc:
        raise PublicDashboardPackageError(
            f"cannot validate public dashboard archive {archive_path}: {exc}"
        ) from exc


def _resolved_output(path: Path, *, kind: str) -> Path:
    resolved = path.parent.resolve() / path.name
    if not resolved.name or resolved == resolved.parent:
        raise ValueError(f"{kind} must name a concrete child path")
    return resolved


def package_public_dashboard(
    input_dir: Path,
    output_dir: Path,
    archive_path: Path,
) -> PublicDashboardPackageResult:
    """Sanitize and deterministically package one validated dashboard generation.

    The input is read-only.  Existing outputs are never overwritten, and a failed build
    cleans both staged and promoted outputs so CI cannot mistake a partial pair for a release.
    """
    source = Path(input_dir).resolve()
    output = _resolved_output(Path(output_dir), kind="output_dir")
    archive = _resolved_output(Path(archive_path), kind="archive_path")
    if archive.suffix.lower() != ".zip":
        raise ValueError("archive_path must end in .zip")
    if output == source or source in output.parents or source in archive.parents:
        raise ValueError("public package outputs must be outside the input generation")
    if archive == output or output in archive.parents:
        raise ValueError("archive_path must be outside output_dir")
    if output.exists() or output.is_symlink():
        raise PublicDashboardPackageError(f"refusing to overwrite existing output {output}")
    if archive.exists() or archive.is_symlink():
        raise PublicDashboardPackageError(f"refusing to overwrite existing archive {archive}")

    source_manifest = validate_dashboard_json(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent))
    descriptor, temporary_archive_name = tempfile.mkstemp(
        prefix=f".{archive.name}.", suffix=".tmp", dir=archive.parent
    )
    os.close(descriptor)
    temporary_archive = Path(temporary_archive_name)
    promoted_output = False
    promoted_archive = False
    succeeded = False
    try:
        manifest = _render_sanitized_generation(source, staging, source_manifest)
        validated_manifest = validate_dashboard_json(staging)
        if validated_manifest["content_sha256"] != manifest["content_sha256"]:
            raise PublicDashboardPackageError(
                "sanitized manifest identity changed during validation"
            )
        _write_deterministic_zip(staging, temporary_archive)
        _validate_archive(staging, temporary_archive)

        os.replace(staging, output)
        promoted_output = True
        os.replace(temporary_archive, archive)
        promoted_archive = True
        final_manifest = validate_dashboard_json(output)
        _validate_archive(output, archive)
        result = PublicDashboardPackageResult(
            output_dir=output,
            archive_path=archive,
            archive_sha256=_sha256_file(archive),
            archive_size_bytes=archive.stat().st_size,
            manifest_content_sha256=str(final_manifest["content_sha256"]),
        )
        succeeded = True
        return result
    except (DashboardJsonError, BiExportError, OSError, zipfile.BadZipFile) as exc:
        raise PublicDashboardPackageError(f"public dashboard package failed: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        temporary_archive.unlink(missing_ok=True)
        # Promotion is all-or-nothing from the caller's perspective.  These paths did not
        # exist on entry, so removing only the outputs this call created cannot clobber a
        # previous package.
        if not succeeded:
            if promoted_output:
                shutil.rmtree(output, ignore_errors=True)
            if promoted_archive:
                archive.unlink(missing_ok=True)


__all__ = [
    "PUBLIC_DASHBOARD_PACKAGE_SCHEMA",
    "PUBLIC_DASHBOARD_PACKAGE_SCHEMA_VERSION",
    "PUBLIC_SQUAD_RULES_PATH",
    "PublicDashboardPackageError",
    "PublicDashboardPackageResult",
    "package_public_dashboard",
]
