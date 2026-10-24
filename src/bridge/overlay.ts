import type { FeedItem } from "../shared/feed-item";
import type { VerdictEntry } from "./verdicts";

export type Stats = { captured: number; batches: number; blocked: number; skipped: number; held: number; timeouts: number; dropped: number; mediaReady: number };
export type QueueRow = { item: FeedItem; verdict: VerdictEntry["verdict"]; media: "none" | "partial" | "ready"; current: boolean; skipped: boolean; why: string | null; score: number | null };
export type SkipLogEntry = { id: string; caption: string; reason: string; why: string | null; leadMs: number | null; adapter: string | null; ms: number | null; ok: boolean | null; at: number };
export type OverlayModel = { stats: Stats; classifier: string; mode: string; adapters: string[]; rows: QueueRow[]; skips: SkipLogEntry[] };

const CSS = `
:host{all:initial}
.panel{position:fixed;left:14px;bottom:14px;z-index:2147483647;width:330px;max-height:72vh;display:flex;flex-direction:column;
  font:12px/1.4 -apple-system,system-ui,sans-serif;color:#e8eaf0;background:rgba(15,17,21,.9);backdrop-filter:blur(10px);
  border:1px solid #ffffff1a;border-radius:14px;box-shadow:0 8px 30px #0009;overflow:hidden}
.head{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #ffffff12;cursor:pointer;user-select:none}
.logo{color:#3ecf8e;font-size:15px}
.title{font-weight:700;letter-spacing:.3px}
.sub{color:#8b91a1;font-size:11px;flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.chips{display:flex;gap:6px;padding:8px 12px 4px;flex-wrap:wrap}
.chip{background:#ffffff0d;border-radius:20px;padding:2px 8px;font-size:11px;color:#c9cdd8}
.chip b{color:#fff}
.chip.stress b{color:#ff5b6b}.chip.calm b{color:#3ecf8e}
.body{overflow:auto;padding:4px 12px 10px}
.sec{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:#8b91a1;margin:8px 0 2px}
.row{display:grid;grid-template-columns:46px 1fr;gap:8px;padding:6px 0;border-top:1px solid #ffffff0d}
.row.cur{background:linear-gradient(90deg,#7c9cff1a,transparent);margin:0 -12px;padding:6px 12px}
.pill{font-size:10px;font-weight:600;text-align:center;border-radius:10px;padding:2px 0;align-self:start}
.pill.allow{background:#3ecf8e22;color:#3ecf8e}.pill.block{background:#ff5b6b22;color:#ff5b6b}.pill.pending{background:#9aa3b51f;color:#9aa3b5}
.cap{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.meta{color:#8b91a1;font-size:10.5px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.tag{color:#ff8b96;font-size:10.5px}
.bar{height:4px;background:#ffffff14;border-radius:2px;margin-top:4px;position:relative;overflow:hidden}
.bar i{position:absolute;inset:0 auto 0 0;border-radius:2px}
.dbg{color:#8b91a1;font-size:10.5px;white-space:pre-wrap;word-break:break-word}
.foot{display:flex;gap:6px;padding:8px 12px;border-top:1px solid #ffffff12}
button{font:inherit;font-size:11px;padding:3px 9px;border-radius:6px;border:0;background:#ffffff14;color:#e8eaf0;cursor:pointer}
.min .chips,.min .body,.min .foot{display:none}
.cover{position:fixed;z-index:2147483646;display:flex;flex-direction:column;gap:8px;align-items:center;justify-content:center;
  background:rgba(12,14,18,.92);backdrop-filter:blur(20px);color:#c9cdd8;font:14px -apple-system,system-ui,sans-serif;border-radius:12px;pointer-events:none}
.spin{width:22px;height:22px;border:2px solid #ffffff33;border-top-color:#3ecf8e;border-radius:50%;animation:s 0.9s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}`;

const el = (tag: string, cls = "", text = ""): HTMLElement => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
};

const ago = (ms: number) => (ms < 60_000 ? `${Math.round(ms / 1000)}s ago` : `${Math.round(ms / 60_000)}m ago`);

const pillText = (r: QueueRow) => (r.verdict === "block" ? (r.skipped ? "skipped" : "stress") : r.verdict === "allow" ? "calm" : "…");

/** Debug panel + the "checking…" cover. Shadow DOM so TikTok's CSS can't touch it. */
export class Overlay {
  private readonly host = document.createElement("div");
  private readonly root = this.host.attachShadow({ mode: "closed" });
  private readonly panel = el("div", "panel");
  private readonly cover = el("div", "cover");
  private minimized = false;
  private details = false;
  private hovering = false;

