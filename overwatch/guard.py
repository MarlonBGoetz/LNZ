"""Safety guard (layers 2 and 3 of the plan's six guardrail layers).

The same pure checks are used two ways:

* **In-tool (layer 2):** :func:`check` is imported by ``run_launch`` /
  ``run_restart`` (and friends) and raises :class:`GuardError` before any
  risky Runpod action is taken.
* **PreToolUse hook (layer 3):** :func:`main` reads a tool-call event as JSON
  on **stdin**, runs the same checks, and on a block writes the reason to
  **stderr** and exits non-zero (which tells Kiro to block the call). An
  allowed call exits ``0``.

Blocked categories (all six):

1. Over-budget launches (per-run cap or remaining session cap exceeded).
2. Disallowed GPUs (not in ``policy.gpu_allowlist``).
3. Deletes of network volumes.
4. ``terminate`` / ``stop`` of a Pod marked keep (``OVERWATCH_KEEP``).
5. Launches without a passed smoke test.
6. Agent edits to ``policy.yaml`` (caps must only move via ``budget_set``).

The guard reads ``policy.yaml`` and ``state.json`` via the existing modules.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

from . import state as state_mod
from .policy import Policy


class GuardError(Exception):
    """Raised by :func:`check` when a tool call must be blocked.

    ``category`` is a short machine code for the violated rule.
    """

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


# Guard categories.
OVER_BUDGET = "over_budget"
DISALLOWED_GPU = "disallowed_gpu"
VOLUME_DELETE = "volume_delete"
KEEP_POD = "keep_pod"
NO_SMOKE = "no_smoke"
POLICY_EDIT = "policy_edit"


def _running_spend_rate(state: Dict[str, Any]) -> float:
    """Sum price/hour of runs that are currently live."""
    total = 0.0
    for run in state_mod.list_runs(state):
        if run.get("status") in ("running", "launching", "pending"):
            total += float(run.get("price_per_hour") or 0.0)
    return total


def _is_policy_path(path: Optional[str]) -> bool:
    if not path:
        return False
    norm = os.path.normpath(str(path))
    return os.path.basename(norm) == "policy.yaml"


def check(
    event: Dict[str, Any],
    *,
    policy: Optional[Policy] = None,
    state: Optional[Dict[str, Any]] = None,
) -> None:
    """Run every guard check for a tool-call ``event``; raise on a block.

    ``event`` shape (a normalised tool call)::

        {
            "tool": "run_launch" | "run_stop" | "fleet_reap" | "fs_write" | ...,
            "args": { ... tool arguments ... },
        }

    Pass ``policy`` / ``state`` to avoid re-reading from disk (the in-tool
    callers already hold them). Missing ones are loaded.
    """
    policy = policy if policy is not None else Policy.load()
    state = state if state is not None else state_mod.load_state()

    tool = event.get("tool") or event.get("name") or ""
    args = event.get("args") or event.get("arguments") or event.get("input") or {}
    if not isinstance(args, dict):
        args = {}

    # --- 6. Agent edits to policy.yaml ---
    # Any file-writing tool targeting policy.yaml is blocked.
    if tool in ("fs_write", "str_replace", "edit", "write", "create", "fsWrite", "fsReplace"):
        target = args.get("path") or args.get("file") or args.get("filePath")
        if _is_policy_path(target):
            raise GuardError(
                POLICY_EDIT,
                "editing policy.yaml directly is blocked; lower caps via budget_set",
            )

    # --- 3. Volume deletes ---
    if tool in ("delete_volume", "volume_delete") or (
        tool == "artifacts_pull" and args.get("delete_volume")
    ):
        raise GuardError(
            VOLUME_DELETE,
            "deleting a network volume is blocked (checkpoints/artifacts live there)",
        )

    # --- 4. terminate / stop of a keep Pod ---
    if tool in ("run_stop", "terminate_pod", "stop_pod", "fleet_reap"):
        if _targets_keep_pod(tool, args, state):
            raise GuardError(
                KEEP_POD,
                "refusing to stop/terminate a Pod marked keep (OVERWATCH_KEEP)",
            )

    # --- launch-specific checks (run_launch / run_restart) ---
    if tool in ("run_launch", "run_restart"):
        gpu = args.get("gpu")
        # 2. Disallowed GPU.
        if gpu and not policy.gpu_allowed(gpu):
            raise GuardError(
                DISALLOWED_GPU,
                f"GPU {gpu!r} is not in the allowlist {policy.gpu_allowlist}",
            )
        # 5. Launch without a passed smoke test.
        if not _smoke_passed(args):
            raise GuardError(
                NO_SMOKE,
                "refusing to launch without a passed smoke test (run_smoke first)",
            )
        # 1. Over-budget launch.
        price = float(args.get("price_per_hour") or 0.0)
        max_hours = float(args.get("max_hours") or policy.max_hours)
        run_cost = price * max_hours
        if run_cost > policy.per_run_cap_usd + 1e-9:
            raise GuardError(
                OVER_BUDGET,
                f"projected run cost ${run_cost:.2f} exceeds per-run cap "
                f"${policy.per_run_cap_usd:.2f}",
            )
        projected_rate = _running_spend_rate(state) + price
        projected_session = projected_rate * max_hours
        if projected_session > policy.session_cap_usd + 1e-9:
            raise GuardError(
                OVER_BUDGET,
                f"projected session spend ${projected_session:.2f} exceeds session "
                f"cap ${policy.session_cap_usd:.2f}",
            )


def _smoke_passed(args: Dict[str, Any]) -> bool:
    val = args.get("smoke_passed")
    if val is None:
        val = args.get("smoke")
    return bool(val)


def _targets_keep_pod(tool: str, args: Dict[str, Any], state: Dict[str, Any]) -> bool:
    """Whether a stop/terminate targets a keep-marked Pod."""
    # fleet_reap never acts on keep Pods by construction; the guard still
    # blocks an explicit reap that names a keep Pod.
    run_id = args.get("run_id")
    pod = args.get("pod") or args.get("pod_id")

    if run_id:
        run = state_mod.get_run(state, run_id)
        if run and _run_is_keep(run):
            # A plain stop (status change) is allowed; terminate is not.
            if tool == "run_stop" and args.get("terminate"):
                return True
            if tool in ("terminate_pod",):
                return True
            # stop_pod / fleet_reap on a keep run: block termination intent.
            if tool in ("stop_pod", "fleet_reap") and args.get("terminate", True):
                return True
    if pod:
        # Pod dict carrying env OVERWATCH_KEEP.
        if isinstance(pod, dict):
            env = pod.get("env") or {}
            if str(env.get("OVERWATCH_KEEP", "")).lower() in ("1", "true", "yes"):
                return True
    return False


def _run_is_keep(run: Dict[str, Any]) -> bool:
    if run.get("keep"):
        return True
    env = run.get("env") or {}
    return str(env.get("OVERWATCH_KEEP", "")).lower() in ("1", "true", "yes")


def main(argv: Optional[list] = None) -> int:
    """PreToolUse hook entrypoint: read event JSON on stdin, block via exit code.

    Returns ``0`` to allow the call and ``1`` to block it (writing the reason to
    stderr). Never raises for an ordinary block.

    ``--require-smoke-passed`` makes the smoke-test requirement explicit for
    ``run_launch`` / ``run_restart`` events: the call is blocked unless the
    event carries a truthy ``smoke_passed`` (the ``guard-launch`` hook passes
    this flag). :func:`check` already enforces the same rule for those tools, so
    the flag tightens intent rather than loosening it.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    require_smoke = "--require-smoke-passed" in argv

    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"guard: invalid event JSON: {exc}\n")
        return 1
    try:
        check(event)
    except GuardError as exc:
        sys.stderr.write(f"BLOCKED [{exc.category}]: {exc.message}\n")
        return 1

    if require_smoke:
        tool = event.get("tool") or event.get("name") or ""
        if tool in ("run_launch", "run_restart"):
            args = event.get("args") or event.get("arguments") or event.get("input") or {}
            if not isinstance(args, dict) or not _smoke_passed(args):
                sys.stderr.write(
                    f"BLOCKED [{NO_SMOKE}]: --require-smoke-passed: "
                    f"{tool} requires a passed smoke test\n"
                )
                return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
