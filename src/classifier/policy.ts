import type { FailMode } from "../shared/config";
import type { Classifier, ClassifyRequest, Verdict } from "./types";

export type ResolvedVerdict = { verdict: Exclude<Verdict, "unknown">; reason: "classifier" | "timeout" | "error" | "unknown" };

/** Runs a classifier with a timeout; anything not answered becomes allow/block per failMode. Never rejects. */
export const classifyWithPolicy = async (
  classifier: Classifier,
  reqs: ClassifyRequest[],
  timeoutMs: number,
  failMode: FailMode,
): Promise<Record<string, ResolvedVerdict>> => {
  const fallback: ResolvedVerdict["verdict"] = failMode === "failOpen" ? "allow" : "block";
  let reason: ResolvedVerdict["reason"] = "unknown";
  let answers: Record<string, Verdict> = {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    answers = await Promise.race([
      classifier.classify(reqs),
      new Promise<never>((_, rej) => (timer = setTimeout(() => rej(new Error("timeout")), timeoutMs))),
    ]);
  } catch (e) {
    reason = (e as Error)?.message === "timeout" ? "timeout" : "error";
  } finally {
    clearTimeout(timer);
  }
  const out: Record<string, ResolvedVerdict> = {};
  for (const { item } of reqs) {
    const v = answers[item.id];
    out[item.id] = v === "allow" || v === "block" ? { verdict: v, reason: "classifier" } : { verdict: fallback, reason };
  }
  return out;
};
