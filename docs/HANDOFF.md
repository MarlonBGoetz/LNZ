# Handoff: first live Runpod distillation run

Written Oct 24, 2026, for the next agent session on `Nathan-T-Ray/gpu-overwatch`.

## Goal

The user wants to use gpu-overwatch to boot Runpod GPUs and collect inference
data from a teacher model for distillation. The data must land on their Runpod
network volume.

## Where things stand

- `main` holds the full Power (94 files). `pytest -q tests/` gives 198 passed,
  offline, using only the Python standard library.
- **Nothing has ever run against real Runpod.** Every test uses the fake
  backend. The real code paths are partly unimplemented (see "Gaps" below).
  Treat this first live session as integration work, not "just run it".
- The previous session could not reach Runpod. Its network mode was
  `INTEGRATIONS_ONLY` and `RUNPOD_API_KEY` was not in its environment. The user
  says they have since added the key as a sandbox secret and opened network
  access. A new session was needed to pick that up.

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

## Gaps to fix before spending money

These were found by reading the code. They are not yet confirmed against the
live API.

1. **It silently falls back to fake.** `runpod_client.get_backend()` and
   `datagen.driver.get_inference()` return the *fake* backend if the key is
   missing or the SDK fails to load. A live run could then "succeed" on made-up
   data. When `RUNPOD_API_KEY` is set and `OVERWATCH_FAKE` is not `1`, make both
   raise an error instead. Add a check that prints which backend is active.
2. **`RealBackend` is incomplete** (`overwatch/runpod_client.py`).
   `create_pod` and `create_volume` raise `NotImplementedError`.
   `list_volumes` returns `[]`. `billing()` returns a spend rate of 0, so the
   budget guard would see $0 of live spend. Implement these with the runpod SDK
   or the REST API (`rest.runpod.io/v1`). The Pod must get the `ow-<run>` name,
   the `OVERWATCH_RUN` and `OVERWATCH_KEEP` env vars, the volume, and the
   sidecar token.
3. **Pod data doesn't match.** The tools expect Pod dicts with `status ==
   "RUNNING"`, `created_by == "overwatch"`, and `env` as a dict. Real Runpod
   data uses other fields (for example `desiredStatus`) and has no
   `created_by`. Without converting it, `fleet_status` labels every Pod as
   foreign, and `fleet_reap` and the session-end reaper find nothing to stop.
   Work out ownership from the `ow-` name prefix and the `OVERWATCH_RUN` env
   var.
4. **The GPU allowlist uses exact names.** `Policy.gpu_allowed` checks
   `gpu in ["A100", "H100"]`, but real Runpod GPU IDs look like
   `NVIDIA A100 80GB PCIe`. Map the short names to real IDs explicitly. Do not
   loosen the check.
5. **The Serverless request shape is a guess.** `_RealServerlessInference`
   sends `{"prompt", "model", "sampling"}` and reads `result["text"]`. Runpod's
   vLLM worker expects a different input (for example `sampling_params`) and
   returns a different output. Check the current Runpod worker-vllm docs. Store
   whatever the user wants kept (logprobs, for example). Also, the retry loop
   only catches `TransientError`. Real SDK, HTTP 429/5xx and timeout errors must
   be converted to `TransientError`, or one bad response kills the whole job.
6. **No endpoint exists yet.** Serverless mode needs `endpoint_id` in the spec
   or `RUNPOD_ENDPOINT_ID` in the environment, and no code creates one. Setting
   up a vLLM endpoint for the teacher model costs money. Show the GPU, worker
   cap and price first, and ask the user. Sharded mode depends on gap 2's
   `create_pod`.
7. **Packaging bug.** `pyproject.toml` lists only `overwatch` and
   `overwatch.sidecar` as packages, so a normal install leaves out
   `overwatch.datagen`. Add it.
8. **The sidecar has to get onto the Pod.** The base image
   (`runpod/pytorch:2.3.0-py3.11-cuda12.1`) doesn't include overwatch, and the
   repo is private. Decide how the Pod installs it, for example by copying the
   package onto the network volume. Never put a GitHub token on a Pod.

Fix these first and add tests for the conversion and error-handling logic.
Keep `pytest -q tests/` green.

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
