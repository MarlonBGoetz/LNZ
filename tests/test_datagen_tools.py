"""Tests for the datagen_* MCP tools (offline, fake backends).

Force the fake inference + Runpod backends via OVERWATCH_FAKE=1, route state at
a temp file and write shards under a tmp output dir. No network, no GPU.
"""

from __future__ import annotations

import json
import os

import pytest

from overwatch import runpod_client, tools
from overwatch import state as state_mod
from overwatch.datagen import driver
from tests.fixtures import seed_fleet


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    monkeypatch.setenv("OVERWATCH_STATE", os.path.join(str(tmp_path), "state.json"))
    backend = runpod_client.FakeBackend(seed_fleet())
    runpod_client.set_backend(backend)
    yield backend
    runpod_client.set_backend(None)


def _assert_result(res):
    result, summary = res
    assert isinstance(result, dict)
    assert isinstance(summary, str) and summary
    json.dumps(result)
    return result, summary


def _write_prompts(path, n):
    with open(path, "w", encoding="utf-8") as handle:
        for i in range(n):
            handle.write(json.dumps({"id": i, "input": f"text {i}"}) + "\n")


def _spec_file(tmp_path, input_path, output_dir, **over):
    """Write a small serverless spec YAML and return its path."""
    body = [
        "name: labels-test",
        "mode: serverless",
        "model: m",
        f"input: {input_path}",
        f"output: {output_dir}",
        "sampling:",
        "  temperature: 0.7",
        "  max_tokens: 16",
        "concurrency: 4",
        "budget_usd: 25",
    ]
    for k, v in over.items():
        body.append(f"{k}: {v}")
    path = os.path.join(str(tmp_path), "spec.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(body) + "\n")
    return path


# ----------------------------------------------------------------------
# start registers a job
# ----------------------------------------------------------------------
def test_datagen_start_registers_job(tmp_path, fake_env):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 5)
    spec = _spec_file(tmp_path, inp, out)

    result, summary = _assert_result(
        tools.datagen_start(spec=spec, base_dir=str(tmp_path), output_dir=out, shard_size=2)
    )
    assert result["status"] == "completed"
    assert result["records"] == 5
    assert result["mode"] == "serverless"
    # The job is registered in state.
    state = state_mod.load_state()
    assert result["job_id"] in state["datagen"]


# ----------------------------------------------------------------------
# job-level budget pauses the job
# ----------------------------------------------------------------------
def test_datagen_start_respects_job_budget(tmp_path, fake_env):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 10)
    # Tiny budget vs a nonzero per-record price -> over budget.
    spec = _spec_file(tmp_path, inp, out, budget_usd=0.001)

    result, summary = _assert_result(
        tools.datagen_start(
            spec=spec, base_dir=str(tmp_path), output_dir=out,
            shard_size=50, price_per_record=1.0,
        )
    )
    assert result["over_budget"] is True
    assert result["status"] == "paused"


# ----------------------------------------------------------------------
# status reports progress/shards/spend
# ----------------------------------------------------------------------
def test_datagen_status_reports_progress(tmp_path, fake_env):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 4)
    spec = _spec_file(tmp_path, inp, out)
    start, _ = tools.datagen_start(
        spec=spec, base_dir=str(tmp_path), output_dir=out, shard_size=2, price_per_record=0.5
    )
    result, summary = _assert_result(tools.datagen_status(job_id=start["job_id"]))
    assert result["records"] == 4
    assert result["shard_count"] == 2
    assert result["spend_usd"] == 2.0
    assert result["qa_status"] == "ok"


def test_datagen_status_unknown_job(fake_env):
    with pytest.raises(KeyError):
        tools.datagen_status(job_id="nope")


# ----------------------------------------------------------------------
# sample returns records
# ----------------------------------------------------------------------
def test_datagen_sample_returns_records(tmp_path, fake_env):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 5)
    spec = _spec_file(tmp_path, inp, out)
    start, _ = tools.datagen_start(spec=spec, base_dir=str(tmp_path), output_dir=out, shard_size=2)

    result, summary = _assert_result(tools.datagen_sample(job_id=start["job_id"], n=3))
    assert result["count"] == 3
    assert all("output" in r and "key" in r for r in result["records"])


# ----------------------------------------------------------------------
# stop tears down + marks job stopped
# ----------------------------------------------------------------------
def test_datagen_stop_serverless(tmp_path, fake_env):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 3)
    spec = _spec_file(tmp_path, inp, out)
    start, _ = tools.datagen_start(spec=spec, base_dir=str(tmp_path), output_dir=out, shard_size=10)

    result, summary = _assert_result(tools.datagen_stop(job_id=start["job_id"]))
    assert result["status"] == "stopped"
    assert result["teardown"]["serverless_max_workers"] == 0
    state = state_mod.load_state()
    assert state["datagen"][start["job_id"]]["status"] == "stopped"


def test_datagen_sharded_mode_launches_and_terminates_pods(tmp_path, fake_env):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 4)
    spec = _spec_file(tmp_path, inp, out, mode="sharded")

    pods_before = len(fake_env.list_pods())
    start, _ = tools.datagen_start(
        spec=spec, base_dir=str(tmp_path), output_dir=out, shard_size=10,
        shards=2, volume_id="vol-PLACEHOLDER",
    )
    assert start["mode"] == "sharded"
    assert len(start["shard_pods"]) == 2
    # Two shard Pods were provisioned (OVERWATCH_SHARD i of N).
    assert len(fake_env.list_pods()) == pods_before + 2
    shard_pod = fake_env.get_pod(start["shard_pods"][0])
    assert "OVERWATCH_SHARD" in shard_pod["env"]
    assert shard_pod["env"]["OVERWATCH_DATAGEN_JOB"] == start["job_id"]

    # Stop terminates the shard Pods.
    stop, _ = tools.datagen_stop(job_id=start["job_id"])
    assert len(stop["teardown"]["sharded_terminated"]) == 2
    assert len(fake_env.list_pods()) == pods_before


def test_datagen_start_committed_spec_loads(fake_env, tmp_path, repo_root):
    """The committed datagen/labels-v1.yaml spec drives the tool end to end."""
    out = os.path.join(str(tmp_path), "out")
    spec_path = os.path.join(repo_root, "datagen", "labels-v1.yaml")
    result, summary = _assert_result(
        tools.datagen_start(spec=spec_path, base_dir=repo_root, output_dir=out, shard_size=3)
    )
    assert result["name"] == "labels-v1"
    assert result["records"] == 6  # the committed data/prompts.jsonl fixture
