# On-pod pipeline (`pod/`)

These scripts run **inside** a gpu-overwatch Runpod H100 Pod, against the
mounted network volume `lhuwcwm7gb` at **`/workspace`**. They are the keyless
TRIBE v2 -> student stress-distillation teacher queue.

> **They do NOT run in the sandbox / CI.** Everything here except
> `verify_hashes.py` imports heavy GPU dependencies (`torch`, `transformers`,
> TRIBE, `huggingface_hub`). The gpu-overwatch pytest suite imports **only**
> `pod/verify_hashes.py` (pure stdlib) and never touches the `*_pipeline.py`
> drivers.

## Keyless by design

- **No SSH.** The Pod self-runs on boot via its container start command.
- **No GitHub token, no private-repo clone on the Pod.** Scripts are delivered
  onto the network volume via the Runpod S3 API (by the orchestrator, from the
  sandbox, before launch) and land at `/workspace/pod/`. A documented fallback
  can fetch them from a public URL (`OW_SCRIPTS_URL`).
- Secrets live under renamed env vars and are **never printed**.

## Layout on the volume (`/workspace`)

```
/workspace/
  pod/                      # these scripts, staged by the orchestrator
    bootstrap.sh            # keyless entrypoint (start command calls this)
    gpu_a_pipeline.sh/.py   # GPU-A: download -> verify -> TRIBE teacher queue
    gpu_b_pipeline.sh/.py   # GPU-B: student encoder smoke -> feature extraction
    verify_hashes.py        # pure-stdlib HARD-STOP sha256 gate
    expected_digests.json   # pinned sha256 for the two safetensors shards
  models/Llama-3.2-3B/      # downloaded weights (plain files, incl. LICENSE)
  hf_cache/                 # HF_HOME: TRIBE + encoders cache here once
  datasets/                 # teacher traces (datagen shards + manifest)
  reports/                  # Step 0 smoke + throughput benchmark report
  logs/                     # per-pipeline logs the orchestrator watches
```

## Start command (what the orchestrator passes as `docker_start_cmd`)

GPU A:

```
bash -lc 'OW_PIPELINE=gpu_a bash /workspace/pod/bootstrap.sh'
```

GPU B:

```
bash -lc 'OW_PIPELINE=gpu_b bash /workspace/pod/bootstrap.sh'
```

`run_launch(..., docker_start_cmd="bash -lc 'OW_PIPELINE=gpu_a bash /workspace/pod/bootstrap.sh'")`
threads this through `create_pod`. The REST field name
(`dockerStartCmd` vs `dockerArgs` vs `containerStartCommand`) is an
**assumption flagged in FEAT-002**; confirm against a live `create` before the
paid launch.

## GPU-A order (non-negotiable)

1. `pip install -U huggingface_hub`
2. `hf download unsloth/Llama-3.2-3B --revision d4446454d87d51aa42e1fb174f25acc5f8762331 --local-dir /workspace/models/Llama-3.2-3B` (plain files, no symlinks)
3. **HARD-STOP** sha256 verify via `verify_hashes.py` (abort nonzero on mismatch)
4. Assert the Llama 3.2 **LICENSE** file is kept next to the weights
5. Wire TRIBE via **config override only** (never edit TRIBE code):
   `TribeModel.from_pretrained("facebook/tribev2", config_update={"data.text_feature.model_name": "/workspace/models/Llama-3.2-3B"})`,
   full trimodal pathway. Set `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`
   **only after** TRIBE + encoders are cached under `/workspace/hf_cache`.
6. Step 0 smoke + throughput benchmark -> `/workspace/reports/`
7. Full teacher queue -> `/workspace/datasets/`

**No fake-teacher fallback.** If the real teacher/model path fails, the job
errors nonzero. The **ONNX export** and the **demo-clip teacher traces** are
explicitly **non-cuttable**.