  constructor(private readonly onExport: () => void) {
    const style = document.createElement("style");
    style.textContent = CSS;
    this.root.append(style, this.panel, this.cover);
    this.panel.style.display = this.cover.style.display = "none";
    this.panel.addEventListener("pointerenter", () => (this.hovering = true));
    this.panel.addEventListener("pointerleave", () => (this.hovering = false));
  }

  private mount(): void {
    if (!this.host.isConnected) document.documentElement.append(this.host);
  }

  showCover(rect: DOMRect | null, text: string): void {
    if (!rect) return void (this.cover.style.display = "none");
    this.mount();
    Object.assign(this.cover.style, { display: "flex", left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px` });
    if (this.cover.dataset.text !== text) {
      this.cover.dataset.text = text;
      this.cover.replaceChildren(el("div", "spin"), el("div", "", text));
    }
  }

  render(m: OverlayModel | null): void {
    if (!m) return void (this.panel.style.display = "none");
    this.mount();
    this.panel.style.display = "flex";
    if (this.hovering && this.panel.childElementCount) return;
    this.panel.classList.toggle("min", this.minimized);
    const s = m.stats;
    const [name, ...status] = m.classifier.split(" · ");

    const head = el("div", "head");
    head.append(el("span", "logo", "◐"), el("span", "title", "LNZ"), el("span", "sub", `${m.mode} · ${name}${status[0] ? ` · ${status[0]}` : ""}`));
    head.onclick = () => ((this.minimized = !this.minimized), this.panel.classList.toggle("min", this.minimized), (this.hovering = false));

    const chips = el("div", "chips");
    const chip = (label: string, v: number, cls = "") => {
      const c = el("span", `chip ${cls}`);
      c.append(el("b", "", String(v)), document.createTextNode(` ${label}`));
      return c;
    };
    chips.append(chip("seen", s.captured), chip("stressful", s.blocked, "stress"), chip("skipped", s.skipped, "stress"), chip("dropped", s.dropped, "stress"));

    const body = el("div", "body");
    body.append(el("div", "sec", "Now + upcoming"));
    for (const r of m.rows) {
      const row = el("div", r.current ? "row cur" : "row");
      const cap = el("div");
      cap.append(el("div", "cap", `${r.current ? "▶ " : ""}${r.item.caption || "(no caption)"}`));
      cap.append(el("div", "meta", r.why ?? `@${r.item.author.handle} · ${r.item.video.durationSec ?? "?"}s · media ${r.media}${r.item.isAd ? " · ad" : ""}`));
      if (r.score !== null) {
        const bar = el("div", "bar");
        const f = el("i");
        f.style.width = `${Math.round(r.score * 100)}%`;
        f.style.background = r.verdict === "block" ? "#ff5b6b" : "#3ecf8e";
        bar.append(f);
        cap.append(bar);
      }
      if (r.verdict === "block") cap.append(el("div", "tag", r.skipped ? "⤼ skipped" : r.current ? "⤼ skipping…" : "⤼ will skip (silenced + blurred)"));
      row.append(el("span", `pill ${r.verdict}`, pillText(r)), cap);
      body.append(row);
    }
    if (m.skips.length) {
      body.append(el("div", "sec", "Recent skips"));
      const now = Date.now();
      for (const k of m.skips) {
        const row = el("div", "row");
        const cap = el("div");
        const lead = k.leadMs === null ? "?" : `${(k.leadMs / 1000).toFixed(1)}s`;
        const res = k.ok === null ? "…" : k.ok ? `${k.adapter} ${k.ms}ms` : "failed";
        cap.append(el("div", "cap", k.caption || "(no caption)"), el("div", "meta", `${k.why ?? k.reason} · known ${lead} ahead · ${res} · ${ago(now - k.at)}`));
        row.append(el("span", "pill block", "skipped"), cap);
        body.append(row);
      }
    }
    if (this.details) {
      body.append(el("div", "sec", "Debug"));
      body.append(el("div", "dbg", `${m.classifier}\nheld ${s.held} · timeouts ${s.timeouts} · media ready ${s.mediaReady} · batches ${s.batches}\nadvance order: ${m.adapters.join(" → ")}`));
    }

    const foot = el("div", "foot");
    const dbg = el("button", "", this.details ? "Hide debug" : "Debug");
    dbg.onclick = () => ((this.details = !this.details), (this.hovering = false));
    const exp = el("button", "", "Export JSON");
    exp.onclick = this.onExport;
    foot.append(dbg, exp);

    this.panel.replaceChildren(head, chips, body, foot);
  }

  destroy(): void {
    this.host.remove();
  }
}
