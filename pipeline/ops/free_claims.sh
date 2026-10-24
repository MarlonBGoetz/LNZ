#!/bin/bash
S=$(dirname "$0")/s3; B=s3://lhuwcwm7gb
npz=$($S s3 ls $B/teacher/ --recursive | awk '{print $NF}' | xargs -n1 basename 2>/dev/null | sed 's/.npz$//')
tsv=$($S s3 ls $B/data/clips/ --recursive | grep '\.tsv$' | awk '{print $NF}' | xargs -n1 basename | sed 's/.tsv$//')
echo "teacher done: $(echo $npz | wc -w)  tsv done: $(echo $tsv | wc -w)"
for c in $($S s3 ls $B/markers/teacher_claims/ | awk '{print $NF}'); do echo "$npz" | grep -qx "$c" || { $S s3 rm $B/markers/teacher_claims/$c --quiet; echo "freed teacher $c"; }; done
for c in $($S s3 ls $B/markers/tsv_claims/ | awk '{print $NF}'); do echo "$tsv" | grep -qx "$c" || { $S s3 rm $B/markers/tsv_claims/$c --quiet; echo "freed tsv $c"; }; done
