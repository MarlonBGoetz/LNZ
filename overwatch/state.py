"""Run registry stored at ``.overwatch/state.json``.

The state store tracks every supervised run (its Pod, status, price, bearer
token, budget, checkpoints and lineage). It holds secrets (per-run bearer
tokens), so the file is gitignored and listed in ``.kiroignore``.

Writes are atomic: the store is written to a temp file and ``os.replace``'d
into place so a crash never leaves a half-written ``state.json``.

The default path is ``.overwatch/state.json`` relative to the current working
directory; tests override it via the ``OVERWATCH_STATE`` environment variable.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from typing import Any, Dict, List, Optional

DEFAULT_STATE_PATH = os.path.join(".overwatch", "state.json")
STATE_ENV = "OVERWATCH_STATE"


def state_path() -> str:
    """Resolve the state file path, honouring ``OVERWATCH_STATE``."""
    return os.environ.get(STATE_ENV, DEFAULT_STATE_PATH)


def _empty_state() -> Dict[str, Any]:
    return {"version": 1, "runs": {}, "session": {"spend_usd": 0.0}}


def load_state(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the state store, returning an empty structure if none exists."""
    target = path or state_path()
    if not os.path.exists(target):
        return _empty_state()
    with open(target, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    # Normalise to guarantee the expected shape.
    data.setdefault("version", 1)
    data.setdefault("runs", {})
    data.setdefault("session", {"spend_usd": 0.0})
    return data


def save_state(state: Dict[str, Any], path: Optional[str] = None) -> None:
    """Atomically persist the state store (temp write + ``os.replace``)."""
    target = path or state_path()
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def new_bearer_token() -> str:
    """Generate a per-run bearer token for the sidecar."""
    return secrets.token_urlsafe(32)


def new_run(
    run_id: str,
    *,
    pod_id: Optional[str] = None,
    status: str = "pending",
    price_per_hour: float = 0.0,
    bearer: Optional[str] = None,
    budget: Optional[float] = None,
    max_hours: Optional[float] = None,
    parent: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a run-registry record with the documented schema."""
    return {
        "run_id": run_id,
        "pod_id": pod_id,
        "status": status,
        "price_per_hour": float(price_per_hour),
        "bearer": bearer or new_bearer_token(),
        "budget": budget,
        "max_hours": max_hours,
        "lineage": {"parent": parent, "children": []},
        "checkpoints": [],
        "created_at": time.time(),
    }


def put_run(state: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or replace a run record in the state store (in place)."""
    state.setdefault("runs", {})[run["run_id"]] = run
    return run


def get_run(state: Dict[str, Any], run_id: str) -> Optional[Dict[str, Any]]:
    """Return a run record by id, or ``None`` if unknown."""
    return state.get("runs", {}).get(run_id)


def list_runs(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all run records."""
    return list(state.get("runs", {}).values())


def add_checkpoint(state: Dict[str, Any], run_id: str, path: str, step: Optional[int] = None) -> None:
    """Append a checkpoint entry to a run."""
    run = get_run(state, run_id)
    if run is None:
        raise KeyError(f"unknown run_id: {run_id}")
    run.setdefault("checkpoints", []).append(
        {"path": path, "step": step, "at": time.time()}
    )
