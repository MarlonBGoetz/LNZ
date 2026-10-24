# Live pipeline runbook (orchestrator-run)

This runbook lists the **exact commands the orchestrator runs** to (a) stage the
on-pod scripts and datagen specs onto the network volume via the Runpod S3 API,
and (b) launch each H100 Pod with its keyless start command.

> **This task does NOT run any of these.** FEAT-004 is implementation + offline
> tests + docs only. Staging and launching are the **orchestrator's** job, after
> review. Do not create/launch a Pod, do not stage to the live volume, do not
> spend money from this task.

Keyless by design: there is **NO SSH**, **NO GitHub token on the Pod**, and **NO
private-repo clone on the Pod**. The Pod self-runs on boot via its container
start command, which executes `pod/bootstrap.sh` from the mounted network
volume (see `pod/README.md`).

## Facts for this run

| Thing            | Value |
|------------------|-------|
| Network volume   | `lhuwcwm7gb` (name `ow-distill-vol`, 200 GB), mounted at `/workspace` |
| Region / DC      | `US-MO-1` |
| Image            | `runpod/pytorch:1.4.1-cu1290-torch291-ubuntu2404` |
| GPU              | `H100` (secure on-demand, $3.99/hr per H100) |
| Per-run cap      | `$20` (read-only in `.overwatch/policy.yaml`) |
| Target run       | focused ~2h |

Secrets live under renamed env vars and must **never be echoed** into logs,
commands, or committed files:

- `RUNPOD_API_KEY` — Runpod REST API key (used by `run_launch`).
- `RUNPOD_API_KEY_S3_ACCESS_KEY` / `RUNPOD_API_KEY_S3_SECRET_ACCESS_KEY` — the
  S3-compatible credentials for the network-volume S3 endpoint.

---

## (a) STAGE `pod/` and `datagen/` onto volume `lhuwcwm7gb` (Runpod S3 API)

Runpod exposes each network volume over an S3-compatible endpoint, addressed by
datacenter. For `US-MO-1` the endpoint is:

```
https://s3api-us-mo-1.runpod.io
```

The volume id `lhuwcwm7gb` is the **bucket** name. Objects uploaded under a
prefix land at that path under the mount, so uploading to `s3://lhuwcwm7gb/pod/`
makes the files appear at `/workspace/pod/` once the Pod mounts the volume.

Source the renamed S3 credentials into the AWS CLI's env vars **without echoing
their values** (no `echo`, no `set -x`). Run from the repo root in the sandbox:

```bash
# Map the renamed secrets into the names the AWS CLI reads. These are read from
# the already-exported env; their values are never printed.
export AWS_ACCESS_KEY_ID="${RUNPOD_API_KEY_S3_ACCESS_KEY:?missing S3 access key}"
export AWS_SECRET_ACCESS_KEY="${RUNPOD_API_KEY_S3_SECRET_ACCESS_KEY:?missing S3 secret}"
export AWS_DEFAULT_REGION="US-MO-1"

ENDPOINT="https://s3api-us-mo-1.runpod.io"
VOL="lhuwcwm7gb"

# Stage the on-pod scripts -> /workspace/pod/
aws s3 sync ./pod "s3://${VOL}/pod/" \
  --endpoint-url "${ENDPOINT}" \
  --exclude ".gitkeep"

# Stage the datagen specs + example manifest + rubric -> /workspace/datagen/
aws s3 sync ./datagen "s3://${VOL}/datagen/" \
  --endpoint-url "${ENDPOINT}" \
  --exclude ".gitkeep"
```

Single-file form (equivalent, if you prefer `cp` per file):

```bash
aws s3 cp ./pod/bootstrap.sh          "s3://${VOL}/pod/bootstrap.sh"          --endpoint-url "${ENDPOINT}"
aws s3 cp ./pod/gpu_a_pipeline.sh     "s3://${VOL}/pod/gpu_a_pipeline.sh"     --endpoint-url "${ENDPOINT}"
aws s3 cp ./pod/gpu_a_pipeline.py     "s3://${VOL}/pod/gpu_a_pipeline.py"     --endpoint-url "${ENDPOINT}"
aws s3 cp ./pod/gpu_b_pipeline.sh     "s3://${VOL}/pod/gpu_b_pipeline.sh"     --endpoint-url "${ENDPOINT}"
aws s3 cp ./pod/gpu_b_pipeline.py     "s3://${VOL}/pod/gpu_b_pipeline.py"     --endpoint-url "${ENDPOINT}"
aws s3 cp ./pod/verify_hashes.py      "s3://${VOL}/pod/verify_hashes.py"      --endpoint-url "${ENDPOINT}"
aws s3 cp ./pod/expected_digests.json "s3://${VOL}/pod/expected_digests.json" --endpoint-url "${ENDPOINT}"
aws s3 cp ./datagen/teacher-queue-v1.yaml "s3://${VOL}/datagen/teacher-queue-v1.yaml" --endpoint-url "${ENDPOINT}"
aws s3 cp ./datagen/qa_rubric_teacher.md  "s3://${VOL}/datagen/qa_rubric_teacher.md"  --endpoint-url "${ENDPOINT}"
```

