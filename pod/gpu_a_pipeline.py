#!/usr/bin/env python3
"""GPU-A heavy driver: TRIBE v2 teacher queue (runs ON THE POD only).

NOT imported by the gpu-overwatch test suite. It imports torch / transformers /
TRIBE / huggingface_hub, which are only present inside the Pod. Keep this file
OUT of the pytest import path.

Order (all steps mandatory; NO fake-teacher fallback -- any real failure
raises and the process exits nonzero):

  5. Wire TRIBE via config override ONLY (never edit TRIBE code):
       model = TribeModel.from_pretrained(
           "facebook/tribev2",
           config_update={"data.text_feature.model_name":
                          "/workspace/models/Llama-3.2-3B"})
     Full trimodal pathway (text included). After TRIBE + the other encoders
     are cached under HF_HOME, flip HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE.
  6. Step 0 smoke test + throughput benchmark -> /workspace/reports/.
  7. Full teacher queue via the datagen driver -> /workspace/datasets/,
     including the NON-CUTTABLE ONNX export and demo-clip teacher traces.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time


def _log(msg: str) -> None:
    print(f"[gpu_a.py] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Step 5: TRIBE via config override only.
# ---------------------------------------------------------------------------
def load_tribe(model_dir: str):
    """Load TRIBE v2 pointing text features at the local Llama copy.

    Config override ONLY -- we never edit TRIBE source. On any failure this
    raises; there is deliberately no fallback to a stub/fake model.
    """
    _log("loading TRIBE facebook/tribev2 via config override (full trimodal)")
    from tribe import TribeModel  # type: ignore  # provided inside the Pod

    model = TribeModel.from_pretrained(
        "facebook/tribev2",
        config_update={"data.text_feature.model_name": model_dir},
    )
    # Full trimodal pathway: text included (do not disable any modality).
    _log("TRIBE loaded; trimodal pathway active (vision + audio + text)")
    return model


def enable_offline_mode() -> None:
    """Flip HF offline toggles -- ONLY call AFTER TRIBE + encoders are cached."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    _log("offline toggles set: HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1")


