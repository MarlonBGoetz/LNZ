# HANDOFF: You now own the GPU runs + training. Time is critical.

You're taking over from another agent that failed partway. Goal: distill Meta's **TRIBE v2** brain-encoding model into a tiny, browser-runnable **student** (frozen small encoders + small MLP head) that predicts TRIBE's brain-region response to short video clips, plus a **stress score** on top. Deliverable: ONNX models + demo files for a live browser demo.

**DEADLINE for final exports: ______ (filled in by the user). Work backwards from it. Speed over polish. Parallelize. Don't stop to ask unless truly blocked or about to break a spending cap.**

---

## 0. First 10 minutes: assess state, then go

1. **Secrets:** list environment variable **names only** (never print values) and map them to these roles. Report the mapping in one line, and ask the user only for missing ones:
   - Runpod API key (`RUNPOD_API_KEY`)
   - Runpod S3 key pair: access `user_...`, secret `rps_...` (`RUNPOD_S3_ACCESS_KEY` / `RUNPOD_S3_SECRET_KEY`). Not the same as the API key.
   - Kaggle (`KAGGLE_USERNAME`, `KAGGLE_KEY`)
   - `HF_TOKEN`: optional. Nothing below needs it.
2. **Runpod state** (via API): list Pods and network volumes. **Stop any running Pod left over from the previous agent** and report it. Find the network volume in **US-MO-1** (200 GB). If none exists, create one: 200 GB, US-MO-1. The user has already approved it.
3. **Volume contents** (via the S3 API, no Pod needed). Endpoint `https://s3api-us-mo-1.runpod.io/`, region `US-MO-1`, bucket = volume ID. Check for `data/raw/liris_accede/`, `data/raw/demo/`, `models/Llama-3.2-3B/`, and any partial outputs from the previous agent.
4. **Previous agent's repo/branch:** skim it for anything reusable. **Don't trust it.** If a script is unclear, rewrite it. Don't spend more than 10 minutes here.
5. Post a 5-line status: what exists, what's missing, and your plan with times.

## 1. Spending rules (hard)

- GPUs: **H100 80GB only**, **secure cloud**, **US-MO-1** (Pods using a network volume run on secure cloud). Expected ~$3.99/hr per H100.
- Caps: **$20 per Pod/run, $50 total this session.** Track spend live (hourly price × running time). Stop a Pod *before* it would cross its cap.
- The user pre-approves launching **up to 2 H100 Pods** for this plan. When launching, post one line: GPU, $/hr, cap. If the price is materially different from ~$3.99/hr, stop and ask.
- **No idle GPUs:** if a GPU has no queued work for 5 minutes, stop it.
- **Dead-man switch:** every Pod's bootstrap script wraps its job in `timeout <hours>` and stops its own Pod when done or killed (`runpodctl stop pod $RUNPOD_POD_ID` if available inside the Pod; otherwise you stop it via the API as soon as its done-marker appears).
- At the end: stop all Pods and confirm via the API. **Never delete the volume.**

## 2. How to drive the Pods

Use the Runpod API or Python SDK (`pip install runpod`) with the API key, and the AWS CLI against the S3 endpoint for files. Check current parameter names in Runpod's docs and SDK. Query the GPU types and use the exact ID for H100 80GB.

**Recommended pattern (no SSH dependency):**
- Write job scripts locally → upload to `s3://<VOL>/code/` → create the Pod with the network volume attached (mounted at `/workspace`) and a start command like `bash /workspace/code/bootstrap_<role>.sh`.
- Jobs write **progress files and logs to the volume** (`/workspace/logs/<job>.log`, `/workspace/logs/<job>.progress.json` with done/total/ETA/last error). Poll them via S3 every few minutes.
- If an SSH key is configured on the account, you may also SSH in for debugging. Don't depend on it.

**Pod image:** a current official Runpod PyTorch image with CUDA 12.x and Python 3.11+. Bootstrap installs, in this order:
1. `pip install "numpy<2.1"` (**first**; tribev2 breaks on newer NumPy)
2. `pip install "tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git@af58661"` (**pinned commit**)
3. `nilearn torch torchaudio transformers huggingface_hub open_clip_torch av onnx onnxruntime scikit-learn pandas tqdm kaggle gdown` + `apt-get install -y ffmpeg`

Set `HF_HOME=/workspace/hf_cache` so every model is downloaded once to the volume and shared by both Pods.

## 3. Llama 3.2-3B (TRIBE's text encoder) — already solved