### Clip manifest (real, large — staged on the volume, NOT committed)

The committed `datagen/teacher-queue-inputs.example.jsonl` only shows the
**record shape** (`id`, `tier`, `dataset`, `path`). The real queue manifest is
assembled on the volume in tier order and uploaded to the path the spec's
`input` points at (`/workspace/datagen/teacher-queue-inputs.jsonl`):

```bash
# Assemble tier-ordered manifest on the volume, then upload it:
#   tier 1: demo clips (NON-CUTTABLE) + TikHarm
#   tier 2: [LIRIS-ACCEDE at the FRONT if/when staged] + XD-Violence (<=300)
aws s3 cp ./teacher-queue-inputs.jsonl "s3://${VOL}/datagen/teacher-queue-inputs.jsonl" \
  --endpoint-url "${ENDPOINT}"
```

Do **not** wait for LIRIS-ACCEDE; prepend its records to the tier-2 segment only
if/when they land on the volume (see the commented placeholder in the example
manifest and in `datagen/teacher-queue-v1.yaml`).

#### GPU-B consumes the same manifest

GPU-B does **not** have its own separate input file. Its student-encoder feature
extraction (`pod/gpu_b_pipeline.py`) reads the **same** tier-ordered clip
manifest that the GPU-A teacher queue runs against —
`/workspace/datagen/teacher-queue-inputs.jsonl` — so the orchestrator stages
that one manifest (step above) and both Pods consume it. GPU-B is **fail-closed**:
if the manifest is missing it raises `FileNotFoundError` and the run aborts
(it never fabricates features). There is no `/workspace/inputs/` staging step.

Verify the upload (lists keys only, no secret values):

```bash
aws s3 ls "s3://${VOL}/pod/"     --endpoint-url "${ENDPOINT}"
aws s3 ls "s3://${VOL}/datagen/" --endpoint-url "${ENDPOINT}"
```

---

## (b) LAUNCH each Pod via `run_launch` with its start command

The exact start-command strings come from `pod/README.md` / `pod/bootstrap.sh`:

- **GPU A:** `bash -lc 'OW_PIPELINE=gpu_a bash /workspace/pod/bootstrap.sh'`
- **GPU B:** `bash -lc 'OW_PIPELINE=gpu_b bash /workspace/pod/bootstrap.sh'`

Smoke must pass first (`run_smoke`), then launch. Example calls:

```python
from overwatch import tools

# Pod A — TRIBE teacher queue (download -> verify -> teacher traces).
tools.run_launch(
    config="teacher-queue-v1",
    run_id="run-gpu-a",
    gpu="H100",
    smoke_passed=True,
    budget=16,
    max_hours=2,                       # 3.99 * 2 = 7.98 <= 20 (per-run cap)
    volume_id="lhuwcwm7gb",
    image="runpod/pytorch:1.4.1-cu1290-torch291-ubuntu2404",
    docker_start_cmd="bash -lc 'OW_PIPELINE=gpu_a bash /workspace/pod/bootstrap.sh'",
)

# Pod B — student encoder smoke + feature extraction.
tools.run_launch(
    config="teacher-queue-v1",
    run_id="run-gpu-b",
    gpu="H100",
    smoke_passed=True,
    budget=16,
    max_hours=2,
    volume_id="lhuwcwm7gb",
    image="runpod/pytorch:1.4.1-cu1290-torch291-ubuntu2404",
    docker_start_cmd="bash -lc 'OW_PIPELINE=gpu_b bash /workspace/pod/bootstrap.sh'",
)
```

After launch, watch via the Runpod API + logs (`/workspace/logs/`), not SSH.

### Budget math (stay under the $20 per-run cap)

The guard enforces `price_per_hour * max_hours <= per_run_cap`:

```
$3.99/hr * max_hours <= $20   =>   max_hours <= ~5.01h
```

Target a focused **~2h** run: `$3.99 * 2 = $7.98 <= $20` per Pod, with headroom.
Two Pods running concurrently is `$7.98/hr` combined; keep the session cap
($50) in mind if both run for their full window.

### Start-command field assumption (UNVERIFIED LIVE — confirm first)

`run_launch` threads `docker_start_cmd` through `create_pod`, which sends it to
the Runpod REST `PodCreateInput` under the field **`dockerStartCmd`**. The exact
live field name (`dockerStartCmd` vs `dockerArgs` vs `containerStartCommand`)
could **NOT** be verified live in this work. Before the paid launch, the
orchestrator **MUST** confirm the field against a live `create` (e.g. a throwaway
create or the current Runpod REST schema) and adjust
`overwatch/runpod_client.py` if the field differs. If the start command is not
honored, the Pod boots idle and burns budget without running the pipeline.
