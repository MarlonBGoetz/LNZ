/**
 * Feed interception contracts. Pure data + pure functions only, so adapters run
 * unchanged in the page's MAIN world, the isolated content script, and tests.
 */
import { DEFAULT_RULES, type FeedRules } from './rules';

export type Site = 'tiktok' | 'x';

export interface FeedItem {
  site: Site;
  /** TikTok item id / X tweet rest_id. */
  id: string;
  author?: string;
  text?: string;
  hashtags?: string[];
  soundTitle?: string;
  videoUrl?: string;
  coverUrl?: string;
  durationSec?: number;
  isVideo: boolean;
  isAd?: boolean;
}

export type FeedVerdict = 'keep' | 'block' | 'unknown';

export interface SiteAdapter {
  site: Site;
  /** True when this response URL carries feed items for the site. */
  claims(url: URL): boolean;
  /** Pull feed items out of a parsed JSON body. Must never throw on odd shapes. */
  extract(body: unknown): FeedItem[];
  /** Return a NEW body without the blocked items. Never mutate the input. */
  filter(body: unknown, blocked: ReadonlySet<string>): unknown;
}

export interface RemovalConfig {
  enabled: boolean;
  /** 'drop-and-jump': remove from feed data + pass over in the DOM. 'jump-only': DOM only. */
  mode: 'drop-and-jump' | 'jump-only' | 'off';
  /** How long a claimed feed response may wait for verdicts (hard max 400). */
  waitBudgetMs: number;
  sites: Record<Site, boolean>;
  autoSkip: boolean;
  rules: FeedRules;
}

export const DEFAULT_REMOVAL: RemovalConfig = {
  enabled: true,
  mode: 'drop-and-jump',
  waitBudgetMs: 150,
  sites: { tiktok: true, x: true },
  autoSkip: true,
  rules: DEFAULT_RULES,
};

export function normalizeRemoval(raw: unknown): RemovalConfig {
  const r = (isObj(raw) ? raw : {}) as Partial<RemovalConfig>;
  const d = DEFAULT_REMOVAL;
  const rr = (isObj(r.rules) ? r.rules : {}) as Partial<FeedRules>;
  const list = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(0, 500) : []);
  return {
    enabled: typeof r.enabled === 'boolean' ? r.enabled : d.enabled,
    mode: r.mode === 'jump-only' || r.mode === 'off' ? r.mode : 'drop-and-jump',
    waitBudgetMs: Math.min(MAX_WAIT_MS, Math.max(0, typeof r.waitBudgetMs === 'number' ? r.waitBudgetMs : d.waitBudgetMs)),
    sites: { tiktok: r.sites?.tiktok ?? true, x: r.sites?.x ?? true },
    autoSkip: typeof r.autoSkip === 'boolean' ? r.autoSkip : d.autoSkip,
    rules: {
      keywords: list(rr.keywords),
      hashtags: list(rr.hashtags),
      creators: list(rr.creators),
      blockAds: rr.blockAds === true,
      videoOnly: rr.videoOnly !== false,
    },
  };
}

export const MAX_WAIT_MS = 400;

/** postMessage channel between the MAIN-world interceptor and the isolated bridge. */
export const FEED_CHANNEL = 'lnz-feed-v1';

/** Port between the isolated bridge and the background judge. */
export const FEED_PORT = 'lnz-feed';
export type FeedPortIn = { type: 'items'; items: FeedItem[] };
export type FeedPortOut = { type: 'config'; config: RemovalConfig } | { type: 'verdicts'; verdicts: Record<string, FeedVerdict> };

export type ToIsolated =
  | { ch: typeof FEED_CHANNEL; dir: 'up'; type: 'items'; items: FeedItem[] }
  | { ch: typeof FEED_CHANNEL; dir: 'up'; type: 'removed'; site: Site; ids: string[] }
  | { ch: typeof FEED_CHANNEL; dir: 'up'; type: 'shape-miss'; site: Site; url: string };

/** Omit that distributes over a union. */
export type Payload<T> = T extends unknown ? Omit<T, 'ch' | 'dir'> : never;

export type ToMain =
  | { ch: typeof FEED_CHANNEL; dir: 'down'; type: 'ready'; config: RemovalConfig }
  | { ch: typeof FEED_CHANNEL; dir: 'down'; type: 'config'; config: RemovalConfig }
  | { ch: typeof FEED_CHANNEL; dir: 'down'; type: 'verdicts'; verdicts: Record<string, FeedVerdict> };

// ---- small, defensive JSON helpers --------------------------------------

export type Json = Record<string, unknown>;

export const isObj = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v);
export const str = (v: unknown): string | undefined => (typeof v === 'string' && v.length ? v : undefined);
export const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);
export const get = (o: unknown, ...path: (string | number)[]): unknown => {
  let cur: unknown = o;
  for (const k of path) {
    if (cur == null || typeof cur !== 'object') return undefined;
    cur = (cur as Record<string | number, unknown>)[k];
  }
  return cur;
};

/** Cheap deep copy for JSON payloads (feed bodies are JSON by definition). */
export const cloneJson = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
