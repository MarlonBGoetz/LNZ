import type { FeedItem, FeedVerdict } from '../sites/types';

/**
 * DOM layer: the safety net for anything the feed-data filter could not drop
 * (server-rendered first page, XHR items with late verdicts, verdicts that land
 * after the page was fetched). Blocked items are silenced the moment they mount
 * and the user's swipe carries them straight past.
 */

export const BLOCK_ATTR = 'data-lnz-blocked';

const STYLE = `
[${BLOCK_ATTR}] video { visibility: hidden !important; }
[${BLOCK_ATTR}][data-lnz-site="tiktok"] > * { visibility: hidden !important; }
[${BLOCK_ATTR}][data-lnz-site="x"] { display: none !important; }
`;

export function injectStyle(doc: Document): void {
  if (doc.getElementById('lnz-feed-style')) return;
  const s = doc.createElement('style');
  s.id = 'lnz-feed-style';
  s.textContent = STYLE;
  (doc.head ?? doc.documentElement).appendChild(s);
}

/** Pause + mute every video under `root`. */
export function silence(root: ParentNode): void {
  for (const v of root.querySelectorAll('video')) {
    v.muted = true;
    if (!v.paused) v.pause();
    v.preload = 'none';
  }
}

export interface Registry {
  items: Map<string, FeedItem>;
  verdicts: Map<string, FeedVerdict>;
}

export interface FeedDom {
  /** Re-scan the page and apply verdicts. Cheap; called on mutations and verdict updates. */
  sync(): void;
  stop(): void;
  stats(): { removedInDom: number; jumps: number };
}

const norm = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim().toLowerCase();

// ----------------------------------------------------------------------------
// TikTok: full-screen snap feed. Blocked items keep their box (so the pager's
// index math stays intact) but render nothing and never play; any arrival on one
// is converted into a jump to the next allowed item in the direction of travel.
// ----------------------------------------------------------------------------

const TT_CONTAINER = '[data-e2e="recommend-list-item-container"], article[data-e2e], div[data-e2e="feed-video"]';

export function tiktokIdOf(el: Element, reg: Registry): string | undefined {
  const cached = (el as HTMLElement).dataset?.lnzId;
  if (cached) return cached;
  let id: string | undefined;
  for (const n of el.querySelectorAll('[id]')) {
    const m = n.id.match(/(\d{15,})/);
    if (m) {
      id = m[1];
      break;
    }
  }
  if (!id) id = el.querySelector<HTMLAnchorElement>('a[href*="/video/"]')?.getAttribute('href')?.match(/\/video\/(\d+)/)?.[1];
  if (!id) {
    // Fall back to author + caption match against items seen in the feed data.
    const author = norm(el.querySelector('[data-e2e="video-author-uniqueid"], [data-e2e="feed-video-nickname"]')?.textContent);
    const desc = norm(el.querySelector('[data-e2e="video-desc"]')?.textContent);
    if (author || desc) {
      for (const it of reg.items.values()) {
        if (it.site !== 'tiktok') continue;
        if (author && norm(it.author) !== author) continue;
        if (desc && it.text && !desc.startsWith(norm(it.text).slice(0, 40))) continue;
        id = it.id;
        break;
      }
    }
  }
  if (id) (el as HTMLElement).dataset.lnzId = id;
  return id;
}

