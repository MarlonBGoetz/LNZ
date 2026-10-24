---
name: gpu-sizing
description: Recommend a GPU type and count for a run from the model size, training method (full / LoRA / QLoRA / inference) and sequence length, preferring interruptible GPUs when checkpoints are frequent.
---

# Size the GPU for a run

Pick the smallest GPU type and count that fits the job, then stay inside the
`gpu_allowlist` in `.overwatch/policy.yaml`. When in doubt call `gpu_recommend`,
which applies the same table.

## Inputs

- **Model size** — parameter count (e.g. 7B, 13B, 70B).
- **Method** — `full`, `LoRA`, `QLoRA` or `inference`. QLoRA and LoRA cut memory
  sharply; full fine-tuning needs the most.
- **Sequence length** — longer context raises activation memory roughly linearly
  (quadratically without flash-attention); size up when it is large.
- **Batch / micro-batch** — larger batches need more memory or more GPUs.

## Procedure

1. Start from the model size and method row in
   [references/sizing-table.md](references/sizing-table.md).
2. Adjust for sequence length: bump the GPU tier (or add a GPU) when the context
   is long, drop it when it is short.
3. Choose count: single GPU until the model + activations no longer fit, then
   scale out (tensor/data parallel).
4. **Prefer interruptible (spot) GPUs when checkpoints are frequent** — the
   checkpoint cadence (every 15 min, see `gpu-policy.md`) makes preemption cheap
   to recover from, and interruptible capacity is cheaper. Use on-demand only
   when checkpoints are sparse or a deadline is hard.
5. Confirm the pick is inside the `gpu_allowlist` and within the per-run budget
   cap before launching.

See [references/sizing-table.md](references/sizing-table.md) for the full lookup.
