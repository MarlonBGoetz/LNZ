import { describe, expect, it } from 'vitest';
import { tiktokAdapter, tiktokRehydrationItems } from '../src/sites/tiktok';
import { xAdapter } from '../src/sites/x';
import { compileRules, DEFAULT_RULES } from '../src/sites/rules';
import { normalizeRemoval } from '../src/sites/types';

const tt = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  desc: `clip ${id} #fyp`,
  author: { uniqueId: `creator_${id.slice(-2)}` },
  music: { title: 'original sound' },
  textExtra: [{ hashtagName: 'fyp' }],
  video: { playAddr: `https://v.example/${id}.mp4`, cover: `https://c.example/${id}.jpg`, duration: 21 },
  ...extra,
});

const ttBody = () => ({
  statusCode: 0,
  hasMore: true,
  cursor: '42',
  itemList: [tt('7300000000000000001'), tt('7300000000000000002', { isAd: true }), tt('7300000000000000003')],
});

describe('tiktok adapter', () => {
  it('claims feed endpoints only', () => {
    expect(tiktokAdapter.claims(new URL('https://www.tiktok.com/api/recommend/item_list/?count=6'))).toBe(true);
    expect(tiktokAdapter.claims(new URL('https://www.tiktok.com/api/user/detail/'))).toBe(false);
    expect(tiktokAdapter.claims(new URL('https://evil.example/api/recommend/item_list/'))).toBe(false);
  });

  it('extracts items with fields', () => {
    const items = tiktokAdapter.extract(ttBody());
    expect(items.map((i) => i.id)).toEqual(['7300000000000000001', '7300000000000000002', '7300000000000000003']);
    expect(items[0]).toMatchObject({ site: 'tiktok', author: 'creator_01', hashtags: ['fyp'], durationSec: 21, isVideo: true });
    expect(items[1].isAd).toBe(true);
  });

  it('filters blocked ids without mutating input and keeps paging fields', () => {
    const body = ttBody();
    const before = JSON.stringify(body);
    const out = tiktokAdapter.filter(body, new Set(['7300000000000000002'])) as ReturnType<typeof ttBody>;
    expect(JSON.stringify(body)).toBe(before);
    expect(out.itemList.map((i) => i.id)).toEqual(['7300000000000000001', '7300000000000000003']);
    expect(out).toMatchObject({ hasMore: true, cursor: '42' });
  });

  it('never returns an empty page', () => {
    const out = tiktokAdapter.filter(ttBody(), new Set(['7300000000000000001', '7300000000000000002', '7300000000000000003'])) as ReturnType<typeof ttBody>;
    expect(out.itemList).toHaveLength(1);
  });

  it('reads search-shaped bodies and rehydration data', () => {
    const search = { data: [{ type: 1, item: tt('7300000000000000009') }, { type: 2, user: {} }] };
    expect(tiktokAdapter.extract(search).map((i) => i.id)).toEqual(['7300000000000000009']);
    const rehydrate = { __DEFAULT_SCOPE__: { 'webapp.video-detail': { itemInfo: { itemStruct: tt('7300000000000000010') } } } };
    expect(tiktokRehydrationItems(rehydrate).map((i) => i.id)).toEqual(['7300000000000000010']);
  });

  it('ignores junk shapes', () => {
    expect(tiktokAdapter.extract(null)).toEqual([]);
    expect(tiktokAdapter.extract({ itemList: [{ id: 'nope' }, 5, null] })).toEqual([]);
  });
});

const tweet = (id: string, video: boolean, extra: Record<string, unknown> = {}) => ({
  __typename: 'Tweet',
  rest_id: id,
  core: { user_results: { result: { legacy: { screen_name: `user${id.slice(-1)}` } } } },
  legacy: {
    full_text: `tweet ${id} #news`,
    entities: { hashtags: [{ text: 'news' }] },
    extended_entities: video
      ? { media: [{ type: 'video', media_url_https: 'https://p.example/t.jpg', video_info: { duration_millis: 9000, variants: [
          { content_type: 'application/x-mpegURL', url: 'https://v.example/x.m3u8' },
          { content_type: 'video/mp4', bitrate: 256000, url: 'https://v.example/low.mp4' },
          { content_type: 'video/mp4', bitrate: 2176000, url: 'https://v.example/high.mp4' },
        ] } }] }
      : undefined,
  },
  ...extra,
});

