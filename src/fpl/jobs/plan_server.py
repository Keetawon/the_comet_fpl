"""Interactive local plan server: solve a wizard request and republish the dashboard.

Owner decision (2026-08-17): the plan-builder wizard needs to trigger a real optimizer run
before the GW1 deadline, not emit a command to paste. This job is that trigger -- a tiny
localhost HTTP service (stdlib only, no new dependency) that runs, per request:

1. ``fpl.jobs.optimize_squad`` on the dev-latest default forecast with the request's locks,
   exclusions, and bench gate, written to a unique timestamped immutable artifact (no-clobber);
2. the same publish chain as dashboard/README.md: ``export_bi`` then
   ``export_dashboard_json``, carrying both required standing plans plus the exact newly solved
   interactive plan, copying staged generations into place via ``before_publish`` because the
   symlink swap needs a privilege this shell may not have.

Every correctness property is inherited, not bypassed: the optimizer still fails closed on a
dirty worktree (surfaced to the UI as a pre-check), DuckDB jobs still run serialized behind a
single-flight lock, and the dashboard still reads only the published read models -- the
browser never queries anything, it just asks this process to run the same jobs.

Run from the repository root: ``python -m fpl.jobs.plan_server`` (``--host 0.0.0.0`` for LAN
use from the phone preview). The wizard's Solve button targets
``http://<window.location.hostname>:8765``. Loopback needs no credential; non-loopback LAN
clients must supply the per-launch token printed by the server.
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import logging
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fpl.config import repo_root
from fpl.jobs.optimize_squad import (
    MAX_EXCLUDED_PLAYERS,
    MAX_LOCKED_PLAYERS,
    _cbc_binary_version,
    _git_worktree_clean,
    _pulp_package_version,
)
from fpl.publish.dashboard_json import NEXT_GW_FILENAME, export_dashboard_json
from fpl.publish.export import export_bi

logger = logging.getLogger("fpl.jobs.plan_server")

DEFAULT_PORT = 8765
# ponytail: the dev-data convention directory from dashboard/README.md, overridable --host
# aside, not a config surface. All interactive artifacts live beside the standing pair.
DEFAULT_BASE = Path(r"D:\tmp\gw1\dev-latest")
DB_PATH = Path("data/fpl.duckdb")
FORECAST_NAME = "gw1_5_default.jsonl"
STANDING_PLANS = ("plan_default.json", "plan_diagnostic.json")
MY_RULES_DIRNAME = "my-rules"
MAX_BODY_BYTES = 4096
RISK_LAMBDA = 0.0  # P0 delivery rule: EV is the result; risk runs stay a separate sensitivity
ACCESS_TOKEN_HEADER = "X-FPL-Plan-Token"
SOLVER_PROBE_COOLDOWN_SECONDS = 2.0
_monotonic = time.monotonic


class RequestError(ValueError):
    """A malformed or refused plan request; str() is safe to show in the UI."""


def _ui_message(exc: Exception) -> str:
    """Translate solver failures into a sentence the wizard can act on, keeping the reason."""
    text = str(exc)
    if "min_bench_appearance" in text:
        return (
            "the rotation threshold is too high: every legal squad would have to bench a "
            "non-locked player whose appearance lower bound is below it (locked players and "
            "the bench goalkeeper are exempt). Lower or switch off the threshold. "
            f"({text})"
        )
    return text


def _run_optimizer_cli(argv: list[str]) -> None:
    """Run the optimizer exactly as the runbook does: a fresh child interpreter.

    The solve never shares this server's process. An in-thread PuLP/CBC run whose ILP raised
    once took the whole server down after the handler had already answered (fatal
    ``PyEval_SaveThread`` GIL error in the main thread), so isolation is a correctness
    requirement here, not an optimization. Failing closed with the CLI's own stderr tail.
    """
    result = subprocess.run(
        [sys.executable, "-m", "fpl.jobs.optimize_squad", *argv],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        cwd=repo_root(),
    )
    if result.returncode != 0:
        lines = (result.stderr or "").strip().splitlines()
        tail = lines[-1] if lines else f"exit code {result.returncode}"
        raise RequestError(f"optimizer run failed: {tail}")


def validate_request(body: dict[str, Any]) -> tuple[list[int], list[int], float]:
    """Parse and bound locks/exclusions/bench gate, mirroring the CLI's checks."""
    locks_value = body.get("locks", [])
    if not isinstance(locks_value, list) or not all(
        isinstance(code, int) and not isinstance(code, bool) for code in locks_value
    ):
        raise RequestError("locks must be a list of player codes (integers)")
    locks = sorted(set(locks_value))
    if len(locks) > MAX_LOCKED_PLAYERS:
        raise RequestError(f"at most {MAX_LOCKED_PLAYERS} players may be locked")
    excludes_value = body.get("excludes", [])
    if not isinstance(excludes_value, list) or not all(
        isinstance(code, int) and not isinstance(code, bool) for code in excludes_value
    ):
        raise RequestError("excludes must be a list of player codes (integers)")
    excludes = sorted(set(excludes_value))
    if len(excludes) > MAX_EXCLUDED_PLAYERS:
        raise RequestError(f"at most {MAX_EXCLUDED_PLAYERS} players may be excluded")
    overlap = sorted(set(locks).intersection(excludes))
    if overlap:
        raise RequestError(f"players cannot be both locked and excluded: {overlap}")
    bench_value = body.get("min_bench_appearance")
    if bench_value is None:
        bench = 0.0
    elif isinstance(bench_value, (int, float)) and 0.0 < float(bench_value) < 1.0:
        bench = float(bench_value)
    else:
        raise RequestError("min_bench_appearance must be null or a fraction strictly in (0, 1)")
    return locks, excludes, bench


