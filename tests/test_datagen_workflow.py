"""Tests for the datagen.workflow.json recipe (offline, stdlib only)."""

from __future__ import annotations

import json
import os

import pytest

from overwatch import validate_workflow


@pytest.fixture()
def workflow(repo_root):
    path = os.path.join(repo_root, ".kiro", "workflows", "datagen.workflow.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle), path


def _all_steps(steps):
    out = []
    for step in steps:
        out.append(step)
        for key in ("steps", "do", "body"):
            if isinstance(step.get(key), list):
                out.extend(_all_steps(step[key]))
    return out


def test_datagen_workflow_parses(workflow):
    data, _ = workflow
    assert data["name"] == "datagen"
    assert isinstance(data["description"], str) and data["description"]
    assert "job_id" in data["inputs"]


def test_datagen_workflow_has_watch_qa_teardown(workflow):
    data, _ = workflow
    steps = _all_steps(data["steps"])
    ids = {s.get("id") for s in steps}
    # a watch on job progress, a QA step on each new sample, a teardown step.
    assert "progress" in ids  # the watch step
    assert "qa" in ids
    assert "teardown" in ids

    # The watch step uses the command-watch contract.
    watch = next(s for s in steps if s.get("id") == "progress")
    handler = watch["watch"]["handler"]
    assert handler["command"] == "python -m overwatch.watch"
    assert "{{" not in handler["command"]  # no templates baked into the command
    assert handler["config"]["runId"] == "{{job_id}}"
    assert handler["config"]["idleTimeoutSec"] == 43200

    # The teardown step writes a report artifact.
    teardown = next(s for s in steps if s.get("id") == "teardown")
    assert teardown["artifacts"]["report"].endswith(".md")


def test_datagen_workflow_passes_validate_workflow(workflow):
    data, path = workflow
    assert validate_workflow.validate(data) == []
    assert validate_workflow.validate_file(path) == []
    assert validate_workflow.main([path]) == 0
