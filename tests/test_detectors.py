"""Unit tests for the Supervision-loop detectors.

Each detector is driven with synthetic input shaped like the output of
``tests/fake_train.py`` for the matching failure mode, plus the budget cases.
All of this runs on CPU with no GPU and no third-party packages.
"""

from __future__ import annotations

import math

from overwatch import detectors
from overwatch.policy import Policy


def _metric(step, loss, **extra):
    rec = {"type": "metric", "step": step, "loss": loss}
    rec.update(extra)
    return rec


def test_nan_at_300_fires():
    series = [_metric(s, 2.0 - s * 0.001) for s in range(50, 300, 50)]
    series.append(_metric(300, float("nan")))
    event = detectors.nan_or_inf_loss(series)
    assert event is not None
    assert event["event"] == "nan_or_inf_loss"
    assert "run_restart" in event["suggested_action"]


def test_inf_loss_fires():
    event = detectors.nan_or_inf_loss([_metric(1, float("inf"))])
    assert event is not None and event["event"] == "nan_or_inf_loss"


def test_clean_loss_no_nan_event():
    series = [_metric(s, 2.0 - s * 0.001) for s in range(50, 500, 50)]
    assert detectors.nan_or_inf_loss(series) is None


def test_loss_divergence_rising_ema():
    pol = Policy()
    pol.thresholds["divergence_ema_rising_steps"] = 5
    # Strictly increasing loss drives the EMA monotonically up.
    rising = [_metric(s, 1.0 + s * 0.1) for s in range(1, 20)]
    event = detectors.loss_divergence(rising, pol)
    assert event is not None and event["event"] == "loss_divergence"


def test_loss_divergence_not_on_decreasing():
    pol = Policy()
    pol.thresholds["divergence_ema_rising_steps"] = 5
    falling = [_metric(s, 5.0 - s * 0.1) for s in range(1, 40)]
    assert detectors.loss_divergence(falling, pol) is None


def test_oom_at_100_fires():
    logs = [
        "step 50 loss 1.94",
        "CUDA out of memory. Tried to allocate 2.00 GiB",
    ]
    event = detectors.cuda_oom(logs)
    assert event is not None and event["event"] == "cuda_oom"
    assert "micro-batch" in event["suggested_action"]


def test_oom_alt_signature():
    event = detectors.cuda_oom(["torch.cuda.OutOfMemoryError: ..."])
    assert event is not None and event["event"] == "cuda_oom"


def test_no_oom_on_clean_logs():
    assert detectors.cuda_oom(["step 1", "step 2 loss 1.0"]) is None


def test_stall_hang_no_step():
    pol = Policy()
    pol.thresholds["stall_no_step_seconds"] = 1.0
    event = detectors.stall(last_step_age_seconds=5.0, policy=pol)
    assert event is not None and event["event"] == "stall"


def test_stall_util_floor():
    pol = Policy()
    pol.thresholds["stall_util_seconds"] = 1.0
    event = detectors.stall(util_below_floor_seconds=5.0, policy=pol)
    assert event is not None and event["event"] == "stall"


def test_no_stall_when_fresh():
    pol = Policy()
    pol.thresholds["stall_no_step_seconds"] = 600.0
    assert detectors.stall(last_step_age_seconds=1.0, policy=pol) is None


def test_crash_nonzero_exit():
    event = detectors.crash(3)
    assert event is not None and event["event"] == "crash"
    assert "3" in event["detail"]


def test_crash_zero_exit_none():
    assert detectors.crash(0) is None
    assert detectors.crash(None) is None


def test_preempt_three_missed_polls():
    event = detectors.preempt([True, False, False, False])
    assert event is not None and event["event"] == "preempt"


def test_preempt_resets_on_reachable():
    # Only two trailing misses -> no fire with default of 3.
    assert detectors.preempt([False, False, True, False, False]) is None


def test_eval_regression_three_worse():
    # Lower is better; best is first, then three strictly worse evals.
    event = detectors.eval_regression([1.0, 1.1, 1.2, 1.3])
    assert event is not None and event["event"] == "eval_regression"


def test_eval_regression_not_when_improving():
    assert detectors.eval_regression([2.0, 1.5, 1.2, 1.0]) is None


def test_budget_warn_at_80_percent():
    # price 10/hr, cap 10 -> 1h = 100%; 0.8h = 80%.
    event = detectors.budget(
        price_per_hour=10.0, uptime_seconds=0.8 * 3600, cap_usd=10.0
    )
    assert event is not None and event["event"] == "budget"
    assert "warn" in event["suggested_action"]


def test_budget_stop_at_100_percent():
    event = detectors.budget(
        price_per_hour=10.0, uptime_seconds=1.0 * 3600, cap_usd=10.0
    )
    assert event is not None and event["event"] == "budget"
    assert event["suggested_action"] == "run_stop"


def test_budget_below_warn_none():
    event = detectors.budget(
        price_per_hour=10.0, uptime_seconds=0.5 * 3600, cap_usd=10.0
    )
    assert event is None


def test_run_all_dispatch():
    events = detectors.run_all(
        metrics=[_metric(300, float("nan"))],
        log_lines=["CUDA out of memory"],
        exit_code=2,
    )
    names = {e["event"] for e in events}
    assert {"nan_or_inf_loss", "cuda_oom", "crash"} <= names
