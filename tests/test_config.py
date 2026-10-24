"""Tests for the stdlib YAML/JSON config loader."""

import os

from overwatch import config


def test_parse_flat_scalars():
    data = config.parse_yaml(
        "name: demo\n"
        "count: 3\n"
        "ratio: 0.5\n"
        "enabled: true\n"
        "disabled: false\n"
        "missing:\n"
    )
    assert data["name"] == "demo"
    assert data["count"] == 3
    assert data["ratio"] == 0.5
    assert data["enabled"] is True
    assert data["disabled"] is False
    assert data["missing"] is None


def test_comments_stripped():
    data = config.parse_yaml(
        "# a full line comment\n"
        "key: value   # trailing comment\n"
        "url: \"http://x#y\"  # hash inside quotes is kept\n"
    )
    assert data["key"] == "value"
    assert data["url"] == "http://x#y"


def test_inline_flow_list_and_map():
    data = config.parse_yaml(
        "allow: [A100, H100]\n"
        "pair: {a: 1, b: two}\n"
    )
    assert data["allow"] == ["A100", "H100"]
    assert data["pair"] == {"a": 1, "b": "two"}


def test_nested_mapping_and_block_sequence():
    text = (
        "runpod:\n"
        "  datacenter: US-OR-1\n"
        "  volume_id: vol-X\n"
        "items:\n"
        "  - one\n"
        "  - two\n"
    )
    data = config.parse_yaml(text)
    assert data["runpod"]["datacenter"] == "US-OR-1"
    assert data["runpod"]["volume_id"] == "vol-X"
    assert data["items"] == ["one", "two"]


def test_block_sequence_of_maps():
    text = (
        "shards:\n"
        "  - name: a\n"
        "    size: 10\n"
        "  - name: b\n"
        "    size: 20\n"
    )
    data = config.parse_yaml(text)
    assert data["shards"] == [
        {"name": "a", "size": 10},
        {"name": "b", "size": 20},
    ]


def _repo_file(repo_root, *parts):
    return os.path.join(repo_root, *parts)


def test_load_committed_policy_yaml(repo_root):
    data = config.load_config(_repo_file(repo_root, ".overwatch", "policy.yaml"))
    assert data["session_cap_usd"] == 50.0
    assert data["per_run_cap_usd"] == 20.0
    assert data["max_hours"] == 8.0
    assert data["gpu_allowlist"] == ["A100", "H100"]
    assert data["thresholds"]["nan_max_retries"] == 2
    assert data["thresholds"]["divergence_ema_rising_steps"] == 200
    assert data["thresholds"]["checkpoint_interval_seconds"] == 900
    assert data["thresholds"]["budget_warn_fraction"] == 0.8


def test_load_committed_project_yaml(repo_root):
    data = config.load_config(_repo_file(repo_root, ".overwatch", "project.yaml"))
    assert data["project"] == "gpu-overwatch"
    assert data["runpod"]["datacenter"] == "US-OR-1"
    assert data["runpod"]["volume_id"] == "vol-PLACEHOLDER"
    assert data["naming"]["pod_prefix"] == "ow-"
    assert data["naming"]["run_env"] == "OVERWATCH_RUN"
    assert data["naming"]["keep_env"] == "OVERWATCH_KEEP"
    assert data["defaults"]["gpu"] == "A100"


def test_datagen_spec_shape():
    """A datagen spec uses flat keys, nested sampling map and inline lists."""
    text = (
        "job: dg-1\n"
        "model: big-llm\n"
        "template: prompts/q.jinja\n"
        "sampling:\n"
        "  temperature: 0.7\n"
        "  top_p: 0.95\n"
        "inputs: [one, two, three]\n"
        "shard_size: 1000\n"
    )
    data = config.parse_yaml(text)
    assert data["job"] == "dg-1"
    assert data["sampling"] == {"temperature": 0.7, "top_p": 0.95}
    assert data["inputs"] == ["one", "two", "three"]
    assert data["shard_size"] == 1000


def test_dump_yaml_round_trips():
    original = {
        "session_cap_usd": 50.0,
        "gpu_allowlist": ["A100", "H100"],
        "thresholds": {"nan_max_retries": 2, "budget_warn_fraction": 0.8},
    }
    text = config.dump_yaml(original)
    reparsed = config.parse_yaml(text)
    assert reparsed == original
