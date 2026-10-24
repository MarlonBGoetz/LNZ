"""Tests for the Phase 4 Kiro wiring authored in FEAT-005.

Asserts, with stdlib only (no network, no third-party packages):

* Every JSON artifact parses: ``plugin.json``, ``mcp.json``, every hook in
  ``.kiro/hooks/*.json`` and ``.kiro/agents/gpu-medic.json``.
* ``plugin.json`` carries the plan's keywords and ``mcp.json`` the plan's two
  servers with the exact commands/args/env.
* The reaper hook (``reap-on-stop``) has the confirm / confirmCommand block with
  the ``reap --confirm-json`` command and ``stop``/``keep`` options.
* Each steering file has the correct ``inclusion`` frontmatter (and the right
  ``fileMatchPattern`` where applicable).
* Every skill directory named in the plan has a ``SKILL.md`` with ``name`` and
  ``description`` frontmatter.
"""

from __future__ import annotations

import glob
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

POWER = os.path.join(REPO, "gpu-overwatch")
PLUGIN = os.path.join(POWER, "plugin.json")
MCP = os.path.join(POWER, "mcp.json")
HOOKS_DIR = os.path.join(REPO, ".kiro", "hooks")
STEERING_DIR = os.path.join(REPO, ".kiro", "steering")
AGENTS_DIR = os.path.join(REPO, ".kiro", "agents")

# Skill directories named in the plan's directory-layout tree.
PLAN_SKILLS = [
    "setup",
    "launch-run",
    "triage-run",
    "gpu-sizing",
    "dataset-fanout",
    "teardown",
]

# Skills actually authored by now (setup lands in FEAT-006).
AUTHORED_SKILLS = [
    "launch-run",
    "triage-run",
    "gpu-sizing",
    "dataset-fanout",
    "teardown",
]


def _load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _frontmatter(text):
    """Return the raw YAML frontmatter block (between the first two ``---``)."""
    stripped = text.lstrip()
    assert stripped.startswith("---"), "file must start with a --- frontmatter block"
    body = stripped[3:]
    end = body.find("---")
    assert end != -1, "frontmatter must be closed with ---"
    return body[:end]


def _hook_files():
    return sorted(glob.glob(os.path.join(HOOKS_DIR, "*.json")))


# --------------------------------------------------------------------------
# Every JSON parses.
# --------------------------------------------------------------------------

def test_all_json_parses():
    targets = _hook_files() + [
        PLUGIN,
        MCP,
        os.path.join(AGENTS_DIR, "gpu-medic.json"),
    ]
    assert targets, "expected JSON artifacts to exist"
    for path in targets:
        data = _load_json(path)
        assert isinstance(data, dict), f"{path} should be a JSON object"


# --------------------------------------------------------------------------
# plugin.json / mcp.json manifests.
# --------------------------------------------------------------------------

def test_plugin_manifest():
    plugin = _load_json(PLUGIN)
    assert plugin["name"] == "gpu-overwatch"
    assert plugin["version"] == "0.1.0"
    assert "schema" in plugin["$schema"] and "plugin" in plugin["$schema"]
    expected_keywords = [
        "runpod",
        "gpu",
        "training",
        "mlops",
        "supervision",
        "fine-tuning",
        "datagen",
        "cost-control",
    ]
    assert plugin["keywords"] == expected_keywords


def test_mcp_manifest_servers():
    mcp = _load_json(MCP)
    servers = mcp["mcpServers"]
    assert set(servers) == {"runpod", "overwatch"}

    runpod = servers["runpod"]
    assert runpod["command"] == "npx"
    assert runpod["args"] == ["-y", "@runpod/mcp-server@latest"]
    assert "RUNPOD_API_KEY" in runpod["env"]

    overwatch = servers["overwatch"]
    assert overwatch["command"] == "python"
    assert overwatch["args"] == ["-m", "overwatch.server"]
    assert "RUNPOD_API_KEY" in overwatch["env"]


# --------------------------------------------------------------------------
# Hooks: triggers present, reaper confirm block verbatim.
# --------------------------------------------------------------------------

def test_hook_triggers_present():
    triggers = {_load_json(p).get("trigger") for p in _hook_files()}
    for required in (
        "SessionStart",
        "PreToolUse",
        "PostToolUse",
        "PostFileSave",
        "Stop",
        "SessionEnd",
    ):
        assert required in triggers, f"missing hook trigger {required}"


