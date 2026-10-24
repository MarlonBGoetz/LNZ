"""Tests for the safety guard (in-tool import path AND PreToolUse stdin path).

Each blocked category is exercised twice: once by calling :func:`guard.check`
directly (the in-tool layer-2 path) and once by feeding an event JSON on stdin
to :func:`guard.main` and asserting the exit code + stderr (the layer-3 hook
path).
"""

from __future__ import annotations

import io
import json
import os

import pytest

from overwatch import guard
from overwatch import state as state_mod
from overwatch.policy import Policy


def _run_main(event, monkeypatch, capsys):
    """Feed an event as stdin to guard.main and return (exit_code, stderr)."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    code = guard.main([])
    captured = capsys.readouterr()
    return code, captured.err


@pytest.fixture()
def policy():
    return Policy()  # defaults: A100/H100 allowlist, caps 50/20/8h


@pytest.fixture()
def empty_state():
    return {"version": 1, "runs": {}, "session": {"spend_usd": 0.0}}


# ----------------------------------------------------------------------
# 1. over-budget launch
# ----------------------------------------------------------------------
def test_over_budget_in_tool(policy, empty_state):
    event = {
        "tool": "run_launch",
        "args": {"gpu": "H100", "smoke_passed": True, "price_per_hour": 2.99, "max_hours": 100},
    }
    with pytest.raises(guard.GuardError) as exc:
        guard.check(event, policy=policy, state=empty_state)
    assert exc.value.category == guard.OVER_BUDGET


def test_over_budget_stdin(monkeypatch, capsys, temp_state):
    event = {
        "tool": "run_launch",
        "args": {"gpu": "H100", "smoke_passed": True, "price_per_hour": 2.99, "max_hours": 100},
    }
    code, err = _run_main(event, monkeypatch, capsys)
    assert code == 1
    assert "over_budget" in err


# ----------------------------------------------------------------------
# 2. disallowed GPU
# ----------------------------------------------------------------------
def test_disallowed_gpu_in_tool(policy, empty_state):
    event = {"tool": "run_launch", "args": {"gpu": "T4", "smoke_passed": True}}
    with pytest.raises(guard.GuardError) as exc:
        guard.check(event, policy=policy, state=empty_state)
    assert exc.value.category == guard.DISALLOWED_GPU


def test_disallowed_gpu_stdin(monkeypatch, capsys, temp_state):
    event = {"tool": "run_launch", "args": {"gpu": "T4", "smoke_passed": True}}
    code, err = _run_main(event, monkeypatch, capsys)
    assert code == 1
    assert "disallowed_gpu" in err


# ----------------------------------------------------------------------
# 3. volume delete
# ----------------------------------------------------------------------
def test_volume_delete_in_tool(policy, empty_state):
    event = {"tool": "delete_volume", "args": {"volume_id": "vol-1"}}
    with pytest.raises(guard.GuardError) as exc:
        guard.check(event, policy=policy, state=empty_state)
    assert exc.value.category == guard.VOLUME_DELETE


def test_volume_delete_stdin(monkeypatch, capsys, temp_state):
    event = {"tool": "delete_volume", "args": {"volume_id": "vol-1"}}
    code, err = _run_main(event, monkeypatch, capsys)
    assert code == 1
    assert "volume_delete" in err


# ----------------------------------------------------------------------
# 4. terminate of a keep Pod
# ----------------------------------------------------------------------
def _state_with_keep_run():
    state = {"version": 1, "runs": {}, "session": {"spend_usd": 0.0}}
    run = state_mod.new_run("run-keep", pod_id="pod-keep", status="running")
    run["keep"] = True
    run["env"] = {"OVERWATCH_RUN": "run-keep", "OVERWATCH_KEEP": "1"}
    state_mod.put_run(state, run)
    return state


def test_terminate_keep_pod_in_tool(policy):
    state = _state_with_keep_run()
    event = {"tool": "run_stop", "args": {"run_id": "run-keep", "terminate": True}}
    with pytest.raises(guard.GuardError) as exc:
        guard.check(event, policy=policy, state=state)
    assert exc.value.category == guard.KEEP_POD


def test_terminate_keep_pod_stdin(monkeypatch, capsys, temp_state):
    state = _state_with_keep_run()
    state_mod.save_state(state, temp_state)
    event = {"tool": "run_stop", "args": {"run_id": "run-keep", "terminate": True}}
    code, err = _run_main(event, monkeypatch, capsys)
    assert code == 1
    assert "keep_pod" in err


def test_stop_keep_pod_without_terminate_allowed(policy):
    state = _state_with_keep_run()
    event = {"tool": "run_stop", "args": {"run_id": "run-keep", "terminate": False}}
    # A plain stop (no terminate) of a keep Pod is allowed.
    guard.check(event, policy=policy, state=state)


# ----------------------------------------------------------------------
# 5. launch without smoke
# ----------------------------------------------------------------------
def test_no_smoke_in_tool(policy, empty_state):
    event = {"tool": "run_launch", "args": {"gpu": "A100", "smoke_passed": False}}
    with pytest.raises(guard.GuardError) as exc:
        guard.check(event, policy=policy, state=empty_state)
    assert exc.value.category == guard.NO_SMOKE


def test_no_smoke_stdin(monkeypatch, capsys, temp_state):
    event = {"tool": "run_launch", "args": {"gpu": "A100", "smoke_passed": False}}
    code, err = _run_main(event, monkeypatch, capsys)
    assert code == 1
    assert "no_smoke" in err


def _run_main_argv(event, argv, monkeypatch, capsys):
    """Feed an event as stdin to guard.main with explicit argv flags."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    code = guard.main(argv)
    captured = capsys.readouterr()
    return code, captured.err


