import { compileRules, combine, wantsJudging, type CompiledRules } from '../sites/rules';
import { tiktokAdapter, tiktokRehydrationItems } from '../sites/tiktok';
import {
  DEFAULT_REMOVAL,
  FEED_CHANNEL,
  MAX_WAIT_MS,
  type FeedItem,
  type FeedVerdict,
  type Payload,
  type RemovalConfig,
  type SiteAdapter,
  type ToIsolated,
  type ToMain,
} from '../sites/types';
import { xAdapter } from '../sites/x';

/**
 * Page-world feed interceptor. Wraps fetch + XHR so feed responses are filtered
 * BEFORE the site's app parses them: blocked items never enter the feed.
 *
 *  - fetch: may wait up to `waitBudgetMs` for classifier verdicts, then drops blocked items.
 *  - XHR: filters synchronously with what is already known (rules + cached verdicts).
 *  - anything not claimed by an adapter, or any error: original response, untouched.
 */

export interface InterceptorEnv {
  win: Window & typeof globalThis;
  adapters?: SiteAdapter[];
  now?: () => number;
}

export interface Interceptor {
  verdicts: Map<string, FeedVerdict>;
  setConfig(c: RemovalConfig): void;
  /** Exposed for tests. */
  filterBody(adapter: SiteAdapter, body: unknown, wait: boolean): Promise<unknown>;
  filterBodySync(adapter: SiteAdapter, body: unknown): unknown;
}

const INSTALLED = Symbol.for('lnz.feed.interceptor');

