#!/usr/bin/env bash
# GPU-A on-pod pipeline: download -> HARD sha256 verify -> keep LICENSE ->
# TRIBE config-override wiring -> offline toggles (AFTER cache) -> Step 0 smoke
# + throughput benchmark -> full teacher queue.
#
# Runs INSIDE the Pod against the mounted network volume at /workspace. No SSH,
# no GitHub token. Never prints secret values. NO fake-teacher fallback: any
# failure aborts the run (set -e + explicit exits).
set -euo pipefail

WORKSPACE="${OW_WORKSPACE:-/workspace}"
POD_DIR="${WORKSPACE}/pod"
MODEL_DIR="${WORKSPACE}/models/Llama-3.2-3B"
REPORTS_DIR="${WORKSPACE}/reports"
DATASETS_DIR="${WORKSPACE}/datasets"
HF_CACHE_DIR="${WORKSPACE}/hf_cache"

MODEL_REPO="unsloth/Llama-3.2-3B"
MODEL_REVISION="d4446454d87d51aa42e1fb174f25acc5f8762331"

mark() { echo "===== [gpu_a] $* ====="; }

mark "START GPU-A pipeline  workspace=${WORKSPACE}"
mkdir -p "${MODEL_DIR}" "${REPORTS_DIR}" "${DATASETS_DIR}" "${HF_CACHE_DIR}"

# Cache HF assets (facebook/tribev2 + encoders) on the volume so a re-run is
# offline. Do NOT set the OFFLINE toggles yet -- the first run must be allowed
# to reach the Hub to populate this cache.
export HF_HOME="${HF_CACHE_DIR}"
export HF_HUB_ENABLE_HF_TRANSFER=1

# ---------------------------------------------------------------------------
# (1) Ensure a fresh huggingface_hub (provides the `hf` CLI).
# ---------------------------------------------------------------------------
mark "(1/7) pip install -U huggingface_hub"
pip install -U "huggingface_hub[hf_transfer]"

# ---------------------------------------------------------------------------
# (2) Download the pinned-revision weights as PLAIN FILES (no symlinks).
# ---------------------------------------------------------------------------
mark "(2/7) hf download ${MODEL_REPO}@${MODEL_REVISION} -> ${MODEL_DIR}"
hf download "${MODEL_REPO}" \
  --revision "${MODEL_REVISION}" \
  --local-dir "${MODEL_DIR}" \
  --local-dir-use-symlinks False

# ---------------------------------------------------------------------------
# (3) HARD-STOP sha256 verification. Abort (nonzero) if any shard differs.
# ---------------------------------------------------------------------------
mark "(3/7) HARD sha256 verify (abort on mismatch)"
python3 "${POD_DIR}/verify_hashes.py" --base-dir "${MODEL_DIR}"
mark "(3/7) sha256 verify PASSED"

# ---------------------------------------------------------------------------
# (4) Keep the Llama 3.2 LICENSE next to the weights (fail if missing).
# ---------------------------------------------------------------------------
mark "(4/7) assert Llama 3.2 LICENSE kept with weights"
LICENSE_FOUND=""
for cand in "LICENSE" "LICENSE.txt" "LICENSE.md" "LICENSE.rst"; do
  if [ -f "${MODEL_DIR}/${cand}" ]; then
    LICENSE_FOUND="${MODEL_DIR}/${cand}"
    break
  fi
done
if [ -z "${LICENSE_FOUND}" ]; then
  echo "[gpu_a] FATAL: Llama 3.2 LICENSE missing in ${MODEL_DIR}; aborting." >&2
  exit 2
fi
mark "(4/7) LICENSE present: ${LICENSE_FOUND}"

# ---------------------------------------------------------------------------
# (5..7) Heavy driver: TRIBE config-override wiring, Step 0 smoke + throughput
# benchmark, then the full teacher queue (incl. non-cuttable ONNX export +
# demo-clip traces). The OFFLINE toggles are flipped INSIDE the driver, only
# AFTER TRIBE + encoders have been cached under HF_HOME.
# ---------------------------------------------------------------------------
mark "(5-7/7) TRIBE wiring + Step 0 smoke/throughput + full teacher queue"
python3 "${POD_DIR}/gpu_a_pipeline.py" \
  --model-dir "${MODEL_DIR}" \
  --reports-dir "${REPORTS_DIR}" \
  --datasets-dir "${DATASETS_DIR}" \
  --hf-cache "${HF_CACHE_DIR}"

mark "DONE GPU-A pipeline"
