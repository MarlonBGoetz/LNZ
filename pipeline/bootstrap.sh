#!/bin/bash
# Pod entrypoint. Dead-man switch: the job runs under `timeout`, and the pod stops itself on exit.
ROLE=${ROLE:-$1}
W=/workspace
mkdir -p $W/logs $W/markers
exec > >(tee -a $W/logs/bootstrap_$ROLE.log) 2>&1
echo "=== bootstrap $(date -u) role=$ROLE pod=$RUNPOD_POD_ID"
stop_pod() {
  echo "=== stopping pod $(date -u)"
  touch $W/markers/finished_$ROLE
  runpodctl stop pod $RUNPOD_POD_ID 2>/dev/null || \
    curl -s -X POST -H "Authorization: Bearer $RP_KEY" https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID/stop
  sleep 600
}
if [ -f $W/markers/finished_$ROLE ]; then echo "already finished"; stop_pod; sleep infinity; fi
trap stop_pod EXIT
LEFT=$(( POD_KILL_EPOCH - $(date +%s) ))
echo "hard timeout in ${LEFT}s"
timeout --signal=TERM --kill-after=30 $LEFT bash $W/code/run.sh
echo "run.sh exit code $?"
