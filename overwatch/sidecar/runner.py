"""Sidecar runner: wraps a training command and watches it.

The :class:`Runner` launches the training command as a subprocess, captures its
stdout/stderr into a bounded log ring buffer, tails the ``ow.log()`` metrics
file, samples the GPU every 15s (via ``nvidia-smi`` if present, else records
``util=null`` / cpu-only), and computes derived stats (loss slope, tokens/s,
ETA). The HTTP server reads a status snapshot from the runner.

Reflexes (all guarded so CPU / missing tools degrade gracefully):

* periodic checkpoint signal every ``checkpoint_interval_seconds``;
* checkpoint on SIGTERM, then exit;
* self-stop at the budget cap or ``max_hours`` -- calls ``runpodctl stop`` if
  that binary is present, else just marks the run stopped.

Everything is standard library only. No GPU and no third-party package is
required for import or for the CPU test path.
"""

from __future__ import annotations

import collections
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from typing import Any, Deque, Dict, List, Optional

from .. import client as _client
from ..policy import Policy

LOG_RING_CAP = 2000  # lines retained in memory; /logs tails a slice of this
METRICS_CAP = 5000  # metric records retained for /metrics downsampling
GPU_SAMPLE_INTERVAL = 15.0  # seconds between nvidia-smi samples


def nvidia_smi_available() -> bool:
    """Whether the ``nvidia-smi`` binary is on PATH."""
    return shutil.which("nvidia-smi") is not None


def runpodctl_available() -> bool:
    """Whether the ``runpodctl`` binary is on PATH."""
    return shutil.which("runpodctl") is not None


def sample_gpu() -> Dict[str, Any]:
    """Sample GPU utilisation.

    Returns ``{"util": <pct|None>, "mem_used_mb": <int|None>, "cpu_only": bool}``.
    On a host without ``nvidia-smi`` this reports ``util=None`` / ``cpu_only``.
    All failures are swallowed so sampling never crashes the runner.
    """
    if not nvidia_smi_available():
        return {"util": None, "mem_used_mb": None, "cpu_only": True}
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        first = out.decode("utf-8", "replace").strip().splitlines()[0]
        util_s, mem_s = (p.strip() for p in first.split(","))
        return {"util": float(util_s), "mem_used_mb": float(mem_s), "cpu_only": False}
    except Exception:  # noqa: BLE001 - sampling must never raise
        return {"util": None, "mem_used_mb": None, "cpu_only": True}


