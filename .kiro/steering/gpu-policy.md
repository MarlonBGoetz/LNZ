---
inclusion: always
---

# GPU policy and cost guardrails

These rules always apply in a gpu-overwatch session. They mirror
`.overwatch/policy.yaml`; the numbers there are the source of truth and can only
ever be **lowered** by tools (`budget_set`), never raised. Editing `policy.yaml`
by hand is blocked by the guard.

## Budget caps

- **Session cap** (`session_cap_usd`, default $50): total spend across all live
  Pods in a session. The guard rejects a launch whose projected session spend
  would exceed this. Detectors warn at 80% and hard-stop at 100%.
- **Per-run cap** (`per_run_cap_usd`, default $20): projected cost of a single
  run (`price_per_hour × max_hours`). A launch over this cap is blocked.
- **Max wall-clock** (`max_hours`, default 8h): the sidecar self-stops at this
  limit even if the budget is not spent.

## GPU allowlist

Only GPUs in `gpu_allowlist` (default `[A100, H100]`) may be launched. A request
for any other GPU type is rejected by the guard. Size runs with the `gpu-sizing`
skill and prefer interruptible GPUs when checkpoints are frequent.

## Smoke before launch

Never launch (or restart) without a **passed smoke test**. `run_launch` and
`run_restart` require `smoke_passed`; the guard blocks a launch without it. Run
`run_smoke` first to validate the image and config on a short run.

## Checkpoint every 15 minutes

The sidecar checkpoints on a fixed cadence (`checkpoint_interval_seconds`,
default 900s = 15 min) and always checkpoints on `SIGTERM`. Frequent checkpoints
make preemption and restarts cheap, which is why interruptible GPUs are
preferred.

## Never destroy work

- **Never delete a network volume** — checkpoints and artifacts live there. The
  guard blocks volume deletes outright.
- **Never terminate or stop a kept Pod** — a Pod marked keep (`OVERWATCH_KEEP`)
  is protected. Reaping and stops skip kept Pods; the guard blocks an explicit
  terminate of one.

## Detector thresholds (tunable in policy.yaml)

Supervision detectors read their thresholds from `policy.yaml` so they can be
tuned without code changes. The defaults:

| Detector | Policy key(s) | Default | Meaning |
|----------|---------------|---------|---------|
| NaN loss | `nan_restart_lr_factor`, `nan_max_retries` | 0.5, 2 | On a NaN/Inf loss, restart from the last checkpoint at half the LR, at most 2 retries, then stop and escalate. |
| Divergence | `divergence_ema_rising_steps` | 200 | Loss EMA rising for this many steps is treated as divergence (checkpoint, then alert/restart). |
| OOM | `oom_microbatch_factor` | 0.5 | On CUDA OOM, restart from checkpoint with the micro-batch halved. |
| Stall | `stall_no_step_seconds`, `stall_util_floor_pct`, `stall_util_seconds` | 600s, 5%, 600s | No optimizer step for 10 min, or GPU utilisation below 5% for 10 min, is a stall (checkpoint, verify, restart if it persists). |
| Preemption | `preempt_missed_polls` | 3 | Three missed polls means the Pod was preempted; re-provision from the latest checkpoint. |
| Eval regression | `eval_regression_evals` | 3 | Eval metric worse for 3 evals in a row triggers an alert (no automatic restart). |
| Budget | `budget_warn_fraction`, `budget_stop_fraction` | 0.8, 1.0 | Warn at 80% of a cap, hard-stop (`run_stop`) at 100%. |
| Checkpoint | `checkpoint_interval_seconds` | 900 | Periodic checkpoint cadence (15 min). |

To tune a detector, lower or adjust the matching key in `.overwatch/policy.yaml`.
Budget caps may only be lowered, never raised.
