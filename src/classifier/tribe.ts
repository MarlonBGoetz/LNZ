import type { FeedItem } from "../shared/feed-item";
import type { Classifier, ClassifyRequest, MediaClip, Verdict } from "./types";

export type StressAnalysis = { stress: number[]; backend: string; totalMs: number; frames: number; audioOk: boolean };

/** Runs the model on a clip. Implemented by the bridge's model-host client; faked in tests. */
export interface StressModel {
  analyze(clip: MediaClip, maxSec: number): Promise<StressAnalysis>;
}

export type TribeOptions = { threshold: number; maxSec: number; timeoutMs: number };

/**
 * Distilled TRIBE v2 student (video + audio). Verdict uses the readout's running stress after the
 * analyzed span (training used one 10 s window per video): block if final stress ≥ threshold.
 */
export class TribeStressClassifier implements Classifier {
  readonly name = "tribe";
  readonly needs = "media";
  readonly defaultTimeoutMs: number;
  private readonly notes = new Map<string, string>();

  constructor(
    private readonly model: StressModel,
    private readonly opts: TribeOptions,
  ) {
    this.defaultTimeoutMs = opts.timeoutMs;
  }

  async classify(reqs: ClassifyRequest[]): Promise<Record<string, Verdict>> {
    const out: Record<string, Verdict> = {};
    for (const { item, media } of reqs) {
      if (!media) {
        out[item.id] = "unknown";
        continue;
      }
      try {
        const a = await this.model.analyze(media, this.opts.maxSec);
        const final = a.stress.at(-1);
        if (final === undefined) throw new Error("empty curve");
        out[item.id] = final >= this.opts.threshold ? "block" : "allow";
        this.notes.set(item.id, `stress ${final.toFixed(2)} (≥${this.opts.threshold} blocks) · ${a.stress.length}s · ${Math.round(a.totalMs)}ms ${a.backend}${a.audioOk ? "" : " · no audio"}`);
      } catch (e) {
        out[item.id] = "unknown";
        this.notes.set(item.id, `model error: ${String(e).slice(0, 80)}`);
      }
    }
    return out;
  }

  explain(item: FeedItem): string | null {
    return this.notes.get(item.id) ?? null;
  }
}
