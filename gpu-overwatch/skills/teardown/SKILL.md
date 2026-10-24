---
name: teardown
description: Wind down a GPU session safely — check the fleet, sync artifacts off the Pods, reap idle Pods, and write run and session reports.
---

# Tear down a GPU session

Use this skill at the end of a session (or when a run finishes) to stop paying
for idle GPUs without losing any work. Never delete a network volume and never
terminate a Pod marked keep (`OVERWATCH_KEEP`); the guard enforces both.

## Steps

1. **Check the fleet.** Call `fleet_status` to see every live Pod, its run, age,
   utilisation and spend. Identify which runs are finished, idle, or still
   working. Cross-check `budget_status` for session and per-run spend vs caps.
2. **Sync artifacts.** For any run you are about to stop, call `artifacts_pull`
   to copy checkpoints/artifacts off the Pod's volume first. Confirm the pull
   succeeded before stopping — the volume itself is never deleted here.
3. **Reap idle Pods.** Call `fleet_reap` (or `python -m overwatch.cli reap
   --idle-minutes 10`) to stop/destroy orphaned or idle Pods. Kept Pods
   (`OVERWATCH_KEEP`) are skipped. The `reap-on-stop` hook offers this on session
   Stop with a confirm prompt; the `session-summary` hook reaps on SessionEnd.
4. **Write reports.** Call `run_report` for each finished run (a Markdown report
   lands in `.overwatch/reports/<run>.md`) and capture a session summary of what
   ran, what fired and the total spend.

## Checklist

- [ ] `fleet_status` reviewed; idle/finished runs identified.
- [ ] Artifacts pulled for every run about to stop.
- [ ] Idle Pods reaped; kept Pods and volumes untouched.
- [ ] `run_report` written for finished runs; session spend summarised.
