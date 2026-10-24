"""In-training-process client: ``ow.log()`` and ``ow.checkpoint()``.

A training script imports this module and calls :func:`log` once per step and
:func:`checkpoint` when it writes a checkpoint. Both append newline-delimited
JSON records to a metrics file that the sidecar tails. Everything here is pure
standard library so it imports inside any training container without extra
dependencies.

Environment variables (all optional, with safe fallbacks):

* ``OVERWATCH_METRICS`` -- explicit path to the metrics ndjson file.
* ``OVERWATCH_CKPT_DIR`` -- directory holding the run's files; when
  ``OVERWATCH_METRICS`` is unset the metrics file defaults to
  ``<OVERWATCH_CKPT_DIR>/metrics.ndjson``.
* ``OVERWATCH_RUN`` -- the run id, stamped into every record.

Record shapes (one compact JSON object per line)::

    {"type": "metric", "run": "...", "step": 1, "loss": 1.23, "ts": 1.0, ...}
    {"type": "checkpoint", "run": "...", "path": "ckpt/step100", "step": 100, "ts": 1.0}

Records are flushed immediately so a tailing reader sees them with minimal
latency, and each write is a single ``line + "\n"`` so a reader never sees a
partial record.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional

RUN_ENV = "OVERWATCH_RUN"
METRICS_ENV = "OVERWATCH_METRICS"
CKPT_DIR_ENV = "OVERWATCH_CKPT_DIR"

DEFAULT_METRICS_NAME = "metrics.ndjson"

_write_lock = threading.Lock()


def run_id() -> Optional[str]:
    """Return the current run id from the environment, if any."""
    return os.environ.get(RUN_ENV)


def metrics_path() -> str:
    """Resolve the metrics ndjson path from the environment.

    Precedence: ``OVERWATCH_METRICS`` wins; otherwise fall back to
    ``<OVERWATCH_CKPT_DIR>/metrics.ndjson``; otherwise ``./metrics.ndjson``.
    """
    explicit = os.environ.get(METRICS_ENV)
    if explicit:
        return explicit
    ckpt_dir = os.environ.get(CKPT_DIR_ENV)
    if ckpt_dir:
        return os.path.join(ckpt_dir, DEFAULT_METRICS_NAME)
    return DEFAULT_METRICS_NAME


def _emit(record: Dict[str, Any]) -> None:
    """Append one compact JSON record (newline-delimited) to the metrics file."""
    record.setdefault("run", run_id())
    record.setdefault("ts", time.time())
    line = json.dumps(record, separators=(",", ":"), sort_keys=False)
    target = metrics_path()
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with _write_lock:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def log(step: int, loss: Optional[float] = None, **metrics: Any) -> Dict[str, Any]:
    """Record a training step.

    ``step`` and ``loss`` are first-class; any additional keyword metrics
    (``lr``, ``grad_norm``, ``tokens``, ...) are stored alongside. Returns the
    record that was written (useful in tests).
    """
    record: Dict[str, Any] = {"type": "metric", "step": int(step)}
    if loss is not None:
        record["loss"] = float(loss)
    for key, value in metrics.items():
        record[key] = value
    _emit(record)
    return record


def checkpoint(path: str, step: Optional[int] = None, **extra: Any) -> Dict[str, Any]:
    """Record that a checkpoint was written at ``path``.

    Returns the record written.
    """
    record: Dict[str, Any] = {"type": "checkpoint", "path": str(path)}
    if step is not None:
        record["step"] = int(step)
    for key, value in extra.items():
        record[key] = value
    _emit(record)
    return record
