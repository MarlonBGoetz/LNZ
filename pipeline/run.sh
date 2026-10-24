#!/bin/bash
# ROLE=A: data prep + model download + teacher.  ROLE=B: teacher + student features + train/export.
# ROLE=AB: everything on one pod.
set -x
W=/workspace
cd $W/code
export HF_HOME=$W/hf_cache PIP_CACHE_DIR=$W/pip_cache UV_CACHE_DIR=/root/uv_cache TORCH_HOME=$W/torch_cache \
       PYTHONUNBUFFERED=1 NILEARN_DATA=$W/nilearn_data HF_HUB_ENABLE_HF_TRANSFER=1 TOKENIZERS_PARALLELISM=false
DO_PREP=0; DO_TRAIN=0
[[ $ROLE == *A* ]] && DO_PREP=1
[[ $ROLE == *B* ]] && DO_TRAIN=1

apt-get update -qq && apt-get install -y -qq ffmpeg git >/dev/null 2>&1
pip install -q "numpy==2.2.6"   # tribev2@af58661 pins numpy==2.2.6 (overrides the handoff's numpy<2.1)
pip install -q "tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git@af58661"
pip install -q nilearn open_clip_torch timm av onnx onnxruntime onnxconverter-common onnxscript scikit-learn \
    pandas tqdm kaggle "huggingface_hub[hf_transfer]" uv
TV=$(python -c "import torch;print(torch.__version__.split('+')[0])")
pip install -q "torchaudio==$TV"   # image's torchaudio is built for an older torch
python -m spacy download en_core_web_sm -q || true
python -c "import numpy, torch; print('numpy', numpy.__version__, 'torch', torch.__version__, torch.cuda.is_available())"

# WhisperX in its own env (same tool TRIBE would call through uvx), installed in the background
( uv venv /root/wx --python 3.11 -q && uv pip install -q --python /root/wx/bin/python whisperx pandas ) \
    > $W/logs/wx_install_$ROLE.log 2>&1 &
WX_INSTALL=$!
git clone -q --depth 1 https://github.com/fschmid56/EfficientAT /root/EfficientAT &

if [ $DO_PREP = 1 ]; then
  python ${PREP_SCRIPT:-prep_data.py} > $W/logs/${PREP_SCRIPT:-prep_data.py}.log 2>&1 &
  python dl_models.py 2>&1 | tee $W/logs/dl_models.log
  if [ -f $W/markers/llama_hash_mismatch ]; then echo "LLAMA HASH MISMATCH - hard stop"; exit 3; fi
fi
while [ ! -f $W/markers/models_ready ]; do echo "waiting models_ready"; sleep 15; done
while [ ! -f $W/markers/demo_ready ]; do echo "waiting demo_ready"; sleep 10; done

run_transcribe() {
  WXP=/root/wx/bin/python
  t0=$(date +%s)
  # (`wait` can't see the install job from this subshell, so poll until whisperx imports)
  until $WXP -c "import whisperx, pandas" 2>/dev/null; do
    if [ $(( $(date +%s) - t0 )) -gt 900 ]; then echo "whisperx not importable after 15 min"; touch $W/markers/whisper_dead_$ROLE; return; fi
    sleep 10
  done
  LIBS=$($WXP -c "import os,nvidia.cudnn,nvidia.cublas;print(os.path.dirname(nvidia.cudnn.__file__)+'/lib:'+os.path.dirname(nvidia.cublas.__file__)+'/lib')" 2>/dev/null)
  LD_LIBRARY_PATH=$LIBS:$LD_LIBRARY_PATH $WXP transcribe.py > $W/logs/transcribe_$ROLE.log 2>&1
  rc=$?
  if [ $rc != 0 ] && [ $(date +%s) -lt $TEACH_END_EPOCH ]; then
    echo "whisperx died rc=$rc"; touch $W/markers/whisper_dead_$ROLE
  fi
}
run_transcribe &
TR=$!

if [ $DO_TRAIN = 1 ]; then
  ( while [ $(date +%s) -lt $TEACH_END_EPOCH ] && [ ! -f $W/markers/stop_features ]; do
      python student_features.py >> $W/logs/student_features.log 2>&1; sleep 20; done ) &
  SF=$!
fi

# restart the teacher if it crashes; only the clock ends this phase
while [ $(date +%s) -lt $TEACH_END_EPOCH ]; do
  python teacher.py >> $W/logs/teacher_$ROLE.log 2>&1
  echo "teacher exited rc=$? $(date -u)"; sleep 20
done
echo "teacher done $(date -u)"
kill $TR 2>/dev/null; pkill -f transcribe.py

if [ $DO_TRAIN = 1 ]; then
  touch $W/markers/stop_features
  wait $SF
  python student_features.py --labeled-only >> $W/logs/student_features.log 2>&1
  python train_export.py 2>&1 | tee $W/logs/train_export.log
fi
echo "run.sh finished $(date -u)"
