"""Tests for the supervise-run workflow recipe + the offline validator.

Loads ``.kiro/workflows/supervise-run.workflow.json`` and asserts it parses,
matches the plan's structure (ids, the gpu-medic agent, the exact command
string, the ``runId`` config key, ``idleTimeoutSec`` 43200, ``maxIterations``
25, the post-mortem artifacts path) and passes ``overwatch.validate_workflow``.
No network, no third-party packages.
"""

from __future__ import annotations

import json
import os

import pytest

from overwatch import validate_workflow

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WORKFLOW = os.path.join(REPO, ".kiro", "workflows", "supervise-run.workflow.json")


@pytest.fixture()
def workflow():
    with open(WORKFLOW, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _find_step(steps, step_id):
    for step in steps:
        if step.get("id") == step_id:
            return step
        for key in ("steps", "do", "body"):
            if isinstance(step.get(key), list):
                found = _find_step(step[key], step_id)
                if found is not None:
                    return found
    return None


def test_workflow_parses_and_has_top_level_shape(workflow):
    assert workflow["name"] == "supervise-run"
    assert workflow["description"] == "Launch, watch, auto-heal and report a Runpod training run."
    assert "run_id" in workflow["inputs"]
    assert workflow["inputs"]["run_id"]["type"] == "string"
    assert isinstance(workflow["steps"], list)


def test_repeat_supervise_step(workflow):
    supervise = _find_step(workflow["steps"], "supervise")
    assert supervise is not None
    repeat = supervise["repeat"]
    assert repeat["maxIterations"] == 25
    assert repeat["onMaxIterations"] == "pause"
    assert repeat["stopWhen"] == "health.terminal"


def test_health_watch_step(workflow):
    health = _find_step(workflow["steps"], "health")
    assert health is not None
    handler = health["watch"]["handler"]
    # The command must be the exact module invocation with NO templates.
    assert handler["command"] == "python -m overwatch.watch"
    assert "{{" not in handler["command"]
    config = handler["config"]
    # The run id travels via the runId config key.
    assert config["runId"] == "{{run_id}}"
    assert config["pollIntervalSec"] == 60
    assert config["commandTimeoutSec"] == 30
    assert config["idleTimeoutSec"] == 43200


def test_triage_step_uses_gpu_medic(workflow):
    triage = _find_step(workflow["steps"], "triage")
    assert triage is not None
    assert triage["agent"] == "gpu-medic"
    assert "smallest" in triage["prompt"].lower()


def test_postmortem_step_report_artifact(workflow):
    post = _find_step(workflow["steps"], "postmortem")
    assert post is not None
    assert post["agent"] == "gpu-medic"
    assert post["artifacts"]["report"] == ".overwatch/reports/{{run_id}}.md"


def test_passes_offline_validator():
    problems = validate_workflow.validate_file(WORKFLOW)
    assert problems == [], problems


def test_validator_rejects_template_in_command(tmp_path):
    bad = {
        "name": "x",
        "description": "d",
        "inputs": {"run_id": {"type": "string"}},
        "steps": [
            {
                "id": "health",
                "watch": {
                    "handler": {
                        "command": "python -m overwatch.watch {{run_id}}",
                        "config": {"runId": "{{run_id}}", "idleTimeoutSec": 43200},
                    }
                },
            }
        ],
    }
    path = os.path.join(str(tmp_path), "bad.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(bad, handle)
    problems = validate_workflow.validate_file(path)
    assert any("template" in p for p in problems)


def test_validator_requires_runid_and_idle_timeout(tmp_path):
    bad = {
        "name": "x",
        "description": "d",
        "inputs": {},
        "steps": [
            {
                "id": "health",
                "watch": {"handler": {"command": "python -m overwatch.watch", "config": {}}},
            }
        ],
    }
    path = os.path.join(str(tmp_path), "bad2.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(bad, handle)
    problems = validate_workflow.validate_file(path)
    assert any("runId" in p for p in problems)
    assert any("idleTimeoutSec" in p for p in problems)


def test_validator_cli_exit_codes(tmp_path):
    # Valid file -> 0.
    assert validate_workflow.main([WORKFLOW]) == 0
    # Invalid file -> non-zero.
    bad = os.path.join(str(tmp_path), "nope.json")
    with open(bad, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    assert validate_workflow.main([bad]) != 0
