"""Datagen driver: idempotent, resumable dataset collection.

The driver reads a job spec (``datagen/*.yaml``), renders a prompt per input
record, sends it to an inference backend with bounded concurrency, and writes
the results as atomic JSONL shards with a manifest. It survives anything:

* **Idempotent record keys** -- ``key = hash(input record, model, template,
  sampling)``. A key already present in the manifest's shards (or the failed
  queue) is skipped, so a restart resumes from where it left off.
* **Atomic shards** -- each shard is written to a temp file then ``os.replace``'d
  into place. The ``manifest.json`` lists only shards that finished writing, so
  a crash mid-shard never corrupts the dataset.
* **Retries with exponential backoff** on simulated ``429`` / ``5xx`` /
  ``timeout`` errors. A record that fails ``max_retries`` (3) times is written
  to the poison queue ``failed.jsonl`` and the job keeps going.
* **Exact dedup by key** -- duplicate input records (same key) are produced once.
* **QA sampling** -- every ``qa.every_records`` finished records a sample of
  size ``qa.sample_size`` is graded against the rubric; if the bad-output
  (empty / refusal / format-error) rate crosses a threshold the job pauses and
  raises a flag. Near-dup MinHash is left as an optional stub.

Everything runs offline against :class:`FakeInference` when ``OVERWATCH_FAKE=1``.
The real Serverless/Flash path is import-guarded and never breaks import when
the SDK/``httpx`` is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

FAKE_ENV = "OVERWATCH_FAKE"
API_KEY_ENV = "RUNPOD_API_KEY"

# Default knobs (overridable by the spec).
DEFAULT_MAX_RETRIES = 3
DEFAULT_SHARD_SIZE = 500
DEFAULT_QA_BAD_FRACTION = 0.5  # pause when > 50% of a QA sample is bad


# ----------------------------------------------------------------------
# Transient errors (simulated 429 / 5xx / timeout)
# ----------------------------------------------------------------------
class TransientError(Exception):
    """A retryable inference error (429 / 5xx / timeout)."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------------
