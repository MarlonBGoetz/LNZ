import type { FeedItem, FeedParser, ParseContext } from "../../shared/feed-item";
import { arr, first, isObj, num, obj, str, type Obj } from "../../shared/json";
import { HOST_PATTERN } from "./config";

const MAX_DEPTH = 12;

/** Video object = numeric string id + `video` object + `author` object. No fixed paths. */
const looksLikeVideo = (o: Obj): boolean =>
  typeof o.id === "string" && /^\d+$/.test(o.id) && isObj(o.video) && isObj(o.author);

export const findVideoObjects = (root: unknown): Obj[] => {
  const found: Obj[] = [];
  const seen = new WeakSet<object>();
  const walk = (node: unknown, depth: number): void => {
    if (depth > MAX_DEPTH || typeof node !== "object" || node === null || seen.has(node)) return;
    seen.add(node);
    if (Array.isArray(node)) return node.forEach((v) => walk(v, depth + 1));
    if (looksLikeVideo(node as Obj)) return void found.push(node as Obj);
    for (const v of Object.values(node)) walk(v, depth + 1);
  };
  walk(root, 0);
  return found;
};

const hashtagsOf = (raw: Obj): string[] => {
  const tags = [
    ...arr(raw.challenges).map((c) => str(obj(c).title)),
    ...arr(raw.textExtra).map((t) => str(obj(t).hashtagName)),
  ].filter((t): t is string => t !== null);
  const byKey = new Map<string, string>();
  for (const t of tags) if (!byKey.has(t.toLowerCase())) byKey.set(t.toLowerCase(), t);
  return [...byKey.values()];
};

/** `ShowAIGC` is a UI flag (true on nearly all items), so it is ignored. */
const aigcOf = (raw: Obj): string | null => {
  const desc = str(raw.AIGCDescription);
  if (desc) return desc;
  const mod = num(raw.moderationAigcLabelType);
  if (mod !== null) return `moderation:${mod}`;
  const creator = num(raw.aigcLabelType);
  if (creator !== null) return `creator:${creator}`;
  return raw.IsAigc === true ? "aigc" : null;
};

export const normalizeTikTokItem = (raw: Obj, feedPosition: number, ctx: ParseContext): FeedItem => {
  const author = obj(raw.author);
  const authorStats = first(isObj(raw.authorStats) ? raw.authorStats : null, isObj(raw.authorStatsV2) ? raw.authorStatsV2 : null) ?? {};
  const video = obj(raw.video);
  const music = obj(raw.music);
  const exact = obj(raw.statsV2);
  const rounded = obj(raw.stats);
  const stat = (k: string) => first(num(exact[k]), num(rounded[k]));
  const createTime = num(raw.createTime);

  return {
    platform: "tiktok",
    id: String(raw.id),
    createdAt: createTime !== null && createTime > 0 ? createTime * 1000 : null,
    isAd: raw.isAd === true || isObj(raw.ad_info),
    caption: str(raw.desc) ?? "",
    hashtags: hashtagsOf(raw),
    language: str(raw.textLanguage),
    author: {
      handle: str(author.uniqueId) ?? "",
      name: str(author.nickname) ?? "",
      verified: author.verified === true,
      followers: first(num(authorStats.followerCount), num(author.followerCount)),
    },
    video: {
      durationSec: num(video.duration),
      width: num(video.width),
      height: num(video.height),
      coverUrl: first(str(video.cover), str(video.originCover)),
      playUrl: first(str(video.playAddr), str(video.downloadAddr)),
      subtitles: arr(video.subtitleInfos),
    },
    music: { id: str(music.id), title: str(music.title), author: str(music.authorName) },
    stats: {
      plays: stat("playCount"),
      likes: stat("diggCount"),
      comments: stat("commentCount"),
      shares: stat("shareCount"),
      saves: stat("collectCount"),
    },
    labels: {
      aigc: aigcOf(raw),
      diversification: arr(raw.diversificationLabels).filter((l): l is string => typeof l === "string"),
    },
    raw,
    capturedAt: ctx.capturedAt,
    feedPosition,
  };
};

/** Parses any TikTok payload (item_list response or rehydration JSON). Dedupes by id within the payload. */
export const parseTikTok = (json: unknown, ctx: ParseContext): FeedItem[] => {
  const ids = new Set<string>();
  const items: FeedItem[] = [];
  for (const raw of findVideoObjects(json)) {
    const id = String(raw.id);
    if (ids.has(id)) continue;
    ids.add(id);
    try {
      items.push(normalizeTikTokItem(raw, items.length, ctx));
    } catch {
      // Malformed item: skip it, keep the batch.
    }
  }
  return items;
};

export const tiktokParser: FeedParser = {
  platform: "tiktok",
  matches: (url) => {
    try {
      return HOST_PATTERN.test(new URL(url).hostname);
    } catch {
      return false;
    }
  },
  parse: parseTikTok,
};
