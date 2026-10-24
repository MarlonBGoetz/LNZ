// MAIN world, document_start. Read-only toward TikTok: never issues requests, only copies/filters responses it already receives.
import { FEED_URL_PATTERN, REHYDRATION_SCRIPT_ID } from "../platforms/tiktok/config";
import { removeBlocked } from "../platforms/tiktok/drop";
import { isMediaUrl } from "../platforms/tiktok/media";
import { HOLD_ATTR } from "../shared/dom";
import { MSG, isPageMessage, type CaptureSource, type PageConfigMessage } from "../shared/messages";

declare global {
  interface Window {
    __LNZ_INSTALLED__?: boolean;
  }
}

const post = (msg: object, transfer: Transferable[] = []) => window.postMessage(msg, location.origin, transfer);

const install = (): void => {
  if (window.__LNZ_INSTALLED__) return;
  window.__LNZ_INSTALLED__ = true;

  // Capture is on until the bridge says otherwise, so the first batch isn't missed. Drop is off until enabled.
  let cfg: PageConfigMessage = { type: MSG.config, active: true, drop: false, dropTimeoutMs: 400 };
  const pendingDrops = new Map<string, (blockIds: string[]) => void>();

  window.addEventListener("message", (e) => {
    if (e.source !== window || !isPageMessage(e.data)) return;
    if (e.data.type === MSG.config) cfg = e.data;
    else if (e.data.type === MSG.dropResponse) pendingDrops.get(e.data.reqId)?.(e.data.blockIds);
  });

  const emitFeed = (via: CaptureSource, url: string, json: unknown) =>
    post({ type: MSG.feed, via, url, capturedAt: Date.now(), json });

  /** Waits for the bridge to name blocked ids, else passes through unchanged (fail open to avoid refetch loops). */
  const askDrop = (json: unknown): Promise<string[]> =>
    new Promise((resolve) => {
      const reqId = Math.random().toString(36).slice(2);
      const done = (ids: string[]) => {
        pendingDrops.delete(reqId);
        clearTimeout(timer);
        resolve(ids);
      };
      const timer = setTimeout(() => done([]), cfg.dropTimeoutMs);
      pendingDrops.set(reqId, done);
      post({ type: MSG.dropRequest, reqId, json, capturedAt: Date.now() });
    });

  const filteredResponse = async (res: Response): Promise<Response> => {
    const text = await res.clone().text();
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      return res;
    }
    if (!cfg.drop) {
      emitFeed("fetch", res.url, json);
      return res;
    }
    const blockIds = await askDrop(json);
    if (blockIds.length === 0) return res;
    const out = new Response(JSON.stringify(removeBlocked(json, new Set(blockIds)).json), {
      status: res.status,
      statusText: res.statusText,
      headers: res.headers,
    });
    Object.defineProperty(out, "url", { value: res.url });
    return out;
  };

  const teeMedia = (res: Response, url: string): void => {
    if (!res.body || (res.status !== 200 && res.status !== 206)) return;
    let path: string;
    try {
      path = new URL(url, location.href).pathname;
    } catch {
      return;
    }
    const range = res.headers.get("content-range")?.match(/bytes (\d+)-\d+\/(\d+)/);
    const start = range ? Number(range[1]) : 0;
    const total = range ? Number(range[2]) : null;
    const contentType = res.headers.get("content-type");
    const reader = res.clone().body!.getReader();
    const parts: Uint8Array[] = [];
    let size = 0;
    const flush = (complete: boolean) => {
      if (!size) return;
      const bytes = new Uint8Array(size);
      let o = 0;
      for (const p of parts) (bytes.set(p, o), (o += p.byteLength));
      post({ type: MSG.media, path, start, total, contentType, complete, bytes: bytes.buffer, at: Date.now() }, [bytes.buffer]);
    };
    const pump = (): void => {
      reader.read().then(
        ({ done, value }) => {
          if (done) return flush(true);
          parts.push(value);
          size += value.byteLength;
          pump();
        },
        () => flush(false),
      );
    };
    pump();
  };

  const nativeFetch = window.fetch;
  window.fetch = function (this: unknown, ...args: Parameters<typeof fetch>) {
    const p = nativeFetch.apply(this, args);
    const reqUrl = typeof args[0] === "string" ? args[0] : args[0] instanceof Request ? args[0].url : String(args[0]);
    if (cfg.active && FEED_URL_PATTERN.test(reqUrl)) return p.then((res) => filteredResponse(res).catch(() => res));
    if (cfg.active && isMediaUrl(reqUrl)) p.then((res) => teeMedia(res, reqUrl), () => {});
    return p;
  } as typeof fetch;

  // XHR: capture only (TikTok uses fetch for the feed; see FINDINGS.md). No drop support.
  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (this: XMLHttpRequest, method: string, url: string | URL, ...rest: unknown[]) {
    if (FEED_URL_PATTERN.test(String(url))) {
      this.addEventListener("load", () => {
        try {
          const t = this.responseType === "" || this.responseType === "text" ? this.responseText : JSON.stringify(this.response);
          emitFeed("xhr", this.responseURL || String(url), JSON.parse(t));
        } catch {}
      });
    }
    return (nativeOpen as (...a: unknown[]) => void).call(this, method, url, ...rest);
  } as typeof XMLHttpRequest.prototype.open;

  // Play guard: TikTok's player calls play() on its own; while held, swallow it.
  const nativePlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
    if (this.hasAttribute(HOLD_ATTR)) return Promise.resolve();    return nativePlay.call(this);
  };

  const readEmbedded = (): void => {
    const el = document.getElementById(REHYDRATION_SCRIPT_ID);
    if (!el?.textContent) return;
    try {
      emitFeed("embedded", location.href, JSON.parse(el.textContent));
    } catch {}
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", readEmbedded, { once: true });
  else readEmbedded();
};

install();
