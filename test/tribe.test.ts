import fs from "node:fs";
import path from "node:path";
import * as ort from "onnxruntime-node";
import { describe, expect, it } from "vitest";
import { AUD_SR, FEAT_DIM, MEL, MODEL_FILES, type Readout } from "../src/model/tribe/contract";
import { headInput, stressCurve, windowFeature } from "../src/model/tribe/features";
import { audioWindows, logMel } from "../src/model/tribe/logmel";
import { runTribe, type TribeRunner } from "../src/model/tribe/pipeline";

const DIR = path.resolve(import.meta.dirname, "../model/tribe_student_export");
const HAVE_MODEL = fs.existsSync(path.join(DIR, MODEL_FILES.readout));
const HAVE_DEMO = fs.existsSync(path.join(DIR, "demo/index.json"));
const readJson = (f: string) => JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8"));

describe.skipIf(!HAVE_DEMO)("stress readout matches the exported demo traces", () => {
  const readout: Readout = readJson(MODEL_FILES.readout);
  const index: { clip_id: string }[] = HAVE_DEMO ? readJson("demo/index.json") : [];

  it.each(index.slice(0, 60).map((c) => c.clip_id))("%s", (id) => {
    const d = readJson(`demo/${id}.json`);
    const ours = stressCurve(d.student.roi, readout);
    ours.forEach((v, i) => expect(v).toBeCloseTo(d.student.stress[i], 3));
  });
});

describe("logMel", () => {
  const sine = (hz: number) => Float32Array.from({ length: AUD_SR }, (_, i) => Math.sin((2 * Math.PI * hz * i) / AUD_SR));

  it("has shape 128 x 101 for a 1 s window", () => expect(logMel(new Float32Array(AUD_SR))).toHaveLength(MEL.nMels * MEL.frames));

  it("puts a tone's energy in the expected mel band", () => {
    const m = logMel(sine(1000));
    const mid = 50;
    const col = Array.from({ length: MEL.nMels }, (_, b) => m[b * MEL.frames + mid]!);
    const peak = col.indexOf(Math.max(...col));
    const mel = (f: number) => 2595 * Math.log10(1 + f / 700);
    expect(Math.abs(peak - Math.round((mel(1000) / mel(16000)) * (MEL.nMels + 1)) + 1)).toBeLessThanOrEqual(1);
  });

  it("silence maps to the log floor", () => {
    const v = logMel(new Float32Array(AUD_SR))[0]!;
    expect(v).toBeCloseTo((Math.log(1e-5) + 4.5) / 5, 5);
  });

  it("windows every 0.25 s with zero-padded tail", () => {
    const w = audioWindows(new Float32Array(AUD_SR * 2), 100);
    expect(w).toHaveLength(8);
    expect(w[7]!.length).toBe(AUD_SR);
  });
});

describe("window features", () => {
  it("builds 2496-dim features and replicate-pads head history", () => {
    const vis = Float32Array.from({ length: 8 * 512 }, (_, i) => Math.floor(i / 512));
    const aud = new Float32Array(8 * 960).fill(2);
    const f0 = windowFeature(vis, aud, 0);
    expect(f0).toHaveLength(FEAT_DIM);
    expect(f0[0]).toBeCloseTo(1.5); // mean of frames 0..3
    expect(f0[512]).toBe(3); // max
    expect(f0[1024]).toBe(1); // mean |diff|
    expect(f0[1536]).toBe(2); // audio mean
    const f1 = windowFeature(vis, aud, 1);
    const h = headInput([f0, f1], 0);
    expect(Array.from(h.subarray(0, 4))).toEqual(Array.from(h.subarray(2 * FEAT_DIM, 2 * FEAT_DIM + 4)));
  });
});

describe.skipIf(!HAVE_MODEL)("runTribe with onnxruntime-node", () => {
  it("produces a bounded stress curve per second", { timeout: 60_000 }, async () => {
    const [vis, aud, head] = await Promise.all([MODEL_FILES.vision, MODEL_FILES.audio, MODEL_FILES.head].map((f) => ort.InferenceSession.create(path.join(DIR, f))));
    const runner: TribeRunner = {
      vision: async (x, n) => (await vis!.run({ image: new ort.Tensor("float32", x, [n, 3, 224, 224]) })).embedding!.data as Float32Array,
      audio: async (x, n) => (await aud!.run({ logmel: new ort.Tensor("float32", x, [n, 1, 128, 101]) })).embedding!.data as Float32Array,
      head: async (x) => (await head!.run({ feats: new ort.Tensor("float32", x, [1, 3, FEAT_DIM]) })).roi!.data as Float32Array,
    };
    const frames = Array.from({ length: 8 }, (_, i) => new Float32Array(3 * 224 * 224).fill(i / 8));
    const wav = Float32Array.from({ length: AUD_SR * 2 }, (_, i) => 0.3 * Math.sin(i / 10));
    const r = await runTribe({ frames, wav }, runner, readJson(MODEL_FILES.readout));
    expect(r.seconds).toBe(2);
    expect(r.roi).toHaveLength(2);
    expect(r.stress.every((s) => s > 0 && s < 1)).toBe(true);
  });
});
