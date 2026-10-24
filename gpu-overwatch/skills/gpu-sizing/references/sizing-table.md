# GPU sizing table

A starting-point lookup by **model size** and **method**. Columns give a sane
default GPU **type** and **count** for a moderate sequence length (~2k–4k
tokens). Adjust up for long context or large batches, down for short context.
All picks must stay inside the `gpu_allowlist` in `.overwatch/policy.yaml`.

## Training

| Model size | Full fine-tune | LoRA | QLoRA |
|------------|----------------|------|-------|
| ≤ 3B | 1× A100 40GB | 1× A100 40GB | 1× A100 40GB |
| 7B | 2× A100 80GB | 1× A100 80GB | 1× A100 40GB |
| 13B | 4× A100 80GB | 1× A100 80GB | 1× A100 80GB |
| 34B | 8× A100 80GB / 4× H100 | 2× A100 80GB | 1× A100 80GB |
| 70B | 8× H100 | 4× A100 80GB / 2× H100 | 2× A100 80GB |
| 70B+ (MoE / >100B) | 8× H100 (multi-node) | 8× H100 | 4× A100 80GB |

## Inference / serving

| Model size | Method | GPU |
|------------|--------|-----|
| ≤ 7B | inference | 1× A100 40GB |
| 13B | inference | 1× A100 80GB |
| 34B | inference | 2× A100 80GB |
| 70B | inference | 2× H100 / 4× A100 80GB |

## Sequence-length adjustment

Activation memory grows with sequence length (roughly linear with
flash-attention, quadratic without). For long context (≥ 8k) move up one tier or
add a GPU; for short context (≤ 1k) you can often move down one tier.

| Sequence length | Adjustment |
|-----------------|------------|
| ≤ 1k | down one tier (optional) |
| 2k–4k | table default |
| 8k | up one tier or +1 GPU |
| 16k+ | up one tier and +1 GPU; enable flash-attention |

## Interruptible vs on-demand

Prefer **interruptible (spot)** capacity when checkpoints are frequent. With the
policy checkpoint cadence (every 15 minutes) a preemption costs at most ~15
minutes of progress, so the cheaper interruptible price is almost always worth
it. Use **on-demand** only when checkpoints are sparse, the run is short, or a
deadline leaves no room for a re-provision.
