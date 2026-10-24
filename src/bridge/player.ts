import { HOLD_ATTR } from "../shared/dom";

export type Current = { video: HTMLVideoElement; container: HTMLElement; id: string | null };
type KnownIds = { has(id: string): boolean };

const ID_RE = /\d{17,20}/g;
const BLUR_ATTR = "data-lnz-blur";

const idIn = (container: HTMLElement, known: KnownIds): string | null => {
  for (const m of container.innerHTML.matchAll(ID_RE)) if (known.has(m[0])) return m[0];
  return null;
};

/** Every <video> on the page (TikTok keeps current + next), mapped to an item id via its feed container. */
export const mapVideos = (known: KnownIds): Current[] =>
  [...document.querySelectorAll("video")].map((video) => {
    const container = (video.closest("article") ?? video.parentElement ?? video) as HTMLElement;
    return { video, container, id: idIn(container, known) };
  });

/** The mapped video nearest the viewport center. URL /video/<id> wins when present. */
export const pickCurrent = (all: Current[], known: KnownIds): Current | null => {
  const mid = innerHeight / 2;
  let best: Current | null = null;
  let bestDist = Infinity;
  for (const c of all) {
    const r = c.video.getBoundingClientRect();
    if (r.height < 50 || r.bottom < 0 || r.top > innerHeight) continue;
    const d = Math.abs(r.top + r.height / 2 - mid);
    if (d < bestDist) (bestDist = d), (best = c);
  }
  const fromUrl = location.pathname.match(/\/video\/(\d+)/)?.[1];
  if (best && !best.id && fromUrl && known.has(fromUrl)) best = { ...best, id: fromUrl };
  return best;
};

/** The element blurred for a video: its player wrapper, so TikTok's poster image is covered too. */
export const blurTarget = (c: Current): HTMLElement => c.video.parentElement ?? c.video;

export const setBlur = (el: HTMLElement, on: boolean): void => {
  if (on === el.hasAttribute(BLUR_ATTR)) return;
  if (on) {
    el.setAttribute(BLUR_ATTR, "1");
    el.style.setProperty("filter", "blur(40px) brightness(0.5)", "important");
  } else {
    el.removeAttribute(BLUR_ATTR);
    el.style.removeProperty("filter");
  }
};

/** Pauses, mutes and marks a video so TikTok's own play() calls are ignored. Restores on release. */
export class PlayerGate {
  private readonly held = new Map<HTMLVideoElement, { muted: boolean }>();

  hold(v: HTMLVideoElement): void {
    if (!this.held.has(v)) this.held.set(v, { muted: v.muted });
    v.setAttribute(HOLD_ATTR, "1");
    v.muted = true;
    if (!v.paused) v.pause();
  }

  release(v: HTMLVideoElement, resume = true): void {
    const prev = this.held.get(v);
    if (!prev) return;
    this.held.delete(v);
    v.removeAttribute(HOLD_ATTR);
    v.muted = prev.muted;
    if (resume && v.isConnected) v.play().catch(() => {});
  }

  releaseAll(resume = false): void {
    for (const v of [...this.held.keys()]) this.release(v, resume);
  }

  /** Forget videos TikTok removed from the DOM. */
  prune(): void {
    for (const v of [...this.held.keys()]) if (!v.isConnected) this.held.delete(v);
  }

  isHeld(v: HTMLVideoElement): boolean {
    return this.held.has(v);
  }
}
