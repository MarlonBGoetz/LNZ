import { AUD_SR, VIS_FPS, VIS_SIZE } from "./contract";
import type { TribeInput } from "./pipeline";

const SEEK_TIMEOUT_MS = 1500;
const LOAD_TIMEOUT_MS = 4000;

const once = (el: EventTarget, ok: string, ms: number): Promise<boolean> =>
  new Promise((resolve) => {
    const done = (v: boolean) => {
      clearTimeout(timer);
      el.removeEventListener(ok, onOk);
      el.removeEventListener("error", onErr);
      resolve(v);
    };
    const onOk = () => done(true);
    const onErr = () => done(false);
    const timer = setTimeout(() => done(false), ms);
    el.addEventListener(ok, onOk);
    el.addEventListener("error", onErr);
  });

/** Resize short side to 224 + center crop == crop the centered square, then scale to 224 (bilinear). Returns RGB NCHW in [0,1]. */
const toTensor = (ctx: CanvasRenderingContext2D, src: HTMLVideoElement): Float32Array => {
  const w = src.videoWidth;
  const h = src.videoHeight;
  const side = Math.min(w, h);
  ctx.drawImage(src, (w - side) / 2, (h - side) / 2, side, side, 0, 0, VIS_SIZE, VIS_SIZE);
  const px = ctx.getImageData(0, 0, VIS_SIZE, VIS_SIZE).data;
  const plane = VIS_SIZE * VIS_SIZE;
  const out = new Float32Array(3 * plane);
  for (let i = 0; i < plane; i++) {
    out[i] = px[i * 4]! / 255;
    out[plane + i] = px[i * 4 + 1]! / 255;
    out[2 * plane + i] = px[i * 4 + 2]! / 255;
  }
  return out;
};

/** Frames at 4 fps from t=0 for up to maxSec, stopping at the end of decodable data (partial downloads). */
const VISIBLE_WAIT_MS = 2000;

/** Chrome defers media loading in hidden pages; wait (bounded) for the tab to become visible. */
const whenVisible = (): Promise<void> =>
  document.visibilityState === "visible"
    ? Promise.resolve()
    : new Promise((r) => {
        const done = () => (document.removeEventListener("visibilitychange", on), clearTimeout(t), r());
        const on = () => document.visibilityState === "visible" && done();
        const t = setTimeout(done, VISIBLE_WAIT_MS);
        document.addEventListener("visibilitychange", on);
      });

export const decodeFrames = async (video: Blob, maxSec: number): Promise<Float32Array[]> => {
  await whenVisible();
  const url = URL.createObjectURL(video);
  const el = document.createElement("video");
  el.muted = true;
  el.preload = "auto";
  el.src = url;
  try {
    if (!(await once(el, "loadeddata", LOAD_TIMEOUT_MS))) return [];
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = VIS_SIZE;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "medium";
    const dur = Number.isFinite(el.duration) ? el.duration : maxSec;
    const n = Math.max(1, Math.min(Math.round(dur * VIS_FPS), maxSec * VIS_FPS));
    const frames: Float32Array[] = [];
    for (let i = 0; i < n; i++) {
      const t = i / VIS_FPS;
      if (i > 0) {
        const end = el.buffered.length ? el.buffered.end(el.buffered.length - 1) : 0;
        if (t > end) break;
        el.currentTime = t;
        if (!(await once(el, "seeked", SEEK_TIMEOUT_MS))) break;
      }
      frames.push(toTensor(ctx, el));
    }
    return frames;
  } finally {
    el.removeAttribute("src");
    el.load();
    URL.revokeObjectURL(url);
  }
};

/** Mono 32 kHz waveform for up to maxSec, or null if the container can't be decoded (e.g. a truncated file). */
export const decodeAudio = async (media: Blob, maxSec: number): Promise<Float32Array | null> => {
  try {
    const ctx = new OfflineAudioContext(1, 1, AUD_SR);
    const buf = await ctx.decodeAudioData(await media.arrayBuffer());
    const len = Math.max(1, Math.min(Math.ceil(buf.duration * AUD_SR), maxSec * AUD_SR));
    const off = new OfflineAudioContext(1, len, AUD_SR);
    const src = off.createBufferSource();
    src.buffer = buf;
    src.connect(off.destination);
    src.start();
    return (await off.startRendering()).getChannelData(0);
  } catch {
    return null;
  }
};

export const decodeClip = async (video: Blob, audio: Blob | null, maxSec: number): Promise<TribeInput & { audioOk: boolean }> => {
  const [frames, wav] = await Promise.all([decodeFrames(video, maxSec), decodeAudio(audio ?? video, maxSec)]);
  return { frames, wav, audioOk: wav !== null };
};
