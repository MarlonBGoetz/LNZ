"""Integration tests for the sidecar HTTP service + runner.

Starts the sidecar on an ephemeral port wrapping ``tests/fake_train.py`` and
exercises the bearer-token guard, the four endpoints, the signal contract, the
log/metric caps, and the SIGTERM / self-stop reflexes. Standard library only;
no GPU, no network beyond localhost.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

import pytest

from overwatch.policy import Policy
from overwatch.sidecar import server as ow_server
from overwatch.sidecar.runner import Runner

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAKE_TRAIN = os.path.join(HERE, "fake_train.py")

TOKEN = "test-bearer-token"


def _train_cmd(extra=None):
    cmd = [sys.executable, FAKE_TRAIN, "--sleep", "0.02"]
    if extra:
        cmd.extend(extra)
    return cmd


def _request(port, path, token=TOKEN, method="GET", body=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            pass
        return exc.code, payload


@pytest.fixture()
def sidecar(tmp_path):
    """Start a runner + HTTP server on an ephemeral port; tear down after."""
    metrics = os.path.join(str(tmp_path), "metrics.ndjson")
    runner = Runner(
        _train_cmd(),
        policy=Policy(),
        run_id="itest",
        metrics_path=metrics,
        ckpt_dir=str(tmp_path),
        checkpoint_interval_seconds=1000.0,  # don't fire during the test
        gpu_sample_interval=1000.0,
    )
    server = ow_server.build_server(runner, host="127.0.0.1", port=0, token=TOKEN)
    port = server.server_address[1]
    thread = ow_server.serve_in_thread(server)
    runner.start()
    try:
        yield runner, port, metrics
    finally:
        runner.signal("stop_graceful")
        runner.wait(timeout=5)
        runner.shutdown()
        server.shutdown()
        thread.join(timeout=5)


def _wait_for_step(port):
    for _ in range(100):
        status, payload = _request(port, "/status")
        if status == 200 and payload.get("step"):
            return payload
        time.sleep(0.05)
    return payload


def test_requires_bearer_token(sidecar):
    _, port, _ = sidecar
    status, _ = _request(port, "/status", token=None)
    assert status == 401
    status, _ = _request(port, "/status", token="wrong")
    assert status == 401


def test_status_with_token_returns_step_and_loss(sidecar):
    _, port, _ = sidecar
    payload = _wait_for_step(port)
    assert payload.get("step") is not None
    assert payload.get("loss") is not None
    assert payload.get("gpu", {}).get("cpu_only") is True


def test_logs_endpoint_capped(sidecar):
    _, port, _ = sidecar
    _wait_for_step(port)
    status, payload = _request(port, "/logs")
    assert status == 200
    assert payload["count"] <= 400
    assert isinstance(payload["lines"], list)


def test_metrics_endpoint_downsampled(sidecar):
    _, port, _ = sidecar
    _wait_for_step(port)
    status, payload = _request(port, "/metrics")
    assert status == 200
    assert payload["count"] <= 500


def test_signal_checkpoint_now_accepted(sidecar):
    _, port, _ = sidecar
    _wait_for_step(port)
    status, payload = _request(
        port, "/signal", method="POST", body={"signal": "checkpoint_now"}
    )
    assert status == 200
    assert payload.get("ok") is True


def test_signal_unknown_rejected(sidecar):
    _, port, _ = sidecar
    status, payload = _request(
        port, "/signal", method="POST", body={"signal": "bogus"}
    )
    assert status == 400


def test_unknown_path_404(sidecar):
    _, port, _ = sidecar
    status, _ = _request(port, "/nope")
    assert status == 404


# ----------------------------------------------------------------------
# Reflexes (unit-level: exercise the runner directly with tiny thresholds).
# ----------------------------------------------------------------------
def _ckpt_records(path):
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return [r for r in records if r.get("type") == "checkpoint"]


def test_sigterm_writes_checkpoint_record(tmp_path):
    metrics = os.path.join(str(tmp_path), "metrics.ndjson")
    runner = Runner(
        _train_cmd(["--hang-seconds", "3", "--fail", "hang@200"]),
        policy=Policy(),
        run_id="sig",
        metrics_path=metrics,
        ckpt_dir=str(tmp_path),
        checkpoint_interval_seconds=1000.0,
        gpu_sample_interval=1000.0,
    )
    runner.start()
    # Let a couple of steps land.
    for _ in range(100):
        if runner.status().get("step"):
            break
        time.sleep(0.02)
    runner.handle_sigterm()
    runner.wait(timeout=5)
    runner.shutdown()
    ckpts = _ckpt_records(metrics)
    assert any(c.get("reason") == "sigterm" for c in ckpts)


def test_self_stop_on_budget_cap(tmp_path):
    metrics = os.path.join(str(tmp_path), "metrics.ndjson")
    runner = Runner(
        _train_cmd(["--hang-seconds", "5", "--fail", "hang@50"]),
        policy=Policy(),
        run_id="budget",
        metrics_path=metrics,
        ckpt_dir=str(tmp_path),
        price_per_hour=3600.0,  # $1 per second of uptime
        budget_cap_usd=0.5,  # cap reached in ~0.5s
        checkpoint_interval_seconds=1000.0,
        gpu_sample_interval=1000.0,
    )
    runner.start()
    runner.wait(timeout=6)
    runner.shutdown()
    status = runner.status()
    assert status["status"] == "stopped"
    assert status["stop_reason"] is not None
    assert "budget" in status["stop_reason"]
    ckpts = _ckpt_records(metrics)
    assert any(c.get("reason") == "self-stop" for c in ckpts)


def test_self_stop_on_max_hours(tmp_path):
    metrics = os.path.join(str(tmp_path), "metrics.ndjson")
    runner = Runner(
        _train_cmd(["--hang-seconds", "5", "--fail", "hang@50"]),
        policy=Policy(),
        run_id="hours",
        metrics_path=metrics,
        ckpt_dir=str(tmp_path),
        max_hours=0.5 / 3600.0,  # 0.5s
        checkpoint_interval_seconds=1000.0,
        gpu_sample_interval=1000.0,
    )
    runner.start()
    runner.wait(timeout=6)
    runner.shutdown()
    status = runner.status()
    assert status["status"] == "stopped"
    assert "max_hours" in (status["stop_reason"] or "")
