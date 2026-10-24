#!/bin/bash
S=$(dirname "$0")/s3; D=${LNZ_OPS_LOGS:-/tmp/lnz-ops-logs}; mkdir -p $D
$S s3 sync s3://lhuwcwm7gb/logs/ $D/ --quiet
echo "--- $(date '+%H:%M:%S') markers:"; $S s3 ls s3://lhuwcwm7gb/markers/ | awk '{print $4}' | grep -v claims | tr '\n' ' '; echo
for f in $D/*.progress.json; do [ -f "$f" ] && echo "$(basename $f): $(python3 -c "import json;d=json.load(open('$f'));d.pop('times',None);le=d.get('last_error');d['last_error']=(le or '')[-250:];print(json.dumps(d))")"; done
for f in "$@"; do echo "== tail $f"; tail -n 15 $D/$f 2>/dev/null; done
