#!/usr/bin/env bash
# GPU-B on-pod pipeline: student encoder smoke test -> feature extraction.
# Runs INSIDE the Pod against /workspace. No SSH, no GitHub token. Never prints
# secrets. NO fake-fallback: any failure aborts the run.
set -euo pipefail

WORKSPACE="${OW_WORKSPACE:-/workspace}"
POD_DIR="${WORKSPACE}/pod"
# Same tier-ordered clip manifest the GPU-A teacher queue consumes, staged on
# the volume by the orchestrator (docs/live-pipeline-runbook.md).
MANIFEST="${WORKSPACE}/datagen/teacher-queue-inputs.jsonl"
FEATURES_DIR="${WORKSPACE}/features"
REPORTS_DIR="${WORKSPACE}/reports"
HF_CACHE_DIR="${WORKSPACE}/hf_cache"

mark() { echo "===== [gpu_b] $* ====="; }

mark "START GPU-B pipeline  workspace=${WORKSPACE}"
mkdir -p "${FEATURES_DIR}" "${REPORTS_DIR}" "${HF_CACHE_DIR}"

export HF_HOME="${HF_CACHE_DIR}"
export HF_HUB_ENABLE_HF_TRANSFER=1

mark "(1/2) ensure huggingface_hub is current"
pip install -U "huggingface_hub[hf_transfer]"

mark "(2/2) student encoder smoke test -> feature extraction (manifest=${MANIFEST})"
python3 "${POD_DIR}/gpu_b_pipeline.py" \
  --manifest "${MANIFEST}" \
  --features-dir "${FEATURES_DIR}" \
  --reports-dir "${REPORTS_DIR}" \
  --hf-cache "${HF_CACHE_DIR}"

mark "DONE GPU-B pipeline"
