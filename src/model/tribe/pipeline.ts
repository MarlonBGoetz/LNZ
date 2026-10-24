import { AUD_DIM, MEL, ROI_NAMES, VIS_DIM, VIS_SIZE, type Readout } from "./contract";
import { headInput, stressCurve, windowFeature } from "./features";
import { audioWindows, logMel } from "./logmel";

/** Model execution, injected so the same pipeline runs on onnxruntime-web (browser) and onnxruntime-node (tests). */
export interface TribeRunner {
  /** images: N x [3,224,224] RGB in [0,1] → N x 512 */
  vision(images: Float32Array, n: number): Promise<Float32Array>;
  /** logmel: N x [1,128,101] → N x 960 */
  audio(logmel: Float32Array, n: number): Promise<Float32Array>;
  /** feats: [1,3,2496] → roi [6] */
  head(feats: Float32Array): Promise<Float32Array>;
}

export type TribeInput = {
  /** Frames sampled at 4 fps from t=0, each [3,224,224]. */
  frames: Float32Array[];
  /** Mono 32 kHz waveform, or null if the audio couldn't be decoded (zeros are used). */
  wav: Float32Array | null;
};

export type TribeResult = {
  seconds: number;
  roi: number[][];
  stress: number[];
  ms: { vision: number; audio: number; head: number };
};

const VISION_BATCH = 8;
const FRAME_LEN = 3 * VIS_SIZE * VIS_SIZE;
const MEL_LEN = MEL.nMels * MEL.frames;

const timed = async <T>(fn: () => Promise<T>): Promise<[T, number]> => {
  const s = performance.now();
  const v = await fn();
  return [v, performance.now() - s];
};

/** Frames + audio → per-second ROI and stress curve, following the README pipeline. */
export const runTribe = async (input: TribeInput, runner: TribeRunner, readout: Readout): Promise<TribeResult> => {
  const nFrames = input.frames.length;
  if (nFrames === 0) throw new Error("no frames");
  const seconds = Math.ceil(nFrames / 4);

  const [vis, visMs] = await timed(async () => {
    const out = new Float32Array(nFrames * VIS_DIM);
    for (let i = 0; i < nFrames; i += VISION_BATCH) {
      const n = Math.min(VISION_BATCH, nFrames - i);
      const batch = new Float32Array(n * FRAME_LEN);
      for (let j = 0; j < n; j++) batch.set(input.frames[i + j]!, j * FRAME_LEN);
      out.set((await runner.vision(batch, n)).subarray(0, n * VIS_DIM), i * VIS_DIM);
    }
    return out;
  });

  const [aud, audMs] = await timed(async () => {
    const wins = audioWindows(input.wav ?? new Float32Array(seconds * 32000), seconds * 4);
    const mel = new Float32Array(wins.length * MEL_LEN);
    wins.forEach((w, i) => mel.set(logMel(w), i * MEL_LEN));
    return (await runner.audio(mel, wins.length)).subarray(0, wins.length * AUD_DIM);
  });

  const [roi, headMs] = await timed(async () => {
    const feats = Array.from({ length: seconds }, (_, t) => windowFeature(vis, aud, t));
    const out: number[][] = [];
    for (let t = 0; t < seconds; t++) out.push(Array.from((await runner.head(headInput(feats, t))).subarray(0, ROI_NAMES.length)));
    return out;
  });

  return { seconds, roi, stress: stressCurve(roi, readout), ms: { vision: visMs, audio: audMs, head: headMs } };
};