def summarize_artifact(path: Path) -> dict[str, Any]:
    """Read the fresh immutable artifact and return the fields the UI greets the user with."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    weeks = payload["plan"]["weeks"]
    return {
        "optimizer_run_id": payload["run_id"],
        "decision_sha256": payload["decision_sha256"],
        "output": str(path),
        "gw": weeks[0]["gw"],
        "gw_expected_points": weeks[0]["expected_points"],
        "horizon_expected_points": payload["plan"]["expected_points_after_hits"],
        "hit_points": payload["plan"]["hit_points"],
        "squad_cost_tenths": weeks[0]["squad_cost_tenths"],
        "captain": weeks[0]["captain"]["web_name"],
        "vice_captain": weeks[0]["vice_captain"]["web_name"],
    }


class ServerState:
    """Serialized run state; one plan runs at a time (DuckDB jobs run sequentially)."""

    def __init__(self, base_dir: Path, *, access_token: str | None = None) -> None:
        self.base_dir = base_dir
        self.access_token = access_token or secrets.token_urlsafe(24)
        self.run_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.solver_probe_lock = threading.Lock()
        self.stage: str | None = None
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.solver_package_version: str | None = None
        self.solver_binary_version: str | None = None
        self.solver_discovery_attempts = 0
        self.solver_discovery_error: str | None = None
        self.solver_last_probe_monotonic: float | None = None
        self.refresh_solver_versions(force=True)

    def refresh_solver_versions(self, *, force: bool = False) -> bool:
        """Retry exact runtime discovery after a transient detached-process launch failure.

        The optimizer child independently performs the same fail-closed discovery before it can
        emit an artifact.  This retry only prevents one failed startup probe from being cached for
        the lifetime of the HTTP server; it never supplies a default or accepts a partial identity.
        """
        acquired = self.solver_probe_lock.acquire(blocking=force)
        if not acquired:
            with self.status_lock:
                return (
                    self.solver_package_version is not None
                    and self.solver_binary_version is not None
                )
        try:
            now = _monotonic()
            with self.status_lock:
                ready = (
                    self.solver_package_version is not None
                    and self.solver_binary_version is not None
                )
                if not force and ready:
                    return True
                if (
                    not force
                    and self.solver_last_probe_monotonic is not None
                    and now - self.solver_last_probe_monotonic < SOLVER_PROBE_COOLDOWN_SECONDS
                ):
                    return ready
            failures: list[str] = []
            try:
                package_version = _pulp_package_version()
            except Exception as exc:
                logger.exception("PuLP package-version probe failed")
                package_version = None
                failures.append(f"PuLP package probe failed ({type(exc).__name__})")
            if package_version is None and not failures:
                failures.append("PuLP package version is unavailable")
            try:
                binary_version = _cbc_binary_version()
            except Exception as exc:
                logger.exception("CBC binary-version probe failed")
                binary_version = None
                failures.append(f"CBC binary probe failed ({type(exc).__name__})")
            if binary_version is None and not any(
                failure.startswith("CBC binary") for failure in failures
            ):
                failures.append("CBC binary version is unavailable")
            with self.status_lock:
                self.solver_discovery_attempts += 1
                self.solver_last_probe_monotonic = _monotonic()
                self.solver_package_version = package_version
                self.solver_binary_version = binary_version
                ready = package_version is not None and binary_version is not None
                self.solver_discovery_error = None if ready else "; ".join(failures)
                return ready
        finally:
            self.solver_probe_lock.release()

    def set_stage(self, stage: str | None) -> None:
        with self.status_lock:
            self.stage = stage
        if stage:
            logger.info("%s", stage)

    def fail(self, message: str) -> None:
        with self.status_lock:
            self.last_error = message
            self.stage = None

    def snapshot(self) -> dict[str, Any]:
        if self.solver_package_version is None or self.solver_binary_version is None:
            self.refresh_solver_versions()
        with self.status_lock:
            return {
                "busy": self.run_lock.locked(),
                "stage": self.stage,
                "last_error": self.last_error,
                "last_result": self.last_result,
                "worktree_clean": _git_worktree_clean(repo_root()),
                "forecast_ready": (self.base_dir / FORECAST_NAME).is_file(),
                "base_dir": str(self.base_dir),
                "runtime": {
                    "python_executable": sys.executable,
                    "python_prefix": sys.prefix,
                    "pulp_package_version": self.solver_package_version,
                    "cbc_binary_version": self.solver_binary_version,
                    "solver_ready": self.solver_package_version is not None
                    and self.solver_binary_version is not None,
                    "solver_discovery_attempts": self.solver_discovery_attempts,
                    "solver_discovery_error": self.solver_discovery_error,
                },
            }


def _keep_staged_copy(target: Path, destination: Path) -> Callable[[], None]:
    """before_publish hook: copy the validated staged generation next to the target, so the
    read models exist even when the directory-symlink swap is refused (no privilege)."""

    def hook() -> None:
        staged = next(target.parent.glob(f".{target.name}.*.tmp"))
        shutil.copytree(staged, destination, dirs_exist_ok=True)

    return hook


def _is_windows_symlink_privilege_error(exc: OSError) -> bool:
    """The staged copy is valid even when Windows alone refuses the final symlink swap."""
    return sys.platform == "win32" and getattr(exc, "winerror", None) == 1314


def _publish_with_windows_copy_fallback(publish: Callable[[], object]) -> None:
    """Permit only the known Windows symlink privilege failure; every other I/O error is fatal."""
    try:
        publish()
    except OSError as exc:
        if not _is_windows_symlink_privilege_error(exc):
            raise


def _verify_dashboard_plans_published(directory: Path, optimizer_run_id: str) -> None:
    """Fail closed unless formal plans and the exact custom result all reached the browser."""
    path = directory / NEXT_GW_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"published dashboard read model is unavailable: {path}") from exc
    plans = payload.get("plans") if isinstance(payload, dict) else None
    if not isinstance(plans, list):
        raise RuntimeError("published dashboard next_gw plans block is malformed")
    exact_custom = any(
        isinstance(plan, dict)
        and plan.get("optimizer_run_id") == optimizer_run_id
        and plan.get("plan_kind") == "user_custom"
        for plan in plans
    )
    kinds = {
        plan.get("plan_kind")
        for plan in plans
        if isinstance(plan, dict) and isinstance(plan.get("plan_kind"), str)
    }
    if not exact_custom:
        raise RuntimeError(
            "dashboard publish did not contain the exact solved optimizer run; refusing success"
        )
    missing = {"platform_default", "platform_diagnostic"} - kinds
    if missing:
        raise RuntimeError(
            f"dashboard publish omitted required formal platform plans: {sorted(missing)}"
        )


def _remove_publish_path(path: Path) -> None:
    """Remove one precisely named publish generation without following directory symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


