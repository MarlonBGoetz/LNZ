// TRIBE student model contract. Source of truth: model/tribe_student_export/README.md + encoders.json.

export const VIS_FPS = 4;
export const VIS_SIZE = 224;
export const VIS_DIM = 512;

export const AUD_SR = 32000;
export const AUD_WIN = AUD_SR; // 1.0 s
export const AUD_HOP = AUD_SR / 4; // 0.25 s
export const AUD_DIM = 960;

export const MEL = { nFft: 1024, winLength: 800, hop: 320, nMels: 128, fMin: 0, fMax: 16000, frames: 101 } as const;

export const HIST_W = 3;
export const FEAT_DIM = VIS_DIM * 3 + AUD_DIM; // 2496
export const ROI_NAMES = ["L_anterior_insula", "R_anterior_insula", "dACC", "mPFC", "early_auditory", "early_visual"] as const;

export type Readout = { roi_names: string[]; weights: number[]; bias: number };

export const MODEL_FILES = {
  vision: "vision_encoder.fp16.onnx",
  audio: "audio_encoder.fp16.onnx",
  head: "student_head.fp16.onnx",
  readout: "stress_readout.json",
} as const;
