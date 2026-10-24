#!/usr/bin/env bash
# Keyless on-pod entrypoint. The Pod's container start command invokes this on
# boot. NO SSH, NO GitHub token, NO private-repo clone.
#
# The orchestrator passes this as docker_start_cmd to run_launch, e.g.:
#
#   GPU A:  bash -lc 'OW_PIPELINE=gpu_a bash /workspace/pod/bootstrap.sh'
#   GPU B:  bash -lc 'OW_PIPELINE=gpu_b bash /workspace/pod/bootstrap.sh'
#
# It (a) locates the pipeline scripts already staged on the mounted network
# volume at /workspace/pod/ (staged by the orchestrator via the Runpod S3 API
# in FEAT-004) OR, as a documented fallback, fetches a tarball from a public
# URL in OW_SCRIPTS_URL; (b) dispatches to gpu_a/gpu_b by OW_PIPELINE; (c)
# streams logs to /workspace/logs/ so the orchestrator can watch via the Runpod
# API + logs. Never prints secret values.
set -euo pipefail

WORKSPACE="${OW_WORKSPACE:-/workspace}"
POD_DIR="${WORKSPACE}/pod"
LOGS_DIR="${WORKSPACE}/logs"
OW_PIPELINE="${OW_PIPELINE:-}"
OW_SCRIPTS_URL="${OW_SCRIPTS_URL:-}"

mkdir -p "${LOGS_DIR}"

mark() { echo "===== [bootstrap] $* ====="; }

mark "boot $(date -u +%Y-%m-%dT%H:%M:%SZ) pipeline='${OW_PIPELINE}' workspace='${WORKSPACE}'"

# ---------------------------------------------------------------------------
# Locate the staged scripts, or fetch them from a public URL fallback.
# ---------------------------------------------------------------------------
if [ ! -f "${POD_DIR}/bootstrap.sh" ] || [ ! -f "${POD_DIR}/verify_hashes.py" ]; then
  if [ -n "${OW_SCRIPTS_URL}" ]; then
    mark "scripts not staged at ${POD_DIR}; fetching from public URL fallback"
    mkdir -p "${POD_DIR}"
    tarball="${WORKSPACE}/_pod_scripts.tar.gz"
    # Public, unauthenticated URL only. Do NOT embed any token here.
    curl -fsSL "${OW_SCRIPTS_URL}" -o "${tarball}"
    tar -xzf "${tarball}" -C "${POD_DIR}" --strip-components=1
    rm -f "${tarball}"
  else
    echo "[bootstrap] FATAL: no scripts at ${POD_DIR} and OW_SCRIPTS_URL unset." >&2
    exit 2
  fi
fi

# ---------------------------------------------------------------------------
# Dispatch by OW_PIPELINE. Stream combined stdout+stderr to a per-run log while
# also echoing to the container console (so Runpod API log tail sees it).
# ---------------------------------------------------------------------------
case "${OW_PIPELINE}" in
  gpu_a) script="${POD_DIR}/gpu_a_pipeline.sh" ;;
  gpu_b) script="${POD_DIR}/gpu_b_pipeline.sh" ;;
  *)
    echo "[bootstrap] FATAL: OW_PIPELINE must be 'gpu_a' or 'gpu_b' (got '${OW_PIPELINE}')." >&2
    exit 2
    ;;
esac

if [ ! -f "${script}" ]; then
  echo "[bootstrap] FATAL: pipeline script not found: ${script}" >&2
  exit 2
fi

log_file="${LOGS_DIR}/${OW_PIPELINE}-$(date -u +%Y%m%dT%H%M%SZ).log"
mark "dispatch ${OW_PIPELINE} -> ${script} (log: ${log_file})"

# `set -o pipefail` is already active: the pipeline's exit status is the script's,
# not tee's, so a failed run still aborts nonzero (no fake success).
set +e
bash "${script}" 2>&1 | tee -a "${log_file}"
status=${PIPESTATUS[0]}
set -e

if [ "${status}" -ne 0 ]; then
  echo "[bootstrap] pipeline ${OW_PIPELINE} FAILED with exit ${status}" | tee -a "${log_file}" >&2
  exit "${status}"
fi

mark "pipeline ${OW_PIPELINE} completed OK"
