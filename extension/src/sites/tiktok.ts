import { cloneJson, get, isObj, num, str, type FeedItem, type Json, type SiteAdapter } from './types';

/**
 * TikTok web feed adapter.
 * Field names follow TikTok's web API as observed in 2024–2026. They are read
 * defensively; unknown shapes yield [] and the caller falls back to DOM skip-jump.
 */

const FEED_PATHS = [
  /\/api\/recommend\/item_list\/?$/,
  /\/api\/preload\/item_list\/?$/,
  /\/api\/related\/item_list\/?$/,
  /\/api\/post\/item_list\/?$/,
  /\/api\/explore\/item_list\/?$/,
  /\/api\/search\/item\/full\/?$/,
  /\/api\/search\/general\/full\/?$/,
];

export function tiktokItem(raw: unknown): FeedItem | null {
  if (!isObj(raw)) return null;
  const id = str(raw.id) ?? (typeof raw.id === 'number' ? String(raw.id) : undefined);
  if (!id || !/^\d{6,}$/.test(id)) return null;
  const video = isObj(raw.video) ? raw.video : undefined;
  const tags = new Set<string>();
  for (const t of (Array.isArray(raw.textExtra) ? raw.textExtra : []) as unknown[]) {
    const h = str(get(t, 'hashtagName'));
    if (h) tags.add(h);
  }
  for (const c of (Array.isArray(raw.challenges) ? raw.challenges : []) as unknown[]) {
    const h = str(get(c, 'title'));
    if (h) tags.add(h);
  }
  return {
    site: 'tiktok',
    id,
    author: str(get(raw, 'author', 'uniqueId')) ?? str(raw.author),
    text: str(raw.desc),
    hashtags: tags.size ? [...tags] : undefined,
    soundTitle: str(get(raw, 'music', 'title')),
    videoUrl: str(video?.playAddr) ?? str(video?.downloadAddr),
    coverUrl: str(video?.cover) ?? str(video?.originCover),
    durationSec: num(video?.duration),
    isVideo: !!video || !raw.imagePost,
    isAd: raw.isAd === true || isObj(raw.adInfo) || undefined,
  };
}

/** Locate the item array(s) in a feed body. Returns [container, key] pairs so filter can rebuild them. */
function lists(body: unknown): { holder: Json; key: string; wrapped: boolean }[] {
  if (!isObj(body)) return [];
  const out: { holder: Json; key: string; wrapped: boolean }[] = [];
  for (const key of ['itemList', 'item_list', 'items']) {
    if (Array.isArray(body[key])) out.push({ holder: body, key, wrapped: false });
  }
  // search: data: [{ type, item: {...} }]
  if (Array.isArray(body.data) && (body.data as unknown[]).some((d) => isObj(get(d, 'item')))) {
    out.push({ holder: body, key: 'data', wrapped: true });
  }
  return out;
}

const rawOf = (entry: unknown, wrapped: boolean): unknown => (wrapped ? get(entry, 'item') : entry);

export const tiktokAdapter: SiteAdapter = {
  site: 'tiktok',

  claims(url) {
    return /(^|\.)tiktok\.com$/.test(url.hostname) && FEED_PATHS.some((re) => re.test(url.pathname));
  },

  extract(body) {
    const items: FeedItem[] = [];
    for (const { holder, key, wrapped } of lists(body)) {
      for (const e of holder[key] as unknown[]) {
        const it = tiktokItem(rawOf(e, wrapped));
        if (it) items.push(it);
      }
    }
    return items;
  },

  filter(body, blocked) {
    if (!blocked.size) return body;
    const copy = cloneJson(body);
    for (const { holder, key, wrapped } of lists(copy)) {
      const arr = holder[key] as unknown[];
      const kept = arr.filter((e) => {
        const it = tiktokItem(rawOf(e, wrapped));
        return !it || !blocked.has(it.id);
      });
      // Empty-page guard: an empty page can stall TikTok's pager. Keep the last
      // item; the DOM skip-jump layer passes over it.
      holder[key] = kept.length === 0 && arr.length > 0 ? [arr[arr.length - 1]] : kept;
    }
    return copy;
  },
};

/**
 * Items from the server-rendered first page (script#__UNIVERSAL_DATA_FOR_REHYDRATION__
 * or SIGI_STATE). Those are already in the app before we can filter, so they only feed
 * the judge + skip-jump path. Generic walk: any object that parses as a TikTok item.
 */
export function tiktokRehydrationItems(json: unknown, limit = 200): FeedItem[] {
  const seen = new Set<string>();
  const out: FeedItem[] = [];
  const stack: unknown[] = [json];
  let steps = 0;
  while (stack.length && out.length < limit && steps++ < 50_000) {
    const v = stack.pop();
    if (Array.isArray(v)) {
      for (const x of v) stack.push(x);
    } else if (isObj(v)) {
      if (isObj(v.video) && (isObj(v.author) || typeof v.author === 'string')) {
        const it = tiktokItem(v);
        if (it && !seen.has(it.id)) {
          seen.add(it.id);
          out.push(it);
          continue;
        }
      }
      for (const k in v) stack.push(v[k]);
    }
  }
  return out;
}
