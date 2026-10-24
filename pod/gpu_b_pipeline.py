#!/usr/bin/env python3
"""GPU-B heavy driver: student encoder smoke test + feature extraction.

NOT imported by the gpu-overwatch test suite (imports torch / transformers).
Keep OUT of the pytest import path. NO fake fallback: any real failure raises
and the process exits nonzero.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys


def _log(msg: str) -> None:
    print(f"[gpu_b.py] {msg}", flush=True)


def load_student_encoder(hf_cache: str):
    """Load the student encoder. Raises on failure (no stub fallback)."""
    _log("loading student encoder")
    os.environ.setdefault("HF_HOME", hf_cache)
    from overwatch_student import StudentEncoder  # type: ignore  # provided in the Pod

    return StudentEncoder.from_pretrained(cache_dir=hf_cache)


def smoke_test(encoder, reports_dir: str) -> dict:
    """Student encoder smoke test -> /workspace/reports/. Raises on failure."""
    _log("student encoder smoke test")
    result = encoder.smoke_test()
    if not result.get("ok", False):
        raise RuntimeError(f"student encoder smoke test FAILED: {result!r}")
    os.makedirs(reports_dir, exist_ok=True)
    out_path = os.path.join(reports_dir, "gpu_b_smoke.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"generated_utc": _dt.datetime.utcnow().isoformat() + "Z", "smoke": result},
            handle,
            indent=2,
            sort_keys=True,
        )
    _log(f"smoke report written: {out_path}")
    return result


def extract_features(encoder, manifest_path: str, features_dir: str) -> int:
    """Extract student features for every input clip -> /workspace/features/.

    Reads clip references from the tier-ordered clip manifest that the
    orchestrator stages on the volume (the SAME manifest the GPU-A teacher queue
    consumes: /workspace/datagen/teacher-queue-inputs.jsonl, see
    docs/live-pipeline-runbook.md). Writes one feature file per clip. Any
    extraction failure raises (never writes fabricated features). Fail-closed:
    a missing manifest aborts the run.
    """
    _log(f"feature extraction: {manifest_path} -> {features_dir}")
    os.makedirs(features_dir, exist_ok=True)

    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"missing input manifest {manifest_path}")

    count = 0
    with open(manifest_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            clip = json.loads(line)
            clip_id = str(clip.get("id") or clip.get("path") or count)
            feats = encoder.extract(clip)  # real extraction; raises on failure
            if feats is None:
                raise RuntimeError(f"student encoder returned no features for {clip_id}")
            safe_id = clip_id.replace("/", "_")
            out_path = os.path.join(features_dir, f"{safe_id}.npy")
            encoder.save_features(out_path, feats)
            count += 1
    _log(f"feature extraction complete: {count} clips")
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GPU-B student encoder driver")
    # GPU-B consumes the same tier-ordered clip manifest the GPU-A teacher queue
    # runs against, staged by the orchestrator at
    # /workspace/datagen/teacher-queue-inputs.jsonl (runbook). Fail-closed if
    # absent.
    parser.add_argument("--manifest", default="/workspace/datagen/teacher-queue-inputs.jsonl")
    parser.add_argument("--features-dir", default="/workspace/features")
    parser.add_argument("--reports-dir", default="/workspace/reports")
    parser.add_argument("--hf-cache", default="/workspace/hf_cache")
    args = parser.parse_args(argv)

    encoder = load_student_encoder(args.hf_cache)
    smoke_test(encoder, args.reports_dir)
    extract_features(encoder, args.manifest, args.features_dir)

    _log("GPU-B driver complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
