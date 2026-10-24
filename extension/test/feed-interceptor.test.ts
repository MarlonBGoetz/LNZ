import { describe, expect, it, vi } from 'vitest';
import { installInterceptor } from '../src/feed/interceptor';
import { DEFAULT_REMOVAL, FEED_CHANNEL } from '../src/sites/types';

/** Minimal window double: same-window postMessage, fetch, location, document. */
function fakeWindow(respond: (url: string) => Response) {
  const listeners: ((e: MessageEvent) => void)[] = [];
  const posted: unknown[] = [];
  const w = {
    location: { href: 'https://www.tiktok.com/foryou', origin: 'https://www.tiktok.com', hostname: 'www.tiktok.com' },
    document: { readyState: 'complete', getElementById: () => null, addEventListener: () => undefined },
    fetch: vi.fn(async (input: string) => {
      const r = respond(input);
      Object.defineProperty(r, 'url', { value: input });
      return r;
    }),
    addEventListener: (t: string, f: (e: MessageEvent) => void) => t === 'message' && listeners.push(f),
    postMessage(data: unknown) {
      posted.push(data);
      queueMicrotask(() => listeners.forEach((f) => f({ source: w, data } as unknown as MessageEvent)));
    },
  };
  return { w: w as unknown as Window & typeof globalThis, posted, down: (m: object) => w.postMessage({ ch: FEED_CHANNEL, dir: 'down', ...m }) };
}

const feed = (ids: string[]) =>
  new Response(JSON.stringify({ hasMore: true, itemList: ids.map((id) => ({ id, desc: `v ${id}`, author: { uniqueId: 'a' }, video: { playAddr: 'x' } })) }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });

const FEED_URL = 'https://www.tiktok.com/api/recommend/item_list/?count=3';
const ids = ['7300000000000000001', '7300000000000000002', '7300000000000000003'];

describe('feed interceptor (fetch)', () => {
  it('drops items with a block verdict that arrives within the wait budget', async () => {
    const { w, posted, down } = fakeWindow(() => feed(ids));
    installInterceptor({ win: w });
    down({ type: 'ready', config: { ...DEFAULT_REMOVAL, waitBudgetMs: 200 } });
    await Promise.resolve();
    const p = w.fetch(FEED_URL);
    setTimeout(() => down({ type: 'verdicts', verdicts: { [ids[0]]: 'keep', [ids[1]]: 'block', [ids[2]]: 'keep' } }), 20);
    const res = await p;
    const body = await res.json();
    expect(body.itemList.map((i: { id: string }) => i.id)).toEqual([ids[0], ids[2]]);
    expect(res.status).toBe(200);
    expect(res.url).toBe(FEED_URL);
    expect(posted.some((m) => (m as { type?: string }).type === 'items')).toBe(true);
    expect(posted.some((m) => (m as { type?: string }).type === 'removed')).toBe(true);
  });

  it('applies keyword rules instantly, with no verdicts at all', async () => {
    const { w, down } = fakeWindow(() => feed(ids));
    installInterceptor({ win: w });
    down({ type: 'ready', config: { ...DEFAULT_REMOVAL, waitBudgetMs: 0, rules: { ...DEFAULT_REMOVAL.rules, keywords: [`v ${ids[2]}`] } } });
    await Promise.resolve();
    const body = await (await w.fetch(FEED_URL)).json();
    expect(body.itemList.map((i: { id: string }) => i.id)).toEqual([ids[0], ids[1]]);
  });

  it('passes through when the budget expires with unknown verdicts', async () => {
    const { w, down } = fakeWindow(() => feed(ids));
    installInterceptor({ win: w });
    down({ type: 'ready', config: { ...DEFAULT_REMOVAL, waitBudgetMs: 30 } });
    await Promise.resolve();
    const t0 = Date.now();
    const body = await (await w.fetch(FEED_URL)).json();
    expect(body.itemList).toHaveLength(3);
    expect(Date.now() - t0).toBeLessThan(300);
  });

  it('does not touch unclaimed or non-JSON responses, nor when removal is off', async () => {
    const { w, down } = fakeWindow((u) => (u.includes('item_list') ? feed(ids) : new Response('<html>', { headers: { 'content-type': 'text/html' } })));
    installInterceptor({ win: w });
    down({ type: 'ready', config: { ...DEFAULT_REMOVAL, mode: 'off' } });
    await Promise.resolve();
    expect(await (await w.fetch('https://www.tiktok.com/')).text()).toBe('<html>');
    down({ type: 'verdicts', verdicts: { [ids[0]]: 'block' } });
    await Promise.resolve();
    expect((await (await w.fetch(FEED_URL)).json()).itemList).toHaveLength(3);
  });

  it('survives malformed JSON and is installed only once', async () => {
    const { w, down } = fakeWindow(() => new Response('{not json', { headers: { 'content-type': 'application/json' } }));
    const a = installInterceptor({ win: w });
    const b = installInterceptor({ win: w });
    expect(a).toBe(b);
    down({ type: 'ready', config: DEFAULT_REMOVAL });
    await Promise.resolve();
    expect(await (await w.fetch(FEED_URL)).text()).toBe('{not json');
  });
});
