import { DEFAULT_STRESS_RULE, isStressful, type StressRule } from "./stress-rule";
import type { Classifier, ClassifyRequest, Verdict } from "./types";

/** Deterministic PRNG so the same id always gets the same fake curve. */
const seeded = (seed: string) => {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 2 ** 32;
};

/**
 * Stand-in for the ONNX stress model until it lands. Waits for media like the real one,
 * fakes a stress curve and latency, then applies the shared StressRule.
 */
export class MockStressClassifier implements Classifier {
  readonly name = "mockStress";
  readonly needs = "media";
  readonly defaultTimeoutMs = 8000;
  constructor(
    private readonly rule: StressRule = DEFAULT_STRESS_RULE,
    private readonly latencyMs: [number, number] = [300, 2500],
    private readonly stressShare = 0.3,
  ) {}

  async classify(reqs: ClassifyRequest[]): Promise<Record<string, Verdict>> {
    const out: Record<string, Verdict> = {};
    for (const { item, media } of reqs) {
      if (!media) {
        out[item.id] = "unknown";
        continue;
      }
      const rnd = seeded(item.id);
      const stressed = rnd() < this.stressShare;
      const n = Math.round(this.rule.windowSec * this.rule.hz);
      const curve = Array.from({ length: n }, () => (stressed ? 0.5 + rnd() * 0.5 : rnd() * 0.55));
      out[item.id] = isStressful(curve, this.rule) ? "block" : "allow";
    }
    const [lo, hi] = this.latencyMs;
    await new Promise((r) => setTimeout(r, lo + Math.random() * (hi - lo)));
    return out;
  }
}
