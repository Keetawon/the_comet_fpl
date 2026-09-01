"""Public dashboard packaging is complete, deterministic, and privacy-safe."""

from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from fpl.jobs.package_public_dashboard import main
from fpl.publish.contract import SEMANTIC_CONTRACT_VERSION
from fpl.publish.dashboard_json import (
    DASHBOARD_JSON_SCHEMA,
    DASHBOARD_JSON_SCHEMA_VERSION,
    FIXTURE_MATRIX_FILENAME,
    FIXTURE_MATRIX_SCHEMA,
    MANIFEST_FILENAME,
    NEXT_GW_FILENAME,
    NEXT_GW_SCHEMA,
    OPTIMIZER_AUDIT_FILENAME,
    OPTIMIZER_AUDIT_SCHEMA,
    PLAYER_ACTUALS_FILENAME,
    PLAYER_ACTUALS_SCHEMA,
    PLAYER_FORECAST_VS_ACTUAL_FILENAME,
    PLAYER_FORECAST_VS_ACTUAL_SCHEMA,
    PLAYER_HORIZONS_FILENAME,
    PLAYER_HORIZONS_SCHEMA,
    PLAYER_PROVISIONAL_ACTUALS_FILENAME,
    PLAYER_PROVISIONAL_ACTUALS_SCHEMA,
    PLAYERS_FILENAME,
    PLAYERS_SCHEMA,
    PROVISIONAL_ACTUALS_JSON_SCHEMA_VERSION,
    SUMMARY_FILENAME,
    SUMMARY_SCHEMA,
    TEAM_ACTUALS_FILENAME,
    TEAM_ACTUALS_SCHEMA,
    TEAM_FORECAST_VS_ACTUAL_FILENAME,
    TEAM_FORECAST_VS_ACTUAL_SCHEMA,
    TEAM_PROVISIONAL_ACTUALS_FILENAME,
    TEAM_PROVISIONAL_ACTUALS_SCHEMA,
    DashboardJsonError,
    _file_row_count,
    _manifest_content_sha256,
    validate_dashboard_json,
)
from fpl.publish.export import _canonical_json_bytes, _sha256_bytes
from fpl.publish.public_dashboard import (
    PUBLIC_DASHBOARD_PACKAGE_SCHEMA,
    PUBLIC_SQUAD_RULES_PATH,
    PublicDashboardPackageError,
    package_public_dashboard,
)

_FILENAMES = (
    FIXTURE_MATRIX_FILENAME,
    PLAYER_FORECAST_VS_ACTUAL_FILENAME,
    TEAM_FORECAST_VS_ACTUAL_FILENAME,
    NEXT_GW_FILENAME,
    OPTIMIZER_AUDIT_FILENAME,
    PLAYER_ACTUALS_FILENAME,
    PLAYER_PROVISIONAL_ACTUALS_FILENAME,
    TEAM_ACTUALS_FILENAME,
    TEAM_PROVISIONAL_ACTUALS_FILENAME,
    PLAYER_HORIZONS_FILENAME,
    PLAYERS_FILENAME,
    SUMMARY_FILENAME,
)
_PLAN_LOCATIONS = (
    (NEXT_GW_FILENAME, "plans"),
    (SUMMARY_FILENAME, "optimizer_plans"),
    (OPTIMIZER_AUDIT_FILENAME, "plans"),
)


def _sha(character: str) -> str:
    return character * 64


def _component_modes(kind: str) -> dict[str, str]:
    if kind == "platform_diagnostic":
        return {"attacking_mode": "v1", "assists_mode": "v1"}
    return {"attacking_mode": "v3", "assists_mode": "coupled"}


def _common_plan(kind: str) -> dict[str, Any]:
    identity = {
        "platform_default": ("default-run", _sha("a"), "Platform default"),
        "platform_diagnostic": ("diagnostic-run", _sha("b"), "Diagnostic sensitivity"),
        "user_custom": ("custom-run", _sha("c"), "Your plan"),
    }[kind]
    return {
        "optimizer_run_id": identity[0],
        "decision_sha256": identity[1],
        "forecast_run_id": "forecast-primary" if kind != "platform_diagnostic" else "forecast-v1",
        "component_modes": _component_modes(kind),
        "plan_kind": kind,
        "display_label": identity[2],
    }


