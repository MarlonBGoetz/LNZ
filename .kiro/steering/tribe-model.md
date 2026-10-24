---
inclusion: manual
---
# TRIBE student model contract (summary)

Source of truth: `model/tribe_student_export/README.md` and `encoders.json`. Code: `src/model/tribe/contract.ts`.

- Vision: 4 fps, short side → 224 bilinear, center crop, RGB [0,1] NCHW; normalization is inside the model. `vision_encoder.fp16.onnx` (int8 is broken, removed).
- Audio: mono 32 kHz, 1 s windows every 0.25 s, torchaudio log-mel (n_fft 1024, win 800 hann, hop 320, 128 HTK mels, center reflect), `(log(mel+1e-5)+4.5)/5` → [1,128,101].
- Window feature (2496) = mean, max, mean|diff| of 4 frame embeddings + mean of 4 audio embeddings.
- Head: last W=3 windows (replicate first), outputs 6 ROI.
- Stress = sigmoid(w · [mean ROI 0..t, max ROI 0..t] + b). Verdict: final stress ≥ threshold (0.72 default; fewer false skips than 0.67).
- Preprocessing mismatches fail silently. Validate against demo traces, don't guess.
