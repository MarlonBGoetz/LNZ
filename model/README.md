# Student brain-response model: web contract

Distilled from Meta TRIBE v2 (commit af58661, full trimodal: V-JEPA2 + Wav2Vec-BERT + Llama-3.2-3B text via WhisperX).
Predicts TRIBE's per-parcel cortical response (Destrieux atlas on fsaverage5, 148 parcels) and 6 stress ROIs,
**stimulus-aligned** at 1 Hz (target shifted by lag_s = 0 s, chosen on validation; TRIBE's own output is already
offset 5 s for hemodynamic lag).

## Pipeline per 1-second window t (t = 0, 1, 2, ... seconds from clip start)

1. **Vision** (`vision_encoder.*.onnx`, MobileCLIP-S1 / datacompdr, 21.5M params)
   - Sample frames at **4 fps** (frames at t, t+0.25, t+0.5, t+0.75 s).
   - Resize short side to 224 (bilinear), center-crop 224x224, RGB, float32 in [0,1], NCHW.
   - Input `image` float32 [N,3,224,224] (normalization mean=[0.0, 0.0, 0.0] std=[1.0, 1.0, 1.0] is applied **inside** the model).
   - Output `embedding` float32 [N,512], L2-normalized.
2. **Audio** (`audio_encoder.*.onnx`, EfficientAT mn10_as (AudioSet), 4.88M params)
   - Mono, **32000 Hz** waveform (float32 in [-1,1]).
   - Windows of **1.0 s** every **0.25 s** starting at 0 (zero-pad the tail).
   - Log-mel per window: n_fft=1024, win_length=800 (hann), hop=320, center=True (reflect pad), power=2,
     128 mel bands, HTK mel scale, f_min=0, f_max=16000, no filter norm; `logmel = (log(mel + 1e-5) + 4.5) / 5`.
     Shape [1,128,101] per window.
   - Input `logmel` float32 [N,1,128,101]. Output `embedding` float32 [N,960].
3. **Window feature** (length 2496) = concat(
   mean of the 4 frame embeddings, elementwise max of the 4, mean |e[i+1]-e[i]| over the 3 consecutive pairs,
   mean of the 4 audio embeddings whose windows start at t, t+.25, t+.5, t+.75).
4. **Head** (`student_head.*.onnx`): input `feats` float32 [1,W,2496] = the last **W = 3** window features,
   oldest first (at clip start, repeat the first window to fill). Feature standardization is inside the model.
   Outputs `parcels` float32 [1,148] and `roi` float32 [1,6] for the newest window, in TRIBE units.
5. **Stress** (`stress_readout.json`): x = concat(mean over windows 0..t of each ROI, max over 0..t of each ROI);
   stress = sigmoid(w . x + bias).

ROI names (order of `roi`): ['L_anterior_insula', 'R_anterior_insula', 'dACC', 'mPFC', 'early_auditory', 'early_visual']
ROI parcel membership: {"L_anterior_insula": ["L_G_insular_short", "L_S_circular_insula_ant"], "R_anterior_insula": ["R_G_insular_short", "R_S_circular_insula_ant"], "dACC": ["L_G_and_S_cingul-Mid-Ant", "R_G_and_S_cingul-Mid-Ant"], "mPFC": ["L_G_and_S_cingul-Ant", "R_G_and_S_cingul-Ant", "L_G_rectus", "R_G_rectus", "L_S_suborbital", "R_S_suborbital"], "early_auditory": ["L_G_temp_sup-G_T_transv", "R_G_temp_sup-G_T_transv", "L_S_temporal_transverse", "R_S_temporal_transverse"], "early_visual": ["L_S_calcarine", "R_S_calcarine", "L_G_cuneus", "R_G_cuneus", "L_Pole_occipital", "R_Pole_occipital"]}
Parcel names (order of `parcels`): see `parcel_names.json`.