def _next_plan(kind: str) -> dict[str, Any]:
    plan = {
        **_common_plan(kind),
        "as_of": "2026-08-21T17:30:00+00:00",
        "season": "2026-27",
        "gw_from": 1,
        "gw_to": 5,
        "policy": {
            "locked_codes": [1968866] if kind == "user_custom" else [],
            "excluded_codes": [],
            "min_bench_appearance": 0.0,
        },
        "weeks": [{"gw": 1, "players": [], "preserved_marker": kind}],
        "player_xp": {},
        "squad_context": {},
    }
    if kind == "user_custom":
        plan["private_owner_note"] = "manager-1968866"
    return plan


def _summary_plan(kind: str) -> dict[str, Any]:
    return _common_plan(kind)


def _audit_plan(kind: str) -> dict[str, Any]:
    origin = "user_custom" if kind == "user_custom" else "platform"
    plan = {
        **_common_plan(kind),
        "as_of": "2026-08-21T17:30:00+00:00",
        "season": "2026-27",
        "gw_from": 1,
        "gw_to": 5,
        "provenance": {
            "optimizer_commit_sha": _sha("d")[:40],
            "optimizer_worktree_clean": True,
            "forecast_artifact_sha256": _sha("e"),
            "forecast_commit_sha": _sha("f")[:40],
            "squad_rules_path": "C:\\Users\\owner\\the_comet_fpl\\config\\squad_2026_27.yaml",
            "squad_rules_contract_version": "1.0",
            "squad_rules_sha256": _sha("1"),
        },
        "solver": {"name": "CBC", "status": "Optimal"},
        "search_policy": {
            "plan_origin": origin,
            "locked_codes": [1968866] if kind == "user_custom" else [],
            "excluded_codes": [],
            "min_bench_appearance": 0.0,
        },
        "rules_snapshot": {"squad_size": 15},
        "assumptions": ["future prices are frozen"],
        "status": "complete",
    }
    if kind == "user_custom":
        plan["private_owner_note"] = "manager-1968866"
    return plan


