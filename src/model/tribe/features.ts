import { AUD_DIM, FEAT_DIM, HIST_W, VIS_DIM, type Readout } from "./contract";

const rows = (flat: Float32Array, dim: number, from: number, to: number): Float32Array[] => {
  const out: Float32Array[] = [];
  for (let i = from; i < to && (i + 1) * dim <= flat.length; i++) out.push(flat.subarray(i * dim, (i + 1) * dim));
  return out;
};

/** encoders.window_features: [mean(vis), max(vis), mean|diff(vis)|, mean(aud)] over the 4 hops of second t. */
export const windowFeature = (vis: Float32Array, aud: Float32Array, t: number): Float32Array => {
  const nVis = vis.length / VIS_DIM;
  const nAud = aud.length / AUD_DIM;
  let v = rows(vis, VIS_DIM, 4 * t, 4 * t + 4);
  if (v.length === 0) v = rows(vis, VIS_DIM, nVis - 1, nVis);
  let a = rows(aud, AUD_DIM, 4 * t, 4 * t + 4);
  if (a.length === 0) a = rows(aud, AUD_DIM, nAud - 1, nAud);
  const out = new Float32Array(FEAT_DIM);
  for (let j = 0; j < VIS_DIM; j++) {
    let sum = 0;
    let max = -Infinity;
    let diff = 0;
    for (let i = 0; i < v.length; i++) {
      const x = v[i]![j]!;
      sum += x;
      if (x > max) max = x;
      if (i > 0) diff += Math.abs(x - v[i - 1]![j]!);
    }
    out[j] = sum / v.length;
    out[VIS_DIM + j] = max;
    out[2 * VIS_DIM + j] = v.length > 1 ? diff / (v.length - 1) : 0;
  }
  for (let j = 0; j < AUD_DIM; j++) {
    let sum = 0;
    for (const r of a) sum += r[j]!;
    out[3 * VIS_DIM + j] = sum / a.length;
  }
  return out;
};

/** Head input for second t: windows [t-2, t-1, t], replicating window 0 at the start. */
export const headInput = (feats: Float32Array[], t: number): Float32Array => {
  const out = new Float32Array(HIST_W * FEAT_DIM);
  for (let k = 0; k < HIST_W; k++) out.set(feats[Math.max(0, t - (HIST_W - 1) + k)]!, k * FEAT_DIM);
  return out;
};

/** stress_readout.json: sigmoid(w · [mean over 0..t of each ROI, max over 0..t] + b), one value per t. */
export const stressCurve = (roi: number[][], r: Readout): number[] => {
  const k = r.roi_names.length;
  const sum = new Array<number>(k).fill(0);
  const max = new Array<number>(k).fill(-Infinity);
  return roi.map((row, t) => {
    let z = r.bias;
    for (let i = 0; i < k; i++) {
      sum[i]! += row[i]!;
      max[i] = Math.max(max[i]!, row[i]!);
      z += r.weights[i]! * (sum[i]! / (t + 1)) + r.weights[k + i]! * max[i]!;
    }
    return 1 / (1 + Math.exp(-z));
  });
};
