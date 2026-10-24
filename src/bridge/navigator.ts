import type { Current } from "./player";

/** One way to move to the next video. Swap or reorder without touching callers. */
export interface AdvanceAdapter {
  readonly name: string;
  advance(cur: Current): void;
}

const nextArticle = (cur: Current): HTMLElement | null => {
  let next = cur.container.nextElementSibling;
  while (next && !(next instanceof HTMLElement && next.getBoundingClientRect().height > 50)) next = next.nextElementSibling;
  return next instanceof HTMLElement ? next : null;
};

/** Jumps with no animation, so a blocked video is never seen mid-scroll. */
export const instantScrollAdapter: AdvanceAdapter = {
  name: "instantScroll",
  advance: (cur) => {
    const next = nextArticle(cur);
    if (next) next.scrollIntoView({ behavior: "instant", block: "center" });
    else window.scrollBy({ top: innerHeight, behavior: "instant" });
  },
};

export const arrowKeyAdapter: AdvanceAdapter = {
  name: "arrowDown",
  advance: () => {
    const init: KeyboardEventInit = { key: "ArrowDown", code: "ArrowDown", keyCode: 40, bubbles: true, cancelable: true };
    const target = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : document.body;
    target.dispatchEvent(new KeyboardEvent("keydown", init));
    target.dispatchEvent(new KeyboardEvent("keyup", init));
  },
};

export const smoothScrollAdapter: AdvanceAdapter = {
  name: "smoothScroll",
  advance: (cur) => {
    const next = nextArticle(cur);
    if (next) next.scrollIntoView({ behavior: "smooth", block: "center" });
    else window.scrollBy({ top: innerHeight, behavior: "smooth" });
  },
};

const VERIFY_MS = 450;

export type AdvanceResult = { adapter: string | null; ok: boolean; ms: number };

/**
 * Tries adapters in order until the current video changes. The adapter that worked moves to the front,
 * so later skips use it first. `notifyCurrent` ends the busy window as soon as the video changes,
 * which lets back-to-back blocked videos be skipped without waiting.
 */
export class Navigator {
  private adapters: AdvanceAdapter[];
  private pending: { from: HTMLVideoElement; started: number; done: (r: AdvanceResult) => void; timers: ReturnType<typeof setTimeout>[]; tried: string | null } | null = null;
  lastAdapter: string | null = null;

  constructor(adapters: AdvanceAdapter[]) {
    this.adapters = [...adapters];
  }

  get busy(): boolean {
    return this.pending !== null;
  }

  get order(): string[] {
    return this.adapters.map((a) => a.name);
  }

  /** Call every tick with the current video. */
  notifyCurrent(video: HTMLVideoElement | null): void {
    const p = this.pending;
    if (!p || !video || video === p.from) return;
    this.finish(true);
  }

  advance(cur: Current, delayMs = 0, done: (r: AdvanceResult) => void = () => {}): void {
    if (this.pending) return;
    const p = (this.pending = { from: cur.video, started: Date.now(), done, timers: [] as ReturnType<typeof setTimeout>[], tried: null as string | null });
    const attempt = (i: number) => {
      if (this.pending !== p) return;
      const a = this.adapters[i];
      if (!a) return this.finish(false);
      p.tried = a.name;
      a.advance(cur);
      p.timers.push(setTimeout(() => attempt(i + 1), VERIFY_MS));
    };
    p.timers.push(setTimeout(() => attempt(0), delayMs));
  }

  private finish(ok: boolean): void {
    const p = this.pending;
    if (!p) return;
    this.pending = null;
    p.timers.forEach(clearTimeout);
    if (ok && p.tried) {
      const i = this.adapters.findIndex((a) => a.name === p.tried);
      if (i > 0) this.adapters.unshift(...this.adapters.splice(i, 1));
      this.lastAdapter = p.tried;
    }
    p.done({ adapter: p.tried, ok, ms: Date.now() - p.started });
  }
}

/** Human-ish pause before acting. */
export const jitter = (minMs: number, maxMs: number): number => minMs + Math.random() * (maxMs - minMs);
