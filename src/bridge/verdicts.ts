import type { ResolvedVerdict } from "../classifier/policy";

export type FinalReason = ResolvedVerdict["reason"] | "holdTimeout";
export type FinalVerdict = { verdict: ResolvedVerdict["verdict"]; reason: FinalReason };
export type VerdictEntry = FinalVerdict | { verdict: "pending"; reason?: undefined };

/** Verdict per item id. Final verdicts never change (a skipped video stays skipped). */
export class VerdictCache {
  private readonly map = new Map<string, FinalVerdict>();
  private readonly at = new Map<string, number>();
  private readonly inFlight = new Set<string>();

  /** When the final verdict was set (epoch ms). */
  atOf(id: string): number | null {
    return this.at.get(id) ?? null;
  }

  get(id: string): VerdictEntry {
    return this.map.get(id) ?? { verdict: "pending" };
  }
  has(id: string): boolean {
    return this.map.has(id);
  }
  isInFlight(id: string): boolean {
    return this.inFlight.has(id);
  }
  start(id: string): void {
    this.inFlight.add(id);
  }
  set(id: string, v: FinalVerdict): void {
    this.inFlight.delete(id);
    if (!this.map.has(id)) {
      this.map.set(id, v);
      this.at.set(id, Date.now());
    }
  }
  /** Classifier changed: forget verdicts for items not yet shown. */
  resetExcept(keep: ReadonlySet<string>): void {
    for (const id of [...this.map.keys()]) if (!keep.has(id)) (this.map.delete(id), this.at.delete(id));
    this.inFlight.clear();
  }
}
