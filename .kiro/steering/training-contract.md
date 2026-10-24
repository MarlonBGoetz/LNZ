---
inclusion: fileMatch
fileMatchPattern: ["**/train*.py", "configs/**"]
---

# Training contract

Any training script supervised by gpu-overwatch must honor this contract so the
sidecar and detectors can watch, checkpoint and auto-heal the run. These rules
apply to training code (`**/train*.py`) and run configs (`configs/**`).

## Log through `ow.log()`

Emit metrics (loss, step, learning rate, throughput, eval scores) via
`ow.log()` from `overwatch.client`, not just to stdout. The sidecar reads these
structured metrics for the detectors (NaN, divergence, stall, eval regression).
Log on every optimizer step so progress and stalls are visible.

```python
from overwatch import client as ow

ow.log(step=step, loss=loss, lr=lr, tokens_per_sec=tps)
```

## Save to `$OVERWATCH_CKPT_DIR`

Write all checkpoints under the directory named by the `OVERWATCH_CKPT_DIR`
environment variable (the sidecar sets it to the run's volume path). Use
`ow.checkpoint()` so the sidecar knows the latest checkpoint for restarts and
artifact pulls. Checkpoint at least every 15 minutes (the sidecar also triggers
periodic checkpoints).

```python
ow.checkpoint(path=os.path.join(os.environ["OVERWATCH_CKPT_DIR"], f"step-{step}"))
```

## Resume from the latest checkpoint

On startup, look for an existing checkpoint under `$OVERWATCH_CKPT_DIR` and
resume from it if present. Restarts (NaN, OOM, preemption) reuse the **same**
`run_id` and expect the script to pick up from the latest checkpoint rather than
starting over.

## Handle `SIGTERM`

Install a `SIGTERM` handler that checkpoints and exits cleanly. The sidecar sends
`SIGTERM` for graceful stops, budget/max-hours self-stop, and preemption so no
progress is lost. Flush logs and the final checkpoint before exiting.

```python
import signal

def _on_term(signum, frame):
    ow.checkpoint(path=...)  # final checkpoint
    raise SystemExit(0)

signal.signal(signal.SIGTERM, _on_term)
```

## Configs

Run configs under `configs/` should pin the image, GPU request (inside the
allowlist), batch/micro-batch, sequence length and checkpoint directory so
`run_smoke`, `gpu_recommend` and the guard can validate them before launch.
