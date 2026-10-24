"""The ``overwatch`` command-line interface (Phase 4b: Guided setup).

Subcommands (all stdlib only, no network, no GPU required to import or run the
offline paths)::

    overwatch init        # guided 8-step setup, resumable via setup.json
    overwatch doctor      # environment health check (--brief, --json)
    overwatch brief       # SessionStart fleet brief (--spend-summary)
    overwatch reap        # idle-Pod reaper (--idle-minutes N, --confirm-json)
    overwatch preflight   # config parse + VRAM estimate + 2-step CPU dry run
    overwatch audit       # append a PostToolUse event to an audit log
    overwatch selftest    # run the offline self-test directly

Both ``python -m overwatch`` and ``python -m overwatch.cli`` dispatch here (see
``overwatch/__main__.py``), and the ``overwatch`` console-script entry point in
``pyproject.toml`` resolves to :func:`main`.

Design rules for ``init`` / ``doctor`` (from the plan's Guided-setup section):

* **Resumable** -- every finished step is recorded in ``.overwatch/setup.json``
  so a rerun skips what is already done.
* **Team-aware** -- when ``project.yaml`` + ``policy.yaml`` already carry team
  settings, a teammate only runs the per-person steps (1, 2, 6, 7).
* **No secrets in chat** -- the API key is read from the ``RUNPOD_API_KEY``
  environment variable; only its last 4 characters are ever printed.
* **Honest checks** -- steps that need live Runpod (API reachability, datacenter
  stock, volume create, live smoke) are only performed if credentials/network
  are present; otherwise they are reported as needing credentials/GPUs and are
  **never** faked.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import config as config_mod
from . import guard as guard_mod
from . import state as state_mod
from . import tools as tools_mod
from .policy import Policy

# ----------------------------------------------------------------------
# paths / constants
# ----------------------------------------------------------------------
OVERWATCH_DIR = ".overwatch"
SETUP_PATH = os.path.join(OVERWATCH_DIR, "setup.json")
POLICY_PATH = os.path.join(OVERWATCH_DIR, "policy.yaml")
PROJECT_PATH = os.path.join(OVERWATCH_DIR, "project.yaml")
API_KEY_ENV = "RUNPOD_API_KEY"
SETUP_ENV = "OVERWATCH_SETUP"  # test override for setup.json path
MCP_SETTINGS_ENV = "OVERWATCH_MCP_SETTINGS"  # test override for mcp.json path

# The 8 setup steps (ids match the plan's table; "live" steps need Runpod).
# "scope": "person" steps are run by every teammate; "team" steps are shared
# config that a teammate inherits once a lead has done them.
STEPS: List[Dict[str, Any]] = [
    {"id": 1, "key": "install_power", "title": "Install the gpu-overwatch Power",
     "scope": "person", "live": False},
    {"id": 2, "key": "api_key", "title": "Set RUNPOD_API_KEY and verify reachability",
     "scope": "person", "live": True},
    {"id": 3, "key": "policy_caps", "title": "Set budget caps in policy.yaml",
     "scope": "team", "live": False},
    {"id": 4, "key": "datacenter_gpu", "title": "Choose datacenter + GPU allowlist",
     "scope": "team", "live": True},
    {"id": 5, "key": "network_volume", "title": "Create/record the network volume",
     "scope": "team", "live": True},
    {"id": 6, "key": "workflows", "title": "Enable Workflows in Kiro",
     "scope": "person", "live": False},
    {"id": 7, "key": "self_test", "title": "Run the free offline self-test",
     "scope": "person", "live": False},
    {"id": 8, "key": "live_smoke", "title": "Run a live smoke on a real GPU",
     "scope": "team", "live": True},
]

# Steps a teammate runs when the project already carries team settings.
TEAMMATE_STEP_IDS = [1, 2, 6, 7]


# ----------------------------------------------------------------------
# setup.json helpers
# ----------------------------------------------------------------------
def setup_path() -> str:
    """Resolve the setup.json path, honouring ``OVERWATCH_SETUP`` (tests)."""
    return os.environ.get(SETUP_ENV, SETUP_PATH)


def load_setup(path: Optional[str] = None) -> Dict[str, Any]:
    """Load setup.json (an empty skeleton when missing)."""
    target = path or setup_path()
    if not os.path.exists(target):
        return {"version": 1, "steps": {}, "team_mode": False}
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "steps": {}, "team_mode": False}
    data.setdefault("version", 1)
    data.setdefault("steps", {})
    data.setdefault("team_mode", False)
    return data


def save_setup(data: Dict[str, Any], path: Optional[str] = None) -> None:
    """Atomically persist setup.json."""
    target = path or setup_path()
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)


def _record_step(
    setup: Dict[str, Any],
    step: Dict[str, Any],
    status: str,
    detail: str = "",
    **extra: Any,
) -> None:
    """Record a step's outcome in the setup dict (in place)."""
    entry = {
        "id": step["id"],
        "key": step["key"],
        "title": step["title"],
        "status": status,  # done | pending | blocked | skipped
        "detail": detail,
        "at": time.time(),
    }
    entry.update(extra)
    setup.setdefault("steps", {})[step["key"]] = entry


def _step_done(setup: Dict[str, Any], key: str) -> bool:
    return (setup.get("steps", {}).get(key, {}) or {}).get("status") == "done"


