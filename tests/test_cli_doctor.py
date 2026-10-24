"""Tests for `overwatch doctor` (overwatch.cli).

Covers the acceptance criteria:
* `doctor --json` emits valid JSON with a status per check and a fix line on
  every failing check;
* `doctor --brief` suggests /gpu-setup when setup.json is incomplete;
* the Workflows check reports needs_confirm (doctor cannot detect the toggle).

Standard library only; no network, no GPU.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from overwatch import cli

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


@pytest.fixture(autouse=True)
def isolated_setup(tmp_path, monkeypatch):
    """Route setup.json + mcp.json + state at temp paths; no key by default."""
    monkeypatch.setenv(cli.SETUP_ENV, os.path.join(str(tmp_path), "setup.json"))
    monkeypatch.setenv(cli.MCP_SETTINGS_ENV, os.path.join(str(tmp_path), "mcp.json"))
    monkeypatch.setenv("OVERWATCH_STATE", os.path.join(str(tmp_path), "state.json"))
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.setenv("OVERWATCH_FAKE", "1")


def _run_cli(args, extra_env=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-m", "overwatch.cli", *args],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO,
        timeout=60,
    )
    return proc


def test_doctor_json_is_valid_with_status_and_fixes():
    args = cli.build_parser().parse_args(["doctor", "--json"])
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_doctor(args)
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert "checks" in payload and isinstance(payload["checks"], list)
    assert payload["checks"], "expected at least one check"
    names = {c["name"] for c in payload["checks"]}
    # Core checks are present.
    for expected in ("python", "node", "runpod_api_key", "power_installed",
                     "policy_caps", "workflows", "self_test"):
        assert expected in names
    # Every check has a status; every FAILING check has a non-empty fix.
    for c in payload["checks"]:
        assert c["status"] in ("ok", "fail")
        if c["status"] == "fail":
            assert c.get("fix"), f"failing check {c['name']} must have a fix line"


def test_doctor_json_subprocess_emits_single_json_line():
    proc = _run_cli(["doctor", "--json"])
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert "checks" in payload


def test_api_key_masked_last_four_only():
    # A set key must be shown masked (last 4 chars only), never in full.
    secret = "sk-SUPERSECRET-ABCD"
    chk = None
    import os as _os

    old = _os.environ.get("RUNPOD_API_KEY")
    _os.environ["RUNPOD_API_KEY"] = secret
    try:
        chk = cli.check_api_key(probe=False)
    finally:
        if old is None:
            _os.environ.pop("RUNPOD_API_KEY", None)
        else:
            _os.environ["RUNPOD_API_KEY"] = old
    assert "SUPERSECRET" not in chk["detail"]
    assert "ABCD" in chk["detail"]  # last 4 shown


def test_doctor_brief_suggests_gpu_setup_when_incomplete():
    args = cli.build_parser().parse_args(["doctor", "--brief"])
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_doctor(args)
    assert rc == 0
    out = buf.getvalue()
    assert "incomplete" in out
    assert "/gpu-setup" in out


def test_doctor_workflows_needs_confirm():
    checks = cli.collect_checks()
    wf = next(c for c in checks if c["name"] == "workflows")
    assert wf.get("needs_confirm") is True
    # Full doctor output includes the "? Workflows enabled? Confirm" prompt.
    args = cli.build_parser().parse_args(["doctor"])
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_doctor(args)
    assert "? Workflows enabled?" in buf.getvalue()


def test_python_m_overwatch_dispatches_to_cli():
    # `python -m overwatch doctor --brief` must behave like the cli entry.
    proc = _run_cli([])  # no-op guard: ensure cli import works
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "overwatch", "doctor", "--brief"],
        text=True, capture_output=True, env=env, cwd=REPO, timeout=60,
    )
    assert proc.returncode == 0
    assert "gpu-overwatch" in proc.stdout