def _documents() -> dict[str, dict[str, Any]]:
    kinds = ("platform_diagnostic", "platform_default", "user_custom")
    return {
        FIXTURE_MATRIX_FILENAME: {
            "schema": FIXTURE_MATRIX_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "teams": [
                {"season": "2026-27", "team_code": 1, "preserved": "fixture"}
            ],
            "schedule": {"gameweeks": [1, 2, 3, 4, 5]},
        },
        PLAYERS_FILENAME: {
            "schema": PLAYERS_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "players": [
                {
                    "run_id": "forecast-primary",
                    "season": "2026-27",
                    "code": 1,
                    "web_name": "Preserved Player",
                    "cold_start_player": False,
                }
            ],
        },
        PLAYER_ACTUALS_FILENAME: {
            "schema": PLAYER_ACTUALS_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "players": [
                {
                    "season": "2025-26",
                    "code": 1,
                    "actuals": [
                        {
                            "gw": 38,
                            "fixture": 380,
                            "kickoff_time": "2026-05-24T15:00:00+00:00",
                            "team_code": 1,
                            "team_short_name": "ALP",
                            "opponent_team_code": 2,
                            "opponent_short_name": "BET",
                            "was_home": True,
                            "minutes": 90,
                            "starts": 1,
                            "goals_scored": 1,
                            "assists": 0,
                            "clean_sheets": 1,
                            "goals_conceded": 0,
                            "saves": 0,
                            "bonus": 3,
                            "bps": 40,
                            "defensive_contribution": 7,
                            "expected_goals": 0.6,
                            "expected_assists": 0.1,
                            "expected_goals_conceded": 0.8,
                            "points_under_rules_2026_27": 10,
                        }
                    ],
                }
            ],
        },
        TEAM_ACTUALS_FILENAME: {
            "schema": TEAM_ACTUALS_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "teams": [
                {
                    "season": "2025-26",
                    "team_code": 1,
                    "actuals": [
                        {
                            "gw": 38,
                            "fixture": 380,
                            "kickoff_time": "2026-05-24T15:00:00+00:00",
                            "opponent_team_code": 2,
                            "opponent_short_name": "BET",
                            "was_home": True,
                            "goals_for": 2,
                            "goals_against": 0,
                            "team_xg": 1.7,
                            "team_xgc": 0.6,
                            "team_bps": 72,
                            "defensive_contribution": 58,
                        }
                    ],
                }
            ],
        },
        PLAYER_PROVISIONAL_ACTUALS_FILENAME: {
            "schema": PLAYER_PROVISIONAL_ACTUALS_SCHEMA,
            "json_schema_version": PROVISIONAL_ACTUALS_JSON_SCHEMA_VERSION,
            "captured_at": None,
            "players": [],
        },
        TEAM_PROVISIONAL_ACTUALS_FILENAME: {
            "schema": TEAM_PROVISIONAL_ACTUALS_SCHEMA,
            "json_schema_version": PROVISIONAL_ACTUALS_JSON_SCHEMA_VERSION,
            "captured_at": None,
            "teams": [],
        },
        PLAYER_HORIZONS_FILENAME: {
            "schema": PLAYER_HORIZONS_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "semantics": {
                "grain": ["run_id", "season", "code", "gw_to"],
                "cumulative_from": "dim_forecast_run.gw_from",
                "distribution_combination": "independent-gameweek-convolution-v1",
                "availability": "raw-model-distribution-unadjusted",
                "value_decimal_places": 6,
                "probability_boundary_policy": "preserve-exact-zero-one-v1",
                "thresholds": {"p_le": [2], "p_ge": [2, 4, 6, 10, 15]},
            },
            "horizon_fields": [
                "gw_to",
                "xp",
                "p_le_2",
                "p_ge_2",
                "p_ge_4",
                "p_ge_6",
                "p_ge_10",
                "p_ge_15",
            ],
            "players": [
                {
                    "run_id": "forecast-primary",
                    "season": "2026-27",
                    "code": 1,
                    "horizons": [[gw, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0] for gw in range(1, 6)],
                }
            ],
        },
        NEXT_GW_FILENAME: {
            "schema": NEXT_GW_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "plans": [_next_plan(kind) for kind in kinds],
        },
        SUMMARY_FILENAME: {
            "schema": SUMMARY_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "latest_run": None,
            "roster": {"players": 0, "teams": 0},
            "next_gameweek": None,
            "top_xp": [],
            "horizon_top_xp": [],
            "flagged_top_xp": [],
            "easiest_fixtures": [],
            "hardest_fixtures": [],
            "optimizer_plans": [_summary_plan(kind) for kind in kinds],
            "ease_index_formula_version": "fixture-ease-v1",
        },
        PLAYER_FORECAST_VS_ACTUAL_FILENAME: {
            "schema": PLAYER_FORECAST_VS_ACTUAL_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "semantics": {"grain": ["run_id", "season", "gw", "code"]},
            "runs": [],
            "has_outcomes": False,
        },
        TEAM_FORECAST_VS_ACTUAL_FILENAME: {
            "schema": TEAM_FORECAST_VS_ACTUAL_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "semantics": {"grain": ["run_id", "season", "fixture", "team_code"]},
            "runs": [],
            "has_outcomes": False,
        },
        OPTIMIZER_AUDIT_FILENAME: {
            "schema": OPTIMIZER_AUDIT_SCHEMA,
            "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
            "plans": [_audit_plan(kind) for kind in kinds],
        },
    }