const entry = (id: string, video: boolean) => ({
  entryId: `tweet-${id}`,
  sortIndex: id,
  content: { entryType: 'TimelineTimelineItem', itemContent: { itemType: 'TimelineTweet', tweet_results: { result: tweet(id, video) } } },
});

const xBody = () => ({
  data: {
    home: {
      home_timeline_urt: {
        instructions: [
          {
            type: 'TimelineAddEntries',
            entries: [
              entry('1800000000000000001', true),
              { entryId: 'promoted-tweet-1800000000000000002', content: { itemContent: { tweet_results: { result: tweet('1800000000000000002', true) }, promotedMetadata: {} } } },
              entry('1800000000000000003', false),
              {
                entryId: 'home-conversation-1',
                content: {
                  entryType: 'TimelineTimelineModule',
                  items: [
                    { entryId: 'c-1', item: { itemContent: { tweet_results: { result: { __typename: 'TweetWithVisibilityResults', tweet: tweet('1800000000000000004', true) } } } } },
                    { entryId: 'c-2', item: { itemContent: { tweet_results: { result: tweet('1800000000000000005', false) } } } },
                  ],
                },
              },
              { entryId: 'cursor-top-1', content: { entryType: 'TimelineTimelineCursor', value: 'a' } },
              { entryId: 'cursor-bottom-1', content: { entryType: 'TimelineTimelineCursor', value: 'b' } },
            ],
          },
        ],
      },
    },
  },
});

describe('x adapter', () => {
  it('claims timeline operations only', () => {
    expect(xAdapter.claims(new URL('https://x.com/i/api/graphql/abc123/HomeTimeline?variables=1'))).toBe(true);
    expect(xAdapter.claims(new URL('https://x.com/i/api/graphql/abc123/UserByScreenName'))).toBe(false);
  });

  it('extracts tweets incl. modules, wrappers and ads; picks best mp4', () => {
    const items = xAdapter.extract(xBody());
    expect(items.map((i) => i.id)).toEqual(['1800000000000000001', '1800000000000000002', '1800000000000000003', '1800000000000000004', '1800000000000000005']);
    expect(items[0]).toMatchObject({ isVideo: true, videoUrl: 'https://v.example/high.mp4', durationSec: 9, author: 'user1' });
    expect(items[1].isAd).toBe(true);
    expect(items[2].isVideo).toBe(false);
  });

  it('removes blocked entries and module items, keeps cursors, does not mutate', () => {
    const body = xBody();
    const before = JSON.stringify(body);
    const out = xAdapter.filter(body, new Set(['1800000000000000001', '1800000000000000004', '1800000000000000005'])) as ReturnType<typeof xBody>;
    expect(JSON.stringify(body)).toBe(before);
    const ids = out.data.home.home_timeline_urt.instructions[0].entries.map((e) => e.entryId);
    expect(ids).toEqual(['promoted-tweet-1800000000000000002', 'tweet-1800000000000000003', 'cursor-top-1', 'cursor-bottom-1']);
  });
});

describe('rules', () => {
  const rules = compileRules({ ...DEFAULT_RULES, keywords: ['street fight'], hashtags: ['#gore'], creators: ['@BadActor'], blockAds: true });
  const base = { site: 'tiktok' as const, id: '1', isVideo: true };
  it('matches keywords on word boundaries, hashtags, creators and ads', () => {
    expect(rules.match({ ...base, text: 'Insane STREET FIGHT caught' })).toMatch(/Keyword/);
    expect(rules.match({ ...base, text: 'streetfighter combo' })).toBeNull();
    expect(rules.match({ ...base, hashtags: ['Gore'] })).toBe('#Gore');
    expect(rules.match({ ...base, author: 'badactor' })).toMatch(/Creator/);
    expect(rules.match({ ...base, isAd: true })).toBe('Promoted');
    expect(rules.match({ ...base, text: 'cooking pasta' })).toBeNull();
  });
  it('normalizes removal config and caps the wait budget', () => {
    const c = normalizeRemoval({ waitBudgetMs: 9999, rules: { keywords: ['a', 3] } });
    expect(c.waitBudgetMs).toBe(400);
    expect(c.rules.keywords).toEqual(['a']);
    expect(c.mode).toBe('drop-and-jump');
  });
});
