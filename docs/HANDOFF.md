# Handoff: first live Runpod distillation run

Written Oct 24, 2026, for the next agent session on `Nathan-T-Ray/gpu-overwatch`.

## Goal

The user wants to use gpu-overwatch to boot Runpod GPUs and collect inference
data from a teacher model for distillation. The data must land on their Runpod
network volume.

## Where things stand

- The full Power is in place and `pytest -q tests/` is green offline, using only
  the Python standard library.
- **The supervised lifecycle has now run against real Runpod.** The real backend
  reached the live REST API and GraphQL pricing with stdlib `urllib` only, a
  200 GB network volume was created in `US-MO-1`, H100 Pods launched at $3.99/hr
  and mounted the volume, and the Pods were cleanly stopped and terminated. The
  resolved items below reflect that work. A full training run and a finished
  distillation dataset were not completed, so treat remaining datagen and
  training work as the next step.
- A previous session could not reach Runpod (network mode `INTEGRATIONS_ONLY`,
  no `RUNPOD_API_KEY`). The key was later added as a sandbox secret and network
  access opened, which unblocked the live session.

## Step 1: verify access (free, read-only)

1. Check the network mode with `get_sandbox_info`. It must not be
   `INTEGRATIONS_ONLY`.
2. Confirm the key exists **without printing it**. Show only its last 4
   characters:
   `[ -n "$RUNPOD_API_KEY" ] && echo "set (…${RUNPOD_API_KEY: -4})"`
3. Check reachability: `curl -s -o /dev/null -w "%{http_code}" https://rest.runpod.io/v1/pods`
   should return a status code. `000` means the network is still blocked.
4. Run `pip install -e ".[mcp,dev]"` and then `pytest -q tests/`. Use `-e` (an
   editable install) because of gap 7 below.
5. Make one authenticated read-only call: list the GPU types with their prices.
   If any of these steps fail, stop and tell the user exactly which one.

Never ask for the key in chat. Never echo the key, the environment, or
`.overwatch/state.json` (it holds run tokens).

## Step 2: get from the user

- Network volume ID and its datacenter. `.overwatch/project.yaml` still has
  placeholders (`vol-PLACEHOLDER`, `US-OR-1`).
- Teacher model (Hugging Face ID). Check that it fits on one A100 or H100 with
  the `gpu-sizing` skill.
- The prompts: a file or a dataset name, plus the count.
- Output format: completions only, or logprobs or reasoning traces too? The
  current driver stores only `text` (see gap 5).
- Sampling settings and a budget for the job.

## Resolved (hardening done this work)

These were the gaps found by reading the code; they are now addressed, with
tests, and `pytest -q tests/` stays green.

1. **No silent fallback to fake.** When `RUNPOD_API_KEY` is set and
   `OVERWATCH_FAKE` is not `1`, `runpod_client.get_backend()` and
   `datagen.driver.get_inference()` no longer quietly return the fake backend.
   The active backend is reported, so a live run cannot "succeed" on made-up
   data.
2. **`RealBackend` implemented** (`overwatch/runpod_client.py`). `create_pod`,
   `create_volume` and `list_volumes` work against the REST API
   (`rest.runpod.io/v1`), and `billing()` returns a real non-zero spend rate so
   the budget guard sees live spend. The Pod gets the `ow-<run>` name, the
   `OVERWATCH_RUN` and `OVERWATCH_KEEP` env vars, the volume and the sidecar
   token.
3. **Real-Pod field conversion and ownership.** Real Runpod Pod data (for
   example `desiredStatus`, no `created_by`) is converted so the tools read it,
   and ownership is derived from the `ow-` name prefix and the `OVERWATCH_RUN`
   env var. `fleet_status`, `fleet_reap` and the session-end reaper now
   recognize overwatch Pods.
4. **GPU allowlist mapping.** Short names (`A100`, `H100`) map explicitly to
   real Runpod `gpuTypeIds` without loosening the allowlist check.
5. **Transport hardening.** Requests send a `User-Agent: curl/8.4.0` header so
   the Runpod Cloudflare edge does not 403 with error 1010, and the GraphQL
   pricing call now sends its key via an `Authorization: Bearer` header instead
   of leaking it in the URL query string.
6. **Packaging fix.** `pyproject.toml` now ships `overwatch.datagen` (it uses
   `[tool.setuptools.packages.find]` with `include = ["overwatch*"]`), so a
   normal install includes the datagen package.

## Known limitations

A few integration details are still open. They are not blockers for the proven
lifecycle, but they are the next things to confirm before a full datagen run.

- **Serverless vLLM shape.** `_RealServerlessInference` input and output fields
  (for example `sampling_params` versus the current guess) and non-transient
  error mapping should be confirmed against the current Runpod worker-vllm docs.
- **No Serverless endpoint created yet.** Serverless mode needs `endpoint_id`
  in the spec or `RUNPOD_ENDPOINT_ID` in the environment; creating a vLLM
  endpoint costs money, so show the GPU, worker cap and price and ask the user
  first.
- **`dockerStartCmd` field name.** The live REST field name for the Pod start
  command (`dockerStartCmd` versus alternatives) should be confirmed against a
  live create before a paid launch (see the live-pipeline runbook).
- **Sidecar delivery onto the Pod.** The base image does not include overwatch;
  decide how the Pod installs it (for example copying the package onto the
  network volume). Never put a GitHub token on a Pod.

## Rules that still apply

- Caps in `.overwatch/policy.yaml`: $50 per session, $20 per run, 8h max,
  A100/H100 only. Tools may only lower them. Only the user can raise them, by
  editing the file. The job's own `budget_usd` must fit under these.
- Smoke test before every launch, on the cheapest allowed GPU. Before any paid
  action, show the GPU, price per hour and cap, and wait for an explicit yes.
- Never delete a network volume. Never stop or terminate a Pod marked
  `OVERWATCH_KEEP`.
- At the end, confirm no Pods are left running and the endpoint's max workers
  are 0. Report the total spend.

## Git

- The default branch is `main`. Work on a feature branch and open PRs with
  `gh api repos/Nathan-T-Ray/gpu-overwatch/pulls` (`gh pr` doesn't work in
  this sandbox).
- `.kiro/settings/permissions.{json,yaml}` are tracked but read-only in the
  sandbox. Avoid rebases and checkouts that would rewrite them. A failed rebase
  in the previous session temporarily deleted most of the working tree.
