#!/bin/bash
SP=$(dirname "$0"); D=$SP/logs; last=""
shopt -s nullglob
while true; do
  $SP/s3 s3 sync s3://lhuwcwm7gb/logs/ $D/ --quiet 2>/dev/null
  out=""
  for f in $D/teacher_*.progress.json $D/transcribe_*.progress.json $D/student_features.progress.json $D/prep.progress.json; do
    out="$out $(basename $f .progress.json)=$(python3 -c "import json;d=json.load(open('$f'));print(str(d.get('done'))+'ok/'+str(d.get('failed'))+'fail/'+str(d.get('sec_per_clip') or d.get('last_s') or ''))" 2>/dev/null)"
  done
  err=$(grep -lE 'Traceback|HASH MISMATCH|whisperx died|Killed|CUDA out of memory' $D/teacher_*.log $D/transcribe_*.log $D/dl_models.log $D/student_features.log $D/bootstrap_*.log 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')
  mk=$($SP/s3 s3 ls s3://lhuwcwm7gb/markers/ 2>/dev/null | awk '{print $NF}' | grep -v claims | tr '\n' ' ')
  cur="markers[$mk] progress[$out] errors_in[$err]"
  # only emit when something other than prep count changed
  key=$(echo "$cur" | sed -E 's/prep=[^ ]*//')
  [ "$key" != "$last" ] && echo "$(date +%H:%M) $cur" && last="$key"
  sleep 45
done
