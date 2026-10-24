import { hashString, type PlaybackController, type VideoNavigator, type VideoRef, type VideoSource } from '@lnz/shared';

/**
 * Default DOM integrations for TikTok web. These are deliberately thin so the
 * detection/navigation teammate can replace them with their own
 * VideoSource / VideoNavigator implementations without touching the UI.
 */

const VISIBLE_MIN = 0.4;

function visibleArea(el: Element): number {
  const r = el.getBoundingClientRect();
  const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
  const h = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
  const total = r.width * r.height;
  return total > 0 ? (w * h) / total : 0;
}

export function findActiveVideoElement(): HTMLVideoElement | null {
  let best: HTMLVideoElement | null = null;
  let bestScore = 0;
  for (const v of document.querySelectorAll('video')) {
    const vis = visibleArea(v);
    if (vis < VISIBLE_MIN) continue;
    const r = v.getBoundingClientRect();
    const score = vis * r.width * r.height * (v.paused ? 0.6 : 1);
    if (score > bestScore) {
      best = v;
      bestScore = score;
    }
  }
  return best;
}

function containerOf(v: HTMLVideoElement): Element {
  return (
    v.closest('article') ??
    v.closest('[data-e2e="recommend-list-item-container"]') ??
    v.closest('[class*="DivItemContainer"]') ??
    v.parentElement?.parentElement?.parentElement ??
    v
  );
}

function text(root: ParentNode, sel: string): string | undefined {
  const t = root.querySelector(sel)?.textContent?.trim();
  return t ? t.slice(0, 160) : undefined;
}

export function describeVideo(v: HTMLVideoElement): VideoRef {
  const c = containerOf(v);
  let videoId: string | undefined = location.pathname.match(/\/video\/(\d+)/)?.[1];
  if (!videoId) {
    for (let el: Element | null = v; el && el !== c.parentElement; el = el.parentElement) {
      const m = el.id?.match(/(\d{15,})/);
      if (m) {
        videoId = m[1];
        break;
      }
    }
  }
  if (!videoId) {
    const href = c.querySelector<HTMLAnchorElement>('a[href*="/video/"]')?.href;
    videoId = href?.match(/\/video\/(\d+)/)?.[1];
  }
  const title =
    text(c, '[data-e2e="video-desc"]') ?? text(c, '[data-e2e="browse-video-desc"]') ?? document.title.replace(/\s*\|\s*TikTok$/, '');
  const author = text(c, '[data-e2e="video-author-uniqueid"]') ?? text(c, '[data-e2e="browse-username"]');
  if (!videoId) videoId = `h${hashString(`${author ?? ''}|${title ?? ''}|${v.poster || v.currentSrc}`).toString(36)}`;
  return {
    videoId,
    url: location.href,
    title,
    author,
    durationSec: Number.isFinite(v.duration) ? Math.round(v.duration) : undefined,
  };
}

export class TikTokDomVideoSource implements VideoSource {
  private cur: VideoRef | null = null;
  private el: HTMLVideoElement | null = null;
  private listeners = new Set<(v: VideoRef | null) => void>();
  private timer: number | undefined;
  private count = 0;

  start(): void {
    const tick = () => this.poll();
    this.timer = window.setInterval(tick, 400);
    addEventListener('scroll', tick, { passive: true, capture: true });
    tick();
  }

  stop(): void {
    clearInterval(this.timer);
  }

  current(): VideoRef | null {
    return this.cur;
  }

  element(): HTMLVideoElement | null {
    return this.el && this.el.isConnected ? this.el : null;
  }

  onActiveVideoChange(cb: (v: VideoRef | null) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private poll(): void {
    const el = findActiveVideoElement();
    if (!el) {
      if (this.cur) this.emit(null, null);
      return;
    }
    const ref = describeVideo(el);
    if (ref.videoId !== this.cur?.videoId) {
      ref.index = ++this.count;
      this.emit(ref, el);
    } else {
      this.el = el;
    }
  }

  private emit(v: VideoRef | null, el: HTMLVideoElement | null): void {
    this.cur = v;
    this.el = el;
    for (const l of this.listeners) l(v);
  }
}

export class TikTokDomNavigator implements VideoNavigator {
  async skipToNext(): Promise<void> {
    const next =
      document.querySelector<HTMLButtonElement>('button[data-e2e="arrow-right"]') ??
      document.querySelector<HTMLButtonElement>('[data-e2e="feed-video-next"]');
    if (next && !next.disabled) {
      next.click();
      return;
    }
    const target = document.activeElement instanceof HTMLElement ? document.activeElement : document.body;
    for (const type of ['keydown', 'keyup'] as const) {
      target.dispatchEvent(new KeyboardEvent(type, { key: 'ArrowDown', code: 'ArrowDown', keyCode: 40, bubbles: true }));
    }
    // Fallback for feeds that ignore synthetic keys: scroll the nearest scrollable ancestor.
    await new Promise((r) => setTimeout(r, 350));
    const v = findActiveVideoElement();
    let el: HTMLElement | null = v?.parentElement ?? null;
    while (el && !(el.scrollHeight > el.clientHeight + 10 && /(auto|scroll)/.test(getComputedStyle(el).overflowY))) el = el.parentElement;
    (el ?? document.scrollingElement ?? document.documentElement).scrollBy({ top: innerHeight * 0.9, behavior: 'smooth' });
  }
}

/** Pauses the active video and keeps it paused (TikTok autoplays) until released. */
export class TikTokPlayback implements PlaybackController {
  private held: HTMLVideoElement | null = null;
  private wasPlaying = false;
  private readonly guard = (e: Event) => (e.target as HTMLVideoElement).pause();

  constructor(private readonly source: TikTokDomVideoSource) {}

  hold(): void {
    if (this.held) return;
    const v = this.source.element() ?? findActiveVideoElement();
    if (!v) return;
    this.held = v;
    this.wasPlaying = !v.paused;
    v.pause();
    v.addEventListener('play', this.guard);
  }

  release(): void {
    const v = this.held;
    if (!v) return;
    v.removeEventListener('play', this.guard);
    this.held = null;
    if (this.wasPlaying && v.isConnected) void v.play().catch(() => undefined);
  }
}
