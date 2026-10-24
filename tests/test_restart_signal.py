"""Tests for run_restart (lineage/budget/guard) and run_signal (bearer token).

* ``run_restart`` preserves the run id, records lineage (a new attempt + child
  Pod), applies an LR override, and is blocked by the guard when over budget.
* ``run_signal`` delivers ``stop_graceful`` to a live local sidecar using the
  per-run bearer token, and is rejected when the run has no bearer token (and
  when the sidecar is handed the wrong token -> 401).

Offline: the fake Runpod backend provides Pods; the sidecar is a local
``http.server`` wrapping ``tests/fake_train.py`` on an ephemeral port.
"""

from __future__ import annotations

import os
import sys

import pytest

from overwatch import runpod_client, tools
from overwatch import state as state_mod
from overwatch.guard import GuardError
from overwatch.policy import Policy
from overwatch.sidecar import server as ow_server
from overwatch.sidecar.runner import Runner
from tests.fixtures import seed_fleet

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_TRAIN = os.path.join(HERE, "fake_train.py")


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    monkeypatch.setenv("OVERWATCH_STATE", os.path.join(str(tmp_path), "state.json"))
    monkeypatch.delenv("OVERWATCH_SIDECAR_URL", raising=False)
    backend = runpod_client.FakeBackend(seed_fleet())
    runpod_client.set_backend(backend)
    yield backend
    runpod_client.set_backend(None)


def _launch(backend, run_id="run-r", budget=30, max_hours=2, lr=1e-3):
    result, _ = tools.run_launch(
        config="c",
        run_id=run_id,
        gpu="A100",
        smoke_passed=True,
        budget=budget,
        max_hours=max_hours,
        volume_id="vol-PLACEHOLDER",
        backend=backend,
    )
    # Seed an initial LR override + a checkpoint so restart has lineage material.
    state = state_mod.load_state()
    run = state_mod.get_run(state, run_id)
    run.setdefault("attempts", []).append({"attempt": 1, "overrides": {"lr": lr}})
    state_mod.add_checkpoint(state, run_id, path="/vol/ckpt-step100", step=100)
    state_mod.save_state(state)
    return result


# ----------------------------------------------------------------------
# run_restart
# ----------------------------------------------------------------------
def test_restart_preserves_run_id_and_records_lineage(fake_env):
    launch = _launch(fake_env)
    original_pod = launch["pod_id"]

    result, summary = tools.run_restart(run_id="run-r", reason="nan", backend=fake_env)

    # Same run id, new Pod.
    assert result["run_id"] == "run-r"
    assert result["previous_pod_id"] == original_pod
    assert result["pod_id"] != original_pod
    assert result["attempt"] == 2

    # Lineage recorded in state; the run id still maps to the NEW pod.
    state = state_mod.load_state()
    run = state_mod.get_run(state, "run-r")
    assert run["pod_id"] == result["pod_id"]
    assert original_pod in run["lineage"]["children"] or result["pod_id"] in run["lineage"]["children"]
    assert len(run["attempts"]) == 2
    assert run["restart_count"] == 1


def test_restart_applies_lr_override(fake_env):
    _launch(fake_env, lr=1e-3)
    # Explicit override wins.
    result, _ = tools.run_restart(run_id="run-r", lr=5e-4, backend=fake_env)
    assert result["overrides"]["lr"] == 5e-4


def test_restart_nan_halves_lr_by_default(fake_env):
    _launch(fake_env, lr=1e-3)
    result, _ = tools.run_restart(run_id="run-r", reason="nan", backend=fake_env)
    # half-LR per the nan_restart_lr_factor policy threshold (0.5).
    assert result["overrides"]["lr"] == pytest.approx(5e-4)


def test_restart_oom_halves_batch_by_default(fake_env):
    launch = _launch(fake_env)
    state = state_mod.load_state()
    run = state_mod.get_run(state, "run-r")
    run["attempts"][-1]["overrides"]["batch_size"] = 8
    state_mod.save_state(state)
    result, _ = tools.run_restart(run_id="run-r", reason="oom", backend=fake_env)
    assert result["overrides"]["batch_size"] == 4