def _write_generation(directory: Path, documents: dict[str, dict[str, Any]]) -> None:
    directory.mkdir()
    files: dict[str, dict[str, Any]] = {}
    for filename in _FILENAMES:
        payload = _canonical_json_bytes(documents[filename], indent=2)
        (directory / filename).write_bytes(payload)
        files[filename] = {
            "row_count": _file_row_count(documents[filename], filename),
            "sha256": _sha256_bytes(payload),
        }
    manifest: dict[str, Any] = {
        "schema": DASHBOARD_JSON_SCHEMA,
        "json_schema_version": DASHBOARD_JSON_SCHEMA_VERSION,
        "generated_at": "2026-08-21T12:00:00+00:00",
        "source": {
            "export_schema": "fpl.bi-semantic-export",
            "export_schema_version": 1,
            "semantic_contract_version": SEMANTIC_CONTRACT_VERSION,
            "export_content_sha256": _sha("2"),
            "export_created_at": "2026-08-21T11:59:00+00:00",
            "database_sha256": _sha("3"),
        },
        "runs": [
            {
                "run_id": "forecast-primary",
                "as_of": "2026-08-21T17:30:00+00:00",
                "season": "2026-27",
                "gw_from": 1,
                "gw_to": 5,
                "horizon_gameweeks": 5,
            }
        ],
        "run_ids": ["forecast-primary"],
        "ease_index_formula_version": "fixture-ease-v1",
        "files": files,
    }
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    (directory / MANIFEST_FILENAME).write_bytes(_canonical_json_bytes(manifest, indent=2))
    validate_dashboard_json(directory)


def _read_documents(directory: Path) -> dict[str, dict[str, Any]]:
    return {
        filename: json.loads((directory / filename).read_text(encoding="utf-8"))
        for filename in _FILENAMES
    }


def test_packages_only_formal_plans_and_reseals_a_deterministic_root_zip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_generation(source, _documents())
    source_bytes = {path.name: path.read_bytes() for path in source.iterdir()}

    first = package_public_dashboard(source, tmp_path / "public-one", tmp_path / "public-one.zip")
    second = package_public_dashboard(source, tmp_path / "public-two", tmp_path / "public-two.zip")

    assert first.archive_sha256 == second.archive_sha256
    assert first.archive_size_bytes == second.archive_size_bytes
    assert first.manifest_content_sha256 == second.manifest_content_sha256
    assert {path.name: path.read_bytes() for path in source.iterdir()} == source_bytes

    manifest = validate_dashboard_json(first.output_dir)
    assert manifest["content_sha256"] == first.manifest_content_sha256
    assert manifest["files"][NEXT_GW_FILENAME]["row_count"] == 2
    assert manifest["files"][OPTIMIZER_AUDIT_FILENAME]["row_count"] == 2
    assert manifest["files"][SUMMARY_FILENAME]["row_count"] == 1

    public_documents = _read_documents(first.output_dir)
    for filename, list_key in _PLAN_LOCATIONS:
        plans = public_documents[filename][list_key]
        assert [plan["plan_kind"] for plan in plans] == [
            "platform_diagnostic",
            "platform_default",
        ]
        assert all(plan["optimizer_run_id"] != "custom-run" for plan in plans)
    for plan in public_documents[OPTIMIZER_AUDIT_FILENAME]["plans"]:
        assert plan["provenance"]["squad_rules_path"] == PUBLIC_SQUAD_RULES_PATH
        assert plan["search_policy"]["plan_origin"] == "platform"
    assert public_documents[FIXTURE_MATRIX_FILENAME] == _documents()[FIXTURE_MATRIX_FILENAME]
    assert public_documents[PLAYERS_FILENAME] == _documents()[PLAYERS_FILENAME]
    assert public_documents[PLAYER_ACTUALS_FILENAME] == _documents()[PLAYER_ACTUALS_FILENAME]
    assert public_documents[TEAM_ACTUALS_FILENAME] == _documents()[TEAM_ACTUALS_FILENAME]
    assert public_documents[PLAYER_PROVISIONAL_ACTUALS_FILENAME] == _documents()[
        PLAYER_PROVISIONAL_ACTUALS_FILENAME
    ]
    assert public_documents[TEAM_PROVISIONAL_ACTUALS_FILENAME] == _documents()[
        TEAM_PROVISIONAL_ACTUALS_FILENAME
    ]
    assert public_documents[PLAYER_HORIZONS_FILENAME] == _documents()[PLAYER_HORIZONS_FILENAME]
    horizon_payload = (first.output_dir / PLAYER_HORIZONS_FILENAME).read_bytes()
    assert horizon_payload.endswith(b"\n")
    assert horizon_payload.count(b"\n") == 1
    assert horizon_payload == _canonical_json_bytes(_documents()[PLAYER_HORIZONS_FILENAME])

    joined_payload = b"".join(path.read_bytes() for path in first.output_dir.iterdir())
    assert b"user_custom" not in joined_payload
    assert b"manager-1968866" not in joined_payload
    assert b"C:\\\\Users\\\\owner" not in joined_payload
    with zipfile.ZipFile(first.archive_path) as archive:
        assert archive.namelist() == sorted((*_FILENAMES, MANIFEST_FILENAME))
        for filename in archive.namelist():
            assert archive.read(filename) == (first.output_dir / filename).read_bytes()


