"""Pure detector functions implementing the Supervision-loop table.

Each detector takes a synthetic series (metric records, log lines, poll
results, ...) plus a :class:`~overwatch.policy.Policy` for thresholds, and
returns either ``None`` (no event) or an event dict::

    {"event": "<name>", "detail": "<human readable>", "suggested_action": "<action>"}

The functions are deliberately side-effect free so they can be unit-tested with
hand-made inputs and reused by the sidecar runner and the watch program.

Supervision-loop table (defaults from :data:`overwatch.policy.DEFAULT_THRESHOLDS`):

======================  =======================================  ==========================
 Condition               Default                                  Action
======================  =======================================  ==========================
 NaN loss                restart at half LR, max 2 retries        run_restart
 Divergence              loss EMA rising for 200 steps            alert / restart
 OOM                     halve micro-batch                        run_restart smaller batch
 Stall                   no step 10 min OR util < 5% for 10 min   alert / restart
 Preemption              3 missed polls                           re-provision
 Eval regression         eval worse for 3 evals                   alert
 Budget                  warn 80%, stop 100%                      run_stop
======================  =======================================  ==========================
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence

from .policy import Policy

# Matches the two canonical CUDA out-of-memory signatures in training logs.
_OOM_RE = re.compile(r"CUDA out of memory|OutOfMemoryError", re.IGNORECASE)


def _policy(policy: Optional[Policy]) -> Policy:
    return policy if policy is not None else Policy()


def _event(name: str, detail: str, action: str) -> Dict[str, Any]:
    return {"event": name, "detail": detail, "suggested_action": action}


def _is_bad_number(value: Any) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return math.isnan(f) or math.isinf(f)


# ----------------------------------------------------------------------
# NaN / Inf loss
# ----------------------------------------------------------------------
def nan_or_inf_loss(
    metrics: Sequence[Dict[str, Any]], policy: Optional[Policy] = None
) -> Optional[Dict[str, Any]]:
    """Fire when any metric record carries a NaN or Inf loss."""
    pol = _policy(policy)
    for record in metrics:
        if "loss" not in record:
            continue
        if _is_bad_number(record.get("loss")):
            step = record.get("step")
            factor = pol.threshold("nan_restart_lr_factor")
            retries = pol.threshold("nan_max_retries")
            return _event(
                "nan_or_inf_loss",
                f"non-finite loss at step {step}",
                f"run_restart at {factor}x LR (max {retries} retries)",
            )
    return None


# ----------------------------------------------------------------------
# Divergence: loss EMA rising for N consecutive steps
# ----------------------------------------------------------------------
def loss_divergence(
    metrics: Sequence[Dict[str, Any]],
    policy: Optional[Policy] = None,
    *,
    alpha: float = 0.1,
) -> Optional[Dict[str, Any]]:
    """Fire when the loss EMA rises for ``divergence_ema_rising_steps`` steps.

    ``alpha`` is the EMA smoothing factor. The detector walks the finite-loss
    records in order, maintaining an EMA, and counts how many consecutive steps
    the EMA has strictly increased. When that streak reaches the configured
    number of steps, it fires.
    """
    pol = _policy(policy)
    need = int(pol.threshold("divergence_ema_rising_steps"))
    ema: Optional[float] = None
    rising = 0
    for record in metrics:
        if "loss" not in record:
            continue
        loss = record.get("loss")
        if _is_bad_number(loss):
            # Non-finite loss is handled by nan_or_inf_loss; skip here.
            continue
        loss = float(loss)
        if ema is None:
            ema = loss
            continue
        new_ema = alpha * loss + (1 - alpha) * ema
        if new_ema > ema:
            rising += 1
        else:
            rising = 0
        ema = new_ema
        if rising >= need:
            return _event(
                "loss_divergence",
                f"loss EMA rising for {rising} steps",
                "alert / run_restart",
            )
    return None


# ----------------------------------------------------------------------
# CUDA OOM via log regex
# ----------------------------------------------------------------------
def cuda_oom(
    log_lines: Sequence[str], policy: Optional[Policy] = None
) -> Optional[Dict[str, Any]]:
    """Fire when a log line matches the CUDA OOM signature."""
    _policy(policy)
    for line in log_lines:
        if _OOM_RE.search(str(line)):
            return _event(
                "cuda_oom",
                f"CUDA OOM in log: {str(line).strip()[:200]}",
                "run_restart with halved micro-batch",
            )
    return None


# ----------------------------------------------------------------------
# Stall: no new step for 10 min OR util < 5% for 10 min
# ----------------------------------------------------------------------
def stall(
    *,
    last_step_age_seconds: Optional[float] = None,
    util_below_floor_seconds: Optional[float] = None,
    policy: Optional[Policy] = None,
) -> Optional[Dict[str, Any]]:
    """Fire when training has stalled.

    ``last_step_age_seconds`` is how long since the last new step. When it
    exceeds ``stall_no_step_seconds`` the run is stalled.

    ``util_below_floor_seconds`` is how long GPU util has been below
    ``stall_util_floor_pct``. When it exceeds ``stall_util_seconds`` the run is
    stalled. On CPU (no util available) pass ``None`` to skip the util branch.
    """
    pol = _policy(policy)
    no_step_limit = float(pol.threshold("stall_no_step_seconds"))
    util_limit = float(pol.threshold("stall_util_seconds"))
    floor = pol.threshold("stall_util_floor_pct")
    if last_step_age_seconds is not None and last_step_age_seconds >= no_step_limit:
        return _event(
            "stall",
            f"no new step for {last_step_age_seconds:.0f}s (>= {no_step_limit:.0f}s)",
            "alert / run_restart",
        )
    if util_below_floor_seconds is not None and util_below_floor_seconds >= util_limit:
        return _event(
            "stall",
            f"GPU util < {floor}% for {util_below_floor_seconds:.0f}s (>= {util_limit:.0f}s)",
            "alert / run_restart",
        )
    return None


# ----------------------------------------------------------------------
# Crash: non-zero exit code
# ----------------------------------------------------------------------
def crash(
    exit_code: Optional[int], policy: Optional[Policy] = None
) -> Optional[Dict[str, Any]]:
    """Fire when the training process exited with a non-zero code."""
    _policy(policy)
    if exit_code is None:
        return None
    if int(exit_code) != 0:
        return _event(
            "crash",
            f"process exited with code {int(exit_code)}",
            "inspect logs / run_restart",
        )
    return None


# ----------------------------------------------------------------------
# Preemption: sidecar unreachable for N consecutive polls
# ----------------------------------------------------------------------
def preempt(
    poll_results: Sequence[bool], policy: Optional[Policy] = None
) -> Optional[Dict[str, Any]]:
    """Fire when the sidecar was unreachable for N consecutive polls.

    ``poll_results`` is an ordered sequence of booleans: ``True`` = reachable,
    ``False`` = missed. Fires once the trailing run of misses reaches
    ``preempt_missed_polls``.
    """
    pol = _policy(policy)
    need = int(pol.threshold("preempt_missed_polls"))
    missed = 0
    for reachable in poll_results:
        if reachable:
            missed = 0
        else:
            missed += 1
        if missed >= need:
            return _event(
                "preempt",
                f"sidecar unreachable for {missed} consecutive polls",
                "re-provision pod",
            )
    return None


# ----------------------------------------------------------------------
# Eval regression: worse than best for N evals
# ----------------------------------------------------------------------
def eval_regression(
    evals: Sequence[float],
    policy: Optional[Policy] = None,
    *,
    higher_is_better: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fire when the last N evals are all worse than the running best.

    ``evals`` is the ordered eval-metric series. By default lower is better
    (e.g. eval loss). When ``higher_is_better`` is True (e.g. accuracy) the
    comparison flips.
    """
    pol = _policy(policy)
    need = int(pol.threshold("eval_regression_evals"))
    if len(evals) < need + 1:
        return None
    best = evals[0]
    worse_streak = 0
    for value in evals[1:]:
        improved = value > best if higher_is_better else value < best
        if improved:
            best = value
            worse_streak = 0
        else:
            worse_streak += 1
        if worse_streak >= need:
            return _event(
                "eval_regression",
                f"eval worse than best for {worse_streak} evals",
                "alert",
            )
    return None