Public, ungated copy: no Meta approval, no HF login.
```
hf download unsloth/Llama-3.2-3B \
  --revision d4446454d87d51aa42e1fb174f25acc5f8762331 \
  --local-dir /workspace/models/Llama-3.2-3B
```
Skip the download if it's already on the volume. **Verify, and hard-stop if a hash differs:**
- `model-00001-of-00002.safetensors` → `584d8d3e3f82f7964955174dfe5e3b1cf117a9d859f022cfdf7fcb884856e002`
- `model-00002-of-00002.safetensors` → `4719a04514ec2f060240711b7c33ab21187cac730ecaba3040b7a0fd95a9cefb`

Load TRIBE with a config override (don't edit TRIBE's code):
```python
from tribev2 import TribeModel
model = TribeModel.from_pretrained(
    "facebook/tribev2", cache_folder="/workspace/hf_cache",
    config_update={"data.text_feature.model_name": "/workspace/models/Llama-3.2-3B"},
)
```
Get the exact inference API (building the events dataframe from a video, then predicting) from the repo's README and `tribe_demo.ipynb` **at commit af58661**. Don't guess. Once everything is cached, set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. Use the full trimodal pathway. Keep Llama's LICENSE file with the weights. TRIBE weights are CC BY-NC 4.0 (non-commercial); record that in the outputs.

## 4. Data

Volume layout:
```
/workspace/data/raw/{liris_accede,tikharm,xd_violence,demo}/
/workspace/data/clips/<dataset>/<clip_id>.mp4
/workspace/data/manifest.csv
/workspace/teacher/<dataset>/<clip_id>.npz
/workspace/student/features/<dataset>/<clip_id>.npz
/workspace/runs/<run>/   /workspace/export/   /workspace/logs/
```

| Dataset | Role | Get it |
|---|---|---|
| **LIRIS-ACCEDE (Discrete)** | Main teacher + stress-label set (~9,800 clips, 8–12 s, valence/arousal ratings) | Uploaded by the user to `data/raw/liris_accede/`. If missing, use the fallback below. |
| **Demo clips** (6–8) | Live demo. Top priority for teacher labels. | Uploaded by the user to `data/raw/demo/`. |
| **TikHarm** | Out-of-domain test (real TikTok). Never train on it. | Kaggle `anhoangvo/tikharm-dataset`. Download on a Pod (Kaggle creds as env vars) straight onto the volume. |
| **XD-Violence** (≤300 clips) | Extra stressful positives (audio-heavy) | Links at https://roc-ng.github.io/XD-Violence/ (use `gdown` if Google Drive). If it takes more than 15 minutes, skip it. |
| ~~RWF-2000~~ | Dropped (files withheld). | n/a |

**Normalize all clips identically** with ffmpeg: same codec, short side 256, fixed 24 fps, mono 16 kHz audio, cut into 8–12 s windows.

**Manifest** columns: `clip_id, dataset, source_group, path, duration_s, valence, arousal, stress_label, split`.
- **Split by `source_group`** (the source film for LIRIS-ACCEDE), never by clip. 80/10/10. TikHarm and demo clips are test-only.
- LIRIS `stress_label`: **1** = bottom-third valence AND top-third arousal. **0** = top-third valence AND bottom-third arousal. Otherwise unlabeled (still used for distillation).
- XD-Violence violent clips → 1. TikHarm "Harmful" → 1, "Safe" → 0, other classes dropped.

**Fallback if LIRIS-ACCEDE isn't on the volume when the GPUs are ready:** don't wait. Start the teacher on demo + TikHarm + XD-Violence, and tell the user. Insert LIRIS-ACCEDE at the front of tier 2 as soon as it lands. If it never arrives: train the stress readout on TikHarm with a held-out split, and say clearly in the report that there's no out-of-domain test.

## 5. Pipeline

**GPU A = teacher (TRIBE only). GPU B = student.** If only one Pod is affordable or available, run both roles on one H100 at once; the student is tiny.

### Step 0: smoke test + benchmark (≤20 min)
- **A:** verify the Llama hashes. Run TRIBE on 20 clips: measure clips/hour/worker, peak memory, and whether 2 workers fit. Confirm output `(T, 20484)` on fsaverage5 at 1 Hz. Check whether the released weights include subcortical predictions (yes/no). Run the demo clips; for any jump-scare or sudden-event clip, plot auditory cortex + anterior insula over time and report whether there's a visible response.
- **B:** encoder smoke test on 20 clips.
- Post **one** message with the numbers and the projected number of clips the queue can label, then **start the full queue immediately**.

