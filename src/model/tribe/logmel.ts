import { AUD_HOP, AUD_SR, AUD_WIN, MEL } from "./contract";

// torchaudio MelSpectrogram(sr=32000, n_fft=1024, win=800 hann periodic, hop=320, center reflect, power 2, htk, norm None),
// then (log(mel + 1e-5) + 4.5) / 5. Output row-major [nMels, frames].

const N_FREQ = MEL.nFft / 2 + 1;

const hzToMel = (f: number) => 2595 * Math.log10(1 + f / 700);
const melToHz = (m: number) => 700 * (10 ** (m / 2595) - 1);

/** [N_FREQ, nMels], same construction as torchaudio.functional.melscale_fbanks. */
const buildFilterbank = (): Float64Array => {
  const fb = new Float64Array(N_FREQ * MEL.nMels);
  const allFreqs = Array.from({ length: N_FREQ }, (_, i) => (i * (AUD_SR / 2)) / (N_FREQ - 1));
  const mMin = hzToMel(MEL.fMin);
  const mMax = hzToMel(MEL.fMax);
  const fPts = Array.from({ length: MEL.nMels + 2 }, (_, i) => melToHz(mMin + ((mMax - mMin) * i) / (MEL.nMels + 1)));
  for (let f = 0; f < N_FREQ; f++)
    for (let m = 0; m < MEL.nMels; m++) {
      const down = (allFreqs[f]! - fPts[m]!) / (fPts[m + 1]! - fPts[m]!);
      const up = (fPts[m + 2]! - allFreqs[f]!) / (fPts[m + 2]! - fPts[m + 1]!);
      fb[f * MEL.nMels + m] = Math.max(0, Math.min(down, up));
    }
  return fb;
};

/** Periodic hann of winLength, zero-padded (centered) to nFft like torch.stft. */
const buildWindow = (): Float64Array => {
  const w = new Float64Array(MEL.nFft);
  const off = Math.floor((MEL.nFft - MEL.winLength) / 2);
  for (let n = 0; n < MEL.winLength; n++) w[off + n] = 0.5 - 0.5 * Math.cos((2 * Math.PI * n) / MEL.winLength);
  return w;
};

const FB = buildFilterbank();
const WINDOW = buildWindow();

const BITREV = (() => {
  const bits = Math.log2(MEL.nFft);
  return Uint16Array.from({ length: MEL.nFft }, (_, i) => {
    let r = 0;
    for (let b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b);
    return r;
  });
})();

/** In-place radix-2 FFT. */
const fft = (re: Float64Array, im: Float64Array): void => {
  const n = re.length;
  for (let i = 0; i < n; i++) {
    const j = BITREV[i]!;
    if (j > i) {
      [re[i], re[j]] = [re[j]!, re[i]!];
      [im[i], im[j]] = [im[j]!, im[i]!];
    }
  }
  for (let size = 2; size <= n; size *= 2) {
    const half = size / 2;
    const step = (-2 * Math.PI) / size;
    for (let start = 0; start < n; start += size)
      for (let k = 0; k < half; k++) {
        const c = Math.cos(step * k);
        const s = Math.sin(step * k);
        const a = start + k;
        const b = a + half;
        const tr = re[b]! * c - im[b]! * s;
        const ti = re[b]! * s + im[b]! * c;
        re[b] = re[a]! - tr;
        im[b] = im[a]! - ti;
        re[a] = re[a]! + tr;
        im[a] = im[a]! + ti;
      }
  }
};

/** One 1 s window (AUD_WIN samples) → log-mel [128 * 101]. */
export const logMel = (wav: Float32Array): Float32Array => {
  const pad = MEL.nFft / 2;
  const n = wav.length;
  const padded = new Float64Array(n + 2 * pad);
  for (let i = 0; i < n; i++) padded[pad + i] = wav[i]!;
  for (let i = 0; i < pad; i++) {
    padded[pad - 1 - i] = wav[Math.min(n - 1, i + 1)]!;
    padded[pad + n + i] = wav[Math.max(0, n - 2 - i)]!;
  }
  const frames = 1 + Math.floor((padded.length - MEL.nFft) / MEL.hop);
  const out = new Float32Array(MEL.nMels * frames);
  const re = new Float64Array(MEL.nFft);
  const im = new Float64Array(MEL.nFft);
  const power = new Float64Array(N_FREQ);
  for (let f = 0; f < frames; f++) {
    const s = f * MEL.hop;
    for (let i = 0; i < MEL.nFft; i++) (re[i] = padded[s + i]! * WINDOW[i]!), (im[i] = 0);
    fft(re, im);
    for (let k = 0; k < N_FREQ; k++) power[k] = re[k]! * re[k]! + im[k]! * im[k]!;
    for (let m = 0; m < MEL.nMels; m++) {
      let acc = 0;
      for (let k = 0; k < N_FREQ; k++) acc += power[k]! * FB[k * MEL.nMels + m]!;
      out[m * frames + f] = (Math.log(acc + 1e-5) + 4.5) / 5;
    }
  }
  return out;
};

/** 1 s windows every 0.25 s from 0, zero-padded at the tail (encoders.audio_windows). Returns the first `count`. */
export const audioWindows = (wav: Float32Array, count: number): Float32Array[] => {
  const total = Math.max(1, Math.ceil(wav.length / AUD_HOP));
  return Array.from({ length: Math.min(count, total) }, (_, i) => {
    const w = new Float32Array(AUD_WIN);
    const start = i * AUD_HOP;
    w.set(wav.subarray(start, Math.min(wav.length, start + AUD_WIN)));
    return w;
  });
};
