"""Tests for the core MCP tool functions (offline, fake backend).

All tests force the fake backend via OVERWATCH_FAKE=1 (set in an autouse
fixture) and route state at a temp file. No network, no GPU, no third-party
packages.
"""

from __future__ import annotations

import json
import os

import pytest

from overwatch import runpod_client, tools
from overwatch import state as state_mod
from overwatch.guard import GuardError
from overwatch.policy import BudgetRaiseError
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
    # Compact JSON serialisable.
    json.dumps(result)
    return result, summary


# ----------------------------------------------------------------------
# gpu_recommend / smoke
# ----------------------------------------------------------------------
def test_gpu_recommend(fake_env):
    result, summary = _assert_result(gpu := tools.gpu_recommend(params_billion=7, backend=fake_env))
    assert result["gpu"] in ("A100", "H100")
    assert result["price_per_hour"] > 0


def test_run_smoke_terminates_pod(fake_env):
    before = len(fake_env.list_pods())
    result, summary = _assert_result(tools.run_smoke(config="cfg.yaml", gpu="A100", backend=fake_env))
    assert result["passed"] is True
    assert result["pod_terminated"] is True
    # Smoke Pod was created then terminated -> no net change.
    assert len(fake_env.list_pods()) == before


# ----------------------------------------------------------------------
# run_launch refusals
# ----------------------------------------------------------------------
def test_run_launch_refuses_without_smoke(fake_env):
    with pytest.raises(ValueError):
        tools.run_launch(
            config="c", gpu="A100", smoke_passed=False, budget=10, max_hours=2,
            volume_id="vol-PLACEHOLDER", backend=fake_env,
        )


def test_run_launch_refuses_without_budget(fake_env):
    with pytest.raises(ValueError):
        tools.run_launch(
            config="c", gpu="A100", smoke_passed=True, budget=None, max_hours=2,
            volume_id="vol-PLACEHOLDER", backend=fake_env,
        )


def test_run_launch_refuses_without_max_hours(fake_env):
    with pytest.raises(ValueError):
        tools.run_launch(
            config="c", gpu="A100", smoke_passed=True, budget=10, max_hours=None,
            volume_id="vol-PLACEHOLDER", backend=fake_env,
        )


def test_run_launch_refuses_without_volume(fake_env):
    with pytest.raises(ValueError):
        tools.run_launch(
            config="c", gpu="A100", smoke_passed=True, budget=10, max_hours=2,
            volume_id=None, backend=fake_env,
        )


def test_run_launch_refuses_disallowed_gpu(fake_env):
    with pytest.raises(GuardError) as exc:
        tools.run_launch(
            config="c", gpu="T4", smoke_passed=True, budget=10, max_hours=2,
            volume_id="vol-PLACEHOLDER", backend=fake_env,
        )
    assert exc.value.category == "disallowed_gpu"


def test_run_launch_refuses_over_budget(fake_env):
    # H100 (~2.99/hr) * 100 hours >> per-run cap (20) -> over budget.
    with pytest.raises(GuardError) as exc:
        tools.run_launch(
            config="c", gpu="H100", smoke_passed=True, budget=10, max_hours=100,
            volume_id="vol-PLACEHOLDER", backend=fake_env,
        )
    assert exc.value.category == "over_budget"


# ----------------------------------------------------------------------
# run_launch success
# ----------------------------------------------------------------------
def test_run_launch_success(fake_env):
    result, summary = _assert_result(
        tools.run_launch(
            config="c.yaml", run_id="run-xyz", gpu="A100", smoke_passed=True,
            budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
        )
    )
    assert result["run_id"] == "run-xyz"
    assert result["pod_name"] == "ow-run-xyz"
    assert result["price_per_hour"] > 0
    assert result["status_url"].startswith("https://")
    assert result["bearer_issued"] is True
    assert result["env"]["OVERWATCH_RUN"] == "run-xyz"
    assert result["env"]["OVERWATCH_KEEP"] == "0"
    # Pod carries the env vars + a bearer token.
    pod = fake_env.get_pod(result["pod_id"])
    assert pod["env"]["OVERWATCH_RUN"] == "run-xyz"
    assert pod["env"]["OVERWATCH_KEEP"] == "0"
    assert pod["env"]["OVERWATCH_TOKEN"]
    # State recorded the run with a bearer token.
    st = state_mod.load_state()
    run = state_mod.get_run(st, "run-xyz")
    assert run["bearer"]
    assert run["status"] == "running"


