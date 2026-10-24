"""Command-watch program (Kiro's command-watch contract).

Kiro drives a watch program by piping a JSON object ``{cursor, config}`` on
**stdin**; the program polls the thing it is watching, prints **exactly one**
JSON result line on stdout -- one of ``idle``, ``new-activity`` or
``terminal-state``, each carrying an updated ``cursor`` -- and exits ``0``.

For gpu-overwatch the watched thing is a supervised training run's sidecar.
The run id travels via the ``runId`` config key (it is **not** templated into
the ``command`` string in the workflow). The program resolves the run's sidecar
(proxy URL + per-run bearer token from ``state.json``), polls ``/status`` and
``/metrics`` over HTTP, runs the detectors, and reports the outcome.

Result shapes (every one carries an updated ``cursor``)::

    {"result": "idle",          "cursor": {...}, "status": {...}}
    {"result": "new-activity",  "cursor": {...}, "event": {...},
     "metrics": {...}, "log_tail": [...], "suggested_action": "..."}
    {"result": "terminal-state","cursor": {...}, "reason": "...", "status": {...}}

The cursor advances by the last-seen step and timestamp so the next poll is
incremental.

Everything here is standard library only. HTTP is plain ``urllib``; there is no
network in tests -- the program is driven against a LOCAL sidecar (an ephemeral
``http.server`` wrapping ``tests/fake_train.py``) or, when a run has no
reachable sidecar, against synthesized state. The sidecar base URL can be
pinned for a run via the ``sidecar_url`` field in the run record, the
``OVERWATCH_SIDECAR_URL`` environment variable, or the ``sidecarUrl`` config
key; otherwise it is derived from the Pod proxy host.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import detectors
from . import state as state_mod
from .policy import Policy

# Config/env keys.
SIDECAR_URL_ENV = "OVERWATCH_SIDECAR_URL"
DEFAULT_POLL_INTERVAL_SEC = 60
DEFAULT_COMMAND_TIMEOUT_SEC = 30
DEFAULT_IDLE_TIMEOUT_SEC = 43200  # 12h; matches the supervise-run workflow

# Terminal run states (from the sidecar runner status snapshot).
_TERMINAL_STATES = {"finished", "stopped", "crashed", "terminated", "failed"}


# ----------------------------------------------------------------------
# stdin / stdout
# ----------------------------------------------------------------------
def _read_stdin() -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("watch stdin payload must be a JSON object")
    return data


def _emit(result: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    sys.stdout.write("\n")
    sys.stdout.flush()


# ----------------------------------------------------------------------
# sidecar resolution + HTTP polling
# ----------------------------------------------------------------------
def _resolve_sidecar(run: Optional[Dict[str, Any]], config: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(base_url, bearer)`` for a run's sidecar.

    Resolution order for the base URL: the run record's ``sidecar_url``, then
    the ``OVERWATCH_SIDECAR_URL`` env var, then the ``sidecarUrl`` config key,
    then the Pod proxy host derived from the run's ``pod_id``. The bearer is the
    per-run token recorded in state.
    """
    base = None
    bearer = None
    if run:
        base = run.get("sidecar_url")
        bearer = run.get("bearer")
    base = base or os.environ.get(SIDECAR_URL_ENV) or config.get("sidecarUrl")
    if not base and run and run.get("pod_id"):
        base = f"https://{run['pod_id']}.runpod.proxy"
    if base:
        base = base.rstrip("/")
    return base, bearer


def _http_get(url: str, bearer: Optional[str], timeout: float) -> Optional[Dict[str, Any]]:
    """GET a JSON endpoint; return the parsed body or ``None`` on any failure."""
    headers = {}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _poll_sidecar(
    base: Optional[str], bearer: Optional[str], timeout: float
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[List[str]]]:
    """Poll ``/status`` + ``/metrics`` + ``/logs``; any may be ``None``."""
    if not base:
        return None, None, None
    status = _http_get(f"{base}/status", bearer, timeout)
    metrics = _http_get(f"{base}/metrics", bearer, timeout)
    logs = _http_get(f"{base}/logs", bearer, timeout)
    log_lines = logs.get("lines") if isinstance(logs, dict) else None
    return status, metrics, log_lines


# ----------------------------------------------------------------------
# cursor helpers
# ----------------------------------------------------------------------
def _new_cursor(
    old: Dict[str, Any],
    *,
    step: Optional[int],
    ts: float,
    polls: int,
    first_seen: float,
    last_progress: float,
) -> Dict[str, Any]:
    cursor = dict(old or {})
    cursor["step"] = step
    cursor["ts"] = ts
    cursor["polls"] = polls
    cursor["first_seen"] = first_seen
    cursor["last_progress"] = last_progress
    return cursor


