#!/bin/bash
SP=$(dirname "$0"); D=$SP/logs; seen=""
while true; do
  $SP/s3 s3 sync s3://lhuwcwm7gb/logs/ $D/ --quiet 2>/dev/null
  mk=$($SP/s3 s3 ls s3://lhuwcwm7gb/markers/ 2>/dev/null | awk '{print $NF}' | grep -E 'export_done|finished_|stop_features' | tr '\n' ' ')
  n=$($SP/s3 s3 ls s3://lhuwcwm7gb/teacher/ --recursive 2>/dev/null | grep -c npz)
  te=$(grep -aE 'EXPORT DONE|Traceback|failed|exported|best val|test:|stress AUROC|shortcut|lag scores' $D/train_export.log 2>/dev/null | cut -c1-220 | tail -12)
  cur="markers[$mk] $te"
  if [ "$cur" != "$seen" ]; then echo "$(date +%H:%M) labeled=$n $cur"; seen="$cur"; fi
  echo "$mk" | grep -q export_done && echo "$mk" | grep -q finished_B && exit 0
  sleep 45
done