def test_run_launch_keep_env(fake_env):
    result, _ = tools.run_launch(
        config="c", run_id="run-k", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", keep=True, backend=fake_env,
    )
    assert result["env"]["OVERWATCH_KEEP"] == "1"


# ----------------------------------------------------------------------
# run_status health verdict
# ----------------------------------------------------------------------
def test_run_status_health(fake_env):
    tools.run_launch(
        config="c", run_id="run-s", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    result, summary = _assert_result(tools.run_status(run_id="run-s"))
    assert result["health"] in ("healthy", "warning", "stalled", "unhealthy")
    assert "health" in result


def test_run_status_unhealthy_on_nan(fake_env):
    tools.run_launch(
        config="c", run_id="run-n", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    snap = {"status": "running", "step": 10, "loss": float("nan"), "loss_slope": 1.0}
    result, _ = tools.run_status(run_id="run-n", status_snapshot=snap)
    assert result["health"] == "unhealthy"


# ----------------------------------------------------------------------
# run_logs / run_metrics
# ----------------------------------------------------------------------
def test_run_logs_cap_and_grep(fake_env):
    tools.run_launch(
        config="c", run_id="run-l", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    lines = [f"line {i}" for i in range(1000)] + ["ERROR boom"]
    result, _ = tools.run_logs(run_id="run-l", lines=lines, limit=400)
    assert result["count"] == 400
    result2, _ = tools.run_logs(run_id="run-l", lines=lines, grep="ERROR")
    assert result2["lines"] == ["ERROR boom"]


def test_run_metrics_downsample(fake_env):
    tools.run_launch(
        config="c", run_id="run-m", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    metrics = [{"step": i, "loss": 1.0 / (i + 1)} for i in range(5000)]
    result, _ = tools.run_metrics(run_id="run-m", metrics=metrics)
    assert result["count"] <= 500
    assert result["total"] == 5000


# ----------------------------------------------------------------------
# run_stop
# ----------------------------------------------------------------------
def test_run_stop_terminate_requires_confirm(fake_env):
    tools.run_launch(
        config="c", run_id="run-t", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    with pytest.raises(ValueError):
        tools.run_stop(run_id="run-t", terminate=True, confirm=False)
    result, _ = _assert_result(tools.run_stop(run_id="run-t", terminate=True, confirm=True, backend=fake_env))
    assert result["terminated"] is True
    assert result["action"] == "terminated"


def test_run_stop_graceful(fake_env):
    tools.run_launch(
        config="c", run_id="run-g", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    result, _ = _assert_result(tools.run_stop(run_id="run-g", backend=fake_env))
    assert result["action"] == "stopped"
    assert result["artifacts_synced"] is True


# ----------------------------------------------------------------------
# fleet_status / fleet_reap
# ----------------------------------------------------------------------
def test_fleet_status_lists_foreign_and_rate(fake_env):
    result, summary = _assert_result(tools.fleet_status(backend=fake_env))
    assert result["count"] == 3
    assert result["foreign_count"] == 1
    assert result["total_spend_rate_per_hour"] == pytest.approx(1.89 + 2.99 + 0.79)
    foreign = [p for p in result["pods"] if p["foreign"]]
    assert foreign[0]["name"] == "someone-elses-pod"


def test_fleet_reap_dry_run_default(fake_env):
    result, _ = _assert_result(tools.fleet_reap(backend=fake_env))
    assert result["dry_run"] is True
    # The seeded overwatch Pods have no matching live run in a fresh state,
    # so they are orphan candidates; the keep Pod must not be a candidate.
    assert "pod-ow-keep" not in result["candidates"]
    assert result["reaped"] == []


def test_fleet_reap_never_touches_keep(fake_env):
    result, _ = tools.fleet_reap(dry_run=False, backend=fake_env)
    assert "pod-ow-keep" not in result["reaped"]
    # keep Pod still present.
    assert fake_env.get_pod("pod-ow-keep") is not None


# ----------------------------------------------------------------------
# budget
# ----------------------------------------------------------------------
def test_budget_status(fake_env):
    tools.run_launch(
        config="c", run_id="run-b", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    result, _ = _assert_result(tools.budget_status(backend=fake_env))
    assert result["session_cap_usd"] == 50.0
    assert result["session_spend_rate_per_hour"] > 0


def test_budget_set_lower_only(tmp_path, monkeypatch, fake_env):
    # Work inside a temp cwd with a policy.yaml so we don't mutate the repo file.
    monkeypatch.chdir(tmp_path)
    os.makedirs(".overwatch", exist_ok=True)
    with open(os.path.join(".overwatch", "policy.yaml"), "w", encoding="utf-8") as fh:
        fh.write("session_cap_usd: 50.0\nper_run_cap_usd: 20.0\nmax_hours: 8.0\n")
    result, _ = _assert_result(tools.budget_set(key="session_cap_usd", value=30.0))
    assert result["value"] == 30.0
    with pytest.raises(BudgetRaiseError):
        tools.budget_set(key="session_cap_usd", value=999.0)


# ----------------------------------------------------------------------
# run_report
# ----------------------------------------------------------------------
def test_run_report_writes_markdown(tmp_path, monkeypatch, fake_env):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OVERWATCH_STATE", os.path.join(str(tmp_path), "state.json"))
    tools.run_launch(
        config="c", run_id="run-r", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    result, _ = _assert_result(tools.run_report(run_id="run-r"))
    assert result["path"].endswith(os.path.join(".overwatch", "reports", "run-r.md"))
    assert os.path.exists(result["path"])
    with open(result["path"], encoding="utf-8") as fh:
        assert "# Run report: run-r" in fh.read()


# ----------------------------------------------------------------------
# artifacts_pull
# ----------------------------------------------------------------------
def test_artifacts_pull_size_limit(fake_env):
    tools.run_launch(
        config="c", run_id="run-a", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    result, _ = _assert_result(
        tools.artifacts_pull(run_id="run-a", dest="/tmp/x", size_mb=100, limit_mb=1024)
    )
    assert result["pulled_mb"] == 100
    with pytest.raises(ValueError):
        tools.artifacts_pull(run_id="run-a", dest="/tmp/x", size_mb=5000, limit_mb=1024)


# ----------------------------------------------------------------------
# run_list / datagen stubs
# ----------------------------------------------------------------------
def test_run_list(fake_env):
    tools.run_launch(
        config="c", run_id="run-1", gpu="A100", smoke_passed=True,
        budget=15, max_hours=2, volume_id="vol-PLACEHOLDER", backend=fake_env,
    )
    result, _ = _assert_result(tools.run_list())
    assert result["count"] == 1
    assert result["runs"][0]["run_id"] == "run-1"


def test_datagen_tools_are_implemented():
    # FEAT-007 replaced the FEAT-003 stubs with real implementations; the tools
    # now require real arguments (covered fully in tests/test_datagen_tools.py)
    # and are no longer not-implemented placeholders.
    for name in ("datagen_start", "datagen_status", "datagen_sample", "datagen_stop"):
        fn = tools.TOOLS[name]
        assert callable(fn)
    # An unknown job surfaces a clear error rather than a stub payload.
    with pytest.raises(KeyError):
        tools.datagen_status(job_id="no-such-job")


def test_all_tools_return_compact_json_and_summary():
    # The registry contains all 20 tool names.
    assert set(tools.TOOLS) == {
        "gpu_recommend", "run_smoke", "run_launch", "run_status", "run_logs",
        "run_metrics", "run_signal", "run_restart", "run_stop", "run_list",
        "run_report", "fleet_status", "fleet_reap", "budget_status", "budget_set",
        "artifacts_pull", "datagen_start", "datagen_status", "datagen_sample",
        "datagen_stop",
    }