@dataclass
class _DashboardGenerationTarget:
    target: Path
    staged: Path
    backup: Path
    had_previous: bool = False
    previous_moved: bool = False
    new_installed: bool = False


def _rollback_dashboard_generations(
    records: list[_DashboardGenerationTarget],
) -> list[tuple[_DashboardGenerationTarget, Exception]]:
    """Best-effort rollback, retaining every backup that could not be restored."""
    failures: list[tuple[_DashboardGenerationTarget, Exception]] = []
    for record in reversed(records):
        if record.new_installed:
            try:
                _remove_publish_path(record.target)
                record.new_installed = False
            except Exception as exc:
                failures.append((record, exc))
                continue
        if record.previous_moved:
            try:
                record.backup.replace(record.target)
                record.previous_moved = False
            except Exception as exc:
                failures.append((record, exc))
    return failures


def _publish_dashboard_generations(
    source: Path, targets: list[Path], optimizer_run_id: str
) -> None:
    """Publish one validated read-model generation to every locally served endpoint.

    ``vite preview`` serves ``dist/data`` captured at build time while ``vite dev`` serves
    ``public/data``.  Stage and validate a complete sibling generation for every applicable
    target before changing any endpoint, then swap directories and retain the old generations
    until all targets verify.  Any swap or verification failure rolls every changed target back.
    """
    _verify_dashboard_plans_published(source, optimizer_run_id)
    records: list[_DashboardGenerationTarget] = []
    try:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            generation_id = uuid.uuid4().hex
            staged = target.parent / f".{target.name}.{generation_id}.tmp"
            backup = target.parent / f".{target.name}.{generation_id}.previous"
            record = _DashboardGenerationTarget(target, staged, backup)
            # Register before copying so even a partial ``copytree`` is cleaned below.
            records.append(record)
            shutil.copytree(source, staged)
            _verify_dashboard_plans_published(staged, optimizer_run_id)

        for record in records:
            record.had_previous = record.target.exists() or record.target.is_symlink()
            if record.had_previous:
                record.target.replace(record.backup)
                record.previous_moved = True
            record.staged.replace(record.target)
            record.new_installed = True

        for record in records:
            _verify_dashboard_plans_published(record.target, optimizer_run_id)
    except Exception as publish_error:
        rollback_failures = _rollback_dashboard_generations(records)
        if rollback_failures:
            recovery_paths = "; ".join(
                f"restore {record.backup} to {record.target} ({failure})"
                for record, failure in rollback_failures
                if record.previous_moved
            )
            if not recovery_paths:
                recovery_paths = "; ".join(
                    f"inspect {record.target} ({failure})" for record, failure in rollback_failures
                )
            raise RuntimeError(
                "dashboard read-model publish failed and automatic rollback was incomplete; "
                f"the previous generation was preserved for manual recovery: {recovery_paths}"
            ) from publish_error
        raise
    else:
        for record in records:
            if record.had_previous:
                _remove_publish_path(record.backup)
                record.previous_moved = False
    finally:
        for record in records:
            try:
                _remove_publish_path(record.staged)
                # Never delete the only recoverable old generation after a failed restore.
                if not record.previous_moved:
                    _remove_publish_path(record.backup)
            except OSError as cleanup_error:
                logger.error(
                    "dashboard publish cleanup failed for %s: %s", record.target, cleanup_error
                )


