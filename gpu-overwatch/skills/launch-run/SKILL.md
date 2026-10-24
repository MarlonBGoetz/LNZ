---
name: launch-run
description: Launch a supervised Runpod training run the safe way — preflight the config, size the GPU, smoke test, launch, then start the supervise-run workflow for the new run id.
---

# Launch a supervised training run

Use this skill to take a run config from "ready" to "supervised and healthy".
Never skip the smoke test: the guard blocks `run_launch`/`run_restart` without a
passed smoke (see `gpu-policy.md`).

## Steps

1. **Preflight the config.** Run `python -m overwatch.cli preflight <config>` (or
   let the `preflight-on-save` hook do it on save). Confirm the training script
   logs through `ow.log()`, checkpoints to `$OVERWATCH_CKPT_DIR`, resumes from
   the latest checkpoint and handles `SIGTERM` (see `training-contract.md`).
2. **Size the GPU.** Call `gpu_recommend` with the model size, method
   (full / LoRA / QLoRA / inference) and sequence length, or consult the
   `gpu-sizing` skill. Stay inside the `gpu_allowlist` from policy. Prefer an
   interruptible/spot GPU when checkpoints are frequent.
3. **Smoke test.** Call `run_smoke` to validate the image and config on a short
   run. Do not proceed unless it passes — the guard requires `smoke_passed`.
4. **Launch.** Call `run_launch` with the config and the sized GPU. The Pod is
   named `ow-<run>` and carries `OVERWATCH_RUN` / `OVERWATCH_KEEP`. Launch goes
   through the guard (budget cap, GPU allowlist, smoke required).
5. **Supervise.** Start the `supervise-run` workflow for the returned `run_id`.
   The `start-supervision` hook does this automatically after `run_launch`; the
   workflow watches, auto-heals via `gpu-medic` and writes a post-mortem.

## Checklist

- [ ] Preflight passed (contract satisfied).
- [ ] GPU sized and inside the allowlist; interruptible chosen if checkpoints are frequent.
- [ ] `run_smoke` passed.
- [ ] `run_launch` succeeded and returned a `run_id`.
- [ ] `supervise-run` is watching the new `run_id`.
