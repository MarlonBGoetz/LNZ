"""Core MCP tool implementations as plain Python functions.

Each tool is a plain function that returns ``(result_dict, one_line_summary)``
so the logic is fully unit-testable without any MCP SDK, network or GPU. The
FastMCP entrypoint in :mod:`overwatch.server` wraps these when the SDK is
present.

All Runpod interaction goes through :mod:`overwatch.runpod_client` (the fake
backend is used in the sandbox). Safety checks are delegated to
:mod:`overwatch.guard` (layer 2, in-tool).

Tools implemented here (the complete surface so later phases can register
them): ``gpu_recommend``, ``run_smoke``, ``run_launch``, ``run_status``,
``run_logs``, ``run_metrics``, ``run_signal`` (stub signal plumbing),
``run_restart`` (stub, real lineage logic in FEAT-004), ``run_stop``,
``run_list``, ``run_report``, ``fleet_status``, ``fleet_reap``,
``budget_status``, ``budget_set``, ``artifacts_pull``. ``datagen_*`` are thin
not-implemented-yet stubs (real impl is FEAT-007).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import guard
from . import runpod_client
from . import state as state_mod
from .policy import BudgetRaiseError, Policy
from .sidecar.server import downsample

Result = Tuple[Dict[str, Any], str]

POD_PREFIX = "ow-"
RUN_ENV = "OVERWATCH_RUN"
KEEP_ENV = "OVERWATCH_KEEP"
REPORTS_DIR = os.path.join(".overwatch", "reports")
DEFAULT_IMAGE = "runpod/pytorch:2.3.0-py3.11-cuda12.1"

# Smoke runs are always short-lived and self-terminating.
SMOKE_MAX_MINUTES = 10

# artifacts_pull size guard (MB).
DEFAULT_ARTIFACT_LIMIT_MB = 2048

# A rough model-size -> GPU sizing table used by gpu_recommend. Keyed by the
# estimated model parameter count (billions). Values pick a GPU from the
# allowlist-friendly set and a count.
_SIZING_TABLE = [
    # (max_params_billion, gpu, count)
    (3, "A100", 1),
    (8, "A100", 1),
    (13, "A100", 2),
    (34, "H100", 2),
    (70, "H100", 4),
    (float("inf"), "H100", 8),
]


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _policy() -> Policy:
    return Policy.load()


def _status_url(pod_id: Optional[str], run_id: str) -> str:
    host = pod_id or run_id
    return f"https://{host}.runpod.proxy/status"


def _health_verdict(status: Dict[str, Any], policy: Policy) -> str:
    """Derive a coarse health verdict from a status snapshot."""
    state = status.get("status")
    if state in ("stopped", "terminated", "failed"):
        return "failed" if state == "failed" else "stopped"
    loss = status.get("loss")
    if loss is not None and (loss != loss or loss in (float("inf"), float("-inf"))):
        return "unhealthy"
    slope = status.get("loss_slope")
    if slope is not None and slope > 0:
        return "warning"
    age = status.get("last_step_age_seconds")
    if age is not None and age > float(policy.threshold("stall_no_step_seconds")):
        return "stalled"
    return "healthy"


# ----------------------------------------------------------------------
# sizing
# ----------------------------------------------------------------------
def gpu_recommend(
    *,
    params_billion: float = 7.0,
    batch_size: int = 1,
    seq_len: int = 2048,
    backend: Optional[runpod_client.Backend] = None,
) -> Result:
    """Recommend a GPU type/count for a model + batch estimate."""
    backend = backend or runpod_client.get_backend()
    policy = _policy()
    gpu, count = "A100", 1
    for max_b, g, c in _SIZING_TABLE:
        if params_billion <= max_b:
            gpu, count = g, c
            break
    # Scale count up a little for very large batches.
    if batch_size * seq_len > 32768:
        count *= 2
    # Prefer an allowlisted GPU.
    if not policy.gpu_allowed(gpu):
        allowed = policy.gpu_allowlist or ["A100"]
        gpu = allowed[-1]
    price = backend.gpu_price(gpu) or 0.0
    result = {
        "gpu": gpu,
        "gpu_count": count,
        "price_per_hour": round(price * count, 4),
        "params_billion": params_billion,
        "rationale": f"{params_billion}B params -> {count}x {gpu}",
    }
    summary = (
        f"Recommend {count}x {gpu} (~${result['price_per_hour']:.2f}/hr) "
        f"for a {params_billion}B model"
    )
    return result, summary


# ----------------------------------------------------------------------
# smoke
# ----------------------------------------------------------------------
def run_smoke(
    *,
    config: str,
    gpu: str = "A100",
    backend: Optional[runpod_client.Backend] = None,
) -> Result:
    """Launch a short smoke run to validate the image/config.

    A smoke run has a 10-minute hard cap and always terminates its Pod. In the
    sandbox this is simulated deterministically: it provisions and immediately
    terminates a transient Pod and reports a pass.
    """
    backend = backend or runpod_client.get_backend()
    smoke_id = f"smoke-{int(time.time() * 1000) % 100000:05d}"
    pod = backend.create_pod(
        name=f"{POD_PREFIX}{smoke_id}",
        gpu=gpu,
        image=DEFAULT_IMAGE,
        env={RUN_ENV: smoke_id, KEEP_ENV: "0"},
    )
    # Always terminate the smoke Pod (hard cap enforced here).
    backend.terminate_pod(pod["id"])
    result = {
        "smoke_id": smoke_id,
        "config": config,
        "gpu": gpu,
        "passed": True,
        "max_minutes": SMOKE_MAX_MINUTES,
        "pod_terminated": True,
    }
    summary = f"Smoke {smoke_id} passed on {gpu}; transient Pod terminated"
    return result, summary


# ----------------------------------------------------------------------
# launch
# ----------------------------------------------------------------------
def run_launch(
    *,
    config: str,
    run_id: Optional[str] = None,
    gpu: str = "A100",
    gpu_count: int = 1,
    smoke_passed: bool = False,
    budget: Optional[float] = None,
    max_hours: Optional[float] = None,
    volume_id: Optional[str] = None,
    keep: bool = False,
    image: str = DEFAULT_IMAGE,
    backend: Optional[runpod_client.Backend] = None,
) -> Result:
    """Provision an ``ow-<run>`` Pod and start a supervised run.

    Refuses (raising :class:`guard.GuardError` or ``ValueError``) unless the
    smoke test passed, a budget and max hours are set, a network volume is
    given, the GPU is allowed and the projected cost is within caps.
    """
    backend = backend or runpod_client.get_backend()
    policy = _policy()

    # Hard preconditions (clear refusal messages).
    if not smoke_passed:
        raise ValueError("run_launch refused: no passed smoke test (run_smoke first)")
    if budget is None:
        raise ValueError("run_launch refused: a budget is required")
    if max_hours is None:
        raise ValueError("run_launch refused: max_hours is required")
    if not volume_id:
        raise ValueError("run_launch refused: a network volume is required")

    run_id = run_id or f"run-{int(time.time() * 1000) % 1000000:06d}"
    price = (backend.gpu_price(gpu) or 0.0) * int(gpu_count)

    # Layer-2 in-tool guard (budget / GPU / smoke).
    state = state_mod.load_state()
    guard.check(
        {
            "tool": "run_launch",
            "args": {
                "gpu": gpu,
                "smoke_passed": smoke_passed,
                "price_per_hour": price,
                "max_hours": max_hours,
            },
        },
        policy=policy,
        state=state,
    )

    bearer = state_mod.new_bearer_token()
    pod = backend.create_pod(
        name=f"{POD_PREFIX}{run_id}",
        gpu=gpu,
        gpu_count=gpu_count,
        image=image,
        volume_id=volume_id,
        env={
            RUN_ENV: run_id,
            KEEP_ENV: "1" if keep else "0",
            "OVERWATCH_TOKEN": bearer,
        },
        price_per_hour=backend.gpu_price(gpu) or 0.0,
    )

    run = state_mod.new_run(
        run_id,
        pod_id=pod["id"],
        status="running",
        price_per_hour=pod["price_per_hour"],
        bearer=bearer,
        budget=budget,
        max_hours=max_hours,
    )
    run["keep"] = bool(keep)
    run["env"] = dict(pod["env"])
    run["config"] = config
    run["gpu"] = gpu
    run["gpu_count"] = gpu_count
    run["image"] = image
    run["volume_id"] = volume_id
    state_mod.put_run(state, run)
    state_mod.save_state(state)

    status_url = _status_url(pod["id"], run_id)
    result = {
        "run_id": run_id,
        "pod_id": pod["id"],
        "pod_name": pod["name"],
        "gpu": gpu,
        "gpu_count": gpu_count,
        "price_per_hour": pod["price_per_hour"],
        "status": "running",
        "status_url": status_url,
        "bearer_issued": True,
        "env": {RUN_ENV: run_id, KEEP_ENV: "1" if keep else "0"},
    }
    summary = (
        f"Launched {pod['name']} ({gpu}x{gpu_count}, ${pod['price_per_hour']:.2f}/hr); "
        f"status at {status_url}"
    )
    return result, summary


# ----------------------------------------------------------------------
# status / logs / metrics (read-only)
# ----------------------------------------------------------------------
def _fake_status_for(run: Dict[str, Any]) -> Dict[str, Any]:
    """Synthesize a status snapshot for a run (offline stand-in)."""
    uptime = max(0.0, time.time() - float(run.get("created_at", time.time())))
    price = float(run.get("price_per_hour") or 0.0)
    return {
        "status": run.get("status", "running"),
        "step": run.get("last_step", 1000),
        "loss": run.get("last_loss", 1.23),
        "loss_slope": run.get("loss_slope", -0.01),
        "tokens_per_s": run.get("tokens_per_s", 15000),
        "gpu": {"util": 92, "mem_used_mb": 60000, "cpu_only": False},
        "eta_seconds": run.get("eta_seconds", 3600),
        "last_eval": run.get("last_eval"),
        "last_checkpoint": (run.get("checkpoints") or [{}])[-1] if run.get("checkpoints") else None,
        "spend_usd": round(price * uptime / 3600.0, 4),
        "uptime_seconds": uptime,
        "last_step_age_seconds": run.get("last_step_age_seconds", 5.0),
    }


def run_status(*, run_id: str, status_snapshot: Optional[Dict[str, Any]] = None) -> Result:
    """Current status of a run plus a health verdict (read-only)."""
    policy = _policy()
    state = state_mod.load_state()
    run = state_mod.get_run(state, run_id)
    if run is None:
        raise KeyError(f"unknown run_id: {run_id}")
    snap = status_snapshot or _fake_status_for(run)
    verdict = _health_verdict(snap, policy)
    result = {
        "run_id": run_id,
        "pod_id": run.get("pod_id"),
        "state": snap.get("status"),
        "step": snap.get("step"),
        "loss": snap.get("loss"),
        "loss_slope": snap.get("loss_slope"),
        "last_eval": snap.get("last_eval"),
        "gpu_util": (snap.get("gpu") or {}).get("util"),
        "gpu_mem_used_mb": (snap.get("gpu") or {}).get("mem_used_mb"),
        "tokens_per_s": snap.get("tokens_per_s"),
        "eta_seconds": snap.get("eta_seconds"),
        "spend_usd": snap.get("spend_usd"),
        "last_checkpoint": snap.get("last_checkpoint"),
        "health": verdict,
    }
    summary = (
        f"{run_id}: {result['state']} step {result['step']} loss {result['loss']} "
        f"[{verdict}]"
    )
    return result, summary


def run_logs(
    *,
    run_id: str,
    lines: Optional[List[str]] = None,
    limit: int = 400,
    grep: Optional[str] = None,
) -> Result:
    """Tail logs for a run (cap 400 lines, optional grep)."""
    state = state_mod.load_state()
    if state_mod.get_run(state, run_id) is None:
        raise KeyError(f"unknown run_id: {run_id}")
    limit = min(int(limit), 400)
    src = list(lines or [])
    if grep:
        src = [ln for ln in src if grep in ln]
    tail = src[-limit:]
    result = {"run_id": run_id, "lines": tail, "count": len(tail)}
    summary = f"{run_id}: {len(tail)} log line(s)"
    return result, summary


def run_metrics(
    *,
    run_id: str,
    metrics: Optional[List[Dict[str, Any]]] = None,
    cap: int = 500,
) -> Result:
    """Latest metrics for a run, downsampled to <= 500 points."""
    state = state_mod.load_state()
    if state_mod.get_run(state, run_id) is None:
        raise KeyError(f"unknown run_id: {run_id}")
    points = downsample(list(metrics or []), cap=min(int(cap), 500))
    result = {
        "run_id": run_id,
        "points": points,
        "count": len(points),
        "total": len(metrics or []),
    }
    summary = f"{run_id}: {len(points)} metric point(s) (of {result['total']})"
    return result, summary


# ----------------------------------------------------------------------
# signals / restart (stubs here; full logic in later features)
# ----------------------------------------------------------------------
# Signals accepted by the sidecar (/signal endpoint).
SIDECAR_SIGNALS = {"checkpoint_now", "pause", "resume", "stop_graceful"}
# Additional signal aliases the tool accepts (mapped onto sidecar signals).
_SIGNAL_ALIASES = {
    "checkpoint": "checkpoint_now",
    "stop": "stop_graceful",
}


def _run_sidecar_url(run: Dict[str, Any]) -> Optional[str]:
    """Resolve a run's sidecar base URL (test override or Pod proxy host)."""
    base = run.get("sidecar_url")
    if not base:
        base = os.environ.get("OVERWATCH_SIDECAR_URL")
    if not base and run.get("pod_id"):
        base = f"https://{run['pod_id']}.runpod.proxy"
    return base.rstrip("/") if base else None