class Runner:
    """Supervises a single training subprocess."""

    def __init__(
        self,
        command: List[str],
        *,
        policy: Optional[Policy] = None,
        run_id: Optional[str] = None,
        metrics_path: Optional[str] = None,
        ckpt_dir: Optional[str] = None,
        price_per_hour: float = 0.0,
        budget_cap_usd: Optional[float] = None,
        max_hours: Optional[float] = None,
        checkpoint_interval_seconds: Optional[float] = None,
        stall_no_step_seconds: Optional[float] = None,
        gpu_sample_interval: float = GPU_SAMPLE_INTERVAL,
    ) -> None:
        self.command = list(command)
        self.policy = policy or Policy()
        self.run_id = run_id or os.environ.get(_client.RUN_ENV)
        self.metrics_path = metrics_path or _client.metrics_path()
        self.ckpt_dir = ckpt_dir or os.environ.get(_client.CKPT_DIR_ENV) or "."
        self.price_per_hour = float(price_per_hour)
        self.budget_cap_usd = budget_cap_usd
        self.max_hours = max_hours
        # Reflex / detector intervals are injectable so tests can use tiny values.
        self.checkpoint_interval_seconds = float(
            checkpoint_interval_seconds
            if checkpoint_interval_seconds is not None
            else self.policy.threshold("checkpoint_interval_seconds")
        )
        self.stall_no_step_seconds = float(
            stall_no_step_seconds
            if stall_no_step_seconds is not None
            else self.policy.threshold("stall_no_step_seconds")
        )
        self.gpu_sample_interval = float(gpu_sample_interval)

        self._lock = threading.RLock()
        self._logs: Deque[str] = collections.deque(maxlen=LOG_RING_CAP)
        self._metrics: Deque[Dict[str, Any]] = collections.deque(maxlen=METRICS_CAP)
        self._gpu: Dict[str, Any] = {"util": None, "mem_used_mb": None, "cpu_only": True}

        self._proc: Optional[subprocess.Popen] = None
        self._exit_code: Optional[int] = None
        self._status = "pending"  # pending|running|checkpointing|paused|stopping|finished|stopped
        self._paused = False
        self._stop_reason: Optional[str] = None
        self._started_at: Optional[float] = None
        self._last_step: Optional[int] = None
        self._last_step_at: Optional[float] = None
        self._last_checkpoint_at: Optional[float] = None
        self._signals: List[Dict[str, Any]] = []

        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Launch the subprocess and background watcher threads."""
        env = dict(os.environ)
        if self.run_id:
            env.setdefault(_client.RUN_ENV, self.run_id)
        env.setdefault(_client.METRICS_ENV, self.metrics_path)
        env.setdefault(_client.CKPT_DIR_ENV, self.ckpt_dir)
        # Ensure a fresh metrics file so the tailer only sees this run.
        directory = os.path.dirname(self.metrics_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        open(self.metrics_path, "w", encoding="utf-8").close()

        self._started_at = time.time()
        self._status = "running"
        self._proc = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
            env=env,
        )
        self._spawn(self._pump_logs, name="ow-logs")
        self._spawn(self._tail_metrics, name="ow-metrics")
        self._spawn(self._sample_loop, name="ow-gpu")
        self._spawn(self._reflex_loop, name="ow-reflex")

    def _spawn(self, target, name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """Wait for the subprocess to exit; return its exit code."""
        if self._proc is None:
            return self._exit_code
        try:
            code = self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        with self._lock:
            self._exit_code = code
            if self._status not in ("stopped",):
                self._status = "finished" if code == 0 else "crashed"
        return code

    def shutdown(self) -> None:
        """Stop watcher threads (does not kill the subprocess)."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Watcher threads
    # ------------------------------------------------------------------
    def _pump_logs(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            with self._lock:
                self._logs.append(line.rstrip("\n"))
            if self._stop_event.is_set():
                break

    def _tail_metrics(self) -> None:
        path = self.metrics_path
        pos = 0
        while not self._stop_event.is_set():
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as handle:
                        handle.seek(pos)
                        chunk = handle.read()
                        pos = handle.tell()
                    if chunk:
                        for line in chunk.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            self._ingest_metric(record)
            except OSError:
                pass
            # Exit shortly after the process ends and the file is drained.
            if self._proc is not None and self._proc.poll() is not None:
                # One more drain pass already done above; stop tailing.
                if not os.path.exists(path):
                    break
                with open(path, "r", encoding="utf-8") as handle:
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == pos:
                        break
            time.sleep(0.05)

    def _ingest_metric(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self._metrics.append(record)
            if record.get("type") == "metric" and "step" in record:
                self._last_step = record["step"]
                self._last_step_at = time.time()
            elif record.get("type") == "checkpoint":
                self._last_checkpoint_at = time.time()

    def _sample_loop(self) -> None:
        while not self._stop_event.is_set():
            gpu = sample_gpu()
            with self._lock:
                self._gpu = gpu
            if self._proc is not None and self._proc.poll() is not None:
                break
            self._stop_event.wait(self.gpu_sample_interval)

    def _reflex_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            # Periodic checkpoint signal.
            last_ckpt = self._last_checkpoint_at or self._started_at or now
            if now - last_ckpt >= self.checkpoint_interval_seconds:
                self.signal("checkpoint_now", source="reflex-periodic")
                self._last_checkpoint_at = now
            # Self-stop at budget cap or max hours.
            reason = self._budget_or_hours_exceeded(now)
            if reason is not None:
                self.self_stop(reason)
                break
            if self._proc is not None and self._proc.poll() is not None:
                break
            self._stop_event.wait(min(1.0, self.checkpoint_interval_seconds))

    def _budget_or_hours_exceeded(self, now: float) -> Optional[str]:
        if self._started_at is None:
            return None
        uptime = now - self._started_at
        if self.max_hours is not None and uptime >= self.max_hours * 3600.0:
            return f"max_hours reached ({self.max_hours}h)"
        if self.budget_cap_usd is not None and self.price_per_hour > 0:
            spend = self.price_per_hour * (uptime / 3600.0)
            if spend >= self.budget_cap_usd:
                return f"budget cap reached (${self.budget_cap_usd})"
        return None

    # ------------------------------------------------------------------
    # Signals / reflexes
    # ------------------------------------------------------------------
    def signal(self, name: str, *, source: str = "api") -> Dict[str, Any]:
        """Apply a control signal. Returns an acknowledgement dict."""
        name = str(name)
        accepted = {"checkpoint_now", "pause", "resume", "stop_graceful"}
        if name not in accepted:
            return {"ok": False, "error": f"unknown signal: {name}"}
        record = {"signal": name, "source": source, "ts": time.time()}
        with self._lock:
            self._signals.append(record)
            if name == "pause":
                self._paused = True
                self._status = "paused"
            elif name == "resume":
                self._paused = False
                self._status = "running"
            elif name == "checkpoint_now":
                self._request_checkpoint()
            elif name == "stop_graceful":
                self._status = "stopping"
                self._request_checkpoint()
                self._terminate_proc()
        return {"ok": True, "signal": name}

    def _request_checkpoint(self) -> None:
        """Ask the training process to checkpoint.

        The real contract forwards a signal to the trainer; on the CPU test
        path we record a checkpoint event directly so the reflex is observable.
        """
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGUSR1)
                return
            except (ValueError, OSError, AttributeError):
                pass
        self._write_checkpoint_record(step=self._last_step, reason="requested")

    def _write_checkpoint_record(self, *, step: Optional[int], reason: str) -> None:
        path = os.path.join(self.ckpt_dir, f"ckpt-step{step if step is not None else 'x'}")
        record = {
            "type": "checkpoint",
            "run": self.run_id,
            "path": path,
            "step": step,
            "reason": reason,
            "ts": time.time(),
        }
        try:
            os.makedirs(os.path.dirname(self.metrics_path) or ".", exist_ok=True)
            with open(self.metrics_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                handle.flush()
        except OSError:
            pass
        self._ingest_metric(record)

    def _terminate_proc(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except (ValueError, OSError):
                pass

    def handle_sigterm(self, *_args: Any) -> None:
        """SIGTERM reflex: checkpoint, then stop the process and exit."""
        with self._lock:
            self._status = "stopping"
            self._write_checkpoint_record(step=self._last_step, reason="sigterm")
        self._terminate_proc()
        self._stop_event.set()

    def self_stop(self, reason: str) -> None:
        """Self-stop at budget/max-hours: checkpoint, call runpodctl, mark stopped."""
        with self._lock:
            self._stop_reason = reason
            self._status = "stopping"
            self._write_checkpoint_record(step=self._last_step, reason="self-stop")
        self._terminate_proc()
        if runpodctl_available() and self.run_id:
            try:
                subprocess.run(
                    ["runpodctl", "stop", "pod", f"ow-{self.run_id}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    check=False,
                )
            except Exception:  # noqa: BLE001 - absence / failure is non-fatal
                pass
        with self._lock:
            self._status = "stopped"

    # ------------------------------------------------------------------
    # Derived stats + status snapshot
    # ------------------------------------------------------------------
    def _loss_slope(self, records: List[Dict[str, Any]]) -> Optional[float]:
        points = [
            (float(r["step"]), float(r["loss"]))
            for r in records
            if r.get("type") == "metric" and "step" in r and "loss" in r
        ]
        points = [(s, l) for s, l in points if l == l and abs(l) != float("inf")]
        if len(points) < 2:
            return None
        n = len(points)
        sx = sum(s for s, _ in points)
        sy = sum(l for _, l in points)
        sxx = sum(s * s for s, _ in points)
        sxy = sum(s * l for s, l in points)
        denom = n * sxx - sx * sx
        if denom == 0:
            return None
        return (n * sxy - sx * sy) / denom

    def _tokens_per_s(self, records: List[Dict[str, Any]]) -> Optional[float]:
        toks = [r for r in records if r.get("type") == "metric" and "tokens" in r]
        if len(toks) < 2:
            return None
        total = sum(float(r["tokens"]) for r in toks)
        span = (self._last_step_at or time.time()) - (self._started_at or time.time())
        if span <= 0:
            return None
        return total / span

    def logs(self, limit: int = 400) -> List[str]:
        """Return the last ``limit`` log lines (ring buffer tail)."""
        with self._lock:
            lines = list(self._logs)
        return lines[-limit:]

    def metrics(self) -> List[Dict[str, Any]]:
        """Return the retained metric/checkpoint records."""
        with self._lock:
            return list(self._metrics)

    def status(self) -> Dict[str, Any]:
        """Return a status snapshot for the HTTP ``/status`` endpoint."""
        with self._lock:
            records = list(self._metrics)
            last_loss = None
            for record in reversed(records):
                if record.get("type") == "metric" and "loss" in record:
                    last_loss = record["loss"]
                    break
            now = time.time()
            uptime = (now - self._started_at) if self._started_at else 0.0
            spend = self.price_per_hour * (uptime / 3600.0)
            snapshot = {
                "run": self.run_id,
                "status": self._status,
                "paused": self._paused,
                "step": self._last_step,
                "loss": last_loss,
                "loss_slope": self._loss_slope(records),
                "tokens_per_s": self._tokens_per_s(records),
                "gpu": dict(self._gpu),
                "uptime_seconds": uptime,
                "spend_usd": spend,
                "exit_code": self._exit_code,
                "stop_reason": self._stop_reason,
                "last_step_age_seconds": (
                    (now - self._last_step_at) if self._last_step_at else None
                ),
                "signals": list(self._signals),
            }
        return snapshot