def test_guard_hook_matchers():
    hooks = {os.path.basename(p): _load_json(p) for p in _hook_files()}

    runpod = hooks["guard-runpod.json"]
    assert runpod["trigger"] == "PreToolUse"
    assert runpod["matcher"] == "@power-gpu-overwatch-runpod"
    assert runpod["action"]["command"] == "python -m overwatch.guard"

    launch = hooks["guard-launch.json"]
    assert launch["trigger"] == "PreToolUse"
    assert "run_launch" in launch["matcher"]
    assert "run_restart" in launch["matcher"]
    assert launch["action"]["command"].startswith("python -m overwatch.guard")


def test_fleet_brief_and_preflight_commands():
    hooks = {os.path.basename(p): _load_json(p) for p in _hook_files()}

    brief = hooks["fleet-brief.json"]
    assert brief["trigger"] == "SessionStart"
    assert brief["action"]["command"] == "python -m overwatch.cli brief"

    preflight = hooks["preflight-on-save.json"]
    assert preflight["trigger"] == "PostFileSave"
    assert "matcher" in preflight
    assert preflight["action"]["command"] == "python -m overwatch.cli preflight"


def test_start_supervision_is_agent_prompt():
    hook = _load_json(os.path.join(HOOKS_DIR, "start-supervision.json"))
    assert hook["trigger"] == "PostToolUse"
    assert "run_launch" in hook["matcher"]
    assert hook["action"]["type"] == "agent"
    assert "supervise" in hook["action"]["prompt"].lower()


def test_audit_log_appends_jsonl():
    hook = _load_json(os.path.join(HOOKS_DIR, "audit-log.json"))
    assert hook["trigger"] == "PostToolUse"
    assert ".overwatch/audit.jsonl" in hook["action"]["command"]


def test_session_summary_hook():
    hook = _load_json(os.path.join(HOOKS_DIR, "session-summary.json"))
    assert hook["trigger"] == "SessionEnd"


def test_reaper_hook_confirm_block():
    hook = _load_json(os.path.join(HOOKS_DIR, "reap-on-stop.json"))
    assert hook["trigger"] == "Stop"
    action = hook["action"]
    # The confirm / confirmCommand block is present.
    assert action.get("confirm") is True
    assert "confirmCommand" in action
    assert action["confirmCommand"] == "python -m overwatch.cli reap --idle-minutes 10 --confirm-json"
    assert "--confirm-json" in action["command"]
    assert action["options"] == ["stop", "keep"]


# --------------------------------------------------------------------------
# Steering frontmatter + fileMatchPattern.
# --------------------------------------------------------------------------

def test_gpu_policy_inclusion_always():
    fm = _frontmatter(_read_text(os.path.join(STEERING_DIR, "gpu-policy.md")))
    assert "inclusion: always" in fm


def test_training_contract_filematch():
    fm = _frontmatter(_read_text(os.path.join(STEERING_DIR, "training-contract.md")))
    assert "inclusion: fileMatch" in fm
    assert "**/train*.py" in fm
    assert "configs/**" in fm


def test_datagen_filematch():
    fm = _frontmatter(_read_text(os.path.join(STEERING_DIR, "datagen.md")))
    assert "inclusion: fileMatch" in fm
    assert "datagen/**" in fm


# --------------------------------------------------------------------------
# Skills: each authored skill dir has SKILL.md with name + description.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("skill", AUTHORED_SKILLS)
def test_skill_frontmatter(skill):
    path = os.path.join(POWER, "skills", skill, "SKILL.md")
    assert os.path.isfile(path), f"missing SKILL.md for {skill}"
    fm = _frontmatter(_read_text(path))
    assert "name:" in fm, f"{skill} SKILL.md missing name frontmatter"
    assert "description:" in fm, f"{skill} SKILL.md missing description frontmatter"


def test_gpu_sizing_has_reference_table():
    path = os.path.join(POWER, "skills", "gpu-sizing", "references", "sizing-table.md")
    assert os.path.isfile(path), "gpu-sizing must ship references/sizing-table.md"


def test_authored_skill_dirs_exist():
    # Every skill authored by this feature exists as a directory. ``setup`` is
    # authored in FEAT-006 and is intentionally excluded here.
    for skill in AUTHORED_SKILLS:
        assert os.path.isdir(
            os.path.join(POWER, "skills", skill)
        ), f"skill dir missing: {skill}"
    # The plan names six skills in total (setup + the five authored here plus
    # triage-run from FEAT-004); guard against a typo in the plan list.
    assert set(AUTHORED_SKILLS).issubset(set(PLAN_SKILLS))