@pytest.mark.parametrize("missing_kind", ["platform_default", "platform_diagnostic"])
def test_refuses_a_generation_missing_either_formal_plan_kind(
    tmp_path: Path, missing_kind: str
) -> None:
    source = tmp_path / "source"
    documents = _documents()
    for filename, list_key in _PLAN_LOCATIONS:
        documents[filename][list_key] = [
            plan for plan in documents[filename][list_key] if plan["plan_kind"] != missing_kind
        ]
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match=missing_kind):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")
    assert not (tmp_path / "public").exists()
    assert not (tmp_path / "public.zip").exists()


def test_refuses_a_formal_plan_with_an_incomplete_shape(tmp_path: Path) -> None:
    source = tmp_path / "source"
    documents = _documents()
    del documents[NEXT_GW_FILENAME]["plans"][0]["weeks"]
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match="weeks must be an array"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


def test_refuses_duplicate_formal_plan_kinds(tmp_path: Path) -> None:
    source = tmp_path / "source"
    documents = _documents()
    for filename, list_key in _PLAN_LOCATIONS:
        duplicate = deepcopy(
            next(
                plan
                for plan in documents[filename][list_key]
                if plan["plan_kind"] == "platform_default"
            )
        )
        duplicate["optimizer_run_id"] = "duplicate-default-run"
        duplicate["decision_sha256"] = _sha("4")
        documents[filename][list_key].append(duplicate)
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match="exactly one platform_default"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


@pytest.mark.parametrize(
    "field_name",
    [
        "optimizer_run_id",
        "plan_kind",
        "decision_sha256",
        "forecast_run_id",
        "component_modes",
        "display_label",
    ],
)
def test_refuses_cross_file_formal_plan_identity_mismatches(
    tmp_path: Path, field_name: str
) -> None:
    source = tmp_path / "source"
    documents = _documents()
    summary_plans = documents[SUMMARY_FILENAME]["optimizer_plans"]
    default = next(plan for plan in summary_plans if plan["plan_kind"] == "platform_default")
    if field_name == "optimizer_run_id":
        default[field_name] = "other-default-run"
    elif field_name == "plan_kind":
        diagnostic = next(
            plan for plan in summary_plans if plan["plan_kind"] == "platform_diagnostic"
        )
        default[field_name], diagnostic[field_name] = diagnostic[field_name], default[field_name]
    elif field_name == "decision_sha256":
        default[field_name] = _sha("5")
    elif field_name == "forecast_run_id":
        default[field_name] = "other-forecast-run"
    elif field_name == "component_modes":
        default[field_name] = {"attacking_mode": "v4", "assists_mode": "coupled"}
    elif field_name == "display_label":
        default[field_name] = "Wrong platform label"
    else:  # pragma: no cover - closed parameter tuple
        raise AssertionError(field_name)
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match="stable identities disagree"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