def test_restart_blocked_by_guard_over_budget(fake_env):
    # A tiny per-run cap makes any restart exceed budget -> guard blocks it.
    _launch(fake_env, budget=30)
    policy = Policy()
    policy.per_run_cap_usd = 0.01
    # Persist a lowered policy so run_restart's Policy.load() sees it.
    os.makedirs(".overwatch", exist_ok=True)
    # Instead of mutating the repo policy, drive the guard directly via a
    # monkeypatched _policy: simplest is to lower via the in-memory path.
    import overwatch.tools as tools_mod

    original = tools_mod._policy
    tools_mod._policy = lambda: policy
    try:
        with pytest.raises(GuardError) as exc:
            tools.run_restart(run_id="run-r", backend=fake_env)
        assert exc.value.category == "over_budget"
    finally:
        tools_mod._policy = original


def test_restart_unknown_run(fake_env):
    with pytest.raises(KeyError):
        tools.run_restart(run_id="does-not-exist", backend=fake_env)


# ----------------------------------------------------------------------
# run_signal (bearer token)
# ----------------------------------------------------------------------
def _start_sidecar(tmp_path, token):
    metrics = os.path.join(str(tmp_path), "metrics.ndjson")
    runner = Runner(
        [sys.executable, FAKE_TRAIN, "--sleep", "0.02"],
        policy=Policy(),
        run_id="run-s",
        metrics_path=metrics,
        ckpt_dir=str(tmp_path),
        checkpoint_interval_seconds=1000.0,
        gpu_sample_interval=1000.0,
    )
    server = ow_server.build_server(runner, host="127.0.0.1", port=0, token=token)
    port = server.server_address[1]
    thread = ow_server.serve_in_thread(server)
    runner.start()
    return runner, server, thread, port


def test_signal_stop_graceful_uses_bearer(fake_env, tmp_path):
    launch = _launch(fake_env, run_id="run-s")
    state = state_mod.load_state()
    run = state_mod.get_run(state, "run-s")
    bearer = run["bearer"]

    runner, server, thread, port = _start_sidecar(tmp_path, token=bearer)
    try:
        # Point the run at the local sidecar.
        run["sidecar_url"] = f"http://127.0.0.1:{port}"
        state_mod.put_run(state, run)
        state_mod.save_state(state)

        result, summary = tools.run_signal(run_id="run-s", signal="stop_graceful")
        assert result["delivered"] is True
        assert result["signal"] == "stop_graceful"
        # The sidecar actually received the signal.
        signals = [s["signal"] for s in runner.status()["signals"]]
        assert "stop_graceful" in signals
    finally:
        runner.signal("stop_graceful")
        runner.shutdown()
        server.shutdown()
        server.server_close()


def test_signal_rejected_without_bearer(fake_env):
    launch = _launch(fake_env, run_id="run-s")
    state = state_mod.load_state()
    run = state_mod.get_run(state, "run-s")
    run["bearer"] = None
    state_mod.put_run(state, run)
    state_mod.save_state(state)
    with pytest.raises(PermissionError):
        tools.run_signal(run_id="run-s", signal="stop_graceful")


def test_signal_wrong_token_gets_401(fake_env, tmp_path):
    _launch(fake_env, run_id="run-s")
    state = state_mod.load_state()
    run = state_mod.get_run(state, "run-s")

    runner, server, thread, port = _start_sidecar(tmp_path, token="the-real-token")
    try:
        # The run's bearer does NOT match the sidecar token -> 401.
        run["bearer"] = "wrong-token"
        run["sidecar_url"] = f"http://127.0.0.1:{port}"
        state_mod.put_run(state, run)
        state_mod.save_state(state)
        with pytest.raises(PermissionError):
            tools.run_signal(run_id="run-s", signal="checkpoint_now")
    finally:
        runner.signal("stop_graceful")
        runner.shutdown()
        server.shutdown()
        server.server_close()


def test_signal_unknown_signal(fake_env):
    _launch(fake_env, run_id="run-s")
    with pytest.raises(ValueError):
        tools.run_signal(run_id="run-s", signal="explode")
