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
     Full trimodal pathway (text included).
  6. Step 0 smoke test + throughput benchmark -> /workspace/reports/. This
     first full trimodal pass is what exercises (and therefore caches under
     HF_HOME) any vision/audio/text encoder that TRIBE loads lazily on the
     first forward. ONLY AFTER this pass completes do we flip
     HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE -- see the ordering note in main().
  7. Full teacher queue via the datagen driver -> /workspace/datasets/,
     running the COMMITTED+TESTED datagen/teacher-queue-v1.yaml spec staged on
     the volume at /workspace/datagen/teacher-queue-v1.yaml (NOT an inline
     divergent spec), including the NON-CUTTABLE ONNX export and demo-clip
     teacher traces.
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
# The committed+tested teacher-queue spec, staged on the volume by the
# orchestrator (see docs/live-pipeline-runbook.md). The Pod MUST run THIS spec
# -- the same single, tier-ordered manifest the offline tests validate (demo +
# TikHarm tier 1, XD-Violence <=300 tier 2, QA rubric, budget) -- rather than a
# divergent inline spec, so the executed queue is the reviewed one.
DEFAULT_SPEC_PATH = "/workspace/datagen/teacher-queue-v1.yaml"


def load_teacher_spec(spec_path: str) -> dict:
    """Load the committed teacher-queue job spec from the volume.

    Uses overwatch.config.load_config (the same stdlib loader the offline tests
    use), so the Pod runs exactly the spec under test. Raises if it is missing
    -- fail closed, never silently substitute a divergent inline spec.
    """
    if not os.path.isfile(spec_path):
        raise FileNotFoundError(
            f"teacher-queue spec not found at {spec_path}; the orchestrator "
            "stages datagen/teacher-queue-v1.yaml onto the volume before launch"
        )
    from overwatch.config import load_config  # type: ignore

    spec = load_config(spec_path)
    if not isinstance(spec, dict):
        raise RuntimeError(f"teacher-queue spec {spec_path} did not parse to a mapping")
    return spec


def run_teacher_queue(model, spec_path: str = DEFAULT_SPEC_PATH) -> dict:
    """Run the full teacher queue via the datagen driver conventions.

    Loads the COMMITTED teacher-queue spec from the volume and runs it through
    overwatch.datagen.driver.run_driver (idempotent/resumable: record keys,
    atomic shards, manifest, failed.jsonl, QA sampling). The inference backend
    is the REAL TRIBE teacher -- NO fake fallback. Any failure raises.

    The spec's budget_usd is forwarded to run_driver (with a conservative
    per-record price) so on-pod spend is tracked against the budget in addition
    to the launch-time guard; set OW_PRICE_PER_RECORD to tune the estimate.
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

    spec = load_teacher_spec(spec_path)
    teacher = _TribeTeacher(model)

    # On-pod spend awareness: forward the spec's budget to the driver. The
    # launch-time guard remains the hard enforcement point (price_per_hour *
    # max_hours <= per-run cap); this gives an in-driver spend estimate too.
    budget_usd = spec.get("budget_usd")
    price_per_record = float(os.environ.get("OW_PRICE_PER_RECORD", "0") or 0.0)

    _log(
        "teacher queue: running committed spec '%s' from %s "
        "(input=%s output=%s budget_usd=%s)"
        % (spec.get("name"), spec_path, spec.get("input"), spec.get("output"), budget_usd)
    )
    summary = run_driver(
        spec,
        inference=teacher,
        output_dir=spec.get("output"),
        budget_usd=float(budget_usd) if budget_usd is not None else None,
        price_per_record=price_per_record,
    )
    _log(
        "teacher queue: '%s' -> %s records (spend_usd=%s over_budget=%s)"
        % (spec.get("name"), summary["records"], summary["spend_usd"], summary["over_budget"])
    )
    return summary


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
    parser.add_argument("--spec", default=DEFAULT_SPEC_PATH,
                        help="committed teacher-queue spec staged on the volume")
    parser.add_argument("--hf-cache", default="/workspace/hf_cache")
    args = parser.parse_args(argv)

    os.environ.setdefault("HF_HOME", args.hf_cache)

    # Step 5: load TRIBE (reaches the Hub to cache encoders under HF_HOME).
    model = load_tribe(args.model_dir)

    # Step 6: Step 0 smoke + throughput benchmark.
    #
    # OFFLINE ORDERING (per the user instruction + review issue #2): do NOT set
    # HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE yet. A full trimodal model commonly
    # materialises its vision/audio/text encoders lazily on the FIRST forward
    # pass, which happens here inside the smoke/benchmark. We keep the Hub
    # reachable for this first pass so every lazily-loaded encoder is fetched
    # and cached under HF_HOME=/workspace/hf_cache.
    step0_smoke_and_benchmark(model, args.reports_dir)

    # Encoders have now been exercised by the full trimodal Step 0 pass and are
    # cached on the volume -> ONLY NOW is it safe to flip the offline toggles,
    # before the full teacher queue runs offline from the volume cache.
    enable_offline_mode()

    # Step 7: full teacher queue (runs the COMMITTED spec) + NON-CUTTABLE extras.
    run_teacher_queue(model, args.spec)
    export_onnx(model, args.reports_dir)

    _log("GPU-A driver complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
