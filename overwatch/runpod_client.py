"""Thin abstraction over the Runpod operations the MCP tools need.

The tools in :mod:`overwatch.tools` never talk to Runpod directly. They go
through a :class:`Backend`, which is either:

* :class:`RealBackend` -- used when ``RUNPOD_API_KEY`` is set, the real
  ``runpod`` SDK (or ``httpx``) is importable and the network is reachable, or
* :class:`FakeBackend` -- a deterministic in-memory stand-in seeded from
  fixtures so the whole tool surface is testable offline with no network, no
  GPU and no third-party packages.

Backend selection (:func:`get_backend`):

* ``OVERWATCH_FAKE=1`` forces the fake backend (tests set this).
* Otherwise the real backend is attempted; if the SDK/network is unavailable we
  fall back to the fake backend rather than crashing on import.

Nothing third-party is imported at module import time. The real SDK import is
guarded inside :class:`RealBackend` so ``import overwatch.runpod_client`` always
works in the sandbox.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

FAKE_ENV = "OVERWATCH_FAKE"
API_KEY_ENV = "RUNPOD_API_KEY"

# Default GPU price list used to seed the fake backend. Prices are USD/hour and
# are illustrative; the sizing table in :mod:`overwatch.tools` references these
# names. They are intentionally deterministic for tests.
DEFAULT_GPU_TYPES: List[Dict[str, Any]] = [
    {"id": "A100", "name": "A100 80GB", "memory_gb": 80, "price_per_hour": 1.89},
    {"id": "H100", "name": "H100 80GB", "memory_gb": 80, "price_per_hour": 2.99},
    {"id": "A40", "name": "A40 48GB", "memory_gb": 48, "price_per_hour": 0.79},
    {"id": "L40S", "name": "L40S 48GB", "memory_gb": 48, "price_per_hour": 1.10},
    {"id": "T4", "name": "T4 16GB", "memory_gb": 16, "price_per_hour": 0.29},
]


class Backend:
    """Interface the tools rely on. See :class:`FakeBackend` for behaviour."""

    def list_gpu_types(self) -> List[Dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    def gpu_price(self, gpu: str) -> Optional[float]:
        for g in self.list_gpu_types():
            if g["id"] == gpu:
                return float(g["price_per_hour"])
        return None

    def create_pod(self, **kwargs: Any) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def stop_pod(self, pod_id: str) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def terminate_pod(self, pod_id: str) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def list_pods(self) -> List[Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def get_pod(self, pod_id: str) -> Optional[Dict[str, Any]]:
        for pod in self.list_pods():
            if pod.get("id") == pod_id:
                return pod
        return None

    def create_volume(self, **kwargs: Any) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def delete_volume(self, volume_id: str) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def list_volumes(self) -> List[Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def billing(self) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class FakeBackend(Backend):
    """Deterministic in-memory backend seeded from a fixture dict.

    The fixture shape::

        {
            "gpu_types": [ {id, name, memory_gb, price_per_hour}, ... ],
            "pods": [ {id, name, gpu, price_per_hour, status, created_by, env, ...} ],
            "volumes": [ {id, name, size_gb}, ... ],
        }

    ``created_by`` on a Pod is ``"overwatch"`` for Pods we provisioned and
    something else (or absent) for foreign Pods. ``env`` carries the Pod env
    vars (``OVERWATCH_RUN`` / ``OVERWATCH_KEEP`` for our Pods).
    """

    def __init__(self, seed: Optional[Dict[str, Any]] = None) -> None:
        seed = seed or {}
        self.gpu_types: List[Dict[str, Any]] = [
            dict(g) for g in seed.get("gpu_types", DEFAULT_GPU_TYPES)
        ]
        self.pods: Dict[str, Dict[str, Any]] = {}
        for pod in seed.get("pods", []):
            self.pods[pod["id"]] = dict(pod)
        self.volumes: Dict[str, Dict[str, Any]] = {}
        for vol in seed.get("volumes", []):
            self.volumes[vol["id"]] = dict(vol)
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter:04d}"

    # -- gpu / pricing -------------------------------------------------
    def list_gpu_types(self) -> List[Dict[str, Any]]:
        return [dict(g) for g in self.gpu_types]

    # -- pods ----------------------------------------------------------
    def create_pod(
        self,
        *,
        name: str,
        gpu: str,
        gpu_count: int = 1,
        image: str = "",
        volume_id: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        price_per_hour: Optional[float] = None,
        created_by: str = "overwatch",
        **extra: Any,
    ) -> Dict[str, Any]:
        pod_id = self._next_id("pod-")
        if price_per_hour is None:
            price_per_hour = self.gpu_price(gpu) or 0.0
        pod = {
            "id": pod_id,
            "name": name,
            "gpu": gpu,
            "gpu_count": int(gpu_count),
            "image": image,
            "volume_id": volume_id,
            "env": dict(env or {}),
            "price_per_hour": float(price_per_hour) * int(gpu_count),
            "status": "RUNNING",
            "created_by": created_by,
            "created_at": time.time(),
        }
        pod.update(extra)
        self.pods[pod_id] = pod
        return dict(pod)

    def stop_pod(self, pod_id: str) -> Dict[str, Any]:
        pod = self.pods.get(pod_id)
        if pod is None:
            raise KeyError(f"unknown pod: {pod_id}")
        pod["status"] = "STOPPED"
        return dict(pod)

    def terminate_pod(self, pod_id: str) -> Dict[str, Any]:
        pod = self.pods.pop(pod_id, None)
        if pod is None:
            raise KeyError(f"unknown pod: {pod_id}")
        pod["status"] = "TERMINATED"
        return dict(pod)

    def list_pods(self) -> List[Dict[str, Any]]:
        return [dict(p) for p in self.pods.values()]

    # -- volumes -------------------------------------------------------
    def create_volume(self, *, name: str, size_gb: int = 50, **extra: Any) -> Dict[str, Any]:
        vol_id = self._next_id("vol-")
        vol = {"id": vol_id, "name": name, "size_gb": int(size_gb)}
        vol.update(extra)
        self.volumes[vol_id] = vol
        return dict(vol)

    def delete_volume(self, volume_id: str) -> Dict[str, Any]:
        vol = self.volumes.pop(volume_id, None)
        if vol is None:
            raise KeyError(f"unknown volume: {volume_id}")
        return dict(vol)

    def list_volumes(self) -> List[Dict[str, Any]]:
        return [dict(v) for v in self.volumes.values()]

    # -- billing -------------------------------------------------------
    def billing(self) -> Dict[str, Any]:
        rate = sum(
            float(p.get("price_per_hour", 0.0))
            for p in self.pods.values()
            if p.get("status") == "RUNNING"
        )
        return {"spend_rate_per_hour": rate, "running_pods": len(
            [p for p in self.pods.values() if p.get("status") == "RUNNING"]
        )}


class RealBackend(Backend):
    """Runpod-backed implementation (SDK/httpx), import-guarded.

    This is never exercised in the sandbox. The SDK is imported lazily so that
    importing this module never fails when ``runpod`` is absent.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._sdk = None
        self._load_sdk()

    def _load_sdk(self) -> None:
        try:  # pragma: no cover - exercised only with the real SDK present
            import runpod  # type: ignore

            runpod.api_key = self.api_key
            self._sdk = runpod
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "runpod SDK is required for the real backend; set OVERWATCH_FAKE=1 "
                "to use the offline fake backend"
            ) from exc

    def list_gpu_types(self) -> List[Dict[str, Any]]:  # pragma: no cover
        gpus = self._sdk.get_gpus()  # type: ignore[union-attr]
        out = []
        for g in gpus:
            out.append(
                {
                    "id": g.get("id"),
                    "name": g.get("displayName", g.get("id")),
                    "memory_gb": g.get("memoryInGb"),
                    "price_per_hour": g.get("securePrice") or g.get("communityPrice") or 0.0,
                }
            )
        return out

    def create_pod(self, **kwargs: Any) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError("real create_pod is executed only against live Runpod")

    def stop_pod(self, pod_id: str) -> Dict[str, Any]:  # pragma: no cover
        return self._sdk.stop_pod(pod_id)  # type: ignore[union-attr]

    def terminate_pod(self, pod_id: str) -> Dict[str, Any]:  # pragma: no cover
        return self._sdk.terminate_pod(pod_id)  # type: ignore[union-attr]

    def list_pods(self) -> List[Dict[str, Any]]:  # pragma: no cover
        return self._sdk.get_pods()  # type: ignore[union-attr]

    def create_volume(self, **kwargs: Any) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def delete_volume(self, volume_id: str) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def list_volumes(self) -> List[Dict[str, Any]]:  # pragma: no cover
        return []

    def billing(self) -> Dict[str, Any]:  # pragma: no cover
        return {"spend_rate_per_hour": 0.0, "running_pods": 0}


# A module-level fake backend may be injected by tests/fixtures so that
# repeated get_backend() calls share state within a test.
_INJECTED: Optional[Backend] = None


def set_backend(backend: Optional[Backend]) -> None:
    """Inject (or clear) a process-wide backend. Used by fixtures/tests."""
    global _INJECTED
    _INJECTED = backend


def use_fake() -> bool:
    """Whether the fake backend should be used."""
    if os.environ.get(FAKE_ENV) == "1":
        return True
    # No API key -> cannot use the real backend; fall back to fake.
    return not os.environ.get(API_KEY_ENV)


def get_backend(seed: Optional[Dict[str, Any]] = None) -> Backend:
    """Return the active backend.

    An injected backend (via :func:`set_backend`) wins. Otherwise we choose the
    fake backend when ``OVERWATCH_FAKE=1`` or no API key is set, and attempt the
    real backend when credentials/SDK are present (falling back to fake on any
    failure rather than crashing).
    """
    if _INJECTED is not None:
        return _INJECTED
    if use_fake():
        return FakeBackend(seed)
    api_key = os.environ.get(API_KEY_ENV)
    try:
        return RealBackend(api_key or "")
    except Exception:
        return FakeBackend(seed)
