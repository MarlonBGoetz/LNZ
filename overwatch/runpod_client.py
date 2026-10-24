"""Thin abstraction over the Runpod operations the MCP tools need.

The tools in :mod:`overwatch.tools` never talk to Runpod directly. They go
through a :class:`Backend`, which is either:

* :class:`RealBackend` -- used when ``RUNPOD_API_KEY`` is set and
  ``OVERWATCH_FAKE`` is not ``1``. It talks to the live Runpod REST API
  (``https://rest.runpod.io/v1``) and the GraphQL pricing endpoint using only
  the Python standard library (:mod:`urllib.request`) -- the ``runpod`` SDK and
  ``httpx`` are NOT required and are never imported, or
* :class:`FakeBackend` -- a deterministic in-memory stand-in seeded from
  fixtures so the whole tool surface is testable offline with no network, no
  GPU and no third-party packages.

Backend selection (:func:`get_backend`):

* ``OVERWATCH_FAKE=1`` (or no API key) selects the fake backend (tests set
  ``OVERWATCH_FAKE=1``).
* Otherwise the real backend is used. There is **no** silent fallback to the
  fake backend: if the real backend's transport fails, the error propagates so
  the operator never unknowingly runs against fake data while a key is present.

Nothing third-party is imported at module import time, so
``import overwatch.runpod_client`` always works in the sandbox. All HTTP goes
through small overridable methods (:meth:`RealBackend._request` /
:meth:`RealBackend._graphql`) that tests monkeypatch to stay offline.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .policy import short_name_for

FAKE_ENV = "OVERWATCH_FAKE"
API_KEY_ENV = "RUNPOD_API_KEY"

# Live Runpod endpoints (see context.json live_api_facts).
REST_BASE = "https://rest.runpod.io/v1"
GRAPHQL_URL = "https://api.runpod.io/graphql"

# The Pod name prefix and env var that identify an overwatch-owned Pod. The
# real Runpod Pod response has NO ``created_by`` field, so ownership is derived
# from the ``ow-`` name prefix OR an ``OVERWATCH_RUN`` env var.
OW_POD_PREFIX = "ow-"
RUN_ENV = "OVERWATCH_RUN"


def _coerce_float(value: Any) -> Optional[float]:
    """Coerce a numeric or numeric-string cost field to float, else ``None``."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _project_datacenter() -> Optional[str]:
    """Best-effort read of ``runpod.datacenter`` from .overwatch/project.yaml."""
    path = os.path.join(".overwatch", "project.yaml")
    if not os.path.exists(path):
        return None
    try:
        from . import config as _config

        data = _config.load_config(path) or {}
        return ((data.get("runpod") or {}).get("datacenter")) or None
    except Exception:
        return None

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


def _normalize_pod(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a live Runpod Pod dict into the internal tool contract.

    The tools in :mod:`overwatch.tools` expect the FakeBackend shape:
    ``status`` (uppercase, e.g. ``"RUNNING"``), ``created_by`` (``"overwatch"``
    for Pods we own), a ``env`` dict, a numeric ``price_per_hour`` and a short
    ``gpu`` name. The real Runpod Pod uses ``desiredStatus``, ``costPerHr`` /
    ``adjustedCostPerHr`` (which may be a numeric string), an ``env`` object and
    has NO ``created_by`` field.

    Ownership is derived WITHOUT ``created_by``: a Pod is ``"overwatch"`` when
    its name starts with the ``ow-`` prefix OR its env carries ``OVERWATCH_RUN``.
    Otherwise the real ``consumerUserId`` (or ``None``) is preserved. This is a
    pure function with no I/O.
    """
    raw = raw or {}
    name = raw.get("name") or ""
    env = raw.get("env")
    env = dict(env) if isinstance(env, dict) else {}

    status = raw.get("desiredStatus") or raw.get("status") or ""
    status = str(status).upper()

    # price_per_hour: adjustedCostPerHr/costPerHr already reflect gpuCount.
    price = _coerce_float(raw.get("adjustedCostPerHr"))
    if price is None:
        price = _coerce_float(raw.get("costPerHr"))
    if price is None:
        price = _coerce_float(raw.get("price_per_hour"))

    # Derive ownership from the ow- prefix OR OVERWATCH_RUN env (no created_by).
    owned = name.startswith(OW_POD_PREFIX) or bool(env.get(RUN_ENV))
    if owned:
        created_by = "overwatch"
    else:
        created_by = raw.get("created_by") or raw.get("consumerUserId") or None

    # Short GPU name for reporting (match the real gpu id/displayName).
    gpu_obj = raw.get("gpu") or {}
    short_gpu = raw.get("gpu") if isinstance(raw.get("gpu"), str) else None
    if short_gpu is None and isinstance(gpu_obj, dict):
        short_gpu = (
            short_name_for(gpu_obj.get("id"))
            or short_name_for(gpu_obj.get("displayName"))
        )
    for gpu_id in raw.get("gpuTypeIds") or []:
        if short_gpu:
            break
        short_gpu = short_name_for(gpu_id)

    gpu_count = raw.get("gpuCount") or raw.get("gpu_count") or 1

    normalized = {
        "id": raw.get("id"),
        "name": name,
        "image": raw.get("image") or raw.get("imageName") or "",
        "status": status,
        "created_by": created_by,
        "env": env,
        "gpu": short_gpu,
        "gpu_count": int(gpu_count) if gpu_count else 1,
        "price_per_hour": float(price) if price is not None else 0.0,
        "networkVolume": raw.get("networkVolume"),
        "machineId": raw.get("machineId"),
    }
    return normalized


def _normalize_volume(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a live Runpod NetworkVolume dict to the internal volume shape."""
    raw = raw or {}
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "size_gb": raw.get("size") if raw.get("size") is not None else raw.get("size_gb"),
        "data_center_id": raw.get("dataCenterId") or raw.get("data_center_id"),
    }


