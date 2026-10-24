"""Tests for the CPU training stand-in ``tests/fake_train.py``.

Each ``--fail`` mode must produce the expected observable signal, and the
default run must exit 0 with a checkpoint. The harness is run as a subprocess
so the test exercises exactly the invocation the sidecar uses.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAKE_TRAIN = os.path.join(HERE, "fake_train.py")


def _run(args, metrics_path, ckpt_dir, timeout=20):
    env = dict(os.environ)
    env["OVERWATCH_METRICS"] = metrics_path
    env["OVERWATCH_CKPT_DIR"] = ckpt_dir
    env["OVERWATCH_RUN"] = "testrun"
    proc = subprocess.run(
        [sys.executable, FAKE_TRAIN, *args],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        timeout=timeout,
    )
    return proc


def _read_records(path):
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def test_clean_run_exits_zero_with_checkpoint(tmp_path):
    metrics = os.path.join(str(tmp_path), "m.ndjson")
    proc = _run([], metrics, str(tmp_path))
    assert proc.returncode == 0
    records = _read_records(metrics)
    assert any(r.get("type") == "checkpoint" for r in records)
    assert any(r.get("type") == "metric" and "loss" in r for r in records)


def test_nan_mode_emits_nan_metric(tmp_path):
    metrics = os.path.join(str(tmp_path), "m.ndjson")
    proc = _run(["--fail", "nan@300"], metrics, str(tmp_path))
    records = _read_records(metrics)
    has_nan = any(
        r.get("type") == "metric"
        and isinstance(r.get("loss"), float)
        and r["loss"] != r["loss"]  # NaN != NaN
        for r in records
    )
    assert has_nan
    assert proc.returncode == 0


def test_oom_mode_logs_and_nonzero_exit(tmp_path):
    metrics = os.path.join(str(tmp_path), "m.ndjson")
    proc = _run(["--fail", "oom@100"], metrics, str(tmp_path))
    assert proc.returncode != 0
    assert "CUDA out of memory" in proc.stdout


def test_crash_mode_nonzero_exit(tmp_path):
    metrics = os.path.join(str(tmp_path), "m.ndjson")
    proc = _run(["--fail", "crash@50"], metrics, str(tmp_path))
    assert proc.returncode != 0


def test_hang_mode_stops_progressing(tmp_path):
    metrics = os.path.join(str(tmp_path), "m.ndjson")
    # hang sleeps for hang-seconds then returns; keep it short for the test.
    proc = _run(["--fail", "hang@200", "--hang-seconds", "0.5"], metrics, str(tmp_path))
    records = [r for r in _read_records(metrics) if r.get("type") == "metric"]
    steps = [r["step"] for r in records if "step" in r]
    # Progress stopped at/under the trigger step; no steps beyond 200.
    assert steps, "expected some steps before the hang"
    assert max(steps) <= 200
    assert "[hang]" in proc.stdout
