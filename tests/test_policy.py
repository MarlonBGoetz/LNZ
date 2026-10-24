"""Tests for the policy model, especially the lower-only budget_set rule."""

import os

import pytest

from overwatch.policy import (
    BudgetRaiseError,
    DEFAULT_THRESHOLDS,
    Policy,
)


def test_defaults_match_plan():
    p = Policy()
    assert p.session_cap_usd == 50.0
    assert p.per_run_cap_usd == 20.0
    assert p.max_hours == 8.0
    assert p.gpu_allowlist == ["A100", "H100"]


def test_threshold_defaults_match_plan():
    p = Policy()
    # NaN: restart at half LR, max 2 retries.
    assert p.threshold("nan_restart_lr_factor") == 0.5
    assert p.threshold("nan_max_retries") == 2
    # Divergence EMA rising 200 steps.
    assert p.threshold("divergence_ema_rising_steps") == 200
    # OOM halve micro-batch.
    assert p.threshold("oom_microbatch_factor") == 0.5
    # Stall: no step 10 min, util < 5% 10 min.
    assert p.threshold("stall_no_step_seconds") == 600
    assert p.threshold("stall_util_floor_pct") == 5
    assert p.threshold("stall_util_seconds") == 600
    # Preempt 3 missed polls.
    assert p.threshold("preempt_missed_polls") == 3
    # Eval regression 3 evals.
    assert p.threshold("eval_regression_evals") == 3
    # Budget warn 80% stop 100%.
    assert p.threshold("budget_warn_fraction") == 0.8
    assert p.threshold("budget_stop_fraction") == 1.0
    # Checkpoint every 15 min.
    assert p.threshold("checkpoint_interval_seconds") == 900


def test_threshold_unknown_raises():
    with pytest.raises(KeyError):
        Policy().threshold("nope")


def test_budget_set_lowering_accepted():
    p = Policy()
    assert p.budget_set("session_cap_usd", 30.0) == 30.0
    assert p.session_cap_usd == 30.0
    assert p.budget_set("per_run_cap_usd", 5.0) == 5.0
    assert p.per_run_cap_usd == 5.0
    assert p.budget_set("max_hours", 2.0) == 2.0
    assert p.max_hours == 2.0


def test_budget_set_equal_is_allowed():
    p = Policy()
    assert p.budget_set("session_cap_usd", 50.0) == 50.0


def test_budget_set_raising_rejected():
    p = Policy()
    with pytest.raises(BudgetRaiseError):
        p.budget_set("session_cap_usd", 100.0)
    # Cap unchanged after a rejected raise.
    assert p.session_cap_usd == 50.0


def test_budget_set_rejects_non_cap_key():
    p = Policy()
    with pytest.raises(KeyError):
        p.budget_set("gpu_allowlist", 1)


def test_gpu_allowed():
    p = Policy()
    assert p.gpu_allowed("A100") is True
    assert p.gpu_allowed("T4") is False


def test_load_from_committed_policy(repo_root):
    path = os.path.join(repo_root, ".overwatch", "policy.yaml")
    p = Policy.load(path)
    assert p.session_cap_usd == 50.0
    assert p.gpu_allowlist == ["A100", "H100"]
    assert p.threshold("checkpoint_interval_seconds") == 900
    # Lower-only rule still holds on a loaded policy.
    with pytest.raises(BudgetRaiseError):
        p.budget_set("per_run_cap_usd", 999.0)


def test_from_dict_fills_defaults():
    p = Policy.from_dict({"session_cap_usd": 10.0})
    assert p.session_cap_usd == 10.0
    assert p.per_run_cap_usd == 20.0  # default
    assert p.thresholds == DEFAULT_THRESHOLDS


def test_load_missing_uses_defaults(tmp_path):
    missing = os.path.join(str(tmp_path), "nope.yaml")
    p = Policy.load(missing)
    assert p.session_cap_usd == 50.0