# ----------------------------------------------------------------------
# Budget: spend = price/hr * uptime, warn at 80% stop at 100%
# ----------------------------------------------------------------------
def budget(
    *,
    price_per_hour: float,
    uptime_seconds: float,
    cap_usd: float,
    policy: Optional[Policy] = None,
) -> Optional[Dict[str, Any]]:
    """Fire when spend crosses the warn (80%) or stop (100%) thresholds.

    Spend is ``price_per_hour * uptime_hours``. Returns a ``budget`` event at
    the stop fraction (suggested action ``run_stop``) or a warning at the warn
    fraction. Returns ``None`` below the warn fraction or when ``cap_usd`` is
    non-positive.
    """
    pol = _policy(policy)
    warn_frac = float(pol.threshold("budget_warn_fraction"))
    stop_frac = float(pol.threshold("budget_stop_fraction"))
    if cap_usd <= 0:
        return None
    spend = float(price_per_hour) * (float(uptime_seconds) / 3600.0)
    fraction = spend / float(cap_usd)
    if fraction >= stop_frac:
        return _event(
            "budget",
            f"spend ${spend:.2f} >= {int(stop_frac * 100)}% of ${cap_usd:.2f} cap",
            "run_stop",
        )
    if fraction >= warn_frac:
        return _event(
            "budget",
            f"spend ${spend:.2f} >= {int(warn_frac * 100)}% of ${cap_usd:.2f} cap",
            "warn / prepare to stop",
        )
    return None


