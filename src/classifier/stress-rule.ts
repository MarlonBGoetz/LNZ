/** Per-video decision from a stress curve (one score per window, 0..1). Shared by mock and real models. */
export type StressRule = { windowSec: number; hz: number; threshold: number; aggregate: "max" | "mean" };

export const DEFAULT_STRESS_RULE: StressRule = { windowSec: 10, hz: 4, threshold: 0.6, aggregate: "max" };

export const isStressful = (curve: number[], rule: StressRule = DEFAULT_STRESS_RULE): boolean => {
  const head = curve.slice(0, Math.max(1, Math.round(rule.windowSec * rule.hz)));
  if (head.length === 0) return false;
  const score = rule.aggregate === "max" ? Math.max(...head) : head.reduce((a, b) => a + b, 0) / head.length;
  return score > rule.threshold;
};
