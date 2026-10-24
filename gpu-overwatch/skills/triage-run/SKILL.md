---
name: triage-run
description: Map each Supervision-loop event to the smallest safe action and the signal outcome (success vs a warning that needs a human decision).
---

# Triage a supervised run

When the supervision loop (`overwatch.watch`) reports **new-activity**, it
carries an `event`, a metric summary, a log tail and a `suggested_action`. Take
the **smallest** action that keeps the run healthy. Never raise a budget cap,
never delete a network volume, and never terminate or stop a Pod marked keep
(`OVERWATCH_KEEP`). When unsure, ask the human before acting.

Each row below maps a detector event to its smallest safe action and the
**signal outcome**: whether the loop should treat it as a success (handled,
keep supervising) or a warning (surface for a human decision).

| Event (`watch` result) | Smallest safe action | Signal outcome |
|------------------------|----------------------|----------------|
| `nan_or_inf_loss` | `run_restart(reason="nan")` — restart from the latest checkpoint at half LR. Honor the max-2-retries cap; if exhausted, stop and escalate. | **success** while retries remain; **warning** once the retry budget is exhausted. |
| `loss_divergence` | First `run_signal(checkpoint_now)` to protect progress, then alert. Only `run_restart` if divergence persists across polls. | **warning** — a human decides whether to restart or let it ride. |
| `cuda_oom` | `run_restart(reason="oom")` — restart from checkpoint with a halved micro-batch. | **success** — OOM has a deterministic remedy. |
| `stall` | `run_signal(checkpoint_now)`, then verify the process; if still no step after the next poll, `run_restart` from the last checkpoint. | **warning** — confirm the stall is real before restarting. |
| `preempt` | Re-provision: `run_restart` from the latest checkpoint onto a fresh Pod (same `run_id`). | **success** — preemption is expected; restarting is routine. |
| `eval_regression` | Alert only. Do **not** restart; keep training and surface the trend. | **warning** — a human decides whether to stop early. |
| `budget` (warn, 80%) | Alert and prepare to stop; `run_signal(checkpoint_now)` so a stop loses no progress. | **warning** — a human decides whether to extend scope (within caps) or stop. |
| `budget` (stop, 100%) | `run_stop` (graceful: checkpoint then stop). Never raise the cap to continue. | **success** — stopping at the cap is the correct, safe outcome. |
| `crash` | Inspect the log tail. If transient, `run_restart` from checkpoint; if the config is at fault, stop and escalate. | **warning** — confirm the cause before restarting. |

## Terminal states

When `watch` reports **terminal-state** (`finished`, `stopped`, `crashed`,
`idle_timeout`, ...), stop supervising and write a post-mortem with `run_report`
(the workflow does this automatically). Do not restart a run that finished
cleanly.

## Reminders

- Always `run_signal(checkpoint_now)` before any stop or restart so no progress
  is lost; signals use the run's per-run bearer token automatically.
- A restart keeps the **same** `run_id` mapped to a new Pod and records lineage;
  it counts against the budget and passes through the guard.
- If an action would raise a budget, delete a volume, or terminate a kept Pod,
  do not take it — ask the human.