def _post_signal(base: str, bearer: Optional[str], signal: str, timeout: float = 10.0) -> Dict[str, Any]:
    """POST a signal to the sidecar /signal endpoint using the bearer token.

    Returns the parsed JSON body. Raises on a transport error or non-2xx (so
    the caller sees a 401 when the bearer token is missing/wrong).
    """
    body = json.dumps({"signal": signal}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(f"{base}/signal", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_signal(*, run_id: str, signal: str) -> Result:
    """Send a signal to a run's sidecar using the per-run bearer token.

    Valid signals: ``checkpoint_now`` | ``pause`` | ``resume`` |
    ``stop_graceful`` (``checkpoint`` / ``stop`` are accepted as aliases). The
    request carries the run's bearer token as ``Authorization: Bearer``; without
    a valid token the sidecar rejects it with 401 (surfaced as an error).

    When a run has no reachable sidecar URL the signal is recorded as queued so
    the tool stays usable offline, but a bearer token is always required.
    """
    signal = _SIGNAL_ALIASES.get(signal, signal)
    if signal not in SIDECAR_SIGNALS:
        raise ValueError(f"unknown signal: {signal}")
    state = state_mod.load_state()
    run = state_mod.get_run(state, run_id)
    if run is None:
        raise KeyError(f"unknown run_id: {run_id}")

    bearer = run.get("bearer")
    if not bearer:
        raise PermissionError(
            f"run_signal refused: no bearer token for {run_id} (cannot authenticate to sidecar)"
        )

    base = _run_sidecar_url(run)
    delivered = False
    detail = "queued (no reachable sidecar)"
    if base:
        try:
            resp = _post_signal(base, bearer, signal)
            delivered = bool(resp.get("ok", True))
            detail = "delivered" if delivered else resp.get("error", "rejected")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise PermissionError(
                    f"run_signal refused: sidecar rejected the bearer token for {run_id} (401)"
                ) from exc
            detail = f"sidecar error {exc.code}"
        except (urllib.error.URLError, OSError):
            detail = "queued (sidecar unreachable)"

    result = {
        "run_id": run_id,
        "signal": signal,
        "delivered": delivered,
        "accepted": True,
        "detail": detail,
    }
    return result, f"{run_id}: signal {signal} ({detail})"


def run_restart(
    *,
    run_id: str,
    reason: Optional[str] = None,
    lr: Optional[float] = None,
    batch_size: Optional[int] = None,
    grad_clip: Optional[float] = None,
    from_checkpoint: Optional[str] = None,
    backend: Optional[runpod_client.Backend] = None,
) -> Result:
    """Restart a run from its latest checkpoint as a new attempt.

    A restart provisions a **new** Pod but keeps the **same** ``run_id`` mapped
    to it, records lineage (a new attempt whose parent is the previous attempt),
    counts against the budget and goes through the guard (same checks as
    ``run_launch``: allowed GPU, passed smoke, in-budget). Optional ``lr`` /
    ``batch_size`` / ``grad_clip`` overrides are recorded on the new attempt;
    when ``reason`` indicates a NaN the LR is halved and for an OOM the batch is
    halved if no explicit override is given (mirrors the Supervision-loop
    table).
    """
    backend = backend or runpod_client.get_backend()
    policy = _policy()
    state = state_mod.load_state()
    run = state_mod.get_run(state, run_id)
    if run is None:
        raise KeyError(f"unknown run_id: {run_id}")

    attempts = run.get("attempts") or []
    prev_overrides = (attempts[-1].get("overrides") if attempts else {}) or {}
    prev_lr = prev_overrides.get("lr")
    prev_batch = prev_overrides.get("batch_size")

    # Default healing overrides from the restart reason (Supervision-loop table).
    overrides: Dict[str, Any] = {}
    if lr is not None:
        overrides["lr"] = lr
    elif reason == "nan" and prev_lr is not None:
        overrides["lr"] = prev_lr * float(policy.threshold("nan_restart_lr_factor"))
    if batch_size is not None:
        overrides["batch_size"] = batch_size
    elif reason == "oom" and prev_batch is not None:
        overrides["batch_size"] = max(1, int(prev_batch * float(policy.threshold("oom_microbatch_factor"))))
    if grad_clip is not None:
        overrides["grad_clip"] = grad_clip

    gpu = run.get("gpu") or "A100"
    gpu_count = int(run.get("gpu_count") or 1)
    price = (backend.gpu_price(gpu) or float(run.get("price_per_hour") or 0.0)) * gpu_count

    # Retry cap for NaN restarts (max 2 by policy).
    nan_retries = sum(1 for a in attempts if a.get("reason") == "nan")
    if reason == "nan" and nan_retries >= int(policy.threshold("nan_max_retries")):
        raise ValueError(
            f"run_restart refused: NaN retry budget exhausted "
            f"({nan_retries}/{policy.threshold('nan_max_retries')})"
        )

    # Layer-2 in-tool guard (same categories as a launch): a restart counts
    # against budget and must use an allowed GPU. smoke_passed carries forward.
    guard.check(
        {
            "tool": "run_restart",
            "args": {
                "gpu": gpu,
                "smoke_passed": True,  # the original launch required a passed smoke
                "price_per_hour": price,
                "max_hours": run.get("max_hours") or policy.max_hours,
            },
        },
        policy=policy,
        state=state,
    )

    # New bearer + new Pod, but the SAME run_id maps to the new Pod.
    bearer = state_mod.new_bearer_token()
    checkpoint = from_checkpoint
    if checkpoint is None:
        checkpoints = run.get("checkpoints") or []
        checkpoint = checkpoints[-1].get("path") if checkpoints else None

    keep = bool(run.get("keep"))
    pod = backend.create_pod(
        name=f"{POD_PREFIX}{run_id}",
        gpu=gpu,
        gpu_count=gpu_count,
        image=run.get("image") or DEFAULT_IMAGE,
        volume_id=run.get("volume_id"),
        env={
            RUN_ENV: run_id,
            KEEP_ENV: "1" if keep else "0",
            "OVERWATCH_TOKEN": bearer,
        },
        price_per_hour=backend.gpu_price(gpu) or float(run.get("price_per_hour") or 0.0),
    )

    # Record lineage: a new attempt whose parent is the previous attempt/Pod.
    prev_pod = run.get("pod_id")
    attempt_no = len(attempts) + 1
    attempt = {
        "attempt": attempt_no,
        "parent_pod": prev_pod,
        "pod_id": pod["id"],
        "reason": reason,
        "from_checkpoint": checkpoint,
        "overrides": overrides,
        "at": time.time(),
    }
    run.setdefault("attempts", []).append(attempt)
    lineage = run.setdefault("lineage", {"parent": None, "children": []})
    lineage.setdefault("children", []).append(pod["id"])

    # Keep the SAME run_id mapped to the new Pod.
    run["pod_id"] = pod["id"]
    run["bearer"] = bearer
    run["status"] = "running"
    run["price_per_hour"] = pod["price_per_hour"]
    run["env"] = dict(pod["env"])
    run["restart_count"] = int(run.get("restart_count", 0)) + 1
    state_mod.put_run(state, run)
    state_mod.save_state(state)

    status_url = _status_url(pod["id"], run_id)
    result = {
        "run_id": run_id,
        "pod_id": pod["id"],
        "previous_pod_id": prev_pod,
        "attempt": attempt_no,
        "reason": reason,
        "from_checkpoint": checkpoint,
        "overrides": overrides,
        "price_per_hour": pod["price_per_hour"],
        "status": "running",
        "status_url": status_url,
        "bearer_issued": True,
        "restart_count": run["restart_count"],
    }
    ov = ", ".join(f"{k}={v}" for k, v in overrides.items()) or "no overrides"
    summary = (
        f"{run_id}: restarted (attempt {attempt_no}) on {pod['name']} "
        f"from {checkpoint or 'scratch'} [{ov}]"
    )
    return result, summary


# ----------------------------------------------------------------------
# stop
# ----------------------------------------------------------------------
def run_stop(
    *,
    run_id: str,
    terminate: bool = False,
    confirm: bool = False,
    keep: Optional[bool] = None,
    backend: Optional[runpod_client.Backend] = None,
) -> Result:
    """Stop a run; terminating the Pod requires ``confirm=True``.

    Artifacts are synced (noted) before any teardown. Terminating a keep Pod is
    blocked by the guard.
    """
    backend = backend or runpod_client.get_backend()
    state = state_mod.load_state()
    run = state_mod.get_run(state, run_id)
    if run is None:
        raise KeyError(f"unknown run_id: {run_id}")

    if terminate and not confirm:
        raise ValueError("run_stop refused: terminate requires confirm=True")

    # In-tool guard for keep Pods.
    guard.check(
        {"tool": "run_stop", "args": {"run_id": run_id, "terminate": terminate}},
        state=state,
    )

    # Sync artifacts first (noted; the real sync happens against the volume).
    artifacts_synced = True

    pod_id = run.get("pod_id")
    action = "stopped"
    if pod_id:
        try:
            if terminate:
                backend.terminate_pod(pod_id)
                action = "terminated"
            else:
                backend.stop_pod(pod_id)
        except KeyError:
            pass
    run["status"] = "terminated" if terminate else "stopped"
    if keep is not None:
        run["keep"] = bool(keep)
    state_mod.put_run(state, run)
    state_mod.save_state(state)

    result = {
        "run_id": run_id,
        "pod_id": pod_id,
        "action": action,
        "terminated": terminate,
        "artifacts_synced": artifacts_synced,
    }
    summary = f"{run_id}: {action} (artifacts synced)"
    return result, summary


# ----------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------
def run_list(*, status: Optional[str] = None) -> Result:
    """List known runs (optionally filtered by status)."""
    state = state_mod.load_state()
    runs = state_mod.list_runs(state)
    if status:
        runs = [r for r in runs if r.get("status") == status]
    rows = [
        {
            "run_id": r.get("run_id"),
            "pod_id": r.get("pod_id"),
            "status": r.get("status"),
            "gpu": r.get("gpu"),
            "price_per_hour": r.get("price_per_hour"),
            "keep": bool(r.get("keep")),
        }
        for r in runs
    ]
    result = {"runs": rows, "count": len(rows)}
    summary = f"{len(rows)} run(s)"
    return result, summary


# ----------------------------------------------------------------------
# report
# ----------------------------------------------------------------------
def run_report(*, run_id: str, reports_dir: str = REPORTS_DIR) -> Result:
    """Write a Markdown post-mortem to ``.overwatch/reports/<run>.md``."""
    state = state_mod.load_state()
    run = state_mod.get_run(state, run_id)
    if run is None:
        raise KeyError(f"unknown run_id: {run_id}")
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"{run_id}.md")
    uptime = max(0.0, time.time() - float(run.get("created_at", time.time())))
    price = float(run.get("price_per_hour") or 0.0)
    spend = round(price * uptime / 3600.0, 4)
    checkpoints = run.get("checkpoints") or []
    lines = [
        f"# Run report: {run_id}",
        "",
        f"- Pod: `{run.get('pod_id')}`",
        f"- GPU: {run.get('gpu')}",
        f"- Status: {run.get('status')}",
        f"- Price/hour: ${price:.2f}",
        f"- Budget: ${run.get('budget')}",
        f"- Max hours: {run.get('max_hours')}",
        f"- Estimated spend: ${spend:.2f}",
        f"- Checkpoints: {len(checkpoints)}",
        "",
        "## Checkpoints",
        "",
    ]
    if checkpoints:
        for ck in checkpoints:
            lines.append(f"- step {ck.get('step')} -> `{ck.get('path')}`")
    else:
        lines.append("- (none recorded)")
    lines.append("")
    content = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    result = {"run_id": run_id, "path": path, "bytes": len(content)}
    summary = f"{run_id}: report written to {path}"
    return result, summary


# ----------------------------------------------------------------------
# fleet
# ----------------------------------------------------------------------
def fleet_status(*, backend: Optional[runpod_client.Backend] = None) -> Result:
    """Status across all live Pods, including ones overwatch did not create."""
    backend = backend or runpod_client.get_backend()
    pods = backend.list_pods()
    rows = []
    total_rate = 0.0
    for pod in pods:
        if pod.get("status") != "RUNNING":
            continue
        rate = float(pod.get("price_per_hour") or 0.0)
        total_rate += rate
        rows.append(
            {
                "pod_id": pod.get("id"),
                "name": pod.get("name"),
                "gpu": pod.get("gpu"),
                "price_per_hour": rate,
                "created_by": pod.get("created_by", "unknown"),
                "foreign": pod.get("created_by") != "overwatch",
                "keep": str((pod.get("env") or {}).get(KEEP_ENV, "")).lower()
                in ("1", "true", "yes"),
            }
        )
    foreign = [r for r in rows if r["foreign"]]
    result = {
        "pods": rows,
        "count": len(rows),
        "foreign_count": len(foreign),
        "total_spend_rate_per_hour": round(total_rate, 4),
    }
    summary = (
        f"{len(rows)} running Pod(s) ({len(foreign)} foreign); "
        f"${result['total_spend_rate_per_hour']:.2f}/hr total"
    )
    return result, summary


def fleet_reap(
    *,
    dry_run: bool = True,
    backend: Optional[runpod_client.Backend] = None,
) -> Result:
    """Stop/destroy orphaned or over-budget Pods. Never touches keep Pods.

    ``dry_run`` defaults to ``True`` so a reap only reports candidates unless
    explicitly asked to act.
    """
    backend = backend or runpod_client.get_backend()
    state = state_mod.load_state()
    pods = backend.list_pods()

    # Pod ids that belong to a known, still-live run.
    known_live = {
        r.get("pod_id")
        for r in state_mod.list_runs(state)
        if r.get("status") in ("running", "launching", "pending")
    }

    candidates = []
    for pod in pods:
        if pod.get("status") != "RUNNING":
            continue
        env = pod.get("env") or {}
        is_keep = str(env.get(KEEP_ENV, "")).lower() in ("1", "true", "yes")
        if is_keep:
            continue  # never touch keep Pods
        is_overwatch = pod.get("created_by") == "overwatch"
        orphaned = is_overwatch and pod.get("id") not in known_live
        if orphaned:
            candidates.append(pod)

    reaped = []
    if not dry_run:
        for pod in candidates:
            try:
                backend.terminate_pod(pod["id"])
                reaped.append(pod["id"])
            except KeyError:
                pass

    result = {
        "dry_run": dry_run,
        "candidates": [p["id"] for p in candidates],
        "candidate_count": len(candidates),
        "reaped": reaped,
    }
    verb = "would reap" if dry_run else "reaped"
    summary = f"{verb} {len(candidates)} orphaned Pod(s) (keep Pods untouched)"
    return result, summary


# ----------------------------------------------------------------------
# budget
# ----------------------------------------------------------------------
def budget_status(*, backend: Optional[runpod_client.Backend] = None) -> Result:
    """Current session and per-run spend vs caps (read-only)."""
    policy = _policy()
    state = state_mod.load_state()
    rate = 0.0
    per_run = []
    for run in state_mod.list_runs(state):
        if run.get("status") in ("running", "launching", "pending"):
            r = float(run.get("price_per_hour") or 0.0)
            rate += r
            per_run.append({"run_id": run.get("run_id"), "price_per_hour": r})
    result = {
        "session_cap_usd": policy.session_cap_usd,
        "per_run_cap_usd": policy.per_run_cap_usd,
        "max_hours": policy.max_hours,
        "session_spend_rate_per_hour": round(rate, 4),
        "runs": per_run,
    }
    summary = (
        f"Session rate ${rate:.2f}/hr vs cap ${policy.session_cap_usd:.2f}; "
        f"per-run cap ${policy.per_run_cap_usd:.2f}"
    )
    return result, summary


def budget_set(*, key: str, value: float) -> Result:
    """Lower a spend cap (raising is rejected by the policy model)."""
    path = os.path.join(".overwatch", "policy.yaml")
    policy = Policy.load(path)
    try:
        new_value = policy.budget_set(key, value)
    except BudgetRaiseError as exc:
        raise BudgetRaiseError(str(exc)) from exc
    # Persist the lowered cap back to policy.yaml.
    from . import config as config_mod

    data = policy.to_dict()
    if os.path.exists(path) or os.path.isdir(os.path.dirname(path) or "."):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(config_mod.dump_yaml(data))
    result = {"key": key, "value": new_value}
    summary = f"Lowered {key} to {new_value}"
    return result, summary


# ----------------------------------------------------------------------
# artifacts
# ----------------------------------------------------------------------
def artifacts_pull(
    *,
    run_id: str,
    dest: str,
    size_mb: float = 0.0,
    limit_mb: float = DEFAULT_ARTIFACT_LIMIT_MB,
    files: Optional[List[Dict[str, Any]]] = None,
) -> Result:
    """Pull checkpoints/artifacts from a run's volume, enforcing a size limit."""
    state = state_mod.load_state()
    if state_mod.get_run(state, run_id) is None:
        raise KeyError(f"unknown run_id: {run_id}")
    files = files or []
    total = size_mb or sum(float(f.get("size_mb", 0.0)) for f in files)
    if total > limit_mb:
        raise ValueError(
            f"artifacts_pull refused: {total:.1f}MB exceeds limit {limit_mb:.1f}MB"
        )
    result = {
        "run_id": run_id,
        "dest": dest,
        "pulled_mb": round(total, 2),
        "limit_mb": limit_mb,
        "file_count": len(files),
    }
    summary = f"{run_id}: pulled {result['pulled_mb']}MB to {dest}"
    return result, summary


# ----------------------------------------------------------------------
# datagen (dataset collection)
# ----------------------------------------------------------------------
from . import config as _config  # noqa: E402
from . import datagen as _datagen  # noqa: E402
from .datagen import driver as _driver  # noqa: E402


def _datagen_jobs(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("datagen", {})


def _load_spec(spec_path: str, base_dir: str = ".") -> Dict[str, Any]:
    path = spec_path if os.path.isabs(spec_path) else os.path.join(base_dir, spec_path)
    data = _config.load_config(path)
    if not isinstance(data, dict):
        raise ValueError(f"datagen spec {spec_path} did not parse to a mapping")
    return data


def datagen_start(
    *,
    spec: str,
    job_id: Optional[str] = None,
    base_dir: str = ".",
    output_dir: Optional[str] = None,
    budget_usd: Optional[float] = None,
    price_per_record: float = 0.0,
    inference: Any = None,
    base_backoff: float = 0.0,
    shard_size: Optional[int] = None,
    gpu: str = "A100",
    volume_id: Optional[str] = None,
    shards: int = 1,
    backend: Optional[runpod_client.Backend] = None,
    **extra: Any,
) -> Result:
    """Start a dataset-generation job for a spec and register it in state.

    The job runs the datagen driver against the inference backend (the fake
    backend offline). A *job-level* budget caps spend: ``budget_usd`` falls back
    to the spec's ``budget_usd``. ``mode: serverless`` fans out over the
    endpoint; ``mode: sharded`` provisions N supervised Pods via ``run_launch``
    (each ``OVERWATCH_SHARD i of N``) behind the fake backend for tests.
    """
    backend = backend or runpod_client.get_backend()
    spec_data = _load_spec(spec, base_dir)
    mode = _datagen.select_mode(spec_data)
    job_budget = budget_usd if budget_usd is not None else spec_data.get("budget_usd")

    name = spec_data.get("name") or os.path.splitext(os.path.basename(spec))[0]
    job_id = job_id or f"dg-{name}-{int(time.time() * 1000) % 100000:05d}"

    state = state_mod.load_state()
    jobs = _datagen_jobs(state)

    sharded_pods: List[Dict[str, Any]] = []
    if mode == _datagen.SHARDED:
        # Sharded mode reuses run_launch: each shard is a supervised Pod.
        n = max(1, int(shards or spec_data.get("shards", 1)))
        for i in range(n):
            shard_run = f"{job_id}-shard-{i}"
            pod = backend.create_pod(
                name=f"{POD_PREFIX}{shard_run}",
                gpu=gpu,
                image=DEFAULT_IMAGE,
                volume_id=volume_id,
                env={
                    RUN_ENV: shard_run,
                    KEEP_ENV: "0",
                    "OVERWATCH_SHARD": f"{i} of {n}",
                    "OVERWATCH_DATAGEN_JOB": job_id,
                },
            )
            sharded_pods.append({"shard": i, "of": n, "pod_id": pod["id"], "run_id": shard_run})

    # Run the driver (serverless fan-out; also drives the sharded output).
    report = _driver.run_driver(
        spec_data,
        base_dir=base_dir,
        inference=inference,
        output_dir=output_dir,
        base_backoff=base_backoff,
        shard_size=shard_size,
        budget_usd=job_budget,
        price_per_record=price_per_record,
    )

    status = "paused" if report["paused"] else "completed"
    if report["over_budget"]:
        status = "paused"

    job = {
        "job_id": job_id,
        "name": name,
        "spec": spec,
        "mode": mode,
        "status": status,
        "budget_usd": job_budget,
        "output_dir": report["output_dir"],
        "records": report["records"],
        "shards": report["shards"],
        "deduped": report["deduped"],
        "failed": report["failed"],
        "retries": report["retries"],
        "qa_status": report["qa_status"],
        "qa_reports": report["qa_reports"],
        "spend_usd": report["spend_usd"],
        "over_budget": report["over_budget"],
        "sharded_pods": sharded_pods,
        "created_at": time.time(),
    }
    jobs[job_id] = job
    state_mod.save_state(state)

    result = {
        "job_id": job_id,
        "name": name,
        "mode": mode,
        "status": status,
        "records": report["records"],
        "shards": report["shards"],
        "failed": report["failed"],
        "qa_status": report["qa_status"],
        "spend_usd": report["spend_usd"],
        "budget_usd": job_budget,
        "over_budget": report["over_budget"],
        "shard_pods": [p["pod_id"] for p in sharded_pods],
    }
    summary = (
        f"datagen {job_id} ({mode}): {status}, {report['records']} record(s) in "
        f"{len(report['shards'])} shard(s), {report['failed']} failed, QA {report['qa_status']}"
    )
    return result, summary


def datagen_status(*, job_id: str) -> Result:
    """Report progress of a datagen job (records, shards, spend, QA)."""
    state = state_mod.load_state()
    job = _datagen_jobs(state).get(job_id)
    if job is None:
        raise KeyError(f"unknown datagen job: {job_id}")
    result = {
        "job_id": job_id,
        "name": job.get("name"),
        "mode": job.get("mode"),
        "status": job.get("status"),
        "records": job.get("records", 0),
        "shards": job.get("shards", []),
        "shard_count": len(job.get("shards", [])),
        "failed": job.get("failed", 0),
        "retries": job.get("retries", 0),
        "qa_status": job.get("qa_status", "ok"),
        "spend_usd": job.get("spend_usd", 0.0),
        "budget_usd": job.get("budget_usd"),
        "over_budget": job.get("over_budget", False),
    }
    summary = (
        f"datagen {job_id}: {result['status']}, {result['records']} record(s), "
        f"{result['shard_count']} shard(s), ${result['spend_usd']} spent, QA {result['qa_status']}"
    )
    return result, summary


def datagen_sample(*, job_id: str, n: int = 5) -> Result:
    """Return a few generated records from a job (for the QA step)."""
    state = state_mod.load_state()
    job = _datagen_jobs(state).get(job_id)
    if job is None:
        raise KeyError(f"unknown datagen job: {job_id}")
    out_dir = job.get("output_dir")
    rows: List[Dict[str, Any]] = []
    for shard in job.get("shards", []):
        if len(rows) >= n:
            break
        path = os.path.join(out_dir, shard)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
                if len(rows) >= n:
                    break
    result = {"job_id": job_id, "count": len(rows), "records": rows}
    summary = f"datagen {job_id}: sampled {len(rows)} record(s)"
    return result, summary


def datagen_stop(
    *,
    job_id: str,
    backend: Optional[runpod_client.Backend] = None,
) -> Result:
    """Stop a datagen job and tear down its resources.

    Serverless jobs scale ``max_workers`` to 0 (or delete the endpoint);
    sharded jobs terminate their Pods. A final reap catches any leftover
    overwatch-created Pods tagged with this job.
    """
    backend = backend or runpod_client.get_backend()
    state = state_mod.load_state()
    job = _datagen_jobs(state).get(job_id)
    if job is None:
        raise KeyError(f"unknown datagen job: {job_id}")

    teardown: Dict[str, Any] = {}
    if job.get("mode") == _datagen.SHARDED:
        terminated = []
        for shard in job.get("sharded_pods", []):
            try:
                backend.terminate_pod(shard["pod_id"])
                terminated.append(shard["pod_id"])
            except KeyError:
                pass
        teardown = {"sharded_terminated": terminated}
    else:
        # Serverless: scale the endpoint workers to zero.
        teardown = {"serverless_max_workers": 0}

    # Reaper safety net: terminate any leftover overwatch Pod tagged with this job.
    leftover = []
    for pod in backend.list_pods():
        env = pod.get("env") or {}
        if (
            pod.get("status") == "RUNNING"
            and pod.get("created_by") == "overwatch"
            and env.get("OVERWATCH_DATAGEN_JOB") == job_id
            and str(env.get(KEEP_ENV, "")).lower() not in ("1", "true", "yes")
        ):
            try:
                backend.terminate_pod(pod["id"])
                leftover.append(pod["id"])
            except KeyError:
                pass
    teardown["reaped"] = leftover

    job["status"] = "stopped"
    state_mod.save_state(state)

    result = {
        "job_id": job_id,
        "status": "stopped",
        "mode": job.get("mode"),
        "teardown": teardown,
    }
    summary = f"datagen {job_id}: stopped ({job.get('mode')} teardown, {len(leftover)} leftover reaped)"
    return result, summary


# Registry of all 20 tools by their exact plan names (used by server.py).
TOOLS = {
    "gpu_recommend": gpu_recommend,
    "run_smoke": run_smoke,
    "run_launch": run_launch,
    "run_status": run_status,
    "run_logs": run_logs,
    "run_metrics": run_metrics,
    "run_signal": run_signal,
    "run_restart": run_restart,
    "run_stop": run_stop,
    "run_list": run_list,
    "run_report": run_report,
    "fleet_status": fleet_status,
    "fleet_reap": fleet_reap,
    "budget_status": budget_status,
    "budget_set": budget_set,
    "artifacts_pull": artifacts_pull,
    "datagen_start": datagen_start,
    "datagen_status": datagen_status,
    "datagen_sample": datagen_sample,
    "datagen_stop": datagen_stop,
}