export function installInterceptor(env: InterceptorEnv): Interceptor {
  const w = env.win as typeof env.win & { [INSTALLED]?: Interceptor };
  if (w[INSTALLED]) return w[INSTALLED]!;

  const adapters = env.adapters ?? [tiktokAdapter, xAdapter];
  const verdicts = new Map<string, FeedVerdict>();
  const waiters = new Set<() => void>();
  let config: RemovalConfig | null = null;
  let rules: CompiledRules = compileRules(DEFAULT_REMOVAL.rules);
  let configWaiters: (() => void)[] = [];
  const seen = new Set<string>();

  const up = (m: Payload<ToIsolated>) => w.postMessage({ ch: FEED_CHANNEL, dir: 'up', ...m } as ToIsolated, w.location.origin);

  const setConfig = (c: RemovalConfig) => {
    config = c;
    rules = compileRules(c.rules);
    const cw = configWaiters;
    configWaiters = [];
    cw.forEach((f) => f());
  };

  w.addEventListener('message', (e: MessageEvent) => {
    if (e.source !== w) return;
    const m = e.data as ToMain;
    if (!m || m.ch !== FEED_CHANNEL || m.dir !== 'down') return;
    if (m.type === 'ready' || m.type === 'config') {
      // Filters may have changed: forget old verdicts and let items be re-announced.
      if (m.type === 'config') {
        verdicts.clear();
        seen.clear();
      }
      setConfig(m.config);
    }
    if (m.type === 'verdicts') {
      for (const [id, v] of Object.entries(m.verdicts)) verdicts.set(id, v);
      if (verdicts.size > 5000) {
        // keep the map bounded: drop oldest insertions
        let n = verdicts.size - 4000;
        for (const k of verdicts.keys()) {
          if (n-- <= 0) break;
          verdicts.delete(k);
        }
      }
      waiters.forEach((f) => f());
    }
  });

  const active = (site: string) =>
    !!config && config.enabled && config.mode !== 'off' && config.sites[site as keyof RemovalConfig['sites']] !== false;

  const announce = (items: FeedItem[]) => {
    const fresh = items.filter((i) => !seen.has(`${i.site}:${i.id}`));
    fresh.forEach((i) => seen.add(`${i.site}:${i.id}`));
    if (seen.size > 20000) seen.clear();
    if (fresh.length) up({ type: 'items', items: fresh });
  };

  const blockedSet = (items: FeedItem[]): Set<string> => {
    const out = new Set<string>();
    for (const it of items) {
      const rule = rules.match(it);
      const v = combine(rule, wantsJudging(it, config?.rules ?? DEFAULT_REMOVAL.rules) ? verdicts.get(it.id) : 'keep');
      if (v === 'block') out.add(it.id);
    }
    return out;
  };

  const settledFor = (items: FeedItem[]) =>
    items.every((it) => rules.match(it) || !wantsJudging(it, config!.rules) || (verdicts.get(it.id) ?? 'unknown') !== 'unknown');

  const waitFor = (pred: () => boolean, ms: number) =>
    new Promise<void>((resolve) => {
      if (pred() || ms <= 0) return resolve();
      const done = () => {
        clearTimeout(t);
        waiters.delete(check);
        resolve();
      };
      const check = () => pred() && done();
      const t = setTimeout(done, ms);
      waiters.add(check);
    });

  const waitConfig = (ms: number) =>
    new Promise<void>((resolve) => {
      if (config) return resolve();
      const t = setTimeout(resolve, ms);
      configWaiters.push(() => {
        clearTimeout(t);
        resolve();
      });
    });

  const finish = (adapter: SiteAdapter, body: unknown, items: FeedItem[]) => {
    if (config?.mode !== 'drop-and-jump') return body;
    const blocked = blockedSet(items);
    if (!blocked.size) return body;
    up({ type: 'removed', site: adapter.site, ids: [...blocked] });
    return adapter.filter(body, blocked);
  };

  const filterBodySync = (adapter: SiteAdapter, body: unknown) => {
    const items = adapter.extract(body);
    if (!items.length) return body;
    announce(items);
    return active(adapter.site) ? finish(adapter, body, items) : body;
  };

  const filterBody = async (adapter: SiteAdapter, body: unknown, wait: boolean) => {
    const items = adapter.extract(body);
    if (!items.length) return body;
    announce(items);
    if (!config) await waitConfig(wait ? MAX_WAIT_MS : 0);
    if (!active(adapter.site)) return body;
    if (wait) await waitFor(() => settledFor(items), Math.min(config!.waitBudgetMs, MAX_WAIT_MS));
    return finish(adapter, body, items);
  };

  const claim = (raw: string | undefined): SiteAdapter | null => {
    if (!raw) return null;
    try {
      const u = new URL(raw, w.location.href);
      return adapters.find((a) => a.claims(u)) ?? null;
    } catch {
      return null;
    }
  };

  // ---- fetch ------------------------------------------------------------
  const origFetch = w.fetch;
  if (typeof origFetch === 'function') {
    const wrapped = async function (this: unknown, input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
      const res: Response = await origFetch.call(this ?? w, input, init);
      const adapter = claim(res.url || (typeof input === 'string' ? input : input instanceof URL ? input.href : (input as Request).url));
      if (!adapter || !res.ok) return res;
      const ct = res.headers.get('content-type') ?? '';
      if (ct && !ct.includes('json')) return res;
      // Read the claimed body once (no clone/tee) and always hand back a rebuilt Response.
      let text: string;
      try {
        text = await res.text();
      } catch {
        return res;
      }
      try {
        let outText = text;
        try {
          const body = JSON.parse(text);
          const out = await filterBody(adapter, body, true);
          if (out !== body) outText = JSON.stringify(out);
        } catch {
          /* not JSON or adapter error: pass the original bytes through */
        }
        const next = new Response(outText, { status: res.status, statusText: res.statusText, headers: res.headers });
        for (const k of ['url', 'redirected', 'type'] as const) {
          try {
            Object.defineProperty(next, k, { value: res[k] });
          } catch {
            /* ignore */
          }
        }
        return next;
      } catch {
        return new Response(text, { status: res.status, statusText: res.statusText, headers: res.headers });
      }
    };
    try {
      Object.defineProperty(wrapped, 'toString', { value: () => origFetch.toString() });
    } catch {
      /* ignore */
    }
    w.fetch = wrapped as typeof fetch;
  }

  // ---- XHR --------------------------------------------------------------
  const XHR = w.XMLHttpRequest;
  if (XHR?.prototype) {
    const proto = XHR.prototype;
    const origOpen = proto.open;
    const textDesc = Object.getOwnPropertyDescriptor(proto, 'responseText');
    const respDesc = Object.getOwnPropertyDescriptor(proto, 'response');
    type Tagged = XMLHttpRequest & { __lnzAdapter?: SiteAdapter | null; __lnzOut?: { text: string; obj: unknown } | null };

    proto.open = function (this: Tagged, method: string, url: string | URL, ...rest: unknown[]) {
      this.__lnzAdapter = claim(typeof url === 'string' ? url : url?.href);
      this.__lnzOut = undefined;
      return (origOpen as (...a: unknown[]) => void).call(this, method, url, ...rest);
    } as typeof proto.open;

    const compute = (x: Tagged): { text: string; obj: unknown } | null => {
      // Only a finished response can be filtered; partial reads pass through uncached.
      if (x.readyState !== 4) return null;
      if (x.__lnzOut !== undefined) return x.__lnzOut;
      x.__lnzOut = null;
      try {
        if (!x.__lnzAdapter || x.status < 200 || x.status >= 300) return null;
        const rt = x.responseType;
        let body: unknown;
        if (rt === '' || rt === 'text') body = JSON.parse(textDesc!.get!.call(x) as string);
        else if (rt === 'json') body = respDesc!.get!.call(x);
        else return null;
        const out = filterBodySync(x.__lnzAdapter, body);
        if (out === body) return null;
        x.__lnzOut = { text: JSON.stringify(out), obj: out };
      } catch {
        x.__lnzOut = null;
      }
      return x.__lnzOut;
    };

    if (textDesc?.get) {
      Object.defineProperty(proto, 'responseText', {
        configurable: true,
        get(this: Tagged) {
          const o = this.__lnzAdapter ? compute(this) : null;
          return o ? o.text : textDesc.get!.call(this);
        },
      });
    }
    if (respDesc?.get) {
      Object.defineProperty(proto, 'response', {
        configurable: true,
        get(this: Tagged) {
          const o = this.__lnzAdapter ? compute(this) : null;
          if (!o) return respDesc.get!.call(this);
          return this.responseType === 'json' ? o.obj : o.text;
        },
      });
    }
  }

  // ---- server-rendered first page (TikTok) --------------------------------
  const readRehydration = () => {
    if (!/(^|\.)tiktok\.com$/.test(w.location.hostname)) return;
    for (const id of ['__UNIVERSAL_DATA_FOR_REHYDRATION__', 'SIGI_STATE']) {
      const el = w.document.getElementById(id);
      if (!el?.textContent) continue;
      try {
        announce(tiktokRehydrationItems(JSON.parse(el.textContent)));
      } catch {
        /* ignore */
      }
    }
  };
  if (w.document.readyState === 'loading') w.document.addEventListener('DOMContentLoaded', readRehydration, { once: true });
  else readRehydration();

  const api: Interceptor = { verdicts, setConfig, filterBody, filterBodySync };
  Object.defineProperty(w, INSTALLED, { value: api });
  return api;
}