## Files
{
 "student_head": {
  "fp32": {
   "file": "student_head.fp32.onnx",
   "mb": 9.67,
   "max_rel_err_vs_torch": 0.0
  },
  "fp16": {
   "file": "student_head.fp16.onnx",
   "mb": 4.84,
   "max_rel_err_vs_torch": 0.00047
  },
  "int8": {
   "file": "student_head.int8.onnx",
   "mb": 2.46,
   "max_rel_err_vs_torch": 0.13427
  },
  "inputs": {
   "feats": [
    1,
    3,
    2496
   ]
  },
  "outputs": [
   "parcels",
   "roi"
  ]
 },
 "vision_encoder": {
  "fp32": {
   "file": "vision_encoder.fp32.onnx",
   "mb": 86.1,
   "max_rel_err_vs_torch": 0.0
  },
  "fp16": {
   "file": "vision_encoder.fp16.onnx",
   "error": "[ONNXRuntimeError] : 1 : FAIL : Load model from /workspace/export/vision_encoder.fp16.onnx failed:Type Error: Type (tensor(float16)) of output arg (/visual/trunk/stages.3/blocks/blocks.0/token_mixer/Cast_output_0) of node (/visual/trunk/stages.3/blocks/blocks.0/token_mixer/Cast) does not match expec"
  },
  "int8": {
   "file": "vision_encoder.int8.onnx",
   "mb": 22.46,
   "max_rel_err_vs_torch": 1.03691
  },
  "inputs": {
   "image": [
    1,
    3,
    224,
    224
   ]
  },
  "outputs": [
   "embedding"
  ]
 },
 "audio_encoder": {
  "fp32": {
   "file": "audio_encoder.fp32.onnx",
   "mb": 11.93,
   "max_rel_err_vs_torch": 0.0
  },
  "fp16": {
   "file": "audio_encoder.fp16.onnx",
   "mb": 6.04,
   "max_rel_err_vs_torch": 0.00322
  },
  "int8": {
   "file": "audio_encoder.int8.onnx",
   "mb": 3.25,
   "max_rel_err_vs_torch": 0.08791
  },
  "inputs": {
   "logmel": [
    1,
    1,
    128,
    101
   ]
  },
  "outputs": [
   "embedding"
  ]
 }
}
fp16 models keep float32 inputs/outputs. int8 = dynamic weight quantization.

## Demo traces
`demo/<clip_id>.json`: 1 Hz, stimulus-aligned, teacher and student ROI curves and stress curves
(`t` lists the seconds that have a teacher value).

## Reference latency
{"p50_ms": 10.06, "p95_ms": 10.17, "note": "H100, PyTorch, per 1 s window = 4 frames + 4 audio hops + head; reference only"}

## Licenses
- TRIBE v2 code and weights: **CC BY-NC 4.0 (non-commercial)**. These student models are distilled from its outputs; treat them as non-commercial.
- Llama 3.2 (TRIBE's text encoder, used only for teacher labels): Llama 3.2 Community License (copy kept on the volume with the weights).
- MobileCLIP-S1: see open_clip / Apple MobileCLIP license. EfficientAT mn10_as (AudioSet): see its repository license.
- TikHarm videos (training data): Kaggle dataset `anhoangvo/tikharm-dataset`; follow its terms.

## Post-export fixes and model status (read this)
| Model | fp16 | int8 |
|---|---|---|
| `vision_encoder` (MobileCLIP-S1) | **Use this.** Repaired after export: the fp16 converter left 8 internal `Cast` nodes targeting float32, so ORT refused to load it; they now cast to float16. Verified vs the pod's PyTorch embeddings on a real clip: cosine 0.994 mean (40 frames). | **Removed**: dynamic int8 broke it (cosine ~0 vs PyTorch). |
| `audio_encoder` (EfficientAT mn10_as) | Use this (max rel err 0.3%). | Usable but lossy (max rel err 8.8%). |
| `student_head` | Use this (max rel err 0.05%). | Lossy (max rel err 13%); prefer fp16. |

Audio log-mel note: computed with torchaudio MelSpectrogram (HTK mel, no pre-emphasis), not EfficientAT's own
front end. Match the parameters above exactly; the encoder was frozen and the head was trained on these features.

Demo traces: `demo/index.json` lists 60 clips (8 demo + all labeled test clips) with label, uploader,
`english_speech` flag and final stress; each has `<id>.json` (1 Hz trace + timed transcript) and `<id>.mp4`.
The final second of every TRIBE prediction is dropped (end-of-clip edge spike).
