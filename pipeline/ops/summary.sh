#!/bin/bash
SP=$(dirname "$0"); D=$SP/logs; lastfail=-1; lastemit=0
while true; do
  $SP/s3 s3 sync s3://lhuwcwm7gb/logs/ $D/ --quiet 2>/dev/null
  line=$(python3 - "$D" <<'PY'
import json,glob,sys,os
D=sys.argv[1]; td=tf=0; tr=0; w=[]
for f in glob.glob(D+"/teacher_*?.progress.json"):
    n=os.path.basename(f).split(".")[0]
    if n in ("teacher_A","teacher_B"): continue
    d=json.load(open(f)); td+=d.get("done",0); tf+=d.get("failed",0); w.append(f"{n[8:]}:{d.get('done')}")
for f in glob.glob(D+"/transcribe_*.progress.json"): tr+=json.load(open(f)).get("done",0)
sf=json.load(open(D+"/student_features.progress.json")).get("done") if os.path.exists(D+"/student_features.progress.json") else 0
pr=json.load(open(D+"/prep.progress.json")) if os.path.exists(D+"/prep.progress.json") else {}
print(f"{td} {tf} teacher={td} fail={tf} [{' '.join(sorted(w))}] transcripts~{tr} student_feats~{sf} prep={pr.get('done')}ok/{pr.get('failed')}fail")
PY
)
  td=${line%% *}; rest=${line#* }; tf=${rest%% *}; msg=${rest#* }
  now=$(date +%s)
  if [ "$tf" != "$lastfail" ] || [ $((now-lastemit)) -ge 480 ]; then
    mk=$($SP/s3 s3 ls s3://lhuwcwm7gb/markers/ 2>/dev/null | awk '{print $NF}' | grep -vE 'claims|_ready' | tr '\n' ' ')
    echo "$(date +%H:%M) $msg markers[$mk]"; lastfail=$tf; lastemit=$now
  fi
  sleep 60
done
