import type { FeedItem } from "../shared/feed-item";
import type { VerdictEntry } from "./verdicts";

export type Stats = { captured: number; batches: number; blocked: number; skipped: number; held: number; timeouts: number; dropped: number; mediaReady: number };
export type QueueRow = { item: FeedItem; verdict: VerdictEntry["verdict"]; media: "none" | "partial" | "ready"; current: boolean; skipped: boolean; why: string | null };
export type SkipLogEntry = { id: string; caption: string; reason: string; why: string | null; leadMs: number | null; adapter: string | null; ms: number | null; ok: boolean | null; at: number };
export type OverlayModel = { stats: Stats; classifier: string; mode: string; adapters: string[]; rows: QueueRow[]; skips: SkipLogEntry[] };

const CSS = `
:host{all:initial}
.panel{position:fixed;left:12px;bottom:12px;z-index:2147483647;width:340px;max-height:70vh;overflow:auto;
  font:12px/1.35 system-ui,sans-serif;color:#eee;background:rgba(20,20,24,.92);border-radius:8px;padding:8px;box-shadow:0 2px 12px #0008}
.row{display:flex;gap:6px;padding:3px 0;border-top:1px solid #333}
.cur{background:#ffffff14}
.dot{flex:none;width:8px;height:8px;border-radius:50%;margin-top:4px}
.allow{background:#3c3}.block{background:#e33}.pending{background:#aaa}
.cap{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.meta{color:#999;font-size:11px}
.tag{color:#f77;font-size:11px}
h4{margin:8px 0 2px;font-size:11px;color:#bbb;font-weight:600}
button{font:inherit;margin:4px 4px 0 0;padding:2px 8px;border-radius:4px;border:0;background:#444;color:#eee;cursor:pointer}
.cover{position:fixed;z-index:2147483646;display:flex;align-items:center;justify-content:center;
  background:#111;color:#bbb;font:14px system-ui,sans-serif;border-radius:8px;pointer-events:none}`;

const el = (tag: string, cls: string, text = ""): HTMLElement => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
};

const ago = (ms: number) => (ms < 60_000 ? `${Math.round(ms / 1000)}s ago` : `${Math.round(ms / 60_000)}m ago`);

/** Debug panel + the "checking…" cover. Shadow DOM so TikTok's CSS can't touch it. */
export class Overlay {
  private readonly host = document.createElement("div");
  private readonly root = this.host.attachShadow({ mode: "closed" });
  private readonly panel = el("div", "panel");
  private readonly cover = el("div", "cover");

  constructor(private readonly onExport: () => void) {
    const style = document.createElement("style");
    style.textContent = CSS;
    this.root.append(style, this.panel, this.cover);
    this.panel.style.display = this.cover.style.display = "none";
  }

  private mount(): void {
    if (!this.host.isConnected) document.documentElement.append(this.host);
  }

  showCover(rect: DOMRect | null, text: string): void {
    if (!rect) return void (this.cover.style.display = "none");
    this.mount();
    Object.assign(this.cover.style, { display: "flex", left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px` });
    this.cover.textContent = text;
  }

  render(m: OverlayModel | null): void {
    if (!m) return void (this.panel.style.display = "none");
    this.mount();
    this.panel.style.display = "block";
    const s = m.stats;
    this.panel.replaceChildren(
      el("div", "", `LNZ · ${m.mode} · ${m.classifier}`),
      el("div", "meta", `captured ${s.captured} (${s.batches} batches) · blocked ${s.blocked} · skipped ${s.skipped} · held ${s.held} · timeouts ${s.timeouts} · dropped ${s.dropped} · media ${s.mediaReady}`),
      el("div", "meta", `advance order: ${m.adapters.join(" → ")}`),
      el("h4", "", "Now + upcoming"),
    );
    for (const r of m.rows) {
      const row = el("div", r.current ? "row cur" : "row");
      const cap = el("div", "cap", `${r.current ? "▶ " : ""}${r.item.caption || "(no caption)"}`);
      const meta = el("div", "meta", `@${r.item.author.handle} · ${r.item.video.durationSec ?? "?"}s · media ${r.media}${r.item.isAd ? " · ad" : ""}`);
      cap.append(meta);
      if (r.verdict !== "block" && r.why) cap.append(el("div", "meta", r.why));
      if (r.verdict === "block") cap.append(el("div", "tag", `${r.skipped ? "⤼ skipped" : r.current ? "⤼ skipping…" : "⤼ will skip"}${r.why ? ` · ${r.why}` : ""}`));
      row.append(el("span", `dot ${r.verdict}`), cap);
      this.panel.append(row);
    }
    if (m.skips.length) {
      this.panel.append(el("h4", "", "Recent skips"));
      const now = Date.now();
      for (const k of m.skips) {
        const row = el("div", "row");
        const cap = el("div", "cap", k.caption || "(no caption)");
        const lead = k.leadMs === null ? "?" : `${(k.leadMs / 1000).toFixed(1)}s`;
        const res = k.ok === null ? "…" : k.ok ? `${k.adapter} ${k.ms}ms` : "failed";
        cap.append(el("div", "meta", `${k.reason}${k.why ? ` · ${k.why}` : ""} · known ${lead} ahead · ${res} · ${ago(now - k.at)}`));
        row.append(el("span", "dot block"), cap);
        this.panel.append(row);
      }
    }
    const exp = el("button", "", "Export JSON");
    exp.onclick = this.onExport;
    this.panel.append(exp);
  }

  destroy(): void {
    this.host.remove();
  }
}
