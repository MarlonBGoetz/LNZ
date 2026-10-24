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
    v.closest('[role="dialog"]') ??
    v.closest('[data-e2e="recommend-list-item-container"]') ??
    v.closest('[class*="DivItemContainer"]') ??
    v.parentElement?.parentElement?.parentElement ??
    v
  );
}

function text(root: ParentNode, sel: string): string | undefined {
  if (typeof root.querySelector !== 'function') return undefined;
  const t = root.querySelector(sel)?.textContent?.trim();
  return t ? t.slice(0, 160) : undefined;
}

/** Site chrome, not a video caption. */
function genericPageTitle(title: string): boolean {
  const s = title.replace(/\s*\|\s*TikTok$/, '').trim();
  return !s || /^(TikTok|Log in|Sign up|Watch|For You)\b/i.test(s);
}

/** X post inside a timeline article or a video modal. */
function describeXVideo(v: HTMLVideoElement, c: Element): VideoRef {
  let videoId = location.pathname.match(/\/status\/(\d+)/)?.[1];
  if (!videoId) {
    const href = c.querySelector<HTMLAnchorElement>('a[href*="/status/"]')?.href;
    videoId = href?.match(/\/status\/(\d+)/)?.[1];
  }
  const user = text(c, '[data-testid="User-Name"]');
  const author = user?.match(/@([A-Za-z0-9_]+)/)?.[1];
  const title = text(c, '[data-testid="tweetText"]');
  if (!videoId) videoId = `h${hashString(`${author ?? ''}|${title ?? ''}|${v.poster || v.currentSrc}`).toString(36)}`;
  return {
    videoId,
    url: location.href,
    title,
    author,
    durationSec: Number.isFinite(v.duration) ? Math.round(v.duration) : undefined,
    platform: 'x',
  };
}

export function describeVideo(v: HTMLVideoElement, platform: 'tiktok' | 'x' = 'tiktok'): VideoRef {
  const c = containerOf(v);
  if (platform === 'x') return describeXVideo(v, c);
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
  // The caption can live outside the <article> (login wall, browse pages, modal
  // layouts). Check the video's container first, then the document, and never
  // fall back to TikTok's generic page title ("TikTok - Make Your Day").
  const title =
    text(c, '[data-e2e="video-desc"]') ??
    text(c, '[data-e2e="browse-video-desc"]') ??
    text(document, '[data-e2e="browse-video-desc"]') ??
    text(document, '[data-e2e="video-desc"]') ??
    (genericPageTitle(document.title) ? undefined : document.title.replace(/\s*\|\s*TikTok$/, '').trim());
  const author =
    text(c, '[data-e2e="video-author-uniqueid"]') ??
    text(c, '[data-e2e="browse-username"]') ??
    text(document, '[data-e2e="browse-username"]');
  if (!videoId) videoId = `h${hashString(`${author ?? ''}|${title ?? ''}|${v.poster || v.currentSrc}`).toString(36)}`;
  return {
    videoId,
    url: location.href,
    title,
    author,
    durationSec: Number.isFinite(v.duration) ? Math.round(v.duration) : undefined,
    platform: 'tiktok',
  };
}

export class TikTokDomVideoSource implements VideoSource {
  private cur: VideoRef | null = null;
  private el: HTMLVideoElement | null = null;
  private listeners = new Set<(v: VideoRef | null) => void>();
  private timer: number | undefined;
  private count = 0;
  private running = false;
  private readonly tick = () => {
    if (this.running) this.poll();
  };

  constructor(private readonly platform: 'tiktok' | 'x' = 'tiktok') {}

  start(): void {
    if (this.running) return;
    this.running = true;
    this.timer = window.setInterval(this.tick, 400);
    addEventListener('scroll', this.tick, { passive: true, capture: true });
    this.tick();
  }

  stop(): void {
    if (!this.running) return;
    this.running = false;
    clearInterval(this.timer);
    this.timer = undefined;
    removeEventListener('scroll', this.tick, true);
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
    const ref = describeVideo(el, this.platform);
    if (ref.videoId !== this.cur?.videoId) {
      ref.index = ++this.count;
      this.emit(ref, el);
    } else if (el !== this.el) {
      // TikTok can replace a video element without changing its logical ID.
      // Notify playback owners so their pause guard follows the new element.
      ref.index = this.cur?.index;
      this.emit(ref, el);
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

/**
 * X has no TikTok-style next button. A rejected post advances to the next
 * timeline article that actually contains a video; if the active video is open
 * in X's modal player, close it first and continue from the post it belonged to.
 */
export class XDomNavigator implements VideoNavigator {
  constructor(private readonly source: TikTokDomVideoSource) {}

  async skipToNext(): Promise<void> {
    const current = this.source.element() ?? findActiveVideoElement();
    const dialog = current?.closest('[role="dialog"]');
    if (dialog) {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }));
      await new Promise((r) => setTimeout(r, 250));
    }

    const articles = [...document.querySelectorAll('article')].filter((a) => a.querySelector('video'));
    const status = location.pathname.match(/\/status\/(\d+)/)?.[1];
    const currentArticle =
      current?.closest('article') ??
      (status ? articles.find((a) => a.querySelector(`a[href*="/status/${status}"]`)) : undefined);
    const index = currentArticle ? articles.indexOf(currentArticle) : -1;
    const next = index >= 0 ? articles[index + 1] : null;

    if (next) next.scrollIntoView({ behavior: 'smooth', block: 'center' });
    else window.scrollBy({ top: innerHeight * 0.85, behavior: 'smooth' });
  }
}

/** Pauses the active video and keeps it paused (TikTok autoplays) until released. */
export class TikTokPlayback implements PlaybackController {
  private held: HTMLVideoElement | null = null;
  private wasPlaying = false;
  private holding = false;
  private unsubscribe: (() => void) | undefined;
  private readonly guard = (e: Event) => {
    if (this.holding && e.target === this.held) this.held?.pause();
  };

  constructor(private readonly source: TikTokDomVideoSource) {}

  hold(): void {
    this.holding = true;
    this.unsubscribe ??= this.source.onActiveVideoChange(() => this.retarget());
    this.retarget();
  }

  private retarget(): void {
    if (!this.holding) return;
    const v = this.source.element() ?? findActiveVideoElement();
    if (v === this.held) return;
    // Leaving a video while editing must not restart it in the background.
    this.detach();
    if (!v) return;
    this.held = v;
    this.wasPlaying = !v.paused;
    v.addEventListener('play', this.guard);
    v.pause();
  }

  private detach(): void {
    this.held?.removeEventListener('play', this.guard);
    this.held = null;
    this.wasPlaying = false;
  }

  release(): void {
    const v = this.held;
    // Check the DOM again: a feed transition may precede the next source poll.
    const shouldResume = this.wasPlaying && v?.isConnected && v === findActiveVideoElement();
    this.dispose();
    if (shouldResume && v) void v.play().catch(() => undefined);
  }

  dispose(): void {
    this.holding = false;
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    this.detach();
  }
}
