"""Tests for the command-watch program (overwatch.watch).

Drives ``python -m overwatch.watch`` by piping ``{cursor, config}`` JSON on
stdin against a LOCAL sidecar (an ephemeral ``http.server`` wrapping
``tests/fake_train.py``) and asserts the command-watch contract:

* exactly one JSON line on stdout and exit code 0 every time;
* a healthy poll yields ``idle`` with an advanced cursor;
* a NaN (``fake_train --fail nan@300``) yields ``new-activity`` with
  ``event == "nan_or_inf_loss"`` and a suggested action;
* a finished run / idle timeout yields ``terminal-state``.

Standard library only; no GPU, no external network (localhost sidecar only).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from overwatch import state as state_mod
from overwatch import watch as watch_mod
from overwatch.policy import Policy
from overwatch.sidecar import server as ow_server
from overwatch.sidecar.runner import Runner

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAKE_TRAIN = os.path.join(HERE, "fake_train.py")
TOKEN = "watch-test-token"


@pytest.fixture()
def state_file(tmp_path, monkeypatch):
    path = os.path.join(str(tmp_path), "state.json")
    monkeypatch.setenv("OVERWATCH_STATE", path)
    return path


def _start_sidecar(tmp_path, run_id, fail=None, token=TOKEN):
    metrics = os.path.join(str(tmp_path), "metrics.ndjson")
    cmd = [sys.executable, FAKE_TRAIN, "--sleep", "0.05"]
    if fail:
        cmd += ["--fail", fail]
    runner = Runner(
        cmd,
        policy=Policy(),
        run_id=run_id,
        metrics_path=metrics,
        ckpt_dir=str(tmp_path),
        checkpoint_interval_seconds=1000.0,
        gpu_sample_interval=1000.0,
    )
    server = ow_server.build_server(runner, host="127.0.0.1", port=0, token=token)
    port = server.server_address[1]
    thread = ow_server.serve_in_thread(server)
    runner.start()
    return runner, server, port


def _seed_run(state_path, run_id, port, bearer=TOKEN):
    state = state_mod.load_state(state_path)
    run = state_mod.new_run(run_id, pod_id=f"pod-{run_id}", status="running", bearer=bearer)
    run["sidecar_url"] = f"http://127.0.0.1:{port}"
    state_mod.put_run(state, run)
    state_mod.save_state(state, state_path)


def _run_watch_subprocess(payload, state_path):
    """Pipe a payload into `python -m overwatch.watch`; return (code, parsed)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env["OVERWATCH_STATE"] = state_path
    proc = subprocess.run(
        [sys.executable, "-m", "overwatch.watch"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO,
        timeout=30,
    )
    # Exactly one JSON line on stdout.
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON line, got: {proc.stdout!r} / {proc.stderr!r}"
    parsed = json.loads(lines[0])
    return proc.returncode, parsed


# ----------------------------------------------------------------------
# contract: one JSON line, exit 0
# ----------------------------------------------------------------------
def test_healthy_poll_is_idle_with_advanced_cursor(state_file, tmp_path):
    run_id = "run-ok"
    runner, server, port = _start_sidecar(tmp_path, run_id)
    try:
        time.sleep(0.4)  # let a few steps land
        _seed_run(state_file, run_id, port)
        payload = {
            "cursor": {},
            "config": {"runId": run_id, "pollIntervalSec": 60, "commandTimeoutSec": 30,
                       "idleTimeoutSec": 43200},
        }
        code, result = _run_watch_subprocess(payload, state_file)
        assert code == 0
        assert result["result"] == "idle"
        # Cursor advanced (polls incremented, a step seen).
        assert result["cursor"]["polls"] == 1
        assert result["cursor"]["step"] is not None
    finally:
        runner.signal("stop_graceful")
        runner.shutdown()
        server.shutdown()
        server.server_close()


def test_cursor_advances_incrementally(state_file, tmp_path):
    run_id = "run-incr"
    runner, server, port = _start_sidecar(tmp_path, run_id)
    try:
        time.sleep(0.3)
        _seed_run(state_file, run_id, port)
        first = watch_mod.watch_once(
            {"cursor": {}, "config": {"runId": run_id, "idleTimeoutSec": 43200}}
        )
        assert first["result"] == "idle"
        c1 = first["cursor"]
        time.sleep(0.3)
        second = watch_mod.watch_once(
            {"cursor": c1, "config": {"runId": run_id, "idleTimeoutSec": 43200}}
        )
        assert second["cursor"]["polls"] == c1["polls"] + 1
        # Step is monotonic non-decreasing across polls.
        assert (second["cursor"]["step"] or 0) >= (c1["step"] or 0)
    finally:
        runner.signal("stop_graceful")
        runner.shutdown()
        server.shutdown()
        server.server_close()


def test_nan_yields_new_activity(state_file, tmp_path):
    run_id = "run-nan"
    runner, server, port = _start_sidecar(tmp_path, run_id, fail="nan@300")
    try:
        runner.wait(timeout=10)
        time.sleep(0.2)
        _seed_run(state_file, run_id, port)
        payload = {"cursor": {}, "config": {"runId": run_id, "idleTimeoutSec": 43200}}
        code, result = _run_watch_subprocess(payload, state_file)
        assert code == 0
        assert result["result"] == "new-activity"
        assert result["event"] == "nan_or_inf_loss"
        assert result["suggested_action"]
        assert "metrics" in result and "cursor" in result
    finally:
        runner.shutdown()
        server.shutdown()
        server.server_close()


def test_crash_yields_new_activity(state_file, tmp_path):
    run_id = "run-crash"
    runner, server, port = _start_sidecar(tmp_path, run_id, fail="oom@100")
    try:
        runner.wait(timeout=10)
        time.sleep(0.2)
        _seed_run(state_file, run_id, port)
        payload = {"cursor": {}, "config": {"runId": run_id, "idleTimeoutSec": 43200}}
        code, result = _run_watch_subprocess(payload, state_file)
        assert code == 0
        assert result["result"] == "new-activity"
        # OOM is detected via the log line (cuda_oom) and/or the nonzero exit.
        assert result["event"] in ("cuda_oom", "crash")
    finally:
        runner.shutdown()
        server.shutdown()
        server.server_close()


def test_clean_finish_yields_terminal_state(state_file, tmp_path):
    run_id = "run-done"
    runner, server, port = _start_sidecar(tmp_path, run_id)
    try:
        runner.wait(timeout=15)
        time.sleep(0.2)
        _seed_run(state_file, run_id, port)
        payload = {"cursor": {}, "config": {"runId": run_id, "idleTimeoutSec": 43200}}
        code, result = _run_watch_subprocess(payload, state_file)
        assert code == 0
        assert result["result"] == "terminal-state"
        assert result["cursor"]["terminal"] is True
    finally:
        runner.shutdown()
        server.shutdown()
        server.server_close()


def test_idle_timeout_yields_terminal_state(state_file):
    run_id = "run-idle"
    # A known run whose sidecar is unreachable (no server): no progress, so a
    # tiny idle timeout + stale last_progress -> terminal-state(idle_timeout).
    state = state_mod.load_state(state_file)
    run = state_mod.new_run(run_id, pod_id=f"pod-{run_id}", status="running", bearer=TOKEN)
    run["sidecar_url"] = "http://127.0.0.1:9"  # unreachable
    state_mod.put_run(state, run)
    state_mod.save_state(state, state_file)
    payload = {
        "cursor": {"polls": 3, "first_seen": 0.0, "last_progress": 0.0, "step": 50},
        "config": {"runId": run_id, "idleTimeoutSec": 1, "commandTimeoutSec": 1},
    }
    code, result = _run_watch_subprocess(payload, state_file)
    assert code == 0
    assert result["result"] == "terminal-state"
    assert result["reason"] == "idle_timeout"


def test_bad_stdin_still_exits_zero(state_file):
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env["OVERWATCH_STATE"] = state_file
    proc = subprocess.run(
        [sys.executable, "-m", "overwatch.watch"],
        input="{ not valid json",
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO,
        timeout=30,
    )
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["result"] == "terminal-state"


def test_empty_stdin_unknown_run_terminal(state_file):
    # No run and no sidecar -> terminal-state (unknown_run), one line, exit 0.
    payload = {"cursor": {}, "config": {"runId": "ghost", "idleTimeoutSec": 43200}}
    code, result = _run_watch_subprocess(payload, state_file)
    assert code == 0
    assert result["result"] == "terminal-state"
    assert result["reason"] == "unknown_run"