export function createTikTokDom(doc: Document, reg: Registry, opts: { autoSkip: () => boolean }): FeedDom {
  const win = doc.defaultView!;
  let removedInDom = 0;
  let jumps = 0;
  let lastActive: Element | null = null;
  let lastIndex = -1;
  let jumping = false;

  const containers = () => [...doc.querySelectorAll(TT_CONTAINER)].filter((c) => c.querySelector('video, img, [id^="xgwrapper"]'));
  const blocked = (c: Element) => c.hasAttribute(BLOCK_ATTR);

  const visibleRatio = (el: Element) => {
    const r = el.getBoundingClientRect();
    if (!r.height) return 0;
    const h = Math.max(0, Math.min(r.bottom, win.innerHeight) - Math.max(r.top, 0));
    return h / Math.min(r.height, win.innerHeight);
  };

  const activeOf = (list: Element[]) => {
    let best: Element | null = null;
    let score = 0.55;
    for (const c of list) {
      const v = visibleRatio(c);
      if (v > score) {
        best = c;
        score = v;
      }
    }
    return best;
  };

  const jumpTo = (target: Element) => {
    jumping = true;
    jumps++;
    target.scrollIntoView({ block: 'start', behavior: 'instant' as ScrollBehavior });
    win.setTimeout(() => (jumping = false), 120);
  };

  /** Next allowed container from index i, going dir (+1/-1). */
  const nextAllowed = (list: Element[], i: number, dir: 1 | -1) => {
    for (let j = i + dir; j >= 0 && j < list.length; j += dir) if (!blocked(list[j])) return list[j];
    return null;
  };

  const apply = (list: Element[]) => {
    for (const c of list) {
      const id = tiktokIdOf(c, reg);
      if (!id) continue;
      const isBlocked = reg.verdicts.get(id) === 'block';
      if (isBlocked && !blocked(c)) {
        c.setAttribute(BLOCK_ATTR, '');
        (c as HTMLElement).dataset.lnzSite = 'tiktok';
        removedInDom++;
      }
      if (isBlocked) silence(c);
    }
  };

  const settle = () => {
    const list = containers();
    apply(list);
    const active = activeOf(list);
    if (!active) return;
    const idx = list.indexOf(active);
    const moved = active !== lastActive;
    const dir: 1 | -1 = lastIndex >= 0 && idx < lastIndex ? -1 : 1;
    if (blocked(active) && !jumping && (moved || opts.autoSkip())) {
      const target = nextAllowed(list, idx, dir) ?? nextAllowed(list, idx, dir === 1 ? -1 : 1);
      if (target) jumpTo(target);
      else silence(active); // end of loaded feed; TikTok will load more and the next settle moves on
    }
    lastActive = active;
    lastIndex = idx;
  };

  // A blocked video must never play, not even for a frame of audio.
  const onPlay = (e: Event) => {
    const v = e.target as HTMLVideoElement;
    if (v?.closest?.(`[${BLOCK_ATTR}]`)) {
      v.muted = true;
      v.pause();
    }
  };

  // Turn the user's own next/prev key into a single jump over blocked items.
  const onKey = (e: KeyboardEvent) => {
    if (!e.isTrusted || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
    const t = e.target as HTMLElement | null;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    const list = containers();
    const active = activeOf(list);
    if (!active) return;
    const dir: 1 | -1 = e.key === 'ArrowDown' ? 1 : -1;
    const idx = list.indexOf(active);
    const neighbour = list[idx + dir];
    if (!neighbour || !blocked(neighbour)) return; // normal move, let TikTok handle it
    const target = nextAllowed(list, idx, dir);
    if (!target) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    jumpTo(target);
  };

  let raf = 0;
  const schedule = () => {
    if (raf) return;
    raf = win.requestAnimationFrame(() => {
      raf = 0;
      settle();
    });
  };

  injectStyle(doc);
  doc.addEventListener('play', onPlay, true);
  win.addEventListener('keydown', onKey, true);
  win.addEventListener('scroll', schedule, { capture: true, passive: true });
  win.addEventListener('scrollend', schedule, { capture: true, passive: true });
  const mo = new MutationObserver(schedule);
  mo.observe(doc.documentElement, { childList: true, subtree: true });
  const iv = win.setInterval(schedule, 400);

  return {
    sync: schedule,
    stop() {
      mo.disconnect();
      win.clearInterval(iv);
      doc.removeEventListener('play', onPlay, true);
      win.removeEventListener('keydown', onKey, true);
      win.removeEventListener('scroll', schedule, true);
      win.removeEventListener('scrollend', schedule, true);
    },
    stats: () => ({ removedInDom, jumps }),
  };
}

// ----------------------------------------------------------------------------
// X: virtualised list of cells. Blocked cells below the viewport are removed from
// layout (no scroll jump, the user never sees them). A blocked cell already on
// screen is silenced and removed once it is off-screen below, never above.
// ----------------------------------------------------------------------------

export function xIdOf(cell: Element): string | undefined {
  const cached = (cell as HTMLElement).dataset?.lnzId;
  if (cached) return cached;
  const a = cell.querySelector('article a[href*="/status/"] time')?.closest('a') ?? cell.querySelector('article a[href*="/status/"]');
  const id = a?.getAttribute('href')?.match(/\/status\/(\d+)/)?.[1];
  if (id) (cell as HTMLElement).dataset.lnzId = id;
  return id;
}

export function createXDom(doc: Document, reg: Registry): FeedDom {
  const win = doc.defaultView!;
  let removedInDom = 0;

  const apply = () => {
    for (const cell of doc.querySelectorAll('[data-testid="cellInnerDiv"]')) {
      if (cell.hasAttribute(BLOCK_ATTR)) continue;
      const id = xIdOf(cell);
      if (!id || reg.verdicts.get(id) !== 'block') continue;
      silence(cell);
      const r = cell.getBoundingClientRect();
      // Only drop from layout while fully below the viewport: no scroll jump, never seen.
      if (r.top >= win.innerHeight) {
        cell.setAttribute(BLOCK_ATTR, '');
        (cell as HTMLElement).dataset.lnzSite = 'x';
        removedInDom++;
      }
    }
  };

  const onPlay = (e: Event) => {
    const v = e.target as HTMLVideoElement;
    const cell = v?.closest?.('[data-testid="cellInnerDiv"]');
    const id = cell && xIdOf(cell);
    if (id && reg.verdicts.get(id) === 'block') {
      v.muted = true;
      v.pause();
    }
  };

  let raf = 0;
  const schedule = () => {
    if (raf) return;
    raf = win.requestAnimationFrame(() => {
      raf = 0;
      apply();
    });
  };

  injectStyle(doc);
  doc.addEventListener('play', onPlay, true);
  win.addEventListener('scroll', schedule, { capture: true, passive: true });
  const mo = new MutationObserver(schedule);
  mo.observe(doc.documentElement, { childList: true, subtree: true });

  return {
    sync: schedule,
    stop() {
      mo.disconnect();
      doc.removeEventListener('play', onPlay, true);
      win.removeEventListener('scroll', schedule, true);
    },
    stats: () => ({ removedInDom, jumps: 0 }),
  };
}