# ----------------------------------------------------------------------
# detector evaluation
# ----------------------------------------------------------------------
def _metric_records(metrics: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(metrics, dict):
        return []
    points = metrics.get("points")
    return list(points) if isinstance(points, list) else []


def _detect(
    status: Optional[Dict[str, Any]],
    records: List[Dict[str, Any]],
    log_lines: Optional[List[str]],
    policy: Policy,
) -> Optional[Dict[str, Any]]:
    """Run detectors over the freshest observation; return one event or None."""
    kwargs: Dict[str, Any] = {"policy": policy}
    if records:
        kwargs["metrics"] = records
    if log_lines:
        kwargs["log_lines"] = log_lines
    if status:
        age = status.get("last_step_age_seconds")
        if age is not None:
            kwargs["last_step_age_seconds"] = age
        exit_code = status.get("exit_code")
        if exit_code is not None and status.get("status") in ("crashed", "failed"):
            kwargs["exit_code"] = exit_code
    events = detectors.run_all(**kwargs)
    return events[0] if events else None


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def watch_once(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single supervision poll and return the result dict.

    Pure with respect to stdout: the caller is responsible for emitting it.
    """
    cursor = payload.get("cursor") or {}
    if not isinstance(cursor, dict):
        cursor = {}
    config = payload.get("config") or {}
    if not isinstance(config, dict):
        config = {}

    run_id = config.get("runId") or config.get("run_id")
    poll_interval = float(config.get("pollIntervalSec", DEFAULT_POLL_INTERVAL_SEC))
    command_timeout = float(config.get("commandTimeoutSec", DEFAULT_COMMAND_TIMEOUT_SEC))
    idle_timeout = float(config.get("idleTimeoutSec", DEFAULT_IDLE_TIMEOUT_SEC))

    now = time.time()
    polls = int(cursor.get("polls", 0)) + 1
    first_seen = float(cursor.get("first_seen", now))
    last_progress = float(cursor.get("last_progress", now))
    last_step = cursor.get("step")

    policy = Policy.load()
    state = state_mod.load_state()
    run = state_mod.get_run(state, run_id) if run_id else None

    base, bearer = _resolve_sidecar(run, config)
    status, metrics, log_lines = _poll_sidecar(base, bearer, command_timeout)

    records = _metric_records(metrics)
    cur_step = None
    for rec in records:
        s = rec.get("step")
        if isinstance(s, int) and (cur_step is None or s > cur_step):
            cur_step = s
    if cur_step is None and isinstance((status or {}).get("step"), int):
        cur_step = status["step"]

    run_state = (status or {}).get("status")

    progressed = cur_step is not None and (last_step is None or cur_step > last_step)
    if progressed:
        last_progress = now

    # --- detector sweep over the fresh observation. ---
    # Detectors run FIRST: an actionable event (e.g. a NaN that coincides with
    # the process exiting) is reported as new-activity so the medic can heal the
    # run, rather than being swallowed by the terminal transition.
    event = _detect(status, records, log_lines, policy)

    if event is not None:
        new_cursor = _new_cursor(
            cursor, step=cur_step if cur_step is not None else last_step,
            ts=now, polls=polls, first_seen=first_seen, last_progress=last_progress,
        )
        metric_summary = _summarize_metrics(records, status)
        return {
            "result": "new-activity",
            "cursor": new_cursor,
            "event": event.get("event"),
            "detail": event.get("detail"),
            "suggested_action": event.get("suggested_action"),
            "metrics": metric_summary,
            "log_tail": (log_lines or [])[-20:],
            "run_id": run_id,
        }

    # --- terminal: the run has ended (cleanly), gone idle, or is unknown. ---
    terminal_reason = None
    if run_state in _TERMINAL_STATES:
        terminal_reason = run_state
    elif (now - last_progress) >= idle_timeout and idle_timeout > 0:
        terminal_reason = "idle_timeout"
    elif run is None and base is None:
        terminal_reason = "unknown_run"

    if terminal_reason is not None:
        new_cursor = _new_cursor(
            cursor, step=cur_step if cur_step is not None else last_step,
            ts=now, polls=polls, first_seen=first_seen, last_progress=last_progress,
        )
        new_cursor["terminal"] = True
        return {
            "result": "terminal-state",
            "cursor": new_cursor,
            "reason": terminal_reason,
            "run_id": run_id,
            "status": status,
        }

    # --- idle: healthy; nothing to escalate. ---
    new_cursor = _new_cursor(
        cursor, step=cur_step if cur_step is not None else last_step,
        ts=now, polls=polls, first_seen=first_seen, last_progress=last_progress,
    )
    return {
        "result": "idle",
        "cursor": new_cursor,
        "run_id": run_id,
        "progressed": bool(progressed),
        "status": status,
        "poll_interval_sec": poll_interval,
    }


def _summarize_metrics(records: List[Dict[str, Any]], status: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact metric summary for a new-activity report."""
    last_loss = None
    last_step = None
    for rec in reversed(records):
        if "loss" in rec and last_loss is None:
            last_loss = rec.get("loss")
        if "step" in rec and last_step is None:
            last_step = rec.get("step")
        if last_loss is not None and last_step is not None:
            break
    summary = {
        "last_step": last_step,
        "last_loss": last_loss,
        "point_count": len(records),
    }
    if isinstance(status, dict):
        summary["loss_slope"] = status.get("loss_slope")
        summary["tokens_per_s"] = status.get("tokens_per_s")
        summary["gpu_util"] = (status.get("gpu") or {}).get("util")
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    """Entrypoint: read stdin, emit one JSON result, return 0.

    Any error is reported as a single terminal-state JSON line (so the workflow
    stops cleanly) while still exiting 0 per the command-watch contract.
    """
    try:
        payload = _read_stdin()
    except (ValueError, json.JSONDecodeError) as exc:
        _emit({"result": "terminal-state", "cursor": {}, "reason": f"bad_input: {exc}"})
        return 0
    try:
        result = watch_once(payload)
    except Exception as exc:  # noqa: BLE001 - watch must always emit one line + exit 0
        cursor = payload.get("cursor") if isinstance(payload.get("cursor"), dict) else {}
        _emit({"result": "terminal-state", "cursor": cursor, "reason": f"error: {exc}"})
        return 0
    _emit(result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
