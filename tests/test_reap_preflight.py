"""Tests for `overwatch reap` and `overwatch preflight` (overwatch.cli).

reap:
* `--confirm-json` returns {"skip": true} when nothing is idle;
* `--confirm-json` returns a confirm payload (with options stop/keep) when an
  idle Pod exists;
* the confirm payload / candidate list never includes a keep Pod;
* the non-dry-run stop path never stops a keep Pod.

preflight:
* parses a config, produces a VRAM estimate, and runs a 2-step CPU dry run.

Standard library only; fake backend; no network, no GPU.
"""

from __future__ import annotations

import io
import contextlib
import json
import os

import pytest

from overwatch import cli
from overwatch import runpod_client
from overwatch import state as state_mod
from tests.fixtures import seed_fleet


@pytest.fixture(autouse=True)
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    monkeypatch.setenv("OVERWATCH_STATE", os.path.join(str(tmp_path), "state.json"))
    monkeypatch.setenv(cli.SETUP_ENV, os.path.join(str(tmp_path), "setup.json"))
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    backend = runpod_client.FakeBackend(seed_fleet())
    runpod_client.set_backend(backend)
    yield backend
    runpod_client.set_backend(None)


def _capture(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = args.func(args)
    return rc, buf.getvalue()


# ----------------------------------------------------------------------
# reap
# ----------------------------------------------------------------------
def test_reap_confirm_json_skips_when_nothing_idle(fake_env):
    # Make every overwatch Pod map to a fresh live run -> nothing idle.
    import time

    state = state_mod.load_state()
    for pod in fake_env.list_pods():
        if pod.get("created_by") == "overwatch":
            run_id = (pod.get("env") or {}).get("OVERWATCH_RUN") or pod["id"]
            run = state_mod.new_run(run_id, pod_id=pod["id"], status="running")
            run["last_progress"] = time.time()
            run["keep"] = str((pod.get("env") or {}).get("OVERWATCH_KEEP", "")) == "1"
            state_mod.put_run(state, run)
    state_mod.save_state(state)

    args = cli.build_parser().parse_args(["reap", "--idle-minutes", "10", "--confirm-json"])
    rc, out = _capture(args)
    assert rc == 0
    payload = json.loads(out.strip())
    assert payload == {"skip": True}


def test_reap_confirm_json_returns_payload_when_idle(fake_env):
    # No live runs seeded -> the two non-keep overwatch Pods are orphaned/idle.
    args = cli.build_parser().parse_args(["reap", "--idle-minutes", "10", "--confirm-json"])
    rc, out = _capture(args)
    assert rc == 0
    payload = json.loads(out.strip())
    assert payload["skip"] is False
    assert payload["options"] == ["stop", "keep"]
    assert payload["candidates"]
    names = [c.get("name") for c in payload["candidates"]]
    # The keep Pod is never a candidate.
    assert "ow-run-keep" not in names
    # A foreign Pod is never a candidate.
    assert "someone-elses-pod" not in names


def test_reap_never_touches_keep_pod_in_stop_path(fake_env):
    # Stop path (non-dry-run): the keep Pod must survive.
    args = cli.build_parser().parse_args(["reap", "--idle-minutes", "0", "--json"])
    rc, out = _capture(args)
    assert rc == 0
    result = json.loads(out.strip())
    # The keep Pod id is never in the stopped list.
    assert "pod-ow-keep" not in result["stopped"]
    # The keep Pod is still RUNNING.
    keep = fake_env.get_pod("pod-ow-keep")
    assert keep is not None and keep["status"] == "RUNNING"


def test_reap_dry_run_lists_candidates(fake_env):
    args = cli.build_parser().parse_args(
        ["reap", "--idle-minutes", "10", "--dry-run", "--json"]
    )
    rc, out = _capture(args)
    assert rc == 0
    result = json.loads(out.strip())
    assert result["dry_run"] is True
    assert result["candidate_count"] >= 1


# ----------------------------------------------------------------------
# preflight
# ----------------------------------------------------------------------
def test_preflight_parses_config_and_runs_two_step_dry_run(tmp_path):
    cfg_path = os.path.join(str(tmp_path), "train.yaml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write("params_billion: 7\nbatch_size: 2\nseq_len: 2048\nmethod: lora\n")
    args = cli.build_parser().parse_args(["preflight", cfg_path, "--json"])
    rc, out = _capture(args)
    result = json.loads(out.strip())
    assert result["parse_ok"] is True
    assert result["vram_estimate_gb"] > 0
    assert result["dry_run"]["ok"] is True
    assert result["dry_run"]["steps_seen"] >= 1
    assert rc == 0


def test_preflight_bad_config_reports_parse_failure(tmp_path):
    bad = os.path.join(str(tmp_path), "bad.json")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("{ not valid json")
    args = cli.build_parser().parse_args(["preflight", bad, "--json"])
    rc, out = _capture(args)
    result = json.loads(out.strip())
    assert result["parse_ok"] is False
    assert "failed to parse" in result["parse_detail"]


def test_preflight_vram_estimate_full_vs_lora(tmp_path):
    full = os.path.join(str(tmp_path), "full.yaml")
    lora = os.path.join(str(tmp_path), "lora.yaml")
    with open(full, "w", encoding="utf-8") as fh:
        fh.write("params_billion: 13\nmethod: full\n")
    with open(lora, "w", encoding="utf-8") as fh:
        fh.write("params_billion: 13\nmethod: lora\n")
    full_est = cli._estimate_vram_gb({"params_billion": 13, "method": "full"})
    lora_est = cli._estimate_vram_gb({"params_billion": 13, "method": "lora"})
    assert full_est > lora_est