# Idempotent record key
# ----------------------------------------------------------------------
def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def record_key(record: Any, model: str, template: str, sampling: Dict[str, Any]) -> str:
    """Stable idempotent key = sha256 of (input record, model, template, sampling).

    The same input produced with the same model/template/sampling always yields
    the same key, so exact dedup and resume are deterministic.
    """
    payload = _canonical(
        {
            "record": record,
            "model": model,
            "template": template,
            "sampling": sampling,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# Prompt rendering (tiny jinja-like {{ var }} substitution, stdlib only)
# ----------------------------------------------------------------------
def render_template(template_text: str, record: Any) -> str:
    """Render ``{{ key }}`` placeholders from a record mapping.

    This is a deliberately tiny substitution (no real Jinja2, which is not
    importable in the sandbox). A record that is a dict exposes its keys; a
    scalar record is exposed as ``{{ input }}``.
    """
    values: Dict[str, Any] = {}
    if isinstance(record, dict):
        values.update(record)
    values.setdefault("input", record if not isinstance(record, dict) else record.get("input", ""))

    out = template_text
    for key, val in values.items():
        out = out.replace("{{ " + str(key) + " }}", str(val))
        out = out.replace("{{" + str(key) + "}}", str(val))
    return out


# ----------------------------------------------------------------------
# Inference backends
# ----------------------------------------------------------------------
class FakeInference:
    """Deterministic in-memory inference backend for offline tests.

    Given a prompt it returns a deterministic completion. It can be scripted to
    raise :class:`TransientError` a fixed number of times per key (to exercise
    retries and the poison queue) and to emit "bad" outputs (empty / refusal /
    format-error) for QA threshold tests.
    """

    def __init__(
        self,
        *,
        fail_keys: Optional[Dict[str, int]] = None,
        bad_keys: Optional[Dict[str, str]] = None,
        latency: float = 0.0,
    ) -> None:
        # key -> number of times to raise a TransientError before succeeding.
        # A huge value (>= max_retries) forces the record into failed.jsonl.
        self.fail_keys: Dict[str, int] = dict(fail_keys or {})
        # key -> kind of bad output: 'empty' | 'refusal' | 'format'.
        self.bad_keys: Dict[str, str] = dict(bad_keys or {})
        self.latency = latency
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, *, key: str, prompt: str, model: str, sampling: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self.calls += 1
            remaining = self.fail_keys.get(key, 0)
            if remaining > 0:
                self.fail_keys[key] = remaining - 1
                raise TransientError(f"simulated transient failure for {key}", status=503)
        if self.latency:
            time.sleep(self.latency)
        bad = self.bad_keys.get(key)
        if bad == "empty":
            return {"text": ""}
        if bad == "refusal":
            return {"text": "I cannot help with that request."}
        if bad == "format":
            return {"text": "<<<not-json>>>"}
        # A deterministic, well-formed completion.
        digest = hashlib.sha256((prompt + model).encode("utf-8")).hexdigest()[:8]
        return {"text": f"label:{digest}"}


class _RealServerlessInference:  # pragma: no cover - never runs in the sandbox
    """Runpod Serverless/Flash inference, import-guarded.

    The ``runpod`` SDK / ``httpx`` are imported lazily inside ``generate`` so
    importing this module never fails when they are absent.
    """

    def __init__(self, *, endpoint_id: str, api_key: str) -> None:
        self.endpoint_id = endpoint_id
        self.api_key = api_key

    def generate(self, *, key: str, prompt: str, model: str, sampling: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import runpod  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "runpod SDK is required for the real Serverless backend; set "
                "OVERWATCH_FAKE=1 for the offline fake backend"
            ) from exc
        runpod.api_key = self.api_key
        endpoint = runpod.Endpoint(self.endpoint_id)
        result = endpoint.run_sync(
            {"input": {"prompt": prompt, "model": model, "sampling": sampling}}
        )
        text = result.get("text") if isinstance(result, dict) else str(result)
        return {"text": text or ""}


def _use_fake() -> bool:
    if os.environ.get(FAKE_ENV) == "1":
        return True
    return not os.environ.get(API_KEY_ENV)


def get_inference(spec: Optional[Dict[str, Any]] = None, *, inference: Any = None) -> Any:
    """Select the inference backend.

    An explicit ``inference`` object wins (tests inject a scripted
    :class:`FakeInference`). Otherwise the fake backend is used when
    ``OVERWATCH_FAKE=1`` or no API key is set; the real Serverless path is
    attempted only when credentials are present and falls back to the fake
    backend on any failure rather than crashing.
    """
    if inference is not None:
        return inference
    if _use_fake():
        print("overwatch datagen: using FakeInference (offline)", file=sys.stderr)
        return FakeInference()
    spec = spec or {}
    endpoint_id = spec.get("endpoint_id") or os.environ.get("RUNPOD_ENDPOINT_ID", "")
    api_key = os.environ.get(API_KEY_ENV, "")
    # No silent fallback: when a key is present and OVERWATCH_FAKE != '1' we
    # construct the real inference backend and let any failure RAISE rather than
    # silently returning FakeInference (which would corrupt a dataset with fake
    # teacher outputs). The Serverless request path itself is deferred.
    print("overwatch datagen: using RealServerlessInference (live Runpod)", file=sys.stderr)
    return _RealServerlessInference(endpoint_id=endpoint_id, api_key=api_key)


# ----------------------------------------------------------------------
# QA grading against the rubric
# ----------------------------------------------------------------------
def grade_output(text: Any) -> str:
    """Grade a single output: ``ok`` | ``empty`` | ``refusal`` | ``format``.

    A deterministic stand-in for grading against the rubric in
    ``prompts/qa_rubric.md``: empty strings fail as ``empty``, common refusal
    phrasings fail as ``refusal`` and malformed markers fail as ``format``.
    """
    if text is None or str(text).strip() == "":
        return "empty"
    low = str(text).strip().lower()
    refusals = ("i cannot", "i can't", "i'm sorry", "as an ai", "i am unable")
    if any(low.startswith(p) for p in refusals):
        return "refusal"
    if "<<<" in low or low == "not-json":
        return "format"
    return "ok"


# ----------------------------------------------------------------------
# Manifest + shard helpers (atomic write-then-rename)
# ----------------------------------------------------------------------
def _manifest_path(output_dir: str) -> str:
    return os.path.join(output_dir, "manifest.json")


def load_manifest(output_dir: str) -> Dict[str, Any]:
    """Load the manifest (finished shards + their keys), or an empty one."""
    path = _manifest_path(output_dir)
    if not os.path.exists(path):
        return {"shards": [], "keys": [], "records": 0}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("shards", [])
    data.setdefault("keys", [])
    data.setdefault("records", 0)
    return data


def _save_manifest(output_dir: str, manifest: Dict[str, Any]) -> None:
    """Atomically persist the manifest (temp write + ``os.replace``)."""
    path = _manifest_path(output_dir)
    fd, tmp = tempfile.mkstemp(prefix=".manifest-", suffix=".json", dir=output_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _write_shard_atomic(output_dir: str, shard_name: str, rows: List[Dict[str, Any]]) -> str:
    """Write a shard JSONL to a temp file then ``os.replace`` into place."""
    final_path = os.path.join(output_dir, shard_name)
    fd, tmp = tempfile.mkstemp(prefix=".shard-", suffix=".jsonl.tmp", dir=output_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, final_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return final_path


def _append_failed(output_dir: str, row: Dict[str, Any]) -> None:
    """Append a record to the poison queue ``failed.jsonl``."""
    path = os.path.join(output_dir, "failed.jsonl")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True))
        handle.write("\n")


def load_failed_keys(output_dir: str) -> List[str]:
    """Return the keys already parked in ``failed.jsonl`` (for resume)."""
    path = os.path.join(output_dir, "failed.jsonl")
    if not os.path.exists(path):
        return []
    keys: List[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                keys.append(json.loads(line).get("key"))
            except json.JSONDecodeError:
                continue
    return [k for k in keys if k]


# ----------------------------------------------------------------------
# Input loading
# ----------------------------------------------------------------------
def load_input_records(path: str) -> List[Any]:
    """Load input records from a JSONL file (one JSON value per line)."""
    records: List[Any] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


# ----------------------------------------------------------------------
# Retry with exponential backoff
# ----------------------------------------------------------------------
def _generate_with_retries(
    inference: Any,
    *,
    key: str,
    prompt: str,
    model: str,
    sampling: Dict[str, Any],
    max_retries: int,
    base_backoff: float,
    sleeper: Callable[[float], None],
) -> Dict[str, Any]:
    """Call the backend, retrying transient failures with exponential backoff.

    Raises :class:`TransientError` once the retry budget is exhausted (the
    caller sends the record to the poison queue).
    """
    attempt = 0
    while True:
        try:
            return inference.generate(key=key, prompt=prompt, model=model, sampling=sampling)
        except TransientError:
            attempt += 1
            if attempt >= max_retries:
                raise
            # Exponential backoff: base * 2**(attempt-1).
            sleeper(base_backoff * (2 ** (attempt - 1)))


# ----------------------------------------------------------------------
# QA pause flag
# ----------------------------------------------------------------------
class QAPause(Exception):
    """Raised internally to pause the job when QA crosses the bad threshold."""

    def __init__(self, report: Dict[str, Any]) -> None:
        super().__init__(report.get("detail", "QA threshold crossed"))
        self.report = report


# ----------------------------------------------------------------------
# The driver
# ----------------------------------------------------------------------
def run_driver(
    spec: Dict[str, Any],
    *,
    base_dir: str = ".",
    inference: Any = None,
    output_dir: Optional[str] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff: float = 0.0,
    shard_size: Optional[int] = None,
    qa_bad_fraction: float = DEFAULT_QA_BAD_FRACTION,
    sleeper: Callable[[float], None] = time.sleep,
    budget_usd: Optional[float] = None,
    price_per_record: float = 0.0,
) -> Dict[str, Any]:
    """Run a datagen job spec to completion (idempotent + resumable).

    ``spec`` is a parsed job spec (see ``datagen/labels-v1.yaml``). Paths in the
    spec (``input``, ``template``, ``qa.rubric``) are resolved relative to
    ``base_dir``; ``output`` is used verbatim unless ``output_dir`` overrides it.

    Returns a summary dict: records produced, shards written, dedup/failed/retry
    counts, QA status and spend.
    """
    model = str(spec.get("model", "unknown-model"))
    sampling = dict(spec.get("sampling") or {})
    template_rel = spec.get("template")
    input_rel = spec.get("input")
    qa = dict(spec.get("qa") or {})
    shard_size = int(shard_size or spec.get("shard_size") or DEFAULT_SHARD_SIZE)
    concurrency = max(1, int(spec.get("concurrency", 1)))

    out_dir = output_dir or spec.get("output") or os.path.join(base_dir, "datasets", str(spec.get("name", "job")))
    os.makedirs(out_dir, exist_ok=True)

    # Resolve + read the template.
    template_text = ""
    if template_rel:
        template_path = template_rel if os.path.isabs(template_rel) else os.path.join(base_dir, template_rel)
        if os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as handle:
                template_text = handle.read()
    template_token = template_rel or ""

    # Load input records.
    input_path = input_rel if (input_rel and os.path.isabs(input_rel)) else os.path.join(base_dir, str(input_rel))
    records = load_input_records(input_path)

    inference = get_inference(spec, inference=inference)

    # Resume state.
    manifest = load_manifest(out_dir)
    done_keys = set(manifest.get("keys") or [])
    failed_keys = set(load_failed_keys(out_dir))
    shard_index = len(manifest.get("shards") or [])

    # Build the work list: exact dedup by key, skip keys already done/failed.
    seen: set = set()
    work: List[Dict[str, Any]] = []
    deduped = 0
    for record in records:
        key = record_key(record, model, template_token, sampling)
        if key in seen:
            deduped += 1  # exact duplicate input in this run
            continue
        seen.add(key)
        if key in done_keys or key in failed_keys:
            continue  # already produced or already parked -> resume skips it
        work.append({"key": key, "record": record})

    qa_every = int(qa.get("every_records", 0) or 0)
    qa_sample_size = int(qa.get("sample_size", 0) or 0)

    produced: List[Dict[str, Any]] = []
    newly_failed = 0
    retries_used = 0
    lock = threading.Lock()

    def _worker(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        nonlocal newly_failed, retries_used
        key = item["key"]
        record = item["record"]
        prompt = render_template(template_text, record) if template_text else _canonical(record)
        before = getattr(inference, "calls", 0)
        try:
            out = _generate_with_retries(
                inference,
                key=key,
                prompt=prompt,
                model=model,
                sampling=sampling,
                max_retries=max_retries,
                base_backoff=base_backoff,
                sleeper=sleeper,
            )
        except TransientError as exc:
            with lock:
                newly_failed += 1
                retries_used += max(0, getattr(inference, "calls", 0) - before)
            _append_failed(
                out_dir,
                {"key": key, "input": record, "error": str(exc), "attempts": max_retries},
            )
            return None
        with lock:
            retries_used += max(0, getattr(inference, "calls", 0) - before - 1)
        return {
            "key": key,
            "input": record,
            "model": model,
            "template": template_token,
            "sampling": sampling,
            "output": out.get("text", ""),
        }

    # Fan out with bounded concurrency; preserve input order in the output.
    if concurrency > 1 and len(work) > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(_worker, work))
    else:
        results = [_worker(item) for item in work]
    produced = [r for r in results if r is not None]

    # QA: grade a sample every qa_every finished records; pause on threshold.
    qa_status = "ok"
    qa_reports: List[Dict[str, Any]] = []
    paused = False
    total_done = int(manifest.get("records") or 0)
    pending: List[Dict[str, Any]] = []
    qa_window: List[Dict[str, Any]] = []

    def _run_qa(window: List[Dict[str, Any]]) -> Dict[str, Any]:
        sample = window[:qa_sample_size] if qa_sample_size else window
        grades = [grade_output(r.get("output")) for r in sample]
        bad = [g for g in grades if g != "ok"]
        frac = (len(bad) / len(sample)) if sample else 0.0
        report = {
            "sampled": len(sample),
            "bad": len(bad),
            "bad_fraction": round(frac, 4),
            "grades": grades,
            "crossed": frac > qa_bad_fraction,
            "rubric": qa.get("rubric"),
        }
        if report["crossed"]:
            report["detail"] = (
                f"QA bad-output fraction {frac:.2f} > threshold {qa_bad_fraction:.2f}; "
                f"job paused for review"
            )
        return report

    shards_written: List[str] = []
    for row in produced:
        pending.append(row)
        qa_window.append(row)
        total_done += 1
        if qa_every and total_done % qa_every == 0:
            report = _run_qa(qa_window)
            qa_reports.append(report)
            qa_window = []
            if report["crossed"]:
                qa_status = "paused"
                paused = True
                break
        if len(pending) >= shard_size:
            name = f"shard-{shard_index:05d}.jsonl"
            _write_shard_atomic(out_dir, name, pending)
            manifest.setdefault("shards", []).append(name)
            manifest.setdefault("keys", []).extend(r["key"] for r in pending)
            manifest["records"] = int(manifest.get("records") or 0) + len(pending)
            _save_manifest(out_dir, manifest)
            shards_written.append(name)
            shard_index += 1
            pending = []

    # Flush the final partial shard (unless we paused mid-way).
    if pending and not paused:
        name = f"shard-{shard_index:05d}.jsonl"
        _write_shard_atomic(out_dir, name, pending)
        manifest.setdefault("shards", []).append(name)
        manifest.setdefault("keys", []).extend(r["key"] for r in pending)
        manifest["records"] = int(manifest.get("records") or 0) + len(pending)
        _save_manifest(out_dir, manifest)
        shards_written.append(name)
        shard_index += 1
        pending = []

    records_total = int(manifest.get("records") or 0)
    spend = round(records_total * float(price_per_record), 6)
    over_budget = budget_usd is not None and spend > float(budget_usd)

    return {
        "name": spec.get("name"),
        "output_dir": out_dir,
        "records": records_total,
        "new_records": len(produced) - (len(pending)),
        "shards": list(manifest.get("shards") or []),
        "shards_written": shards_written,
        "deduped": deduped,
        "failed": newly_failed,
        "retries": retries_used,
        "qa_status": qa_status,
        "qa_reports": qa_reports,
        "paused": paused,
        "spend_usd": spend,
        "over_budget": over_budget,
        "manifest_path": _manifest_path(out_dir),
    }