class RealBackend(Backend):
    """Runpod-backed implementation over the stdlib ``urllib`` (no SDK/httpx).

    All HTTP goes through the overridable :meth:`_request` (REST) and
    :meth:`_graphql` (pricing) methods so tests can monkeypatch a fake transport
    and never touch the network. The ``runpod`` SDK and ``httpx`` are never
    imported, so this class constructs fine in a sandbox without them.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError(
                "RUNPOD_API_KEY is required for the real backend; set "
                "OVERWATCH_FAKE=1 to use the offline fake backend"
            )
        self.api_key = api_key

    # -- transport -----------------------------------------------------
    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        """Perform a REST call against ``REST_BASE`` and return parsed JSON.

        Overridable so tests can inject a fake transport. Follows the stdlib
        ``urllib.request`` pattern already used in ``overwatch.tools``.
        """
        url = f"{REST_BASE}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            payload = resp.read().decode("utf-8")
        if not payload:
            return None
        return json.loads(payload)

    def _graphql(self, query: str) -> Any:
        """Perform a GraphQL POST (pricing) and return parsed JSON.

        Overridable so tests can inject a fake transport.
        """
        url = f"{GRAPHQL_URL}?api_key={self.api_key}"
        data = json.dumps({"query": query}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload) if payload else None

    # -- gpu / pricing -------------------------------------------------
    def list_gpu_types(self) -> List[Dict[str, Any]]:
        query = (
            "{ gpuTypes{ id displayName memoryInGb secureCloud communityCloud "
            "lowestPrice(input:{gpuCount:1}){ uninterruptablePrice minimumBidPrice } } }"
        )
        resp = self._graphql(query) or {}
        gpu_types = ((resp.get("data") or {}).get("gpuTypes")) or []
        out: List[Dict[str, Any]] = []
        for g in gpu_types:
            lowest = g.get("lowestPrice") or {}
            price = _coerce_float(lowest.get("uninterruptablePrice"))
            out.append(
                {
                    "id": g.get("id"),
                    "name": g.get("displayName", g.get("id")),
                    "memory_gb": g.get("memoryInGb"),
                    "price_per_hour": price if price is not None else 0.0,
                }
            )
        return out

    def gpu_price(self, gpu: str) -> Optional[float]:
        """Resolve a price for a short name (via the map) or a full Runpod id."""
        from .policy import gpu_type_ids

        types = self.list_gpu_types()
        by_id = {g["id"]: g for g in types if g.get("id")}
        # Direct full-id match first.
        if gpu in by_id:
            return _coerce_float(by_id[gpu].get("price_per_hour"))
        # Short name -> preferred/available full ids.
        try:
            candidates = gpu_type_ids(gpu)
        except KeyError:
            candidates = []
        for full_id in candidates:
            if full_id in by_id:
                price = _coerce_float(by_id[full_id].get("price_per_hour"))
                if price is not None:
                    return price
        return None

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
        data_center_id: Optional[str] = None,
        cloud_type: str = "SECURE",
        **extra: Any,
    ) -> Dict[str, Any]:
        from .policy import gpu_type_ids

        gpu_ids = gpu_type_ids(gpu)  # raises KeyError for an unknown short name
        datacenter = data_center_id or _project_datacenter()
        body: Dict[str, Any] = {
            "name": name,
            "imageName": image,
            "gpuTypeIds": gpu_ids,
            "gpuCount": int(gpu_count),
            "cloudType": cloud_type,
            "env": dict(env or {}),
            "volumeMountPath": "/workspace",
        }
        if datacenter:
            body["dataCenterIds"] = [datacenter]
        if volume_id:
            body["networkVolumeId"] = volume_id
        for key in ("containerDiskInGb", "volumeInGb"):
            if key in extra:
                body[key] = extra[key]
        raw = self._request("POST", "/pods", body) or {}
        pod = _normalize_pod(raw)
        # price_per_hour: prefer the API cost; fall back to gpu_price*count.
        if pod.get("price_per_hour"):
            pass
        elif price_per_hour is not None:
            pod["price_per_hour"] = float(price_per_hour) * int(gpu_count)
        else:
            unit = self.gpu_price(gpu) or 0.0
            pod["price_per_hour"] = float(unit) * int(gpu_count)
        # Preserve the short gpu the caller asked for when the response omits it.
        if not pod.get("gpu"):
            pod["gpu"] = gpu
        return pod

    def stop_pod(self, pod_id: str) -> Dict[str, Any]:
        raw = self._request("POST", f"/pods/{pod_id}/stop") or {}
        return _normalize_pod(raw) if raw else {"id": pod_id, "status": "STOPPED"}

    def terminate_pod(self, pod_id: str) -> Dict[str, Any]:
        self._request("DELETE", f"/pods/{pod_id}")
        return {"id": pod_id, "status": "TERMINATED"}

    def list_pods(self) -> List[Dict[str, Any]]:
        raw = self._request("GET", "/pods") or []
        if isinstance(raw, dict):
            raw = raw.get("pods") or raw.get("data") or []
        return [_normalize_pod(p) for p in raw]

    def get_pod(self, pod_id: str) -> Optional[Dict[str, Any]]:
        try:
            raw = self._request("GET", f"/pods/{pod_id}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        if not raw:
            return None
        return _normalize_pod(raw)

    # -- volumes -------------------------------------------------------
    def create_volume(
        self,
        *,
        name: str,
        size_gb: int = 50,
        data_center_id: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        datacenter = data_center_id or _project_datacenter()
        if not datacenter:
            raise ValueError(
                "create_volume refused: dataCenterId is required (pass data_center_id "
                "or set runpod.datacenter in .overwatch/project.yaml)"
            )
        body = {"name": name, "size": int(size_gb), "dataCenterId": datacenter}
        raw = self._request("POST", "/networkvolumes", body) or {}
        return _normalize_volume(raw)

    def delete_volume(self, volume_id: str) -> Dict[str, Any]:
        # Implemented for completeness; volume deletes are guarded off elsewhere
        # and this must never be called in tests.
        self._request("DELETE", f"/networkvolumes/{volume_id}")
        return {"id": volume_id, "deleted": True}

    def list_volumes(self) -> List[Dict[str, Any]]:
        raw = self._request("GET", "/networkvolumes") or []
        if isinstance(raw, dict):
            raw = raw.get("networkVolumes") or raw.get("data") or []
        return [_normalize_volume(v) for v in raw]

    # -- billing -------------------------------------------------------
    def billing(self) -> Dict[str, Any]:
        """Sum per-hour cost across currently-running Pods (never 0 if priced).

        A ``$0`` spend rate while priced Pods run is the single most dangerous
        bug (the budget guard depends on this), so when a running Pod lacks a
        cost field we fall back to ``gpu_price(short_gpu) * gpu_count``.
        """
        pods = self.list_pods()
        rate = 0.0
        running = 0
        for pod in pods:
            if pod.get("status") != "RUNNING":
                continue
            running += 1
            price = _coerce_float(pod.get("price_per_hour"))
            if not price:
                short = pod.get("gpu")
                unit = self.gpu_price(short) if short else None
                if unit:
                    price = float(unit) * int(pod.get("gpu_count") or 1)
            rate += float(price or 0.0)
        return {"spend_rate_per_hour": rate, "running_pods": running}


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
    fake backend ONLY when ``OVERWATCH_FAKE=1`` or no API key is set. When an
    API key is present and ``OVERWATCH_FAKE != '1'`` we return the real backend
    and let any construction/transport failure RAISE -- there is deliberately NO
    silent fallback to the fake backend, so the operator never unknowingly runs
    against fake data while a key is set.
    """
    if _INJECTED is not None:
        return _INJECTED
    if use_fake():
        print("overwatch: using FakeBackend (offline)", file=sys.stderr)
        return FakeBackend(seed)
    api_key = os.environ.get(API_KEY_ENV)
    backend = RealBackend(api_key or "")
    print("overwatch: using RealBackend (live Runpod)", file=sys.stderr)
    return backend
