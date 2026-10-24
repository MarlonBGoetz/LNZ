import type { FeedItem } from "../shared/feed-item";
import type { Classifier, ClassifyRequest, Verdict } from "./types";

export class StubClassifier implements Classifier {
  readonly name = "stub";
  readonly needs = "metadata";
  readonly defaultTimeoutMs = 300;
  async classify(reqs: ClassifyRequest[]): Promise<Record<string, Verdict>> {
    return Object.fromEntries(reqs.map((r) => [r.item.id, "allow" as const]));
  }
}

/** Test classifier: blocks items whose caption or hashtags contain the pattern (case-insensitive). */
export class KeywordClassifier implements Classifier {
  readonly name = "keyword";
  readonly needs = "metadata";
  readonly defaultTimeoutMs = 300;
  private readonly needle: string;
  constructor(pattern: string) {
    this.needle = pattern.trim().toLowerCase();
  }
  private hit(r: ClassifyRequest): boolean {
    if (!this.needle) return false;
    const tag = this.needle.replace(/^#/, "");
    return r.item.caption.toLowerCase().includes(this.needle) || r.item.hashtags.some((h) => h.toLowerCase() === tag);
  }
  async classify(reqs: ClassifyRequest[]): Promise<Record<string, Verdict>> {
    return Object.fromEntries(reqs.map((r) => [r.item.id, this.hit(r) ? "block" : ("allow" as Verdict)]));
  }
  explain(item: FeedItem): string | null {
    return this.hit({ item, media: null }) ? `keyword "${this.needle}"` : null;
  }
}
