import type { FeedItem } from "../shared/feed-item";

export type Verdict = "allow" | "block" | "unknown";

/** Encoded media captured from TikTok's own downloads. */
export type MediaClip = {
  /** muxed = one MP4 with both tracks; split = separate video/audio files (long videos). */
  layout: "muxed" | "split";
  video: Blob;
  audio: Blob | null;
  /** True if the whole file arrived, false if only a prefix. */
  complete: boolean;
};

export type ClassifyRequest = { item: FeedItem; media: MediaClip | null };

export interface Classifier {
  readonly name: string;
  /** "media" classifiers are called only once the item's media has been captured. */
  readonly needs: "metadata" | "media";
  readonly defaultTimeoutMs: number;
  classify(reqs: ClassifyRequest[]): Promise<Record<string, Verdict>>;
  /** Optional debug text: why an item would be blocked. */
  explain?(item: FeedItem): string | null;
  /** Optional debug score in [0,1] for UI bars (e.g. stress probability). */
  score?(item: FeedItem): number | null;
}
