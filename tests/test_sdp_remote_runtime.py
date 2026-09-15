"""Offline tests for the SDP primary remote runtime.

Covers read-only receipt-health parsing (including running, partial, malformed, undated,
future-dated, nested, and failed receipts), null-unknown semantics, the
never-healthy-over-a-suspect rule, deterministic time, the explicit-bound staleness
rule, and consistency of the systemd package in ``deploy/sdp-primary``.
No network, no scheduler registration, no database, no deployment.
"""

from __future__ import annotations

import configparser
import contextlib
import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fpl.config import repo_root
from fpl.jobs import sdp_capture_health as health

REPO = repo_root()
DEPLOY = REPO / "deploy" / "sdp-primary"
RUNTIME_DOC = REPO / "docs" / "sdp-primary-remote-runtime.md"

NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
NOW_ISO = "2026-09-08T12:00:00+00:00"
DATABASE = "/srv/fpl/operational.duckdb"


def _run_id(hours_before_now: int, serial: int) -> str:
    """Receipt directory name in the daily job's fixed-width ``<utcstamp>-<hex>`` shape."""
    stamp = NOW - timedelta(hours=hours_before_now)
    return stamp.strftime("%Y%m%dT%H%M%S") + f".{serial:06d}Z-cafe{serial:04d}"


def _payload(
    *,
    finished: datetime | str | None,
    healthy: bool = True,
    database: str | None = DATABASE,
    mode: str = "capture_and_stage",
    production: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": "n/a",
        "started_at": "2026-09-07T06:00:00+00:00",
        "finished_at": finished,
        "database": database,
        "healthy": healthy,
        "consumer_ready": healthy and mode == "capture_and_stage",
        "exit_code": 0 if healthy else 1,
        "mode": mode,
        "staging_status": "verified" if mode == "capture_and_stage" else "deferred",
    }
    if production is not None:
        payload["production_health"] = production
    if extra:
        payload.update(extra)
    return payload


def _write_receipt(
    runs_root: Path,
    run_id: str,
    payload: dict[str, Any] | None = None,
    *,
    raw: str | None = None,
    report: bool = True,
) -> Path:
    directory = runs_root / run_id
    directory.mkdir(parents=True)
    if report:
        # Mimic the daily job's json.dump(..., default=str) datetime serialization.
        text = raw if raw is not None else json.dumps(payload, default=str)
        (directory / "report.json").write_text(text, encoding="utf-8")
    return directory


