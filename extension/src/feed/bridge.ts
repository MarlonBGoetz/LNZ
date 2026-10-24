import { DEFAULT_REMOVAL, FEED_CHANNEL, FEED_PORT, type FeedItem, type FeedPortIn, type FeedPortOut, type FeedVerdict, type RemovalConfig, type Payload, type ToIsolated, type ToMain } from '../sites/types';
import { createTikTokDom, createXDom, type FeedDom, type Registry } from './dom';

/**
 * Isolated-world bridge (document_start on tiktok.com / x.com):
 *   MAIN-world interceptor  <-postMessage->  bridge  <-port->  background judge
 * and owner of the DOM safety net.
 */

const site = /(^|\.)tiktok\.com$/.test(location.hostname) ? 'tiktok' : /(^|\.)(x|twitter)\.com$/.test(location.hostname) ? 'x' : null;

if (site) {
  const reg: Registry = { items: new Map<string, FeedItem>(), verdicts: new Map<string, FeedVerdict>() };
  let config: RemovalConfig = { ...DEFAULT_REMOVAL, enabled: false };
  let dom: FeedDom | null = null;
  let port: chrome.runtime.Port | null = null;
  let sentReady = false;

  const down = (m: Payload<ToMain>) => window.postMessage({ ch: FEED_CHANNEL, dir: 'down', ...m } as ToMain, location.origin);

  const send = (m: FeedPortIn) => {
    try {
      port?.postMessage(m);
    } catch {
      /* reconnecting */
    }
  };

  const ensureDom = () => {
    const on = config.enabled && config.mode !== 'off' && config.sites[site];
    if (on && !dom && document.documentElement) {
      dom = site === 'tiktok' ? createTikTokDom(document, reg, { autoSkip: () => config.autoSkip }) : createXDom(document, reg);
    } else if (!on && dom) {
      dom.stop();
      dom = null;
      for (const el of document.querySelectorAll('[data-lnz-blocked]')) el.removeAttribute('data-lnz-blocked');
    }
  };

  const connect = () => {
    port = chrome.runtime.connect({ name: FEED_PORT });
    port.onMessage.addListener((m: FeedPortOut) => {
      if (m.type === 'config') {
        config = m.config;
        reg.verdicts.clear();
        for (const el of document.querySelectorAll('[data-lnz-blocked]')) el.removeAttribute('data-lnz-blocked');
        down({ type: sentReady ? 'config' : 'ready', config });
        sentReady = true;
        ensureDom();
        // Re-judge everything already on the page under the new filters.
        if (reg.items.size) send({ type: 'items', items: [...reg.items.values()].slice(-200) });
      }
      if (m.type === 'verdicts') {
        for (const [id, v] of Object.entries(m.verdicts)) reg.verdicts.set(id, v);
        down({ type: 'verdicts', verdicts: m.verdicts });
        dom?.sync();
      }
    });
    port.onDisconnect.addListener(() => {
      port = null;
      setTimeout(connect, 800); // service worker restarted
    });
  };

  window.addEventListener('message', (e: MessageEvent) => {
    if (e.source !== window) return;
    const m = e.data as ToIsolated;
    if (!m || m.ch !== FEED_CHANNEL || m.dir !== 'up') return;
    if (m.type === 'items') {
      const items = m.items.filter((i) => i && i.site === site && typeof i.id === 'string').slice(0, 200);
      for (const it of items) reg.items.set(it.id, it);
      if (reg.items.size > 3000) {
        let n = reg.items.size - 2500;
        for (const k of reg.items.keys()) {
          if (n-- <= 0) break;
          reg.items.delete(k);
        }
      }
      send({ type: 'items', items });
    }
  });

  connect();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensureDom, { once: true });
}
