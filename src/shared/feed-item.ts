export type Platform = "tiktok";

export type FeedItem = {
  platform: Platform;
  id: string;
  /** Epoch ms. */
  createdAt: number | null;
  isAd: boolean;
  caption: string;
  hashtags: string[];
  language: string | null;
  author: { handle: string; name: string; verified: boolean; followers: number | null };
  video: {
    durationSec: number | null;
    width: number | null;
    height: number | null;
    coverUrl: string | null;
    playUrl: string | null;
    subtitles: unknown[];
  };
  music: { id: string | null; title: string | null; author: string | null };
  stats: {
    plays: number | null;
    likes: number | null;
    comments: number | null;
    shares: number | null;
    saves: number | null;
  };
  labels: { aigc: string | null; diversification: string[] };
  raw: unknown;
  /** Epoch ms. Media URLs expire, so keep this. */
  capturedAt: number;
  feedPosition: number;
};

export type ParseContext = { capturedAt: number };

/** One implementation per platform; the bridge picks by URL. */
export interface FeedParser {
  readonly platform: Platform;
  matches(url: string): boolean;
  parse(json: unknown, ctx: ParseContext): FeedItem[];
}