def run_all(
    *,
    metrics: Optional[Sequence[Dict[str, Any]]] = None,
    log_lines: Optional[Sequence[str]] = None,
    exit_code: Optional[int] = None,
    last_step_age_seconds: Optional[float] = None,
    util_below_floor_seconds: Optional[float] = None,
    poll_results: Optional[Sequence[bool]] = None,
    evals: Optional[Sequence[float]] = None,
    price_per_hour: Optional[float] = None,
    uptime_seconds: Optional[float] = None,
    cap_usd: Optional[float] = None,
    policy: Optional[Policy] = None,
) -> List[Dict[str, Any]]:
    """Run every applicable detector and return all fired events.

    Only detectors whose inputs are supplied are evaluated. This is a
    convenience for the sidecar / watch program; individual detectors remain
    independently testable.
    """
    pol = _policy(policy)
    events: List[Dict[str, Any]] = []
    if metrics is not None:
        for det in (nan_or_inf_loss, loss_divergence):
            result = det(metrics, pol)
            if result:
                events.append(result)
    if log_lines is not None:
        result = cuda_oom(log_lines, pol)
        if result:
            events.append(result)
    if last_step_age_seconds is not None or util_below_floor_seconds is not None:
        result = stall(
            last_step_age_seconds=last_step_age_seconds,
            util_below_floor_seconds=util_below_floor_seconds,
            policy=pol,
        )
        if result:
            events.append(result)
    if exit_code is not None:
        result = crash(exit_code, pol)
        if result:
            events.append(result)
    if poll_results is not None:
        result = preempt(poll_results, pol)
        if result:
            events.append(result)
    if evals is not None:
        result = eval_regression(evals, pol)
        if result:
            events.append(result)
    if price_per_hour is not None and uptime_seconds is not None and cap_usd is not None:
        result = budget(
            price_per_hour=price_per_hour,
            uptime_seconds=uptime_seconds,
            cap_usd=cap_usd,
            policy=pol,
        )
        if result:
            events.append(result)
    return events