def run_plan(
    state: ServerState,
    locks: list[int],
    excludes: list[int],
    min_bench_appearance: float,
) -> dict[str, Any]:
    """Solve one request and republish; raises RequestError with a UI-safe message on refusal."""
    if not state.run_lock.acquire(blocking=False):
        raise RequestError("a plan run is already in progress - wait for it to finish")
    try:
        base = state.base_dir
        if not state.refresh_solver_versions(force=True):
            detail = state.solver_discovery_error or "unknown discovery failure"
            raise RequestError(
                "the plan server cannot verify its PuLP/CBC runtime; restart it from the "
                "repository with .venv\\Scripts\\python.exe -m fpl.jobs.plan_server "
                f"({detail})"
            )
        forecast = base / FORECAST_NAME
        if not forecast.is_file():
            raise RequestError(
                f"forecast artifact missing: {forecast} (regenerate it via dashboard/README.md)"
            )
        if not _git_worktree_clean(repo_root()):
            raise RequestError(
                "the Git worktree is dirty - commit first: the optimizer refuses to write an "
                "artifact that cannot pin how it was produced"
            )
        standing_paths = [base / name for name in STANDING_PLANS]
        missing_standing = [path.name for path in standing_paths if not path.is_file()]
        if missing_standing:
            raise RequestError(
                "required platform plan artifacts are missing; refusing to publish a custom-only "
                f"dashboard: {missing_standing}"
            )
        my_rules_dir = base / MY_RULES_DIRNAME
        my_rules_dir.mkdir(parents=True, exist_ok=True)
        output = my_rules_dir / (f"plan-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}.json")
        argv = [
            str(forecast),
            "--risk-lambda",
            str(RISK_LAMBDA),
            "--plan-origin",
            "user_custom",
            *[part for code in locks for part in ("--lock", str(code))],
            *[part for code in excludes for part in ("--exclude", str(code))],
        ]
        if min_bench_appearance > 0.0:
            argv += ["--min-bench-appearance", str(min_bench_appearance)]
        argv += ["--output", str(output)]
        state.set_stage("solving squad (exact ILP + bounded transfer search)")
        _run_optimizer_cli(argv)
        if not output.is_file():
            raise RuntimeError(f"optimizer reported success but did not write {output}")
        summary = summarize_artifact(output)
        state.set_stage("publishing BI export and dashboard read models")
        plan_paths = [*standing_paths, output]
        bi_dir = base / "bi-export"
        # The symlink swap needs a privilege this shell may not have; the validated copy in
        # bi-export-copy is what the read-model step reads either way.
        _publish_with_windows_copy_fallback(
            lambda: export_bi(
                repo_root() / DB_PATH,
                bi_dir,
                optimizer_plan_paths=plan_paths,
                before_publish=_keep_staged_copy(bi_dir, base / "bi-export-copy"),
            )
        )
        models_dir = base / "dashboard-models"
        validated_models = base / f".dashboard-read-models.{uuid.uuid4().hex}.tmp"
        dashboard_root = repo_root() / "dashboard"
        public_data = dashboard_root / "public" / "data"
        try:
            _publish_with_windows_copy_fallback(
                lambda: export_dashboard_json(
                    base / "bi-export-copy",
                    models_dir,
                    before_publish=_keep_staged_copy(models_dir, validated_models),
                )
            )
            served_targets = [public_data]
            if (dashboard_root / "dist" / "index.html").is_file():
                served_targets.append(dashboard_root / "dist" / "data")
            _publish_dashboard_generations(
                validated_models,
                served_targets,
                str(summary["optimizer_run_id"]),
            )
        finally:
            _remove_publish_path(validated_models)
        with state.status_lock:
            state.last_result = summary
            state.last_error = None
            state.stage = None
        return summary
    finally:
        state.set_stage(None)
        state.run_lock.release()


