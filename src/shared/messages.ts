// window.postMessage protocol between injected (MAIN) and bridge (isolated). All types prefixed LNZ_.

export const MSG = {
  feed: "LNZ_FEED_RESPONSE",
  media: "LNZ_MEDIA_CHUNK",
  config: "LNZ_PAGE_CONFIG",
  dropRequest: "LNZ_DROP_REQUEST",
  dropResponse: "LNZ_DROP_RESPONSE",
} as const;

export type CaptureSource = "fetch" | "xhr" | "embedded";

export type FeedResponseMessage = {
  type: typeof MSG.feed;
  via: CaptureSource;
  url: string;
  capturedAt: number;
  json: unknown;
};

/** One media response body (or the part delivered before TikTok aborted it). */
export type MediaChunkMessage = {
  type: typeof MSG.media;
  path: string;
  start: number;
  total: number | null;
  contentType: string | null;
  complete: boolean;
  bytes: ArrayBuffer;
  at: number;
};

/** Config subset the MAIN world needs. */
export type PageConfigMessage = { type: typeof MSG.config; active: boolean; drop: boolean; dropTimeoutMs: number };

export type DropRequestMessage = { type: typeof MSG.dropRequest; reqId: string; json: unknown; capturedAt: number };
export type DropResponseMessage = { type: typeof MSG.dropResponse; reqId: string; blockIds: string[] };

export type PageMessage = FeedResponseMessage | MediaChunkMessage | PageConfigMessage | DropRequestMessage | DropResponseMessage;

export const isPageMessage = (d: unknown): d is PageMessage =>
  typeof d === "object" && d !== null && typeof (d as { type?: unknown }).type === "string" && (d as { type: string }).type.startsWith("LNZ_");
