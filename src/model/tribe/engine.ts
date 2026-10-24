import * as ort from "onnxruntime-web/webgpu";
import { FEAT_DIM, MODEL_FILES, type Readout } from "./contract";
import { decodeClip } from "./decode";
import { runTribe, type TribeResult, type TribeRunner } from "./pipeline";

export type Backend = "webgpu" | "wasm";
export type EngineResult = TribeResult & { backend: Backend; frames: number; audioOk: boolean; decodeMs: number; totalMs: number };

const create = async (url: string, backend: Backend) =>
  ort.InferenceSession.create(url, { executionProviders: [backend], graphOptimizationLevel: "all" });

/** Loads the three ONNX models (WebGPU first, WASM fallback) and runs MediaClip bytes → stress. Browser only. */
export class TribeEngine {
  backend: Backend | null = null;
  /** Why a preferred backend was skipped (debug). */
  fallbackReason: string | null = null;
  /** Debug hook: called when a run enters a new stage. */
  onStage: (stage: string) => void = () => {};
  private runner: TribeRunner | null = null;
  private readout: Readout | null = null;
  private loading: Promise<void> | null = null;

  constructor(private readonly baseUrl: string) {
    ort.env.wasm.wasmPaths = new URL("ort/", baseUrl).href;
    ort.env.wasm.numThreads = 1; // extension frames are not cross-origin isolated
    ort.env.logLevel = "error";
  }

  init(): Promise<void> {
    return (this.loading ??= this.load());
  }

  private async load(): Promise<void> {
    const file = (f: string) => new URL(`models/${f}`, this.baseUrl).href;
    this.readout = await (await fetch(file(MODEL_FILES.readout))).json();
    const backends: Backend[] = "gpu" in navigator ? ["webgpu", "wasm"] : ["wasm"];
    let last: unknown;
    for (const b of backends) {
      try {
        // Sequential: the WebGPU EP rejects concurrent session creation.
        const vis = await create(file(MODEL_FILES.vision), b);
        const aud = await create(file(MODEL_FILES.audio), b);
        const head = await create(file(MODEL_FILES.head), b);
        this.runner = {
          vision: async (x, n) => (await vis.run({ image: new ort.Tensor("float32", x, [n, 3, 224, 224]) })).embedding!.getData() as Promise<Float32Array>,
          audio: async (x, n) => (await aud.run({ logmel: new ort.Tensor("float32", x, [n, 1, 128, 101]) })).embedding!.getData() as Promise<Float32Array>,
          head: async (x) => (await head.run({ feats: new ort.Tensor("float32", x, [1, 3, FEAT_DIM]) })).roi!.getData() as Promise<Float32Array>,
        };
        this.backend = b;
        await this.warmup();
        return;
      } catch (e) {
        last = e;
        this.fallbackReason = `${b}: ${String(e).slice(0, 300)}`;
      }
    }
    throw last ?? new Error("no backend");
  }

  private async warmup(): Promise<void> {
    await runTribe({ frames: [new Float32Array(3 * 224 * 224)], wav: null }, this.runner!, this.readout!);
  }

  async run(video: Blob, audio: Blob | null, maxSec: number): Promise<EngineResult> {
    await this.init();
    const t0 = performance.now();
    this.onStage("decode");
    const input = await decodeClip(video, audio, maxSec);
    const decodeMs = performance.now() - t0;
    if (input.frames.length === 0) throw new Error("could not decode video frames");
    this.onStage("infer");
    const r = await runTribe(input, this.runner!, this.readout!);
    return { ...r, backend: this.backend!, frames: input.frames.length, audioOk: input.audioOk, decodeMs, totalMs: performance.now() - t0 };
  }
}