# ----------------------------------------------------------------------
# environment probes (honest; never fabricate success)
# ----------------------------------------------------------------------
def _mask_key(value: Optional[str]) -> str:
    """Show only the last 4 characters of a secret."""
    if not value:
        return ""
    v = str(value)
    if len(v) <= 4:
        return "*" * len(v)
    return "****" + v[-4:]


def check_python() -> Dict[str, Any]:
    ok = sys.version_info >= (3, 10)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return {
        "name": "python",
        "ok": ok,
        "detail": f"Python {ver}",
        "fix": "" if ok else "Install Python 3.10+ and re-run from that interpreter.",
    }


def _node_version() -> Optional[Tuple[int, int, int]]:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.check_output([node, "--version"], stderr=subprocess.DEVNULL, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return None
    text = out.decode("utf-8", "replace").strip().lstrip("v")
    parts = text.split(".")
    try:
        nums = [int(parts[i]) for i in range(3)]
    except (IndexError, ValueError):
        return None
    return (nums[0], nums[1], nums[2])


def check_node() -> Dict[str, Any]:
    ver = _node_version()
    if ver is None:
        return {
            "name": "node",
            "ok": False,
            "detail": "Node not found on PATH",
            "fix": "Install Node 20+ (the Runpod MCP server runs via npx).",
        }
    ok = ver[0] >= 20
    return {
        "name": "node",
        "ok": ok,
        "detail": f"Node v{ver[0]}.{ver[1]}.{ver[2]}",
        "fix": "" if ok else "Upgrade to Node 20+ (the Runpod MCP server needs it).",
    }


def check_overwatch_importable() -> Dict[str, Any]:
    try:
        import overwatch  # noqa: F401

        return {"name": "overwatch", "ok": True, "detail": "overwatch package importable", "fix": ""}
    except Exception as exc:  # pragma: no cover - import always works here
        return {
            "name": "overwatch",
            "ok": False,
            "detail": f"import failed: {exc}",
            "fix": "Run from the repo root or `pip install -e .` so `overwatch` is importable.",
        }


def _runpod_reachable(api_key: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """A read-only reachability probe against the Runpod REST API.

    Returns ``(ok, detail)``. Never raises; any transport failure (including no
    network, as in the sandbox) is reported as not-reachable with a reason.
    """
    url = "https://rest.runpod.io/v1/pods"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
        return (200 <= code < 500), f"Runpod API responded ({code})"
    except urllib.error.HTTPError as exc:
        # A 401/403 still proves reachability (the endpoint answered).
        return (exc.code in (401, 403)) is False and (200 <= exc.code < 500), (
            f"Runpod API responded ({exc.code})"
        )
    except (urllib.error.URLError, OSError) as exc:
        return False, f"Runpod API unreachable ({exc})"


def check_api_key(*, probe: bool = True) -> Dict[str, Any]:
    """Check RUNPOD_API_KEY is set; optionally probe reachability (live)."""
    key = os.environ.get(API_KEY_ENV)
    if not key:
        return {
            "name": "runpod_api_key",
            "ok": False,
            "detail": "RUNPOD_API_KEY is not set",
            "fix": "Export RUNPOD_API_KEY (from the Runpod console) in your shell env; never paste it in chat.",
            "live": "unavailable",
        }
    masked = _mask_key(key)
    result = {
        "name": "runpod_api_key",
        "ok": True,
        "detail": f"RUNPOD_API_KEY set ({masked})",
        "fix": "",
    }
    if not probe:
        result["live"] = "skipped"
        return result
    reachable, reason = _runpod_reachable(key)
    if reachable:
        result["live"] = "ok"
        result["detail"] = f"RUNPOD_API_KEY set ({masked}); {reason}"
    else:
        # Key present but reachability could not be confirmed: report honestly,
        # do NOT mark the live part as success.
        result["live"] = "unavailable"
        result["detail"] = f"RUNPOD_API_KEY set ({masked}); {reason}"
        result["fix"] = "Confirm network access to rest.runpod.io and that the key is valid."
    return result


def _mcp_settings_path() -> str:
    override = os.environ.get(MCP_SETTINGS_ENV)
    if override:
        return override
    return os.path.expanduser(os.path.join("~", ".kiro", "settings", "mcp.json"))


def check_power_installed() -> Dict[str, Any]:
    """Check the Power is installed by looking in ~/.kiro/settings/mcp.json."""
    path = _mcp_settings_path()
    fix = ("Install the gpu-overwatch Power in Kiro (adds the runpod + overwatch "
           "MCP servers to ~/.kiro/settings/mcp.json); then run /gpu-setup.")
    if not os.path.exists(path):
        return {
            "name": "power_installed",
            "ok": False,
            "detail": f"no MCP settings at {path}",
            "fix": fix,
        }
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "name": "power_installed",
            "ok": False,
            "detail": f"could not read {path}: {exc}",
            "fix": fix,
        }
    servers = data.get("mcpServers") or data.get("servers") or {}
    has_overwatch = "overwatch" in servers
    has_runpod = "runpod" in servers
    ok = bool(has_overwatch and has_runpod)
    detail = f"mcp.json servers: {sorted(servers.keys())}"
    return {
        "name": "power_installed",
        "ok": ok,
        "detail": detail,
        "fix": "" if ok else fix,
    }


def check_policy_caps() -> Dict[str, Any]:
    """Check policy.yaml exists and carries sane (lowered-from-default) caps."""
    if not os.path.exists(POLICY_PATH):
        return {
            "name": "policy_caps",
            "ok": False,
            "detail": "no .overwatch/policy.yaml",
            "fix": "Run `overwatch init` (step 3) to write policy.yaml with your budget caps.",
        }
    policy = Policy.load(POLICY_PATH)
    ok = policy.session_cap_usd > 0 and policy.per_run_cap_usd > 0 and policy.max_hours > 0
    detail = (
        f"caps: session ${policy.session_cap_usd:.0f}, per-run "
        f"${policy.per_run_cap_usd:.0f}, {policy.max_hours:.0f}h"
    )
    return {
        "name": "policy_caps",
        "ok": ok,
        "detail": detail,
        "fix": "" if ok else "Set positive session_cap_usd/per_run_cap_usd/max_hours in policy.yaml.",
    }


def _project_data() -> Dict[str, Any]:
    if not os.path.exists(PROJECT_PATH):
        return {}
    try:
        data = config_mod.load_config(PROJECT_PATH)
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def check_datacenter_gpu() -> Dict[str, Any]:
    """Check a datacenter + a GPU allowlist are chosen (offline part)."""
    project = _project_data()
    runpod = project.get("runpod") or {}
    datacenter = runpod.get("datacenter")
    policy = Policy.load(POLICY_PATH) if os.path.exists(POLICY_PATH) else Policy()
    allowlist = policy.gpu_allowlist
    chosen = bool(datacenter) and datacenter != "US-OR-1" and bool(allowlist)
    # A placeholder datacenter means the user has not actually chosen one.
    detail = f"datacenter={datacenter!r}, gpu_allowlist={allowlist}"
    fix = ("Pick a real datacenter in project.yaml and confirm the GPU allowlist "
           "(live stock check needs RUNPOD_API_KEY + network).")
    return {
        "name": "datacenter_gpu",
        "ok": chosen,
        "detail": detail,
        "fix": "" if chosen else fix,
    }


def check_network_volume() -> Dict[str, Any]:
    """Check a network volume id is recorded (not the committed placeholder)."""
    project = _project_data()
    runpod = project.get("runpod") or {}
    volume_id = runpod.get("volume_id")
    ok = bool(volume_id) and volume_id != "vol-PLACEHOLDER"
    fix = ("Create a network volume on Runpod (needs credentials) and record its id "
           "as runpod.volume_id in project.yaml.")
    return {
        "name": "network_volume",
        "ok": ok,
        "detail": f"volume_id={volume_id!r}",
        "fix": "" if ok else fix,
    }


def check_self_test(setup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Report the recorded self-test result from setup.json."""
    setup = setup if setup is not None else load_setup()
    entry = setup.get("steps", {}).get("self_test", {}) or {}
    status = entry.get("status")
    if status == "done":
        return {
            "name": "self_test",
            "ok": True,
            "detail": entry.get("detail") or "self-test passed",
            "fix": "",
        }
    return {
        "name": "self_test",
        "ok": False,
        "detail": entry.get("detail") or "self-test not run",
        "fix": "Run `overwatch selftest` (or `overwatch init`) to run the offline self-test.",
    }


def check_workflows(setup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Workflows toggle cannot be detected; report that the user must confirm.

    doctor prints a ``? Workflows enabled? Confirm ...`` line. The recorded
    confirmation (from ``init``) lives in setup.json.
    """
    setup = setup if setup is not None else load_setup()
    entry = setup.get("steps", {}).get("workflows", {}) or {}
    confirmed = entry.get("status") == "done"
    return {
        "name": "workflows",
        "ok": confirmed,
        "needs_confirm": True,
        "detail": "Workflows enabled (confirmed)" if confirmed else "cannot detect Workflows toggle",
        "fix": "" if confirmed else "Enable Workflows in Kiro settings, then confirm with `overwatch init`.",
    }


# ----------------------------------------------------------------------
# doctor
# ----------------------------------------------------------------------
def collect_checks() -> List[Dict[str, Any]]:
    """Run every doctor check and return a list of check dicts."""
    setup = load_setup()
    return [
        check_python(),
        check_node(),
        check_overwatch_importable(),
        check_api_key(probe=True),
        check_power_installed(),
        check_policy_caps(),
        check_datacenter_gpu(),
        check_network_volume(),
        check_workflows(setup),
        check_self_test(setup),
    ]


def _setup_complete(checks: List[Dict[str, Any]]) -> bool:
    return all(c.get("ok") for c in checks)


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = collect_checks()
    complete = _setup_complete(checks)

    if args.json:
        payload = {
            "ok": complete,
            "complete": complete,
            "checks": [
                {
                    "name": c["name"],
                    "status": "ok" if c.get("ok") else "fail",
                    "detail": c.get("detail", ""),
                    "fix": c.get("fix", ""),
                    **({"live": c["live"]} if "live" in c else {}),
                    **({"needs_confirm": True} if c.get("needs_confirm") else {}),
                }
                for c in checks
            ],
        }
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return 0 if complete else 0  # doctor always exits 0 (it is a report)

    if args.brief:
        n_ok = sum(1 for c in checks if c.get("ok"))
        total = len(checks)
        if complete:
            sys.stdout.write(f"gpu-overwatch: setup complete ({n_ok}/{total} checks ok)\n")
        else:
            failing = [c["name"] for c in checks if not c.get("ok")]
            sys.stdout.write(
                f"gpu-overwatch: setup incomplete ({n_ok}/{total} ok). "
                f"Needs: {', '.join(failing)}. Run /gpu-setup to finish.\n"
            )
        return 0

    # Full, human-readable report (mirrors the plan's illustrative format).
    sys.stdout.write("overwatch doctor\n")
    sys.stdout.write("================\n")
    for c in checks:
        mark = "ok  " if c.get("ok") else "FAIL"
        line = f"[{mark}] {c['name']}: {c.get('detail', '')}"
        sys.stdout.write(line + "\n")
        if c.get("needs_confirm") and not c.get("ok"):
            sys.stdout.write(
                "       ? Workflows enabled? Confirm in Kiro settings, then re-run (doctor cannot detect this).\n"
            )
        if not c.get("ok") and c.get("fix"):
            sys.stdout.write(f"       fix: {c['fix']}\n")
    sys.stdout.write("\n")
    if complete:
        sys.stdout.write("All checks passed. You are ready to launch supervised runs.\n")
    else:
        sys.stdout.write("Setup incomplete. Run /gpu-setup (or `overwatch init`) to finish.\n")
    return 0


# ----------------------------------------------------------------------
# self-test (offline): sidecar + fake_train nan@300 + guard over-budget block
# ----------------------------------------------------------------------
def _fake_train_path() -> str:
    """Path to the CPU fake trainer used by the self-test."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    return os.path.join(repo, "tests", "fake_train.py")


def run_self_test() -> Dict[str, Any]:
    """Fully-offline self-test.

    1. Launch a local sidecar wrapping ``tests/fake_train.py --fail nan@300``.
    2. Drive :func:`overwatch.watch.watch_once` against it and assert the NaN is
       reported as ``new-activity`` with ``event == "nan_or_inf_loss"``.
    3. Assert the guard blocks an over-budget launch.

    Returns a result dict ``{ok, nan_detected, guard_blocked, detail}``. Never
    raises; any failure is captured in the result. No network, no GPU.
    """
    import tempfile

    from . import watch as watch_mod
    from .policy import Policy as _Policy
    from .sidecar import server as ow_server
    from .sidecar.runner import Runner

    result: Dict[str, Any] = {
        "ok": False,
        "nan_detected": False,
        "guard_blocked": False,
        "detail": "",
    }

    token = "selftest-token"
    run_id = "selftest-nan"
    tmp = tempfile.mkdtemp(prefix="ow-selftest-")
    state_file = os.path.join(tmp, "state.json")
    prev_state_env = os.environ.get(state_mod.STATE_ENV)
    os.environ[state_mod.STATE_ENV] = state_file

    runner = None
    server = None
    try:
        metrics = os.path.join(tmp, "metrics.ndjson")
        cmd = [sys.executable, _fake_train_path(), "--sleep", "0.02", "--fail", "nan@300"]
        runner = Runner(
            cmd,
            policy=_Policy(),
            run_id=run_id,
            metrics_path=metrics,
            ckpt_dir=tmp,
            checkpoint_interval_seconds=1000.0,
            gpu_sample_interval=1000.0,
        )
        server = ow_server.build_server(runner, host="127.0.0.1", port=0, token=token)
        port = server.server_address[1]
        ow_server.serve_in_thread(server)
        runner.start()
        runner.wait(timeout=15)
        time.sleep(0.2)

        # Seed a run pointing at the local sidecar so watch can resolve it.
        state = state_mod.load_state(state_file)
        run = state_mod.new_run(run_id, pod_id=f"pod-{run_id}", status="running", bearer=token)
        run["sidecar_url"] = f"http://127.0.0.1:{port}"
        state_mod.put_run(state, run)
        state_mod.save_state(state, state_file)

        watch_result = watch_mod.watch_once(
            {"cursor": {}, "config": {"runId": run_id, "idleTimeoutSec": 43200}}
        )
        nan_detected = (
            watch_result.get("result") == "new-activity"
            and watch_result.get("event") == "nan_or_inf_loss"
        )
        result["nan_detected"] = bool(nan_detected)

        # Guard: an over-budget launch must be blocked. Use a tight policy so a
        # realistic price is clearly over the per-run cap.
        tight = _Policy(session_cap_usd=1.0, per_run_cap_usd=1.0, max_hours=8.0)
        guard_blocked = False
        try:
            guard_mod.check(
                {
                    "tool": "run_launch",
                    "args": {
                        "gpu": "A100",
                        "smoke_passed": True,
                        "price_per_hour": 2.99,
                        "max_hours": 8.0,
                    },
                },
                policy=tight,
                state={"runs": {}},
            )
        except guard_mod.GuardError as exc:
            guard_blocked = exc.category == guard_mod.OVER_BUDGET
        result["guard_blocked"] = bool(guard_blocked)

        result["ok"] = bool(nan_detected and guard_blocked)
        result["detail"] = (
            f"nan_detected={result['nan_detected']}, guard_blocked={result['guard_blocked']}"
        )
    except Exception as exc:  # noqa: BLE001 - self-test must never crash init/doctor
        result["detail"] = f"self-test error: {exc}"
    finally:
        try:
            if runner is not None:
                runner.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            if server is not None:
                server.shutdown()
                server.server_close()
        except Exception:  # noqa: BLE001
            pass
        if prev_state_env is None:
            os.environ.pop(state_mod.STATE_ENV, None)
        else:
            os.environ[state_mod.STATE_ENV] = prev_state_env
    return result


def cmd_selftest(args: argparse.Namespace) -> int:
    result = run_self_test()
    # Record the outcome in setup.json too (step 7).
    setup = load_setup()
    step = next(s for s in STEPS if s["key"] == "self_test")
    _record_step(
        setup,
        step,
        "done" if result["ok"] else "blocked",
        result["detail"],
        passed=result["ok"],
    )
    save_setup(setup)
    if args.json:
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    else:
        verdict = "PASSED" if result["ok"] else "FAILED"
        sys.stdout.write(f"self-test {verdict}: {result['detail']}\n")
    return 0 if result["ok"] else 1


# ----------------------------------------------------------------------
# init (resumable, team-aware)
# ----------------------------------------------------------------------
def _has_team_settings() -> bool:
    """Whether project.yaml + policy.yaml already carry shared team settings.

    True when a real datacenter + a non-placeholder volume are recorded and the
    budget caps exist. In that case a teammate only runs per-person steps.
    """
    if not (os.path.exists(PROJECT_PATH) and os.path.exists(POLICY_PATH)):
        return False
    project = _project_data()
    runpod = project.get("runpod") or {}
    datacenter = runpod.get("datacenter")
    volume_id = runpod.get("volume_id")
    has_dc = bool(datacenter) and datacenter != "US-OR-1"
    has_vol = bool(volume_id) and volume_id != "vol-PLACEHOLDER"
    return bool(has_dc and has_vol)


def _steps_for_run(team_mode: bool) -> List[Dict[str, Any]]:
    if team_mode:
        return [s for s in STEPS if s["id"] in TEAMMATE_STEP_IDS]
    return list(STEPS)


def _run_step(step: Dict[str, Any], setup: Dict[str, Any], args: argparse.Namespace) -> None:
    """Perform one setup step, recording the outcome. Honest about live steps."""
    key = step["key"]
    emit = _init_emit(args)

    if key == "install_power":
        chk = check_power_installed()
        _record_step(setup, step, "done" if chk["ok"] else "pending", chk["detail"])
        emit(step, chk["ok"], chk["detail"], chk.get("fix"))

    elif key == "api_key":
        # Live step: only confirm reachability if a key + network are present.
        chk = check_api_key(probe=True)
        if chk["ok"] and chk.get("live") == "ok":
            _record_step(setup, step, "done", chk["detail"])
            emit(step, True, chk["detail"], None)
        elif chk["ok"]:
            # Key set but reachability not confirmed -> honest "needs live".
            _record_step(setup, step, "pending", chk["detail"], live="unavailable")
            emit(step, False, chk["detail"] + " (live reachability not confirmed)", chk.get("fix"))
        else:
            _record_step(setup, step, "pending", chk["detail"], live="unavailable")
            emit(step, False, chk["detail"], chk.get("fix"))

    elif key == "policy_caps":
        chk = check_policy_caps()
        _record_step(setup, step, "done" if chk["ok"] else "pending", chk["detail"])
        emit(step, chk["ok"], chk["detail"], chk.get("fix"))

    elif key == "datacenter_gpu":
        chk = check_datacenter_gpu()
        # The offline part (a choice recorded) can pass; live stock needs creds.
        status = "done" if chk["ok"] else "pending"
        _record_step(setup, step, status, chk["detail"], live_stock="requires_credentials")
        detail = chk["detail"]
        if not chk["ok"]:
            detail += " (live datacenter stock check requires RUNPOD_API_KEY + network)"
        emit(step, chk["ok"], detail, chk.get("fix"))

    elif key == "network_volume":
        chk = check_network_volume()
        status = "done" if chk["ok"] else "pending"
        _record_step(setup, step, status, chk["detail"], live_create="requires_credentials")
        detail = chk["detail"]
        if not chk["ok"]:
            detail += " (creating a volume requires RUNPOD_API_KEY + network)"
        emit(step, chk["ok"], detail, chk.get("fix"))

    elif key == "workflows":
        # Cannot detect; ASK the user to confirm (unless --assume-yes).
        confirmed = bool(getattr(args, "assume_yes", False))
        if not confirmed and sys.stdin and sys.stdin.isatty():
            sys.stdout.write("? Workflows enabled in Kiro settings? [y/N] ")
            sys.stdout.flush()
            try:
                answer = sys.stdin.readline().strip().lower()
            except Exception:  # noqa: BLE001
                answer = ""
            confirmed = answer in ("y", "yes")
        if confirmed:
            _record_step(setup, step, "done", "Workflows confirmed enabled")
            emit(step, True, "Workflows confirmed enabled", None)
        else:
            _record_step(setup, step, "pending", "Workflows not confirmed")
            emit(step, False, "cannot detect Workflows toggle; confirm it in Kiro settings",
                 "Enable Workflows in Kiro, then re-run `overwatch init` (or pass --assume-yes).")

    elif key == "self_test":
        res = run_self_test()
        _record_step(setup, step, "done" if res["ok"] else "blocked", res["detail"], passed=res["ok"])
        emit(step, res["ok"], res["detail"],
             None if res["ok"] else "Fix the self-test failure, then re-run `overwatch selftest`.")

    elif key == "live_smoke":
        # Live-only: never faked. Requires credentials + a real GPU.
        key_set = bool(os.environ.get(API_KEY_ENV))
        detail = ("live smoke requires RUNPOD_API_KEY + a real GPU; not run offline"
                  if not key_set else
                  "RUNPOD_API_KEY set, but a live smoke must be run explicitly on a real GPU")
        _record_step(setup, step, "pending", detail, live="requires_credentials")
        emit(step, False, detail,
             "Run a live smoke (`run_smoke`) on a real GPU once credentials are in place.")


def _init_emit(args: argparse.Namespace):
    def emit(step: Dict[str, Any], ok: bool, detail: str, fix: Optional[str]) -> None:
        if getattr(args, "json", False):
            return
        mark = "ok  " if ok else "todo"
        sys.stdout.write(f"[{mark}] step {step['id']}: {step['title']} -- {detail}\n")
        if not ok and fix:
            sys.stdout.write(f"       fix: {fix}\n")
    return emit


def cmd_init(args: argparse.Namespace) -> int:
    setup = load_setup()
    team_mode = _has_team_settings()
    setup["team_mode"] = team_mode
    if team_mode and not getattr(args, "json", False):
        sys.stdout.write(
            "Team settings detected in project.yaml + policy.yaml -- running the "
            "per-person steps only (1, 2, 6, 7).\n"
        )

    steps = _steps_for_run(team_mode)
    ran: List[int] = []
    skipped: List[int] = []
    for step in steps:
        if _step_done(setup, step["key"]) and not getattr(args, "force", False):
            skipped.append(step["id"])
            if not getattr(args, "json", False):
                sys.stdout.write(f"[skip] step {step['id']}: {step['title']} (already done)\n")
            continue
        _run_step(step, setup, args)
        ran.append(step["id"])
        save_setup(setup)

    save_setup(setup)

    if getattr(args, "json", False):
        payload = {
            "team_mode": team_mode,
            "ran": ran,
            "skipped": skipped,
            "steps": setup.get("steps", {}),
        }
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    else:
        done = sum(1 for s in steps if _step_done(setup, s["key"]))
        sys.stdout.write(
            f"\ninit: {done}/{len(steps)} step(s) complete. "
            f"Run `overwatch doctor` to verify.\n"
        )
    return 0


# ----------------------------------------------------------------------
# brief (SessionStart fleet brief)
# ----------------------------------------------------------------------
def _fleet_snapshot() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return ``(fleet_result, budget_result)`` using the tools (offline-safe)."""
    try:
        fleet, _ = tools_mod.fleet_status()
    except Exception as exc:  # noqa: BLE001
        fleet = {"pods": [], "count": 0, "error": str(exc), "total_spend_rate_per_hour": 0.0}
    try:
        budget, _ = tools_mod.budget_status()
    except Exception as exc:  # noqa: BLE001
        budget = {"error": str(exc)}
    return fleet, budget


def cmd_brief(args: argparse.Namespace) -> int:
    checks = collect_checks()
    complete = _setup_complete(checks)
    fleet, budget = _fleet_snapshot()

    if args.json:
        payload = {
            "setup_complete": complete,
            "fleet": fleet,
            "budget": budget,
        }
        if not complete:
            payload["suggestion"] = "Run /gpu-setup to finish setup."
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return 0

    count = fleet.get("count", 0)
    rate = fleet.get("total_spend_rate_per_hour", 0.0)
    sys.stdout.write("gpu-overwatch fleet brief\n")
    sys.stdout.write(f"- running Pods: {count}\n")
    sys.stdout.write(f"- spend rate:   ${rate:.2f}/hr\n")
    if fleet.get("foreign_count"):
        sys.stdout.write(f"- foreign Pods: {fleet['foreign_count']}\n")
    if "session_cap_usd" in budget:
        sys.stdout.write(
            f"- caps: session ${budget['session_cap_usd']:.0f}, "
            f"per-run ${budget['per_run_cap_usd']:.0f}\n"
        )
    if args.spend_summary:
        sys.stdout.write(
            f"- session spend rate: ${fleet.get('total_spend_rate_per_hour', 0.0):.2f}/hr\n"
        )
    if not complete:
        failing = [c["name"] for c in checks if not c.get("ok")]
        sys.stdout.write(
            f"\nSetup incomplete ({', '.join(failing)}). Run /gpu-setup to finish.\n"
        )
    return 0


# ----------------------------------------------------------------------
# reap (idle Pods; dynamic confirm; never touches keep)
# ----------------------------------------------------------------------
def _idle_pods(idle_minutes: float) -> List[Dict[str, Any]]:
    """Return reap candidates: overwatch-created RUNNING Pods that are idle.

    "Idle" means not mapped to a live run (orphaned) OR a run whose last
    progress is older than ``idle_minutes``. Keep Pods are never included.
    """
    try:
        fleet, _ = tools_mod.fleet_status()
    except Exception:  # noqa: BLE001
        return []
    state = state_mod.load_state()
    live_runs = {
        r.get("pod_id"): r
        for r in state_mod.list_runs(state)
        if r.get("status") in ("running", "launching", "pending")
    }
    now = time.time()
    threshold = float(idle_minutes) * 60.0
    candidates: List[Dict[str, Any]] = []
    for pod in fleet.get("pods", []):
        if pod.get("foreign"):
            continue
        if pod.get("keep"):
            continue  # never touch keep Pods
        pod_id = pod.get("pod_id")
        run = live_runs.get(pod_id)
        if run is None:
            # Orphaned overwatch Pod: idle by definition.
            candidates.append({"pod_id": pod_id, "name": pod.get("name"), "reason": "orphaned"})
            continue
        last = float(run.get("last_progress") or run.get("created_at") or now)
        if (now - last) >= threshold:
            candidates.append(
                {"pod_id": pod_id, "name": pod.get("name"), "reason": "idle",
                 "idle_seconds": round(now - last, 1)}
            )
    return candidates


def cmd_reap(args: argparse.Namespace) -> int:
    candidates = _idle_pods(args.idle_minutes)

    if args.confirm_json:
        # Dynamic confirm payload for the Stop hook: {"skip": true} when there
        # is nothing idle, else a confirm payload describing the action.
        if not candidates:
            sys.stdout.write(json.dumps({"skip": True}, separators=(",", ":")) + "\n")
            return 0
        names = [c.get("name") or c.get("pod_id") for c in candidates]
        payload = {
            "skip": False,
            "title": "Reap idle Pods?",
            "message": (
                f"{len(candidates)} idle Pod(s) ({', '.join(names)}) have been idle "
                f">= {args.idle_minutes} min. Stop them?"
            ),
            "options": ["stop", "keep"],
            "candidates": candidates,
        }
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return 0

    # Non-confirm path.
    if args.dry_run:
        result = {"dry_run": True, "candidates": candidates, "candidate_count": len(candidates)}
        if args.json:
            sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        else:
            sys.stdout.write(f"reap (dry run): {len(candidates)} idle Pod(s)\n")
        return 0

    # Real stop path: stop each idle Pod via run_stop (guard protects keep Pods).
    backend = tools_mod.runpod_client.get_backend()
    state = state_mod.load_state()
    pod_to_run = {r.get("pod_id"): r.get("run_id") for r in state_mod.list_runs(state)}
    stopped: List[str] = []
    skipped_keep: List[str] = []
    for cand in candidates:
        pod_id = cand.get("pod_id")
        run_id = pod_to_run.get(pod_id)
        try:
            if run_id:
                tools_mod.run_stop(run_id=run_id, terminate=False, backend=backend)
            else:
                backend.stop_pod(pod_id)
            stopped.append(pod_id)
        except guard_mod.GuardError:
            skipped_keep.append(pod_id)  # keep Pod -> never touched
        except Exception:  # noqa: BLE001
            pass
    result = {
        "dry_run": False,
        "stopped": stopped,
        "stopped_count": len(stopped),
        "skipped_keep": skipped_keep,
    }
    if args.json:
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(f"reap: stopped {len(stopped)} idle Pod(s); kept {len(skipped_keep)}\n")
    return 0


# ----------------------------------------------------------------------
# preflight (config parse + VRAM estimate + 2-step CPU dry run)
# ----------------------------------------------------------------------
def _estimate_vram_gb(cfg: Dict[str, Any]) -> float:
    """Rough VRAM estimate (GB) from a training config.

    Uses a simple heuristic: ~2 bytes/param (fp16 weights) plus an optimizer +
    activation multiplier scaled by batch and sequence length. Deterministic
    and stdlib only -- this is a sizing hint, not a precise figure.
    """
    params_b = float(cfg.get("params_billion") or cfg.get("model_size_b") or 7.0)
    batch = float(cfg.get("batch_size") or cfg.get("micro_batch_size") or 1)
    seq = float(cfg.get("seq_len") or cfg.get("max_seq_len") or 2048)
    method = str(cfg.get("method") or "full").lower()
    # Weights: 2 bytes/param (fp16).
    weights_gb = params_b * 2.0
    # Optimizer + grads multiplier: full fine-tune ~ x3 more than weights;
    # LoRA/QLoRA far less.
    if method in ("lora", "qlora", "inference"):
        opt_mult = 0.25
    else:
        opt_mult = 3.0
    optimizer_gb = params_b * 2.0 * opt_mult
    # Activations scale with batch*seq (very rough).
    activations_gb = (batch * seq / 2048.0) * params_b * 0.5
    total = weights_gb + optimizer_gb + activations_gb
    return round(total, 1)


def _cpu_dry_run(script: str, steps: int = 2, timeout: float = 30.0) -> Dict[str, Any]:
    """Run a 2-step CPU dry run of a training script via the fake trainer.

    We do not execute arbitrary user scripts; instead we run the CPU fake
    trainer for a tiny number of steps to prove the sidecar/metric path works
    end to end on this machine. Returns ``{ok, steps_seen, detail}``.
    """
    import tempfile

    tmp = tempfile.mkdtemp(prefix="ow-preflight-")
    metrics = os.path.join(tmp, "metrics.ndjson")
    env = dict(os.environ)
    env["OVERWATCH_METRICS"] = metrics
    env["OVERWATCH_CKPT_DIR"] = tmp
    env["OVERWATCH_RUN"] = "preflight"
    # Scale so the fake trainer stops after ~`steps` emitted records quickly.
    cmd = [
        sys.executable,
        _fake_train_path(),
        "--total-steps",
        str(max(2, steps)),
        "--scale",
        "1",
        "--sleep",
        "0",
    ]
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout,
            cwd=os.path.dirname(_fake_train_path()),
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "steps_seen": 0, "detail": f"dry run failed: {exc}"}
    steps_seen = 0
    if os.path.exists(metrics):
        with open(metrics, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") == "metric" and rec.get("step") is not None:
                    steps_seen += 1
    ok = proc.returncode == 0 and steps_seen >= 1
    return {
        "ok": ok,
        "steps_seen": steps_seen,
        "exit_code": proc.returncode,
        "script": script,
        "detail": f"ran {steps_seen} step(s), exit {proc.returncode}",
    }


def cmd_preflight(args: argparse.Namespace) -> int:
    paths = list(args.paths or [])
    config_path = None
    script_path = None
    for p in paths:
        if p.endswith((".yaml", ".yml", ".json")):
            config_path = config_path or p
        elif p.endswith(".py"):
            script_path = script_path or p
    # Fall back: if nothing was passed, still run a dry run.
    cfg: Dict[str, Any] = {}
    parse_ok = True
    parse_detail = "no config provided"
    if config_path:
        try:
            loaded = config_mod.load_config(config_path)
            cfg = loaded if isinstance(loaded, dict) else {}
            parse_detail = f"parsed {config_path}"
        except Exception as exc:  # noqa: BLE001
            parse_ok = False
            parse_detail = f"failed to parse {config_path}: {exc}"

    vram = _estimate_vram_gb(cfg)
    dry = _cpu_dry_run(script_path or "(fake_train)", steps=2)

    result = {
        "config": config_path,
        "script": script_path,
        "parse_ok": parse_ok,
        "parse_detail": parse_detail,
        "vram_estimate_gb": vram,
        "dry_run": dry,
        "ok": parse_ok and dry["ok"],
    }
    if args.json:
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write("overwatch preflight\n")
        sys.stdout.write(f"- config: {parse_detail}\n")
        sys.stdout.write(f"- estimated VRAM: ~{vram} GB\n")
        sys.stdout.write(
            f"- CPU dry run: {dry['detail']} ({'ok' if dry['ok'] else 'FAILED'})\n"
        )
    return 0 if result["ok"] else 1


# ----------------------------------------------------------------------
# audit (append a PostToolUse event to a JSONL log)
# ----------------------------------------------------------------------
def cmd_audit(args: argparse.Namespace) -> int:
    """Read a tool-call event JSON on stdin and append it to the audit log."""
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {"raw": raw}
    record = {"at": time.time(), "event": event}
    dest = args.append
    directory = os.path.dirname(dest) or "."
    os.makedirs(directory, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    # Audit must not block the tool call; always exit 0.
    return 0


# ----------------------------------------------------------------------
# argument parser / dispatch
# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overwatch", description="gpu-overwatch CLI")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="guided, resumable 8-step setup")
    p_init.add_argument("--json", action="store_true", help="machine-readable output")
    p_init.add_argument("--force", action="store_true", help="re-run even completed steps")
    p_init.add_argument("--assume-yes", action="store_true", dest="assume_yes",
                        help="auto-confirm the Workflows prompt (non-interactive)")
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="environment health check")
    p_doctor.add_argument("--json", action="store_true", help="machine-readable output")
    p_doctor.add_argument("--brief", action="store_true", help="short SessionStart form")
    p_doctor.set_defaults(func=cmd_doctor)

    p_brief = sub.add_parser("brief", help="SessionStart fleet brief")
    p_brief.add_argument("--json", action="store_true", help="machine-readable output")
    p_brief.add_argument("--spend-summary", action="store_true", dest="spend_summary",
                         help="include a spend summary (SessionEnd)")
    p_brief.set_defaults(func=cmd_brief)

    p_reap = sub.add_parser("reap", help="reap idle Pods (never touches keep Pods)")
    p_reap.add_argument("--idle-minutes", type=float, default=10.0, dest="idle_minutes",
                        help="idle threshold in minutes")
    p_reap.add_argument("--confirm-json", action="store_true", dest="confirm_json",
                        help="emit a dynamic confirm payload for the Stop hook")
    p_reap.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="list candidates without stopping")
    p_reap.add_argument("--json", action="store_true", help="machine-readable output")
    p_reap.set_defaults(func=cmd_reap)

    p_pre = sub.add_parser("preflight", help="config parse + VRAM estimate + 2-step CPU dry run")
    p_pre.add_argument("paths", nargs="*", help="training script and/or config path(s)")
    p_pre.add_argument("--json", action="store_true", help="machine-readable output")
    p_pre.set_defaults(func=cmd_preflight)

    p_self = sub.add_parser("selftest", help="run the offline self-test")
    p_self.add_argument("--json", action="store_true", help="machine-readable output")
    p_self.set_defaults(func=cmd_selftest)

    p_audit = sub.add_parser("audit", help="append a PostToolUse event to an audit log")
    p_audit.add_argument("--append", default=os.path.join(OVERWATCH_DIR, "audit.jsonl"),
                         help="audit log path (JSONL)")
    p_audit.set_defaults(func=cmd_audit)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
