#!/usr/bin/env bash
# gpu-overwatch setup helper: run the environment doctor.
#
# Forwards all arguments to the overwatch CLI doctor so the setup skill can run
# `bash scripts/doctor.sh --json` (machine-readable) or `bash scripts/doctor.sh`
# (human-readable). This is a thin shim; all logic lives in overwatch/cli.py.
set -euo pipefail
exec python -m overwatch.cli doctor "$@"
