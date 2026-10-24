"""Sidecar HTTP service (stdlib ``http.server`` only).

Exposes four endpoints, every one guarded by a per-run bearer token:

* ``GET  /status``  -- the runner status snapshot.
* ``GET  /logs``    -- the log ring buffer tail, capped at 400 lines.
* ``GET  /metrics`` -- the metric series, downsampled to <= 500 points.
* ``POST /signal``  -- apply ``checkpoint_now`` | ``pause`` | ``resume`` |
  ``stop_graceful`` (signal name in the JSON body or ``?signal=`` query).

Requests must carry ``Authorization: Bearer <token>`` matching the token the
server was constructed with (sourced from ``OVERWATCH_TOKEN`` by
:func:`build_server`). Any other request is rejected with ``401``. Responses
are compact JSON.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

LOGS_CAP = 400
METRICS_CAP = 500
TOKEN_ENV = "OVERWATCH_TOKEN"


def downsample(records: List[Any], cap: int = METRICS_CAP) -> List[Any]:
    """Uniformly downsample ``records`` to at most ``cap`` points.

    Keeps the first and last points and picks evenly spaced indices between.
    """
    n = len(records)
    if n <= cap:
        return list(records)
    if cap <= 1:
        return [records[-1]] if cap == 1 else []
    # Reserve the final slot for the last point, pick cap-1 evenly spaced
    # indices from the head so the result is always <= cap points.
    step = (n - 1) / float(cap - 1)
    picked = []
    seen = set()
    for i in range(cap - 1):
        idx = int(i * step)
        if idx >= n - 1:
            idx = n - 2
        if idx not in seen:
            seen.add(idx)
            picked.append(records[idx])
    picked.append(records[-1])
    return picked


class _Handler(BaseHTTPRequestHandler):
    # Set per-instance by the server factory.
    runner = None
    token = None

    # Silence the default stderr access log.
    def log_message(self, *_args: Any) -> None:  # noqa: D401
        return

    # ------------------------------------------------------------------
    def _authorized(self) -> bool:
        if not self.token:
            return True
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return header[len(prefix):].strip() == self.token

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_unauthorized(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", "Bearer")
        self.send_header("Content-Type", "application/json")
        body = json.dumps({"error": "unauthorized"}, separators=(",", ":")).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if not self._authorized():
            self._reject_unauthorized()
            return
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if path == "/status":
            self._send_json(200, self.runner.status())
        elif path == "/logs":
            limit = LOGS_CAP
            if "limit" in query:
                try:
                    limit = min(LOGS_CAP, max(1, int(query["limit"][0])))
                except ValueError:
                    limit = LOGS_CAP
            lines = self.runner.logs(limit=limit)
            self._send_json(200, {"lines": lines, "count": len(lines)})
        elif path == "/metrics":
            records = self.runner.metrics()
            points = downsample(records, METRICS_CAP)
            self._send_json(200, {"points": points, "count": len(points), "total": len(records)})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if not self._authorized():
            self._reject_unauthorized()
            return
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if path != "/signal":
            self._send_json(404, {"error": "not found"})
            return
        name: Optional[str] = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict):
                    name = payload.get("signal")
            except (json.JSONDecodeError, UnicodeDecodeError):
                name = None
        if name is None and "signal" in query:
            name = query["signal"][0]
        if not name:
            self._send_json(400, {"error": "missing signal"})
            return
        result = self.runner.signal(name)
        self._send_json(200 if result.get("ok") else 400, result)


def build_server(
    runner: Any,
    *,
    host: str = "0.0.0.0",
    port: int = 0,
    token: Optional[str] = None,
) -> ThreadingHTTPServer:
    """Create a configured (not yet serving) :class:`ThreadingHTTPServer`.

    The bearer token defaults to ``OVERWATCH_TOKEN`` from the environment. Pass
    ``port=0`` to bind an ephemeral port (recommended in tests); read the real
    port from ``server.server_address[1]``.
    """
    resolved_token = token if token is not None else os.environ.get(TOKEN_ENV)

    handler = type(
        "_BoundHandler",
        (_Handler,),
        {"runner": runner, "token": resolved_token},
    )
    server = ThreadingHTTPServer((host, port), handler)
    return server


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    """Run ``server.serve_forever`` in a daemon thread and return it."""
    thread = threading.Thread(target=server.serve_forever, name="ow-http", daemon=True)
    thread.start()
    return thread
