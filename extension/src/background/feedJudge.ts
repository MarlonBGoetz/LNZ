import { decide, type ClassifierResult, type FilterId, type LnzConfig, type VideoRef } from '@lnz/shared';
import { readConfig } from '../lib/storage';
import {
  FEED_PORT,
  normalizeRemoval,
  type FeedItem,
  type FeedPortIn,
  type FeedPortOut,
  type FeedVerdict,
  type RemovalConfig,
} from '../sites/types';
import { buildProviders } from './providers';

/**
 * Background "judge ahead" for feed items. Classifies items as soon as the
 * interceptor sees them in the feed data (usually several videos before the user
 * reaches them), caches verdicts by site:id, and broadcasts them to every tab.
 *
 * Wire-up: call `registerFeedJudge()` once from background/index.ts.
 */

export { FEED_PORT };
export const REMOVAL_KEY = 'lnz:removal';

const FILTER_IDS: FilterId[] = ['calm', 'learn', 'shield'];
const CONCURRENCY = 3;
const PER_ITEM_TIMEOUT_MS = 10_000;
const CACHE_MAX = 4000;

/** Map a classifier decision to a feed verdict. Fail-open: unverified items are kept. */
export function verdictFor(cfg: LnzConfig, videoId: string, results: Partial<Record<FilterId, ClassifierResult>>): FeedVerdict {
  const d = decide(videoId, cfg.filters, results);
  if (d.verdict === 'skip') return 'block';
  if (d.verdict === 'pending') return 'unknown';
  return 'keep';
}

export async function readRemoval(): Promise<RemovalConfig> {
  const [r, cfg] = await Promise.all([chrome.storage.local.get(REMOVAL_KEY), readConfig()]);
  const rem = normalizeRemoval(r[REMOVAL_KEY]);
  // Master switch and auto-skip come from the PIN-protected main config.
  return { ...rem, enabled: rem.enabled && cfg.active, autoSkip: cfg.autoSkip };
}

export function toVideoRef(it: FeedItem): VideoRef & Omit<FeedItem, 'id'> {
  const url = it.site === 'tiktok' ? `https://www.tiktok.com/@${it.author ?? '_'}/video/${it.id}` : `https://x.com/${it.author ?? 'i'}/status/${it.id}`;
  return { ...it, videoId: it.id, url, title: it.text?.slice(0, 160) };
}

export function registerFeedJudge(): void {
  const ports = new Set<chrome.runtime.Port>();
  const cache = new Map<string, FeedVerdict>();
  const queue: FeedItem[] = [];
  const queued = new Set<string>();
  let running = 0;

  const broadcast = (verdicts: Record<string, FeedVerdict>) => {
    const msg: FeedPortOut = { type: 'verdicts', verdicts };
    for (const p of ports) {
      try {
        p.postMessage(msg);
      } catch {
        ports.delete(p);
      }
    }
  };

  const remember = (key: string, v: FeedVerdict) => {
    cache.delete(key);
    cache.set(key, v);
    if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value as string);
  };

  const judge = async (it: FeedItem) => {
    const cfg = await readConfig();
    if (!cfg.active) return;
    const providers = buildProviders(cfg);
    const ref = toVideoRef(it);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PER_ITEM_TIMEOUT_MS);
    const results: Partial<Record<FilterId, ClassifierResult>> = {};
    await Promise.all(
      FILTER_IDS.filter((id) => cfg.filters[id].enabled).map(async (filterId) => {
        const p = providers.find((x) => x.filterId === filterId);
        const base = { filterId, videoId: it.id, provider: p?.id ?? 'none', isDemo: p?.isDemo ?? false, receivedAt: Date.now() };
        if (!p) return void (results[filterId] = { ...base, state: 'unavailable' });
        try {
          const output = await p.classify(ref, ctrl.signal);
          results[filterId] = { ...base, state: 'ready', output };
        } catch (e) {
          results[filterId] = { ...base, state: e instanceof TypeError ? 'unavailable' : 'error' };
        }
      }),
    );
    clearTimeout(timer);
    const v = verdictFor(cfg, it.id, results);
    remember(`${it.site}:${it.id}`, v);
    broadcast({ [it.id]: v });
  };

  const pump = () => {
    while (running < CONCURRENCY && queue.length) {
      const it = queue.shift()!;
      running++;
      judge(it)
        .catch(() => undefined)
        .finally(() => {
          queued.delete(`${it.site}:${it.id}`);
          running--;
          pump();
        });
    }
  };

  const accept = (items: FeedItem[]) => {
    const hits: Record<string, FeedVerdict> = {};
    for (const it of items) {
      const key = `${it.site}:${it.id}`;
      const c = cache.get(key);
      if (c && c !== 'unknown') hits[it.id] = c;
      else if (!queued.has(key)) {
        queued.add(key);
        queue.push(it);
      }
    }
    if (Object.keys(hits).length) broadcast(hits);
    // Keep the queue bounded; the newest feed page matters most.
    while (queue.length > 120) queued.delete(`${queue[0].site}:${queue.shift()!.id}`);
    pump();
  };

  if (!chrome.runtime?.onConnect || !chrome.storage?.onChanged) return; // partial test doubles
  chrome.runtime.onConnect.addListener((port) => {
    if (port.name !== FEED_PORT || port.sender?.id !== chrome.runtime.id) return;
    ports.add(port);
    void readRemoval().then((config) => port.postMessage({ type: 'config', config } satisfies FeedPortOut));
    port.onMessage.addListener((m: FeedPortIn) => {
      if (m.type === 'items' && Array.isArray(m.items)) accept(m.items.slice(0, 200));
    });
    port.onDisconnect.addListener(() => ports.delete(port));
  });

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (!changes[REMOVAL_KEY] && !changes['lnz:config']) return;
    if (changes['lnz:config']) cache.clear(); // filters changed: old verdicts are stale
    void readRemoval().then((config) => {
      for (const p of ports) {
        try {
          p.postMessage({ type: 'config', config } satisfies FeedPortOut);
        } catch {
          ports.delete(p);
        }
      }
    });
  });
}