### Step 1: teacher queue (GPU A, until ~1 h before the deadline)
Tiers, in order: (1) demo clips; (2) LIRIS-ACCEDE clips with `stress_label ∈ {0,1}`, balanced across splits; (3) TikHarm test + XD-Violence; (4) remaining LIRIS-ACCEDE.
Per clip, `teacher/<dataset>/<clip_id>.npz`:
- `vertices` float16 `(T, 20484)`
- `parcels` float32 `(T, P)`: per-parcel mean over a cortical atlas on fsaverage5 (HCP-MMP if available, else Destrieux via nilearn). Save the parcel names.
- `roi` float32 `(T, K)`: left/right anterior insula, dorsal anterior cingulate, medial prefrontal cortex, early auditory cortex, early visual cortex. Save the exact parcel membership.
- metadata: TRIBE commit, text pathway on/off, runtime.

**Resumable:** skip clips whose output exists, log failures and continue, write progress every 25 clips.

### Step 2: student features (GPU B, start right after Step 0, for ALL clips)
- **Vision:** a small frozen CLIP-style encoder that exports to ONNX and runs in-browser (MobileCLIP-S0/S1 or similar). **4 fps**, 224 px, per-frame embeddings.
- **Audio:** a small frozen AudioSet-pretrained CNN that exports to ONNX (YAMNet/EfficientAT class). 16 kHz, 1 s windows, 250 ms hop.
- Save encoder names, versions and param counts.

### Step 3: train (GPU B, iterate as teacher labels arrive; retraining from cached features is cheap)
- Per 1 s window input: vision mean + max over the 4 frames + frame-difference magnitude, concatenated with the audio embedding.
- Model: 2–3 layer MLP (hidden ≤512) + short temporal 1D conv over neighbouring windows. Fewer than 5M trainable params.
- Targets: `parcels` (primary) + `roi` (auxiliary). **Lag:** TRIBE lags the stimulus by ~5 s. Estimate the best lag (0–8 s) by cross-correlation on train, then shift targets earlier so predictions are **stimulus-aligned**. Save the lag in the config.
- Loss: MSE + (1 − Pearson r) per parcel.
- **Stress readout:** freeze the student. Fit logistic regression on clip-level mean + max of the predicted `roi`/`parcels` using `stress_label` (LIRIS train). Save coefficients by ROI name.
- Keep the best run by val parcel correlation.

### Step 4: evaluate (~45 min before the deadline)
`runs/<best>/metrics.json` + `REPORT.md`:
- Student vs teacher Pearson r (mean/median per parcel and per stress ROI) on LIRIS **test** films.
- Stress AUROC on LIRIS test and TikHarm.
- Ablations: audio-only / vision-only / both.
- Demo clips: student vs teacher stress-ROI curves.
- Data counts per dataset and split.

### Step 5: export (~30 min before the deadline; never cut this)
Into `export/`:
- `vision_encoder.onnx`, `audio_encoder.onnx`, `student_head.onnx`, each in **fp16 and int8**. Check ONNX outputs match PyTorch within tolerance.
- `stress_readout.json`: ROI names, feature definition (mean/max), weights, bias.
- `demo/<clip_id>.json` for every demo clip, 1 Hz, stimulus-aligned:
  ```json
  {"clip_id": "...", "hz": 1, "lag_s": 5,
   "roi_names": ["..."],
   "teacher": {"roi": [[...]], "stress": [...]},
   "student": {"roi": [[...]], "stress": [...]}}
  ```
- `export/README.md`, the **contract for the web team**: exact preprocessing (fps, crop, normalization mean/std, audio sample rate, waveform vs log-mel and its params, window/hop, pooling formula), every model's input/output names, shapes and dtypes, the history length W the head expects, parcel/ROI names, lag, licenses.
- Student latency on the GPU (per 1 s window, encoders + head, p50/p95), for reference only.

**If time runs short, cut in this order:** tier 4 of the queue → ablations → int8 export → XD-Violence. **Never cut:** demo-clip teacher traces, the fp16 ONNX export, `export/README.md`.

## 6. Hand back

Copy `export/` to the user's machine with `aws s3 sync` and tell them where it is. Stop all Pods and confirm. Final message: total spend, what was trained on (clip counts), headline metrics, and anything the web team must know.

**Status line every ~15 min:** `[time] A: <job n/total ETA> | B: <job> | spend $X / $50`