def _invoke(arguments: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = health.main(arguments)
    return code, json.loads(buffer.getvalue())


def _run_health(
    runs_root: Path,
    *,
    now: str = NOW_ISO,
    max_age: str | None = None,
    fail_on_production: bool = False,
    database: str | None = None,
) -> tuple[int, dict[str, Any]]:
    arguments = ["--runs", str(runs_root), "--now", now]
    if max_age is not None:
        arguments += ["--max-success-age-hours", max_age]
    if fail_on_production:
        arguments.append("--fail-on-production-failure")
    if database is not None:
        arguments += ["--db", database]
    return _invoke(arguments)


def _write_dated(
    root: Path,
    run_id: str,
    hours_old: int,
    **payload_kwargs: Any,
) -> str:
    _write_receipt(
        root, run_id, _payload(finished=NOW - timedelta(hours=hours_old), **payload_kwargs)
    )
    return run_id


# --- receipt parsing, nulls, and failure handling ---


def test_missing_or_empty_runs_root_is_unknown_and_exits_zero(tmp_path: Path) -> None:
    code, report = _run_health(tmp_path / "absent")
    assert code == 0
    assert report["verdict"] == "unknown"
    assert report["schema_version"] == 2
    assert report["receipts_scanned"] == 0
    assert report["latest_completed"] is None
    assert report["latest_success"] is None
    assert report["success_age_hours"] is None
    assert report["stale"] is None
    assert report["healthy"] is None
    empty = tmp_path / "empty"
    empty.mkdir()
    code, report = _run_health(empty)
    assert code == 0
    assert report["verdict"] == "unknown"


def test_receipt_fields_parse_and_success_age_is_deterministic(tmp_path: Path) -> None:
    run_id = _run_id(30, 1)
    payload = _payload(
        finished=NOW - timedelta(hours=30),
        production={"matches_valid": 19, "global_failure": None, "failures": {}},
    )
    root = tmp_path / "runs"
    _write_receipt(root, run_id, payload)
    code, report = _run_health(root)
    assert code == 0
    assert report["verdict"] == "healthy"
    completed = report["latest_completed"]
    assert completed["run_id"] == run_id
    assert completed["healthy"] is True
    assert completed["consumer_ready"] is True
    assert completed["mode"] == "capture_and_stage"
    assert completed["database"] == DATABASE
    assert completed["finished_at"] == "2026-09-07T06:00:00+00:00"
    assert report["success_age_hours"] == 30.0
    assert report["latest_success"]["run_id"] == run_id
    assert report["production_health"]["source_run_id"] == run_id
    assert report["production_health"]["global_failure"] is None
    assert report["production_health"]["failure_count"] == 0
    assert report["healthy"] is True
    assert report["checked_at"] == NOW_ISO
    assert report["newer_suspects"]["count"] == 0


def test_staleness_only_judged_against_the_explicit_bound(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    run_id = _write_dated(root, _run_id(30, 1), 30)
    code, report = _run_health(root)
    assert (code, report["stale"]) == (0, None)
    code, report = _run_health(root, max_age="24")
    assert code == 1
    assert report["stale"] is True
    assert report["verdict"] == "stale"
    code, report = _run_health(root, max_age="48")
    assert code == 0
    assert report["stale"] is False
    assert (root / run_id / "report.json").is_file()


@pytest.mark.parametrize("bound", ["0", "-5", "nan", "inf", "abc"])
def test_age_bound_must_be_finite_and_positive(
    bound: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run_health(tmp_path, max_age=bound)
    assert excinfo.value.code == 2
    # argparse rejects non-numbers; the finite-positive guard rejects the rest.
    assert "max-success-age-hours" in capsys.readouterr().err


def test_unhealthy_newest_receipt_fails_while_older_success_is_reported(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    good_id = _write_dated(root, _run_id(30, 1), 30)
    bad_id = _run_id(6, 2)
    bad = _payload(finished=NOW - timedelta(hours=6), healthy=False)
    bad["failures"] = ["match 7001: HTTP 503"]
    _write_receipt(root, bad_id, bad)
    code, report = _run_health(root)
    assert code == 1
    assert report["verdict"] == "unhealthy"
    assert report["healthy"] is False
    assert report["latest_completed"]["run_id"] == bad_id
    assert report["latest_success"]["run_id"] == good_id
    assert report["success_age_hours"] == 30.0
    assert report["failed_receipts"]["count"] == 1
    assert report["failed_receipts"]["latest_run_id"] == bad_id
    # The failure is visible, never erased: receipts stay on disk.
    assert (root / bad_id / "report.json").is_file()


def test_running_partial_and_malformed_receipts_are_reported_and_never_fatal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    _write_receipt(root, _run_id(1, 4), report=False)  # still running or crashed
    _write_receipt(root, _run_id(2, 3), raw="{not json")
    _write_receipt(root, _run_id(3, 2), raw="{}")
    _write_receipt(root, _run_id(4, 1), raw=json.dumps({"healthy": "yes"}))
    code, report = _run_health(root)
    assert code == 0
    assert report["verdict"] == "unknown"
    assert report["running_receipts"]["count"] == 1
    assert report["running_receipts"]["latest_run_id"] == _run_id(1, 4)
    assert report["malformed_receipts"]["count"] == 3
    assert report["newer_suspects"]["count"] == 3
    assert report["undated_receipts"]["count"] == 0
    assert report["completed_receipts"]["count"] == 0
    assert report["latest_completed"] is None
    assert report["healthy"] is None
    # Under an explicit bound, a world with no provable success is stale: no receipt
    # lies healthy merely because it is unreadable.
    code, report = _run_health(root, max_age="24")
    assert code == 1
    assert report["stale"] is True


def test_undated_success_timestamp_proves_no_freshness(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    run_id = _run_id(5, 1)
    payload = _payload(finished="not-a-timestamp")
    _write_receipt(root, run_id, payload)
    code, report = _run_health(root, max_age="24")
    # Unknown timestamp != healthy freshness: the receipt is undated, so it cannot
    # prove health or freshness, and with a bound the world is stale, not fine.
    assert report["undated_receipts"]["count"] == 1
    assert report["undated_receipts"]["latest_run_id"] == run_id
    assert report["latest_success"] is None
    assert report["success_age_hours"] is None
    assert report["healthy"] is None
    assert report["stale"] is True
    assert code == 1
    assert report["verdict"] == "stale"


def test_naive_and_future_timestamps_are_rejected_as_unknown(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    naive_id = _run_id(5, 1)
    _write_receipt(root, naive_id, _payload(finished="2026-09-07 07:00:00"))
    future_id = _run_id(6, 2)
    _write_receipt(root, future_id, _payload(finished=NOW + timedelta(hours=2)))
    code, report = _run_health(root, max_age="24")
    assert report["undated_receipts"]["count"] == 2
    assert report["latest_success"] is None
    assert report["healthy"] is None
    assert report["stale"] is True
    assert code == 1


def test_older_dated_malformed_receipt_does_not_block_a_newer_proven_success(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    # A parseable-but-untrustworthy receipt can still carry a validated time: dated
    # 30h ago, provably older than the 2h success, so it blocks nothing.
    older_malformed = _payload(finished=NOW - timedelta(hours=30))
    older_malformed["healthy"] = "yes"
    _write_receipt(root, _run_id(30, 1), older_malformed)
    good_id = _write_dated(root, _run_id(2, 2), 2)
    code, report = _run_health(root, max_age="24")
    assert code == 0
    assert report["verdict"] == "healthy"
    assert report["healthy"] is True
    assert report["latest_success"]["run_id"] == good_id
    assert report["newer_suspects"]["count"] == 0
    assert report["malformed_receipts"]["count"] == 1


def test_newer_malformed_receipt_blocks_healthy_from_older_success(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    good_id = _write_dated(root, _run_id(30, 1), 30)
    # Unreadable JSON: position unknown, could be the newest state, so it blocks.
    _write_receipt(root, _run_id(2, 2), raw="{not json")
    code, report = _run_health(root, max_age="24")
    # Under an explicit bound, unproven freshness must not exit success: nonzero with
    # verdict unknown, while staleness stays null (no invented time).
    assert code == 1
    assert report["verdict"] == "unknown"
    assert report["freshness_unproven"] is True
    assert report["healthy"] is None
    assert report["stale"] is None
    assert report["latest_success"]["run_id"] == good_id
    assert report["newer_suspects"]["count"] == 1
    assert report["malformed_receipts"]["count"] == 1
    code, report = _run_health(root)
    assert code == 0
    assert report["verdict"] == "unknown"
    assert report["freshness_unproven"] is False


def test_newer_undated_completed_receipt_blocks_healthy(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    good_id = _write_dated(root, _run_id(30, 1), 30)
    newer_id = _run_id(2, 2)
    _write_receipt(root, newer_id, _payload(finished=None))  # completed, undated
    code, report = _run_health(root, max_age="24")
    assert code == 1
    assert report["verdict"] == "unknown"
    assert report["freshness_unproven"] is True
    assert report["healthy"] is None
    assert report["stale"] is None
    assert report["undated_receipts"]["count"] == 1
    assert report["undated_receipts"]["latest_run_id"] == newer_id
    assert report["latest_success"]["run_id"] == good_id


def test_receipts_order_by_validated_time_not_directory_name(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    # Directory name looks older, validated time is the newest.
    misnamed_id = _run_id(10, 1)
    _write_receipt(root, misnamed_id, _payload(finished=NOW - timedelta(hours=1)))
    # Directory name looks newer, validated time is older.
    _write_receipt(root, _run_id(2, 2), _payload(finished=NOW - timedelta(hours=20)))
    code, report = _run_health(root, max_age="24")
    assert code == 0
    assert report["latest_completed"]["run_id"] == misnamed_id
    assert report["latest_success"]["run_id"] == misnamed_id
    assert report["success_age_hours"] == 1.0
    assert report["healthy"] is True


def test_nested_predeadline_receipts_are_included_and_ordered_by_time(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    nested_good = _run_id(20, 1)
    _write_dated(root / "predeadline", nested_good, 20)  # nested, older, healthy
    direct_newer = _write_dated(root, _run_id(2, 2), 2)  # direct, newer, healthy
    code, report = _run_health(root, max_age="24")
    assert code == 0
    assert report["healthy"] is True
    assert report["latest_success"]["run_id"] == direct_newer
    assert report["receipts_scanned"] == 2
    # A newer nested pre-deadline malformed receipt blocks the healthy claim.
    nested_bad = _run_id(1, 3)
    _write_receipt(root / "predeadline", nested_bad, raw="{broken")
    code, report = _run_health(root, max_age="24")
    assert code == 1
    assert report["verdict"] == "unknown"
    assert report["freshness_unproven"] is True
    assert report["healthy"] is None
    assert report["newer_suspects"]["count"] == 1
    assert report["newer_suspects"]["latest_run_id"] == f"predeadline/{nested_bad}"
    assert report["receipts_scanned"] == 3


def test_running_nested_leaf_directory_is_a_running_receipt(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    (root / "predeadline" / _run_id(0, 1)).mkdir(parents=True)
    (_code, report) = _run_health(root)
    assert report["running_receipts"]["count"] == 1
    assert report["running_receipts"]["latest_run_id"] == f"predeadline/{_run_id(0, 1)}"
    assert report["verdict"] == "unknown"


def test_staging_outputs_of_completed_receipts_are_not_phantom_running(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    run_id = _run_id(6, 1)
    directory = _write_receipt(root, run_id, _payload(finished=NOW - timedelta(hours=6)))
    # The real daily tree: each completed receipt carries a staging/ leaf with output
    # files and no report.json of its own.
    staging = directory / "staging"
    staging.mkdir()
    (staging / "pl_sdp_identity_audit.json").write_text("{}", encoding="utf-8")
    code, report = _run_health(root)
    assert code == 0
    assert report["receipts_scanned"] == 1
    assert report["completed_receipts"]["count"] == 1
    assert report["running_receipts"]["count"] == 0
    assert report["running_receipts"]["latest_run_id"] is None


def test_pending_requires_a_true_run_directory(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    # The runs root itself is never a receipt; arbitrary grouping/empty folders are not
    # pending runs.
    (root / "grouping").mkdir(parents=True)
    (root / "grouping" / "nested-group").mkdir(parents=True)
    (root / "some-empty-folder").mkdir()
    (_code, report) = _run_health(root)
    assert report["receipts_scanned"] == 0
    assert report["running_receipts"]["count"] == 0
    # A daily-job timestamp run id is a pending run even before any file exists.
    (root / "grouping" / _run_id(0, 1)).mkdir(parents=True)
    (_code, report) = _run_health(root)
    assert report["running_receipts"]["count"] == 1
    # So is an in-progress directory witnessed by the daily job's own files, even
    # without a timestamp-shaped name.
    started = root / "grouping" / "manual-run"
    started.mkdir()
    (started / "run.log").write_text("log", encoding="utf-8")
    (_code, report) = _run_health(root)
    assert report["running_receipts"]["count"] == 2
    # But a plain folder containing only data files is not a run.
    (root / "grouping" / "not-a-run").mkdir()
    (root / "grouping" / "not-a-run" / "notes.txt").write_text("x", encoding="utf-8")
    (_code, report) = _run_health(root)
    assert report["running_receipts"]["count"] == 2


def test_database_filter_selects_matching_receipts_and_exposes_unattributed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    mine_id = _write_dated(root, _run_id(20, 1), 20)
    _write_dated(root, _run_id(2, 2), 2, database="/other/operational.duckdb")
    _write_receipt(root, _run_id(1, 3), raw="{not json")  # unattributable malformed
    code, report = _run_health(root, max_age="24", database=DATABASE)
    assert code == 1
    assert report["verdict"] == "unknown"
    assert report["receipts_scanned"] == 3
    # The other database's receipt is attributable and excluded; the malformed one is
    # unattributed, stays visible, and blocks a healthy verdict (it could be ours).
    assert report["other_database_receipts"]["count"] == 1
    assert report["unattributed_receipts"]["count"] == 1
    assert report["malformed_receipts"]["count"] == 1
    assert report["newer_suspects"]["count"] == 1
    assert report["healthy"] is None
    assert report["latest_completed"]["database"] == DATABASE
    assert report["latest_completed"]["run_id"] == mine_id
    # Without the filter the malformed receipt still belongs to the one implicit
    # database and still blocks: with a bound, unproven freshness exits nonzero.
    code, report = _run_health(root, max_age="24")
    assert code == 1
    assert report["verdict"] == "unknown"
    assert report["freshness_unproven"] is True
    assert report["healthy"] is None
    assert report["newer_suspects"]["count"] == 1


def test_unattributed_success_never_proves_freshness_for_a_requested_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    # Exactly attributed success, 30 hours old.
    attributed_id = _write_dated(root, _run_id(30, 1), 30)
    # Newer healthy, dated, but recorded without a database: it cannot prove success
    # for the requested database and blocks like any other newer suspect.
    unattributed_id = _run_id(2, 2)
    _write_dated(root, unattributed_id, 2, database=None)
    code, report = _run_health(root, max_age="24", database=DATABASE)
    assert code == 1
    assert report["verdict"] == "unknown"
    assert report["latest_success"]["run_id"] == attributed_id
    assert report["latest_completed"]["run_id"] == unattributed_id
    assert report["unattributed_receipts"]["count"] == 1
    assert report["newer_suspects"]["count"] == 1
    assert report["healthy"] is None
    # An unattributed-only world proves nothing at all for the requested database.
    root2 = tmp_path / "runs2"
    _write_dated(root2, _run_id(2, 5), 2, database=None)
    code, report = _run_health(root2, max_age="24", database=DATABASE)
    assert code == 1
    assert report["latest_success"] is None
    assert report["stale"] is True
    assert report["healthy"] is None


def test_production_health_is_reported_separately_and_opt_in_only(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    older_id = _run_id(28, 1)
    _write_receipt(
        root,
        older_id,
        _payload(
            finished=NOW - timedelta(hours=28),
            production={
                "matches_valid": 19,
                "global_failure": "SDP_SOURCE_FALLBACK",
                "schema_validation_failures": 0,
                "identity_failures": 2,
                "failures": {"7001": "SDP_IDENTITY_FALLBACK"},
            },
        ),
    )
    newest_id = _run_id(2, 2)
    _write_receipt(root, newest_id, _payload(finished=NOW - timedelta(hours=2), mode="raw_only"))
    code, report = _run_health(root, max_age="24")
    assert code == 0
    assert report["healthy"] is True
    production = report["production_health"]
    assert production["source_run_id"] == older_id
    assert production["global_failure"] == "SDP_SOURCE_FALLBACK"
    assert production["matches_valid"] == 19
    assert production["identity_failures"] == 2
    assert production["failure_count"] == 1
    assert production["failure_count_scope"] == "all_retained_seasons"
    assert production["current_failure_count"] is None
    code, report = _run_health(root, max_age="24", fail_on_production=True)
    assert code == 1
    assert report["verdict"] == "production_failure"


def test_health_cli_never_writes_anything(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _write_receipt(root, _run_id(6, 1), _payload(finished=NOW - timedelta(hours=6)))
    _write_receipt(root, _run_id(2, 2), report=False)

    def snapshot() -> dict[str, bytes]:
        return {
            str(path.relative_to(tmp_path)): path.read_bytes()
            for path in sorted(tmp_path.rglob("*"))
            if path.is_file()
        }

    before = snapshot()
    code, _ = _run_health(root, max_age="48")
    assert code == 0
    assert snapshot() == before


# --- systemd package consistency ---


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        delimiters=("=",),
        comment_prefixes=("#", ";"),
        interpolation=None,
        strict=False,
    )
    parser.optionxform = str
    with (DEPLOY / name).open(encoding="utf-8") as handle:
        parser.read_file(handle)
    return parser


def _env_sample() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (
        (DEPLOY / "comet-fpl-sdp-capture.env.sample").read_text(encoding="utf-8").splitlines()
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        assert sep, f"env sample line is not KEY=VALUE: {line}"
        values[key.strip()] = value.strip()
    return values


def _dollar_variables(command: str) -> set[str]:
    return set(re.findall(r"\$\{(\w+)\}", command))


def test_capture_service_runs_pinned_daily_wrapper_with_bounded_timeouts() -> None:
    unit = _unit("comet-fpl-sdp-capture.service")
    service = unit["Service"]
    assert service["Type"] == "oneshot"
    assert service["User"] == "comet-fpl"
    assert service["Group"] == "comet-fpl"
    assert service["EnvironmentFile"] == "/etc/default/comet-fpl-sdp"
    assert service["Environment"] == (
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory "
        "GIT_CONFIG_VALUE_0=/opt/comet-fpl/checkout"
    )
    assert service["ExecStartPre"] == (
        "/bin/sh /usr/local/sbin/comet-fpl-verify-pin /opt/comet-fpl/checkout"
    )
    exec_start = service["ExecStart"]
    assert "/opt/comet-fpl/venv/bin/python" in exec_start
    assert "-m fpl.jobs.daily_pl_sdp" in exec_start
    assert "--db ${SDP_DB}" in exec_start
    assert "--runs ${SDP_RUNS}" in exec_start
    assert "--lookback-days 5" in exec_start
    assert "--workload" in exec_start
    # RuntimeMaxSec does not apply to Type=oneshot; the start phase is TimeoutStartSec.
    assert "RuntimeMaxSec" not in service
    assert service["TimeoutStartSec"] == "7200"
    assert service["TimeoutStopSec"] == "120"
    assert service["KillSignal"] == "SIGINT"
    assert service["Restart"] == "on-failure"
    assert service["RestartSec"] == "30min"
    assert unit["Unit"]["StartLimitIntervalSec"] == "4h"
    assert unit["Unit"]["StartLimitBurst"] == "3"
    assert service["ReadWritePaths"] == "/var/lib/comet-fpl"
    assert service["ProtectSystem"] == "strict"
    assert service["NoNewPrivileges"] == "true"
    assert service["CapabilityBoundingSet"] == ""


def test_health_service_is_offline_read_only_with_bounded_timeouts() -> None:
    unit = _unit("comet-fpl-sdp-health.service")
    service = unit["Service"]
    assert service["User"] == "comet-fpl"
    assert service["ExecStartPre"] == (
        "/bin/sh /usr/local/sbin/comet-fpl-verify-pin /opt/comet-fpl/checkout"
    )
    exec_start = service["ExecStart"]
    assert "-m fpl.jobs.sdp_capture_health" in exec_start
    assert "--runs ${SDP_RUNS}" in exec_start
    assert "--db ${SDP_DB}" in exec_start
    assert "--max-success-age-hours ${SDP_HEALTH_MAX_AGE_HOURS}" in exec_start
    assert "RuntimeMaxSec" not in service
    assert service["TimeoutStartSec"] == "300"
    assert service["TimeoutStopSec"] == "60"
    assert service["RestrictAddressFamilies"] == "AF_UNIX"
    assert service["ProtectSystem"] == "strict"


def test_capture_timer_is_daily_persistent_and_points_at_the_service() -> None:
    unit = _unit("comet-fpl-sdp-capture.timer")
    timer = unit["Timer"]
    assert timer["OnCalendar"] == "*-*-* 07:00:00"
    assert timer["Persistent"] == "true"
    assert timer["Unit"] == "comet-fpl-sdp-capture.service"
    assert "RandomizedDelaySec" in timer
    assert unit["Install"]["WantedBy"] == "timers.target"


def test_environment_sample_covers_every_unit_variable_without_secrets() -> None:
    env = _env_sample()
    assert set(env) == {
        "SDP_DB",
        "SDP_RUNS",
        "SDP_CODE_PIN",
        "SDP_HEALTH_MAX_AGE_HOURS",
        "PYTHONUNBUFFERED",
    }
    assert env["SDP_DB"] == "/var/lib/comet-fpl/db/operational.duckdb"
    assert env["SDP_RUNS"] == "/var/lib/comet-fpl/runs"
    assert env["SDP_HEALTH_MAX_AGE_HOURS"] == "30"
    assert all(value != "" for value in env.values())
    referenced: set[str] = set()
    for name in ("comet-fpl-sdp-capture.service", "comet-fpl-sdp-health.service"):
        service = _unit(name)["Service"]
        for command in (service["ExecStartPre"], service["ExecStart"]):
            referenced |= _dollar_variables(command)
    assert referenced == {"SDP_RUNS", "SDP_DB", "SDP_HEALTH_MAX_AGE_HOURS"}
    assert referenced <= set(env)


def test_install_script_uses_frozen_lock_validates_before_mutation() -> None:
    script = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    # Frozen lockfile-based environment, no unpinned pip resolution.
    assert "uv sync --frozen" in script
    assert 'UV_PROJECT_ENVIRONMENT="$VENV"' in script
    assert "--python 3.12" in script
    # System-interpreter pinning: no root-private interpreter downloads.
    assert "UV_PYTHON_PREFERENCE=only-system" in script
    assert "UV_PYTHON_DOWNLOADS=never" in script
    assert "command -v python3.12" in script
    assert "never downloads" in script
    assert "uv is a deployment prerequisite" in script
    assert "pip install" not in script
    # Pin and bound validated before any mutation.
    assert "must be a 40-hex-character commit SHA" in script
    assert "must be a finite positive number" in script
    assert "before any mutation" in script or "strictly before any mutation" in script
    # Persist-only path policy under /var/lib/comet-fpl, conservative charset.
    assert "/var/lib/comet-fpl" in script
    assert "realpath -m" in script
    assert "must live under" in script
    assert "unsafe path" in script
    # Paths passed to Python as argv, never interpolated into source.
    assert "sys.argv[1]" in script
    # Import of an operator-provided checkpointed DB; schema-only never forecast-ready.
    assert "NOT forecast-ready" in script
    assert "--init-empty-schema" in script
    assert "CHECKPOINTED" in script
    assert "duckdb.connect(sys.argv[1], read_only=True)" in script
    # Guard installed outside the checkout; no chmod of checkout files.
    assert "/usr/local/sbin/comet-fpl-verify-pin" in script
    assert 'install -m 0755 "$DEPLOY_DIR/verify-pin.sh"' in script
    assert "chmod" not in script.replace("chmod 0644", "")
    assert "pip install" not in script
    assert "uv sync --frozen" in script
    # Unprivileged service user, timer enabled, daemon reloaded.
    assert "nologin" in script
    assert "enable --now comet-fpl-sdp-capture.timer" in script
    assert "daemon-reload" in script
    assert "does not equal --pin" in script


def test_verify_pin_rejects_dirty_worktree_and_scopes_safe_directory() -> None:
    script = (DEPLOY / "verify-pin.sh").read_text(encoding="utf-8")
    assert "SDP_CODE_PIN is empty or unset" in script
    assert "must be a 40-hex-character commit SHA" in script
    assert "does not equal pinned commit" in script
    assert "exit 1" in script
    assert "git -C" in script
    # Dirty tracked/untracked worktree is code drift and refuses the start.
    assert "status --porcelain" in script
    assert "worktree is dirty" in script
    # Narrow safe.directory handling for a root-owned checkout: exactly this path via
    # protected-config environment, never a wildcard.
    assert "GIT_CONFIG_KEY_0" in script
    assert 'GIT_CONFIG_VALUE_0="$checkout"' in script
    assert "safe.directory" in script
    assert not re.search(r'safe\.directory\s*\*|"safe\.directory=\*"', script)
    for name in ("comet-fpl-sdp-capture.service", "comet-fpl-sdp-health.service"):
        assert _unit(name)["Service"]["ExecStartPre"] == (
            "/bin/sh /usr/local/sbin/comet-fpl-verify-pin /opt/comet-fpl/checkout"
        )


def test_runtime_doc_records_blocked_status_and_matches_the_package() -> None:
    text = RUNTIME_DOC.read_text(encoding="utf-8")
    assert "BLOCKED ONLY ON RUNTIME AUTHORIZATION / CREDENTIALS" in text
    lowered = text.lower()
    assert "not deployed" in lowered or "nothing deployed" in lowered
    assert "sdp_capture_health" in text
    assert "--max-success-age-hours" in text
    assert "daily_pl_sdp" in text
    assert "--lookback-days 5" in text
    assert "--workload" in text
    assert "sdp-primary-operations.md" in text
    # Timeout semantics cite the systemd.service manpage; no invented version claim.
    assert "manpages.debian.org/trixie/systemd/systemd.service.5.en.html" in text
    assert "TimeoutStartSec" in text
    assert ">= 250" not in text and "systemd >= 250" not in text
    # SIGINT is best-effort; SIGKILL/WAL recovery stays manual; nothing auto-deleted.
    assert "best-effort" in lowered
    assert "SIGKILL" in text
    assert "manual" in lowered
    # Frozen uv.lock deployment and the database import requirement are documented.
    assert "uv sync --frozen" in text
    assert "uv.lock" in text
    assert "NOT forecast-ready" in text or "not forecast-ready" in lowered
    # Storage expectations: ~1.4 GB source database and a per-run full backup.
    assert "1.4 GB" in text or "1.4GB" in text
    # Health evidence rules are documented.
    assert "validated" in lowered and "finished_at" in text
    assert "undated" in lowered
    assert "unattributed" in lowered
    assert "cannot be proven" in lowered
    assert "freshness_unproven" in text
    assert "UV_PYTHON_PREFERENCE=only-system" in text
    assert "staging/" in text
    assert "unattributed (`database`-less) receipt never proves success" in text
    readme = (DEPLOY / "README.md").read_text(encoding="utf-8")
    assert "docs/sdp-primary-remote-runtime.md" in readme
    assert "install.sh --pin" in readme
    assert "uv" in readme
    assert "1.4 GB" in readme or "1.4GB" in readme
