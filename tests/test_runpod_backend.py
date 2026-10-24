"""RealBackend over a fake stdlib-urllib transport (fully offline).

Every HTTP call is intercepted by monkeypatching RealBackend._request /
_graphql, so no network is touched and neither runpod nor httpx is imported.
Covers: Pod field normalization (desiredStatus, numeric-string costPerHr, env
object, no created_by, ownership from ow- prefix OR OVERWATCH_RUN), create_pod
building gpuTypeIds from the short name, create_volume dataCenterId handling,
GPU pricing via GraphQL, and billing summing the real per-hour spend rate.
"""

from __future__ import annotations

import pytest

from overwatch import runpod_client, tools
from overwatch import state as state_mod
from overwatch.runpod_client import RealBackend, _normalize_pod


# ----------------------------------------------------------------------
# pure normalization
# ----------------------------------------------------------------------
def test_normalize_owned_pod_by_prefix_and_env():
    raw = {
        "id": "pod-x",
        "name": "ow-run-x",
        "image": "img",
        "desiredStatus": "RUNNING",
        "costPerHr": "0.74",  # numeric STRING
        "env": {"OVERWATCH_RUN": "run-x", "OVERWATCH_KEEP": "1"},
        "gpu": {"id": "NVIDIA H100 80GB HBM3", "displayName": "H100 SXM"},
        "gpuCount": 2,
    }
    pod = _normalize_pod(raw)
    assert pod["status"] == "RUNNING"
    assert pod["created_by"] == "overwatch"
    assert pod["price_per_hour"] == pytest.approx(0.74)
    assert isinstance(pod["env"], dict)
    assert pod["env"]["OVERWATCH_KEEP"] == "1"
    assert pod["gpu"] == "H100"  # short name recognised for reporting


def test_normalize_owned_by_env_without_prefix():
    raw = {
        "id": "pod-y",
        "name": "custom-name",  # no ow- prefix
        "desiredStatus": "RUNNING",
        "adjustedCostPerHr": 1.5,
        "env": {"OVERWATCH_RUN": "run-y"},
    }
    pod = _normalize_pod(raw)
    assert pod["created_by"] == "overwatch"
    assert pod["price_per_hour"] == pytest.approx(1.5)


def test_normalize_foreign_pod_not_overwatch():
    raw = {
        "id": "pod-z",
        "name": "someone-elses-pod",
        "desiredStatus": "RUNNING",
        "costPerHr": "2.0",
        "env": {},
        "consumerUserId": "user-123",
    }
    pod = _normalize_pod(raw)
    assert pod["created_by"] != "overwatch"
    assert pod["created_by"] == "user-123"


def test_normalize_adjusted_cost_preferred():
    raw = {"id": "p", "name": "ow-a", "desiredStatus": "RUNNING",
           "adjustedCostPerHr": "3.0", "costPerHr": "9.0", "env": {}}
    assert _normalize_pod(raw)["price_per_hour"] == pytest.approx(3.0)