def test_require_smoke_passed_flag_blocks_missing_smoke(monkeypatch, capsys, temp_state):
    """The guard-launch hook's --require-smoke-passed flag is honored: a
    run_launch without smoke_passed is blocked for NO_SMOKE."""
    event = {"tool": "run_launch", "args": {"gpu": "A100"}}  # no smoke_passed
    code, err = _run_main_argv(event, ["--require-smoke-passed"], monkeypatch, capsys)
    assert code == 1
    assert "no_smoke" in err


def test_require_smoke_passed_flag_allows_with_smoke(monkeypatch, capsys, temp_state):
    """With smoke_passed truthy, the flagged launch is allowed."""
    event = {
        "tool": "run_launch",
        "args": {"gpu": "A100", "smoke_passed": True, "price_per_hour": 1.89, "max_hours": 1},
    }
    code, err = _run_main_argv(event, ["--require-smoke-passed"], monkeypatch, capsys)
    assert code == 0
    assert err == ""


# ----------------------------------------------------------------------
# 6. agent edit to policy.yaml
# ----------------------------------------------------------------------
def test_policy_edit_in_tool(policy, empty_state):
    event = {"tool": "fs_write", "args": {"path": ".overwatch/policy.yaml"}}
    with pytest.raises(guard.GuardError) as exc:
        guard.check(event, policy=policy, state=empty_state)
    assert exc.value.category == guard.POLICY_EDIT


def test_policy_edit_stdin(monkeypatch, capsys, temp_state):
    event = {"tool": "str_replace", "args": {"path": "/abs/.overwatch/policy.yaml"}}
    code, err = _run_main(event, monkeypatch, capsys)
    assert code == 1
    assert "policy_edit" in err


def test_edit_other_file_allowed(policy, empty_state):
    event = {"tool": "fs_write", "args": {"path": ".overwatch/project.yaml"}}
    guard.check(event, policy=policy, state=empty_state)


# ----------------------------------------------------------------------
# allow: in-budget, allowed GPU, smoke passed
# ----------------------------------------------------------------------
def test_allowed_launch_in_tool(policy, empty_state):
    event = {
        "tool": "run_launch",
        "args": {"gpu": "A100", "smoke_passed": True, "price_per_hour": 1.89, "max_hours": 2},
    }
    guard.check(event, policy=policy, state=empty_state)  # no raise


def test_allowed_launch_stdin(monkeypatch, capsys, temp_state):
    event = {
        "tool": "run_launch",
        "args": {"gpu": "A100", "smoke_passed": True, "price_per_hour": 1.89, "max_hours": 2},
    }
    code, err = _run_main(event, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_main_invalid_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    code = guard.main([])
    err = capsys.readouterr().err
    assert code == 1
    assert "invalid event JSON" in err
