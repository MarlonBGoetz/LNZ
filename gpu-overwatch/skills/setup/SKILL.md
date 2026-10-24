---
name: setup
description: >-
  Guided, resumable setup for the gpu-overwatch Power. Run this when the fleet
  brief or `overwatch doctor` reports setup is incomplete, or when the user
  invokes /gpu-setup. Walks the 8 setup steps one concern at a time, skips steps
  that are already done, and never asks for the RUNPOD_API_KEY in chat.
---

# gpu-overwatch guided setup

This skill brings a workspace from "Power installed" to "ready to launch
supervised Runpod runs". It is **resumable** (finished steps are recorded in
`.overwatch/setup.json` and skipped on a rerun), **team-aware** (a teammate who
joins a project that already carries shared settings only runs the per-person
steps), and **honest** (anything that needs live Runpod is reported as needing
credentials, never faked).

## Before you start

1. Run the doctor first and read its JSON so you know what is already done:

   ```bash
   bash scripts/doctor.sh --json
   ```

   (That script shells to `python -m overwatch.cli doctor "$@"`.) Each check has
   a `status` (`ok`/`fail`) and, when failing, a concrete `fix` line. **Skip any
   step whose check is already `ok`.**

2. Ask the user **one question at a time**. Do not dump the whole checklist.
3. **Never ask for the API key in chat.** The key is read from the
   `RUNPOD_API_KEY` environment variable; tell the user to export it in their
   shell. Only the last 4 characters are ever shown.

You can let the CLI drive the whole flow with `overwatch init` (it records each
step in `setup.json`); use the steps below to explain and gate each concern.

## Steps 1-8

1. **Install the Power.** Confirm `~/.kiro/settings/mcp.json` has the `runpod`
   and `overwatch` MCP servers. Fix: install the gpu-overwatch Power in Kiro.
2. **API key + reachability (live).** Ask the user to export `RUNPOD_API_KEY`
   in their shell (never in chat). When a key and network are present, the CLI
   makes a read-only reachability call to Runpod; offline it reports "needs
   credentials" instead of faking success.
3. **Budget caps.** Confirm `session_cap_usd`, `per_run_cap_usd` and `max_hours`
   in `.overwatch/policy.yaml`. Caps may only be lowered, never raised.
4. **Datacenter + GPU allowlist (live stock).** Choose a real datacenter in
   `project.yaml` and confirm the GPU allowlist. The live stock check needs
   credentials + network; without them, record the choice and mark the live
   check as pending.
5. **Network volume (live create).** Create a Runpod network volume for
   checkpoints/artifacts and record its id as `runpod.volume_id` in
   `project.yaml`. Creating a volume needs credentials; never fabricate an id.
6. **Enable Workflows.** Kiro's Workflows toggle cannot be detected. **Ask the
   user to confirm** they enabled it, then record the confirmation.
7. **Free self-test (offline).** Run `overwatch selftest`. It starts a local
   sidecar wrapping `tests/fake_train.py --fail nan@300`, drives the watch to
   confirm the NaN is detected, and confirms the guard blocks an over-budget
   launch. The pass/fail is recorded in `setup.json`.
8. **Live smoke (live).** Run a real smoke (`run_smoke`) on a GPU once
   credentials are in place. This is never run offline; report it as needing
   credentials + a GPU.

## Finish

When the per-step work is done, **run the doctor again** to verify everything is
green:

```bash
bash scripts/doctor.sh
```

If any check still fails, read its `fix` line and resolve it, then rerun. When
all checks pass the workspace is ready to launch supervised runs.
