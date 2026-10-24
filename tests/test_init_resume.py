"""Tests for the resumable, team-aware `overwatch init` (overwatch.cli).

Covers:
* init records each step's result in setup.json;
* a rerun skips steps already marked done;
* when project.yaml + policy.yaml carry team settings, a teammate run targets
  only the per-person steps (1, 2, 6, 7).

Standard library only; no network, no GPU.
"""

from __future__ import annotations

import json
import os

import pytest

from overwatch import cli
from overwatch import config as config_mod


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(cli.SETUP_ENV, os.path.join(str(tmp_path), "setup.json"))
    monkeypatch.setenv(cli.MCP_SETTINGS_ENV, os.path.join(str(tmp_path), "mcp.json"))
    monkeypatch.setenv("OVERWATCH_STATE", os.path.join(str(tmp_path), "state.json"))
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    # Run inside a temp CWD so policy.yaml/project.yaml are isolated.
    monkeypatch.chdir(tmp_path)
    os.makedirs(".overwatch", exist_ok=True)


def _write_solo_project():
    """Placeholder project.yaml/policy.yaml -> NOT team mode."""
    with open(os.path.join(".overwatch", "policy.yaml"), "w", encoding="utf-8") as fh:
        fh.write("session_cap_usd: 50.0\nper_run_cap_usd: 20.0\nmax_hours: 8.0\n"
                 "gpu_allowlist: [A100, H100]\n")
    with open(os.path.join(".overwatch", "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project: gpu-overwatch\nrunpod:\n  datacenter: US-OR-1\n"
                 "  volume_id: vol-PLACEHOLDER\n")


def _write_team_project():
    """Real datacenter + non-placeholder volume -> TEAM mode."""
    with open(os.path.join(".overwatch", "policy.yaml"), "w", encoding="utf-8") as fh:
        fh.write("session_cap_usd: 40.0\nper_run_cap_usd: 15.0\nmax_hours: 6.0\n"
                 "gpu_allowlist: [A100, H100]\n")
    with open(os.path.join(".overwatch", "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project: gpu-overwatch\nrunpod:\n  datacenter: EU-RO-1\n"
                 "  volume_id: vol-realteam01\n")


def test_init_records_steps_in_setup_json():
    _write_solo_project()
    args = cli.build_parser().parse_args(["init", "--json", "--assume-yes"])
    rc = cli.cmd_init(args)
    assert rc == 0
    setup = cli.load_setup()
    # All 8 steps attempted in solo mode; each has a recorded status.
    assert setup["team_mode"] is False
    recorded = setup["steps"]
    for step in cli.STEPS:
        assert step["key"] in recorded
        assert recorded[step["key"]]["status"] in ("done", "pending", "blocked", "skipped")
    # The offline self-test must have run and passed and been recorded.
    assert recorded["self_test"]["status"] == "done"
    assert recorded["self_test"]["passed"] is True
    # Workflows confirmed via --assume-yes.
    assert recorded["workflows"]["status"] == "done"


def test_init_rerun_skips_completed_steps():
    _write_solo_project()
    args = cli.build_parser().parse_args(["init", "--json", "--assume-yes"])
    cli.cmd_init(args)

    # Second run: completed steps are skipped.
    import io
    import contextlib

    args2 = cli.build_parser().parse_args(["init", "--json", "--assume-yes"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_init(args2)
    payload = json.loads(buf.getvalue())
    # self_test + workflows + policy_caps were done, so they must be skipped.
    assert 7 in payload["skipped"]  # self_test
    assert 6 in payload["skipped"]  # workflows
    assert 3 in payload["skipped"]  # policy_caps
    # A live-gated step that stayed pending is re-attempted (not skipped).
    assert 2 in payload["ran"]  # api_key (no key -> pending -> retried)


def test_team_mode_limits_teammate_to_person_steps():
    _write_team_project()
    assert cli._has_team_settings() is True
    args = cli.build_parser().parse_args(["init", "--json", "--assume-yes"])
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_init(args)
    payload = json.loads(buf.getvalue())
    assert payload["team_mode"] is True
    # Only per-person steps 1,2,6,7 are attempted (ran or skipped).
    touched = set(payload["ran"]) | set(payload["skipped"])
    assert touched == set(cli.TEAMMATE_STEP_IDS)
    # The shared/team steps 3,4,5,8 are NOT touched by the teammate.
    for shared in (3, 4, 5, 8):
        assert shared not in touched


def test_solo_mode_runs_all_steps():
    _write_solo_project()
    assert cli._has_team_settings() is False
    args = cli.build_parser().parse_args(["init", "--json", "--assume-yes"])
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_init(args)
    payload = json.loads(buf.getvalue())
    touched = set(payload["ran"]) | set(payload["skipped"])
    assert touched == {s["id"] for s in cli.STEPS}


def test_live_steps_reported_not_faked():
    _write_solo_project()
    args = cli.build_parser().parse_args(["init", "--json", "--assume-yes"])
    cli.cmd_init(args)
    setup = cli.load_setup()
    # Without a key/network, the live steps must be pending (never done/faked).
    assert setup["steps"]["api_key"]["status"] == "pending"
    assert setup["steps"]["live_smoke"]["status"] == "pending"
    assert setup["steps"]["live_smoke"]["live"] == "requires_credentials"
