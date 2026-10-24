"""Tests for the atomic state store."""

import json
import os

from overwatch import state


def test_load_missing_returns_empty(temp_state):
    data = state.load_state()
    assert data["runs"] == {}
    assert data["session"]["spend_usd"] == 0.0
    assert not os.path.exists(temp_state)  # load must not create the file


def test_round_trip(temp_state):
    s = state.load_state()
    run = state.new_run(
        "r1",
        pod_id="pod-abc",
        status="running",
        price_per_hour=1.89,
        budget=10.0,
        max_hours=4.0,
    )
    state.put_run(s, run)
    state.save_state(s)

    reloaded = state.load_state()
    got = state.get_run(reloaded, "r1")
    assert got is not None
    assert got["pod_id"] == "pod-abc"
    assert got["status"] == "running"
    assert got["price_per_hour"] == 1.89
    assert got["budget"] == 10.0
    assert got["max_hours"] == 4.0
    assert got["bearer"]  # a token was generated
    assert got["lineage"] == {"parent": None, "children": []}
    assert got["checkpoints"] == []
    assert "created_at" in got


def test_run_record_schema_has_expected_keys():
    run = state.new_run("r2")
    for key in (
        "run_id",
        "pod_id",
        "status",
        "price_per_hour",
        "bearer",
        "budget",
        "max_hours",
        "lineage",
        "checkpoints",
        "created_at",
    ):
        assert key in run


def test_add_checkpoint(temp_state):
    s = state.load_state()
    state.put_run(s, state.new_run("r3"))
    state.add_checkpoint(s, "r3", "/workspace/checkpoints/step-100.pt", step=100)
    state.save_state(s)
    reloaded = state.load_state()
    ckpts = state.get_run(reloaded, "r3")["checkpoints"]
    assert len(ckpts) == 1
    assert ckpts[0]["path"].endswith("step-100.pt")
    assert ckpts[0]["step"] == 100


def test_save_is_atomic_no_temp_left(temp_state):
    s = state.load_state()
    state.put_run(s, state.new_run("r4"))
    state.save_state(s)
    directory = os.path.dirname(temp_state)
    leftovers = [f for f in os.listdir(directory) if f.startswith(".state-")]
    assert leftovers == []
    # File is valid JSON.
    with open(temp_state, "r", encoding="utf-8") as handle:
        assert json.load(handle)["runs"]["r4"]["run_id"] == "r4"


def test_env_override(tmp_path, monkeypatch):
    custom = os.path.join(str(tmp_path), "nested", "custom.json")
    monkeypatch.setenv("OVERWATCH_STATE", custom)
    assert state.state_path() == custom
    s = state.load_state()
    state.put_run(s, state.new_run("r5"))
    state.save_state(s)
    assert os.path.exists(custom)