# ----------------------------------------------------------------------
# fake transport fixture
# ----------------------------------------------------------------------
class _FakeTransport:
    """Records REST calls and returns scripted responses."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        key = (method, path)
        # Allow prefix match for /pods/{id}/stop etc.
        if key in self.responses:
            return self.responses[key]
        for (m, p), resp in self.responses.items():
            if m == method and path.startswith(p.rstrip("*")):
                return resp
        return None


def _backend(monkeypatch, responses=None, graphql=None):
    be = RealBackend("sk-test")
    transport = _FakeTransport(responses or {})
    monkeypatch.setattr(be, "_request", transport)
    if graphql is not None:
        monkeypatch.setattr(be, "_graphql", lambda query: graphql)
    return be, transport


# ----------------------------------------------------------------------
# create_pod
# ----------------------------------------------------------------------
def test_create_pod_builds_gpu_type_ids(monkeypatch):
    be, transport = _backend(
        monkeypatch,
        responses={("POST", "/pods"): {
            "id": "pod-new", "name": "ow-run-1", "desiredStatus": "RUNNING",
            "costPerHr": "5.38", "env": {"OVERWATCH_RUN": "run-1"},
            "gpu": {"id": "NVIDIA H100 80GB HBM3"},
        }},
    )
    pod = be.create_pod(
        name="ow-run-1", gpu="H100", gpu_count=2, image="img",
        volume_id="vol-1", env={"OVERWATCH_RUN": "run-1", "OVERWATCH_KEEP": "0"},
        data_center_id="US-MO-1",
    )
    method, path, body = transport.calls[0]
    assert (method, path) == ("POST", "/pods")
    assert body["gpuTypeIds"][0] == "NVIDIA H100 80GB HBM3"
    assert body["gpuCount"] == 2
    assert body["cloudType"] == "SECURE"
    assert body["dataCenterIds"] == ["US-MO-1"]
    assert body["networkVolumeId"] == "vol-1"
    assert body["volumeMountPath"] == "/workspace"
    assert body["env"]["OVERWATCH_RUN"] == "run-1"
    # Returned pod is normalized to the internal contract.
    assert pod["status"] == "RUNNING"
    assert pod["created_by"] == "overwatch"
    assert pod["price_per_hour"] == pytest.approx(5.38)


def test_create_pod_unknown_gpu_raises(monkeypatch):
    be, _ = _backend(monkeypatch, responses={("POST", "/pods"): {}})
    with pytest.raises(KeyError):
        be.create_pod(name="ow-x", gpu="T4")


def test_create_pod_price_fallback_when_no_cost(monkeypatch):
    graphql = {"data": {"gpuTypes": [
        {"id": "NVIDIA H100 80GB HBM3", "displayName": "H100", "memoryInGb": 80,
         "lowestPrice": {"uninterruptablePrice": 2.69}},
    ]}}
    be, _ = _backend(
        monkeypatch,
        responses={("POST", "/pods"): {
            "id": "p", "name": "ow-r", "desiredStatus": "RUNNING", "env": {},
        }},
        graphql=graphql,
    )
    pod = be.create_pod(name="ow-r", gpu="H100", gpu_count=2)
    # No cost in response -> gpu_price(H100)*2 = 5.38
    assert pod["price_per_hour"] == pytest.approx(5.38)


# ----------------------------------------------------------------------
# create_volume
# ----------------------------------------------------------------------
def test_create_volume_requires_datacenter(monkeypatch):
    be, _ = _backend(monkeypatch, responses={})
    # No data_center_id and (in a temp cwd) no project.yaml -> ValueError.
    monkeypatch.setattr(runpod_client, "_project_datacenter", lambda: None)
    with pytest.raises(ValueError):
        be.create_volume(name="checkpoints", size_gb=200)


def test_create_volume_posts_input_and_normalizes(monkeypatch):
    be, transport = _backend(
        monkeypatch,
        responses={("POST", "/networkvolumes"): {
            "id": "vol-abc", "name": "checkpoints", "size": 200,
            "dataCenterId": "US-MO-1",
        }},
    )
    vol = be.create_volume(name="checkpoints", size_gb=200, data_center_id="US-MO-1")
    method, path, body = transport.calls[0]
    assert (method, path) == ("POST", "/networkvolumes")
    assert body == {"name": "checkpoints", "size": 200, "dataCenterId": "US-MO-1"}
    assert vol == {"id": "vol-abc", "name": "checkpoints", "size_gb": 200,
                   "data_center_id": "US-MO-1"}


def test_list_volumes_normalizes(monkeypatch):
    be, _ = _backend(
        monkeypatch,
        responses={("GET", "/networkvolumes"): [
            {"id": "vol-1", "name": "ck", "size": 200, "dataCenterId": "US-MO-1"},
        ]},
    )
    vols = be.list_volumes()
    assert vols[0]["size_gb"] == 200
    assert vols[0]["data_center_id"] == "US-MO-1"


# ----------------------------------------------------------------------
# pricing
# ----------------------------------------------------------------------
def test_gpu_price_short_and_full(monkeypatch):
    graphql = {"data": {"gpuTypes": [
        {"id": "NVIDIA H100 80GB HBM3", "displayName": "H100", "memoryInGb": 80,
         "lowestPrice": {"uninterruptablePrice": 2.69}},
        {"id": "NVIDIA A100 80GB PCIe", "displayName": "A100", "memoryInGb": 80,
         "lowestPrice": {"uninterruptablePrice": 1.19}},
    ]}}
    be, _ = _backend(monkeypatch, graphql=graphql)
    assert be.gpu_price("H100") == pytest.approx(2.69)  # short name via map
    assert be.gpu_price("NVIDIA A100 80GB PCIe") == pytest.approx(1.19)  # full id
    assert be.gpu_price("T4") is None


# ----------------------------------------------------------------------
# billing -- the critical spend-rate logic
# ----------------------------------------------------------------------
def test_billing_sums_running_pods(monkeypatch):
    be = RealBackend("sk-test")
    pods = [
        {"id": "a", "status": "RUNNING", "price_per_hour": 2.69, "gpu": "H100", "gpu_count": 1},
        {"id": "b", "status": "RUNNING", "price_per_hour": 1.19, "gpu": "A100", "gpu_count": 1},
        {"id": "c", "status": "STOPPED", "price_per_hour": 9.99, "gpu": "H100", "gpu_count": 1},
    ]
    monkeypatch.setattr(be, "list_pods", lambda: pods)
    out = be.billing()
    assert out["running_pods"] == 2
    assert out["spend_rate_per_hour"] == pytest.approx(3.88)  # only running pods


def test_billing_never_zero_for_priced_running_pod(monkeypatch):
    """A running Pod with no cost field falls back to gpu_price*count (> 0)."""
    be = RealBackend("sk-test")
    pods = [{"id": "a", "status": "RUNNING", "price_per_hour": 0.0, "gpu": "H100", "gpu_count": 2}]
    monkeypatch.setattr(be, "list_pods", lambda: pods)
    monkeypatch.setattr(be, "gpu_price", lambda g: 2.69 if g == "H100" else None)
    out = be.billing()
    assert out["running_pods"] == 1
    assert out["spend_rate_per_hour"] == pytest.approx(5.38)
    assert out["spend_rate_per_hour"] > 0


def test_billing_zero_when_nothing_running(monkeypatch):
    be = RealBackend("sk-test")
    monkeypatch.setattr(be, "list_pods", lambda: [
        {"id": "a", "status": "STOPPED", "price_per_hour": 5.0, "gpu": "H100"},
    ])
    out = be.billing()
    assert out == {"spend_rate_per_hour": 0.0, "running_pods": 0}


# ----------------------------------------------------------------------
# normalized fleet feeds the tools correctly (fleet_status / fleet_reap)
# ----------------------------------------------------------------------
def test_normalized_fleet_feeds_fleet_status(monkeypatch):
    be = RealBackend("sk-test")
    raw_pods = [
        {"id": "p1", "name": "ow-run-aaa", "desiredStatus": "RUNNING",
         "costPerHr": "2.69", "env": {"OVERWATCH_RUN": "run-aaa", "OVERWATCH_KEEP": "0"},
         "gpu": {"id": "NVIDIA H100 80GB HBM3"}},
        {"id": "p2", "name": "ow-run-keep", "desiredStatus": "RUNNING",
         "costPerHr": "1.19", "env": {"OVERWATCH_RUN": "run-keep", "OVERWATCH_KEEP": "1"},
         "gpu": {"id": "NVIDIA A100 80GB PCIe"}},
        {"id": "p3", "name": "foreign", "desiredStatus": "RUNNING",
         "costPerHr": "0.5", "env": {}, "gpu": {"id": "NVIDIA T4"}},
    ]
    monkeypatch.setattr(be, "_request", lambda m, p, body=None: raw_pods)
    result, _ = tools.fleet_status(backend=be)
    by_id = {r["pod_id"]: r for r in result["pods"]}
    assert by_id["p1"]["foreign"] is False
    assert by_id["p1"]["gpu"] == "H100"
    assert by_id["p2"]["keep"] is True
    assert by_id["p3"]["foreign"] is True
    assert result["foreign_count"] == 1


def test_normalized_fleet_feeds_fleet_reap(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERWATCH_STATE", str(tmp_path / "state.json"))
    be = RealBackend("sk-test")
    raw_pods = [
        {"id": "orphan", "name": "ow-run-orphan", "desiredStatus": "RUNNING",
         "costPerHr": "2.69", "env": {"OVERWATCH_RUN": "run-orphan", "OVERWATCH_KEEP": "0"}},
        {"id": "keep", "name": "ow-run-keep", "desiredStatus": "RUNNING",
         "costPerHr": "2.69", "env": {"OVERWATCH_RUN": "run-keep", "OVERWATCH_KEEP": "1"}},
    ]
    monkeypatch.setattr(be, "_request", lambda m, p, body=None: raw_pods)
    # No known-live runs in state -> the non-keep overwatch Pod is an orphan.
    result, _ = tools.fleet_reap(dry_run=True, backend=be)
    assert "orphan" in result["candidates"]
    assert "keep" not in result["candidates"]  # keep Pod never reaped
