"""A local stub of the FPL API.

Exists so the snapshot job's full code path can be exercised with no network at all --
`daily_snapshot --dry-run` uses it, and so does every client test. R5 is the one job that
absolutely must work, so it needs to be provable offline.

Not a test-only helper: `--dry-run` is a supported operational mode for verifying a
deployment before trusting it with the real endpoint.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Any, Self


@dataclass
class StubRoute:
    """One canned response.

    `fail_times` makes the route return `fail_status` for its first N requests before
    succeeding, which is how the retry/backoff path is tested without waiting on a real
    flaky server.
    """

    body: Any = None
    status: int = 200
    fail_times: int = 0
    fail_status: int = 503
    _served: int = field(default=0, init=False)

    def next_response(self) -> tuple[int, bytes]:
        self._served += 1
        if self._served <= self.fail_times:
            return self.fail_status, b'{"error": "stub transient failure"}'
        if self.status != 200:
            return self.status, b'{"error": "stub error"}'
        return 200, json.dumps(self.body).encode("utf-8")

    @property
    def served(self) -> int:
        return self._served


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, StubRoute]

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        route = self.routes.get(path) or self.routes.get(path.rstrip("/"))
        if route is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "no stub route"}')
            return
        status, payload = route.next_response()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_: Any) -> None:
        """Silence the default stderr access log."""


class StubFplApi:
    """Context manager yielding a base URL that speaks the FPL API's shapes."""

    def __init__(self, routes: dict[str, StubRoute]) -> None:
        self.routes = routes
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @classmethod
    def from_fixtures(
        cls,
        *,
        bootstrap_path: Path,
        fixtures_path: Path,
        bootstrap_route: str = "/bootstrap-static",
        fixtures_route: str = "/fixtures",
        event_live_route: str = "/event/1/live",
    ) -> Self:
        return cls(
            {
                bootstrap_route: StubRoute(body=json.loads(bootstrap_path.read_text("utf-8"))),
                fixtures_route: StubRoute(body=json.loads(fixtures_path.read_text("utf-8"))),
                event_live_route: StubRoute(body={"elements": []}),
            }
        )

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("stub server is not running")
        address = self._server.server_address
        raw_host, raw_port = address[0], address[1]
        host = raw_host.decode() if isinstance(raw_host, bytes) else str(raw_host)
        return f"http://{host}:{int(raw_port)}"

    def start(self) -> str:
        handler = type("_BoundHandler", (_Handler,), {"routes": self.routes})
        # Port 0 lets the OS pick a free port, so concurrent test runs cannot collide.
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