@pytest.mark.parametrize(
    ("filename", "list_key", "policy_key"),
    [
        (NEXT_GW_FILENAME, "plans", "policy"),
        (OPTIMIZER_AUDIT_FILENAME, "plans", "search_policy"),
    ],
)
def test_refuses_locked_codes_disguised_as_a_formal_platform_plan(
    tmp_path: Path, filename: str, list_key: str, policy_key: str
) -> None:
    source = tmp_path / "source"
    documents = _documents()
    default = next(
        plan for plan in documents[filename][list_key] if plan["plan_kind"] == "platform_default"
    )
    default[policy_key]["locked_codes"] = [1968866]
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match="formal locked_codes must be empty"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


def test_refuses_an_absolute_path_outside_the_normalized_provenance_field(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    documents = _documents()
    documents[PLAYERS_FILENAME]["players"][0]["private_path"] = "/home/owner/secret.json"
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match="absolute path"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


@pytest.mark.parametrize("field_name", ["manager_id", "owner_email", "session_cookie"])
def test_refuses_sensitive_fields_at_any_nesting_depth(tmp_path: Path, field_name: str) -> None:
    source = tmp_path / "source"
    documents = _documents()
    documents[PLAYERS_FILENAME]["players"][0][field_name] = "do-not-publish"
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match=field_name):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


@pytest.mark.parametrize(
    "private_text",
    ["friend@example.com", "manager-1968866", "entry id: 1968866", "user_custom"],
)
def test_refuses_private_looking_text_under_an_otherwise_generic_field(
    tmp_path: Path, private_text: str
) -> None:
    source = tmp_path / "source"
    documents = _documents()
    documents[PLAYERS_FILENAME]["players"][0]["note"] = private_text
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match=r"private-looking text|custom-plan"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


@pytest.mark.parametrize("field_name", ["bank_tenths", "selling_prices", "current_squad_codes"])
def test_refuses_owner_specific_fields_disguised_as_formal_policy(
    tmp_path: Path, field_name: str
) -> None:
    source = tmp_path / "source"
    documents = _documents()
    default = next(
        plan
        for plan in documents[NEXT_GW_FILENAME]["plans"]
        if plan["plan_kind"] == "platform_default"
    )
    default["policy"][field_name] = [] if field_name.endswith(("prices", "codes")) else 0
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match="owner-specific fields"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


def test_refuses_unknown_top_level_fields_until_the_public_contract_is_reviewed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    documents = _documents()
    documents[PLAYERS_FILENAME]["future_field"] = []
    _write_generation(source, documents)

    with pytest.raises(PublicDashboardPackageError, match="unsupported top-level field drift"):
        package_public_dashboard(source, tmp_path / "public", tmp_path / "public.zip")


def test_removes_both_promoted_outputs_when_final_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _write_generation(source, _documents())
    output = tmp_path / "public"
    archive = tmp_path / "public.zip"
    real_validate = validate_dashboard_json
    calls = 0

    def fail_final_validation(path: Path) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise DashboardJsonError("forced final validation failure")
        return real_validate(path)

    monkeypatch.setattr(
        "fpl.publish.public_dashboard.validate_dashboard_json", fail_final_validation
    )
    with pytest.raises(PublicDashboardPackageError, match="forced final validation failure"):
        package_public_dashboard(source, output, archive)
    assert not output.exists()
    assert not archive.exists()


def test_cli_prints_one_machine_readable_metadata_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    _write_generation(source, deepcopy(_documents()))
    output = tmp_path / "public"
    archive = tmp_path / "dashboard-public-data.zip"

    assert main(["--input", str(source), "--output", str(output), "--archive", str(archive)]) == 0
    captured = capsys.readouterr()
    metadata = json.loads(captured.out)
    assert captured.err == ""
    assert metadata["schema"] == PUBLIC_DASHBOARD_PACKAGE_SCHEMA
    assert metadata["schema_version"] == 1
    assert metadata["output_dir"] == str(output)
    assert metadata["asset_path"] == str(archive)
    assert metadata["asset_name"] == archive.name
    assert metadata["asset_size_bytes"] == archive.stat().st_size
    assert metadata["manifest_content_sha256"] == validate_dashboard_json(output)["content_sha256"]
    assert len(metadata["asset_sha256"]) == 64
