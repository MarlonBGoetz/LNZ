import { cloneJson, get, isObj, num, str, type FeedItem, type Json, type SiteAdapter } from './types';

/**
 * X (x.com / twitter.com) GraphQL timeline adapter.
 * Timelines arrive as `data.<…>.instructions[]`. Tweets live in entries
 * (TimelineTimelineItem) or inside modules (TimelineTimelineModule, e.g. conversations).
 * Cursor entries are never removed.
 */

const OPS = /\/i\/api\/graphql\/[^/]+\/(HomeTimeline|HomeLatestTimeline|UserTweets|UserTweetsAndReplies|UserMedia|SearchTimeline|ListLatestTweetsTimeline|TweetDetail|CommunityTweetsTimeline|Bookmarks|Likes)$/;

/** Unwrap TweetWithVisibilityResults and similar wrappers. */
function tweetResult(r: unknown): Json | undefined {
  if (!isObj(r)) return undefined;
  if (r.__typename === 'TweetWithVisibilityResults' && isObj(r.tweet)) return r.tweet;
  if (isObj(r.tweet) && !r.rest_id) return r.tweet;
  return r;
}

export function xTweet(result: unknown, promoted = false): FeedItem | null {
  const t = tweetResult(result);
  if (!t) return null;
  const id = str(t.rest_id);
  if (!id || !/^\d{5,}$/.test(id)) return null;
  const legacy = isObj(t.legacy) ? t.legacy : {};
  const user = get(t, 'core', 'user_results', 'result');
  const media = (get(legacy, 'extended_entities', 'media') ?? get(legacy, 'entities', 'media') ?? []) as unknown[];
  let videoUrl: string | undefined;
  let durationSec: number | undefined;
  let coverUrl: string | undefined;
  let isVideo = false;
  for (const m of Array.isArray(media) ? media : []) {
    const type = str(get(m, 'type'));
    if (type !== 'video' && type !== 'animated_gif') continue;
    isVideo = true;
    coverUrl ??= str(get(m, 'media_url_https'));
    const ms = num(get(m, 'video_info', 'duration_millis'));
    if (ms != null) durationSec = Math.round(ms / 1000);
    const variants = (get(m, 'video_info', 'variants') ?? []) as unknown[];
    let best = -1;
    for (const v of Array.isArray(variants) ? variants : []) {
      if (get(v, 'content_type') !== 'video/mp4') continue;
      const br = num(get(v, 'bitrate')) ?? 0;
      if (br > best) {
        best = br;
        videoUrl = str(get(v, 'url'));
      }
    }
  }
  const hashtags = ((get(legacy, 'entities', 'hashtags') ?? []) as unknown[])
    .map((h) => str(get(h, 'text')))
    .filter((h): h is string => !!h);
  return {
    site: 'x',
    id,
    author: str(get(user, 'core', 'screen_name')) ?? str(get(user, 'legacy', 'screen_name')),
    text: str(get(t, 'note_tweet', 'note_tweet_results', 'result', 'text')) ?? str(legacy.full_text),
    hashtags: hashtags.length ? hashtags : undefined,
    videoUrl,
    coverUrl,
    durationSec,
    isVideo,
    isAd: promoted || isObj(t.promotedMetadata) || undefined,
  };
}

/** Every `instructions` array in the body (path differs per operation). */
function instructionLists(body: unknown): unknown[][] {
  const out: unknown[][] = [];
  const stack: unknown[] = [body];
  let steps = 0;
  while (stack.length && steps++ < 5000) {
    const v = stack.pop();
    if (!isObj(v)) continue;
    for (const k in v) {
      const c = v[k];
      if (k === 'instructions' && Array.isArray(c)) out.push(c);
      else if (isObj(c)) stack.push(c);
    }
  }
  return out;
}

const isCursor = (entry: unknown) => {
  const id = str(get(entry, 'entryId')) ?? '';
  return id.startsWith('cursor-') || get(entry, 'content', 'entryType') === 'TimelineTimelineCursor' || get(entry, 'content', '__typename') === 'TimelineTimelineCursor';
};
const isPromotedEntry = (entry: unknown) => (str(get(entry, 'entryId')) ?? '').startsWith('promoted');

/** Tweet held directly by an entry or module item (`itemContent`). */
const tweetOfItemContent = (ic: unknown, promoted: boolean) => xTweet(get(ic, 'tweet_results', 'result'), promoted || isObj(get(ic, 'promotedMetadata')));

function entryTweet(entry: unknown): FeedItem | null {
  return tweetOfItemContent(get(entry, 'content', 'itemContent'), isPromotedEntry(entry));
}

function moduleItems(entry: unknown): unknown[] | undefined {
  const items = get(entry, 'content', 'items');
  return Array.isArray(items) ? items : undefined;
}

export const xAdapter: SiteAdapter = {
  site: 'x',

  claims(url) {
    return /(^|\.)(x|twitter)\.com$/.test(url.hostname) && OPS.test(url.pathname);
  },

  extract(body) {
    const items: FeedItem[] = [];
    const add = (it: FeedItem | null) => it && items.push(it);
    for (const list of instructionLists(body)) {
      for (const ins of list) {
        const entries = (get(ins, 'entries') ?? (get(ins, 'entry') ? [get(ins, 'entry')] : [])) as unknown[];
        for (const e of Array.isArray(entries) ? entries : []) {
          if (isCursor(e)) continue;
          add(entryTweet(e));
          for (const mi of moduleItems(e) ?? []) add(tweetOfItemContent(get(mi, 'item', 'itemContent'), false));
        }
        const mItems = get(ins, 'moduleItems');
        for (const mi of Array.isArray(mItems) ? mItems : []) add(tweetOfItemContent(get(mi, 'item', 'itemContent'), false));
      }
    }
    return items;
  },

  filter(body, blocked) {
    if (!blocked.size) return body;
    const copy = cloneJson(body);
    const blockedTweet = (ic: unknown) => {
      const t = tweetOfItemContent(ic, false);
      return !!t && blocked.has(t.id);
    };
    for (const list of instructionLists(copy)) {
      for (const ins of list) {
        if (!isObj(ins)) continue;
        if (Array.isArray(ins.entries)) {
          ins.entries = (ins.entries as unknown[]).filter((e) => {
            if (isCursor(e)) return true;
            if (blockedTweet(get(e, 'content', 'itemContent'))) return false;
            const mods = moduleItems(e);
            if (mods) {
              const kept = mods.filter((mi) => !blockedTweet(get(mi, 'item', 'itemContent')));
              (get(e, 'content') as Json).items = kept;
              return kept.length > 0;
            }
            return true;
          });
        }
        if (Array.isArray(ins.moduleItems)) {
          ins.moduleItems = (ins.moduleItems as unknown[]).filter((mi) => !blockedTweet(get(mi, 'item', 'itemContent')));
        }
        // Single-entry instructions (TimelinePinEntry / TimelineReplaceEntry) are left
        // alone: rewriting them can break the client. The DOM layer hides those.
      }
    }
    return copy;
  },
};
