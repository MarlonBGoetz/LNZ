"""Dataset-collection (datagen) subpackage for gpu-overwatch.

This package implements the aggressive-inference dataset-collection path from
the plan: many short GPU calls fanned out over a Serverless endpoint (or a set
of sharded Pods), retried, deduplicated and written as atomic JSONL shards with
a manifest. The whole surface is testable offline against a deterministic
:class:`~overwatch.datagen.driver.FakeInference` backend selected when
``OVERWATCH_FAKE=1``.

Public API:

* :func:`~overwatch.datagen.driver.run_driver` -- run a job spec to completion
  (idempotent, resumable).
* :func:`~overwatch.datagen.driver.record_key` -- the idempotent record key.
* :func:`~overwatch.datagen.driver.get_inference` -- select the inference
  backend (fake vs real Serverless, import-guarded).
* :func:`select_mode` -- choose the serverless vs sharded execution mode.
"""

from __future__ import annotations

from typing import Any, Dict

SERVERLESS = "serverless"
SHARDED = "sharded"


def select_mode(spec: Dict[str, Any]) -> str:
    """Return the execution mode for a job spec.

    ``serverless`` fans out over a Serverless/Flash endpoint; ``sharded`` runs
    the job as N supervised Pods (each a shard, ``OVERWATCH_SHARD i of N``) and
    reuses ``run_launch``. The spec's ``mode`` key wins; anything unrecognised
    falls back to ``serverless``.
    """
    mode = str(spec.get("mode", SERVERLESS)).strip().lower()
    return mode if mode in (SERVERLESS, SHARDED) else SERVERLESS


from . import driver  # noqa: E402  (re-export after constants are defined)

__all__ = ["SERVERLESS", "SHARDED", "select_mode", "driver"]
