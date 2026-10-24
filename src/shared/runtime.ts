import type { Verdict } from "../classifier/types";
import type { FeedItem } from "./feed-item";

/** content/popup → background */
export type RuntimeRequest =
  | { kind: "httpClassify"; url: string; items: Omit<FeedItem, "raw">[]; timeoutMs: number }
  | { kind: "ping" };

export type HttpClassifyResponse = { ok: true; verdicts: Record<string, Verdict> } | { ok: false; error: string };