def _allowed_origin(origin: str | None) -> bool:
    """Allow only loopback or an address assigned to this dashboard host."""
    if not origin:
        return True  # not a browser (curl, tests): no Origin header
    try:
        host = urlparse(origin).hostname or ""
    except ValueError:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # not an address literal; never resolve names on the request path
    if address.is_loopback:
        return True
    try:
        local_ips = {
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None)
            if info[0] in (socket.AF_INET, socket.AF_INET6)
        }
    except OSError:
        local_ips = set()
    return host in local_ips


def _peer_authenticated(peer_host: str, supplied_token: str | None, expected_token: str) -> bool:
    """Loopback is zero-friction; every non-loopback client needs the per-launch secret."""
    try:
        if ipaddress.ip_address(peer_host).is_loopback:
            return True
    except ValueError:
        return False
    if not supplied_token:
        return False
    return hmac.compare_digest(supplied_token, expected_token)


def make_handler(state: ServerState) -> type[BaseHTTPRequestHandler]:
    class PlanRequestHandler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            return _allowed_origin(self.headers.get("Origin")) and _peer_authenticated(
                self.client_address[0],
                self.headers.get(ACCESS_TOKEN_HEADER),
                state.access_token,
            )

        def _respond(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            origin = self.headers.get("Origin")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # Echo the allowed same-machine origin; no wildcard so other sites cannot trigger runs.
            if origin and _allowed_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            origin = self.headers.get("Origin")
            if origin and not _allowed_origin(origin):
                self._respond(403, {"error": "origin not allowed"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin or "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", f"Content-Type, {ACCESS_TOKEN_HEADER}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if urlparse(self.path).path != "/status":
                self._respond(404, {"error": "unknown endpoint"})
                return
            if not self._authorized():
                self._respond(403, {"error": "origin or plan-server token not allowed"})
                return
            self._respond(200, state.snapshot())

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/plan":
                self._respond(404, {"error": "unknown endpoint"})
                return
            if not self._authorized():
                self._respond(403, {"error": "origin or plan-server token not allowed"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise RequestError("missing or oversized request body")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise RequestError("request body must be a JSON object")
                locks, excludes, bench = validate_request(body)
                summary = run_plan(state, locks, excludes, bench)
                self._respond(200, {"ok": True, **summary})
            except RequestError as exc:
                message = _ui_message(exc)
                state.fail(message)
                self._respond(409, {"ok": False, "error": message})
            except Exception as exc:
                logger.exception("plan run crashed")
                message = _ui_message(exc)
                state.fail(message)
                self._respond(500, {"ok": False, "error": message})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            logger.info("%s %s", self.address_string(), format % args)

    return PlanRequestHandler


def serve(host: str, port: int, base_dir: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    state = ServerState(base_dir)
    server = ThreadingHTTPServer((host, port), make_handler(state))
    bound_host = str(server.server_address[0])
    bound_port = server.server_address[1]
    print(f"plan server listening on http://{bound_host}:{bound_port} (base {base_dir})")
    print(
        f"LAN access token ({ACCESS_TOKEN_HEADER}; loopback does not need it): {state.access_token}"
    )
    print(
        'POST /plan {"locks": [...], "excludes": [...], '
        '"min_bench_appearance": 0.25|null} · GET /status'
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local interactive plan solver + republisher.")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 for LAN use)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="dev-latest convention dir")
    args = parser.parse_args(argv)
    serve(args.host, args.port, args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