# ---------------------------------------------------------------------------
# Step 6: Step 0 smoke test + throughput benchmark.
# ---------------------------------------------------------------------------
def step0_smoke_and_benchmark(model, reports_dir: str) -> dict:
    """Run the TRIBE Step 0 smoke test and a throughput benchmark.

    Reports clips/hour/worker for 1 vs 2 workers, whether subcortical responses
    fire, whether the jump-scare response fires, and projected clips labeled in
    the queue window. Written to /workspace/reports/. Raises on real failure.
    """
    _log("Step 0: TRIBE smoke test")
    smoke = model.smoke_test()  # real TRIBE path; raises if the model is broken
    if not smoke.get("ok", False):
        raise RuntimeError(f"TRIBE Step 0 smoke test FAILED: {smoke!r}")

    _log("Step 0: throughput benchmark (1 vs 2 workers)")
    bench = {}
    for workers in (1, 2):
        t0 = time.time()
        res = model.benchmark(workers=workers)  # real timed pass over sample clips
        elapsed = time.time() - t0
        clips = int(res.get("clips", 0))
        clips_per_hour = (clips / elapsed * 3600.0) if elapsed > 0 else 0.0
        bench[f"workers_{workers}"] = {
            "clips": clips,
            "elapsed_s": round(elapsed, 3),
            "clips_per_hour_per_worker": round(clips_per_hour / workers, 1),
            "clips_per_hour_total": round(clips_per_hour, 1),
        }

    # Queue-window projection for a focused ~2h run.
    queue_window_hours = float(os.environ.get("OW_QUEUE_WINDOW_HOURS", "2"))
    best = max(b["clips_per_hour_total"] for b in bench.values())
    projected_clips = int(best * queue_window_hours)

    report = {
        "generated_utc": _dt.datetime.utcnow().isoformat() + "Z",
        "model_dir": getattr(model, "text_feature_model_name", None),
        "smoke": smoke,
        "throughput": bench,
        "subcortical_response_fires": bool(smoke.get("subcortical_fires")),
        "jump_scare_response_fires": bool(smoke.get("jump_scare_fires")),
        "queue_window_hours": queue_window_hours,
        "projected_clips_labeled": projected_clips,
    }

    os.makedirs(reports_dir, exist_ok=True)
    out_path = os.path.join(reports_dir, "step0_benchmark.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    _log(f"Step 0 report written: {out_path}")
    _log(
        "subcortical_fires=%s jump_scare_fires=%s projected_clips=%s"
        % (
            report["subcortical_response_fires"],
            report["jump_scare_response_fires"],
            report["projected_clips_labeled"],
        )
    )
    return report


# ---------------------------------------------------------------------------
# Step 7: full teacher queue (datagen driver), then non-cuttable extras.
# ---------------------------------------------------------------------------
def _teacher_specs(datasets_dir: str) -> list:
    """Teacher-queue job specs (shape mirrors datagen/labels-v1.yaml).

    Tier 1: XD-Violence subset (<=300 clips) + TikHarm + demo clips.
    LIRIS-ACCEDE goes to the FRONT of tier 2 if/when it lands on the volume; we
    do not wait for it. FEAT-004 stages the concrete spec file(s); this is the
    on-pod default wiring.
    """
    base = {
        "mode": "tribe-teacher",
        "model": "facebook/tribev2",
        "template": None,
        "sampling": {},
        "concurrency": 2,
        "qa": {"every_records": 200, "sample_size": 20, "rubric": None},
    }
    tier1 = [
        {**base, "name": "xd-violence-subset", "input": "/workspace/inputs/xd_violence.jsonl",
         "output": os.path.join(datasets_dir, "xd-violence-subset")},
        {**base, "name": "tikharm", "input": "/workspace/inputs/tikharm.jsonl",
         "output": os.path.join(datasets_dir, "tikharm")},
        # NON-CUTTABLE: demo-clip teacher traces must always run.
        {**base, "name": "demo-clips", "input": "/workspace/inputs/demo_clips.jsonl",
         "output": os.path.join(datasets_dir, "demo-clips")},
    ]
    return tier1


def run_teacher_queue(model, datasets_dir: str) -> list:
    """Run the full teacher queue via the datagen driver conventions.

    Reuses overwatch.datagen.driver.run_driver (idempotent/resumable: record
    keys, atomic shards, manifest, failed.jsonl, QA sampling). The inference
    backend is the REAL TRIBE teacher -- NO fake fallback. Any failure raises.
    """
    # The overwatch package is available because bootstrap stages it / adds it
    # to PYTHONPATH on the Pod. Import lazily so this driver file stays usable
    # even before that wiring is in place.
    from overwatch.datagen.driver import run_driver  # type: ignore

    class _TribeTeacher:
        """Real TRIBE teacher adapter matching the driver's inference API.

        NO fake fallback: a failure inside TRIBE propagates as a real error so
        the dataset is never poisoned with fabricated teacher traces.
        """

        def __init__(self, tribe_model) -> None:
            self._model = tribe_model

        def generate(self, *, key, prompt, model, sampling):
            trace = self._model.teacher_trace(clip=prompt, sampling=sampling)
            if trace is None:
                raise RuntimeError(f"TRIBE teacher produced no trace for {key}")
            return {"text": json.dumps(trace, sort_keys=True)}

    teacher = _TribeTeacher(model)
    summaries = []
    for spec in _teacher_specs(datasets_dir):
        _log(f"teacher queue: running spec '{spec['name']}'")
        summary = run_driver(spec, inference=teacher, output_dir=spec["output"])
        summaries.append(summary)
        _log(f"teacher queue: '{spec['name']}' -> {summary['records']} records")
    return summaries


def export_onnx(model, reports_dir: str) -> str:
    """NON-CUTTABLE: export the TRIBE/student graph to ONNX. Raises on failure."""
    _log("NON-CUTTABLE: ONNX export")
    out_path = os.path.join(reports_dir, "tribe_student.onnx")
    model.export_onnx(out_path)  # real export; raises if it cannot be produced
    if not os.path.isfile(out_path):
        raise RuntimeError(f"ONNX export did not produce {out_path}")
    _log(f"ONNX export written: {out_path}")
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GPU-A TRIBE teacher-queue driver")
    parser.add_argument("--model-dir", default="/workspace/models/Llama-3.2-3B")
    parser.add_argument("--reports-dir", default="/workspace/reports")
    parser.add_argument("--datasets-dir", default="/workspace/datasets")
    parser.add_argument("--hf-cache", default="/workspace/hf_cache")
    args = parser.parse_args(argv)

    os.environ.setdefault("HF_HOME", args.hf_cache)

    # Step 5: load TRIBE (reaches the Hub to cache encoders under HF_HOME).
    model = load_tribe(args.model_dir)
    # Encoders are now cached on the volume -> safe to go offline.
    enable_offline_mode()

    # Step 6: Step 0 smoke + throughput benchmark.
    step0_smoke_and_benchmark(model, args.reports_dir)

    # Step 7: full teacher queue + NON-CUTTABLE extras.
    run_teacher_queue(model, args.datasets_dir)
    export_onnx(model, args.reports_dir)

    _log("GPU-A driver complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
