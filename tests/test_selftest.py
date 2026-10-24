"""Tests for the fully-offline self-test (overwatch.cli.run_self_test).

The self-test must:
* launch a local sidecar wrapping `tests/fake_train.py --fail nan@300`, drive
  `overwatch.watch.watch_once` against it, and detect the injected NaN;
* confirm the guard blocks an over-budget launch.

It must run with no network and no GPU, and must record its pass/fail in
setup.json when invoked via the CLI.
"""

from __future__ import annotations

import json
import os

import pytest

from overwatch import cli


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(cli.SETUP_ENV, os.path.join(str(tmp_path), "setup.json"))
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)


def test_self_test_detects_nan_and_blocks_over_budget():
    result = cli.run_self_test()
    assert result["nan_detected"] is True, result
    assert result["guard_blocked"] is True, result
    assert result["ok"] is True


def test_self_test_restores_state_env(monkeypatch):
    # The self-test temporarily points OVERWATCH_STATE at a temp file; it must
    # restore the previous value afterwards.
    monkeypatch.setenv("OVERWATCH_STATE", "/tmp/sentinel-state.json")
    cli.run_self_test()
    assert os.environ.get("OVERWATCH_STATE") == "/tmp/sentinel-state.json"


def test_selftest_cli_records_result_in_setup_json():
    args = cli.build_parser().parse_args(["selftest", "--json"])
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_selftest(args)
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is True
    setup = cli.load_setup()
    entry = setup["steps"]["self_test"]
    assert entry["status"] == "done"
    assert entry["passed"] is True
