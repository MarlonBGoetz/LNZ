import { classifyWithPolicy } from "../classifier/policy";
import { createClassifier, timeoutFor } from "../classifier/registry";
import type { Classifier, ClassifyRequest, Verdict } from "../classifier/types";
import { tiktokParser } from "../platforms/tiktok/parser";
import { DEFAULT_CONFIG, loadConfig, onConfigChange, type Config } from "../shared/config";
import type { FeedItem } from "../shared/feed-item";
import { MSG, isPageMessage, type DropRequestMessage, type MediaChunkMessage } from "../shared/messages";
import type { HttpClassifyResponse, RuntimeRequest } from "../shared/runtime";
import { FeedStore } from "./feed-store";
import { MediaStore } from "./media-store";
import { ModelHostClient } from "./model-host-client";
import { Navigator, arrowKeyAdapter, instantScrollAdapter, jitter, smoothScrollAdapter } from "./navigator";
import { Overlay, type SkipLogEntry, type Stats } from "./overlay";
import { PlayerGate, blurTarget, mapVideos, pickCurrent, setBlur, type Current } from "./player";
import { VerdictCache } from "./verdicts";

const TICK_MS = 250;
const PERSIST_MAX = 500;
const PERSIST_DEBOUNCE_MS = 2000;

let cfg: Config = DEFAULT_CONFIG;
let classifier: Classifier;
const feed = new FeedStore();
const media = new MediaStore();
const verdicts = new VerdictCache();
const gate = new PlayerGate();
const stats: Stats = { captured: 0, batches: 0, blocked: 0, skipped: 0, held: 0, timeouts: 0, dropped: 0, mediaReady: 0 };
let current: Current | null = null;
/** Items that have been the current video; their verdicts survive classifier changes. */
const shown = new Set<string>();
/** Removed from TikTok's batch by drop mode; never rendered, so hidden from the queue. */
const dropped = new Set<string>();
const navigator_ = new Navigator([instantScrollAdapter, arrowKeyAdapter, smoothScrollAdapter]);

/** Created on first use so the models only load when the TRIBE classifier is selected. */
let modelHost: ModelHostClient | null = null;
const stressModel = () => {
  modelHost ??= new ModelHostClient();
  modelHost.warm();
  return modelHost;
};

const httpTransport = async (url: string, items: Omit<FeedItem, "raw">[]): Promise<Record<string, Verdict>> => {
  const req: RuntimeRequest = { kind: "httpClassify", url, items, timeoutMs: timeoutFor(cfg, classifier) };
  const res = (await chrome.runtime.sendMessage(req)) as HttpClassifyResponse;
  if (!res?.ok) throw new Error(res?.error ?? "no response");
  return res.verdicts;
};

const postPageConfig = () =>
  window.postMessage(
    { type: MSG.config, active: cfg.enabled, drop: cfg.enabled && cfg.drop && classifier.needs === "metadata", dropTimeoutMs: timeoutFor(cfg, classifier) + 100 },
    location.origin,
  );

const applyConfig = (next: Config) => {
  const classifierChanged = !classifier || next.classifier !== cfg.classifier || next.keywordPattern !== cfg.keywordPattern || next.httpUrl !== cfg.httpUrl || next.tribeThreshold !== cfg.tribeThreshold || next.tribeSeconds !== cfg.tribeSeconds;
  cfg = next;
  if (classifierChanged) {
    classifier = createClassifier(cfg, { http: httpTransport, stressModel });
    verdicts.resetExcept(shown);
    const pending = feed.order.filter((id) => !shown.has(id));
    if (classifier.needs === "metadata") void runClassifier(pending.map((id) => ({ item: feed.items.get(id)!, media: null })));
    else pending.forEach(classifyIfReady);
  }
  postPageConfig();
  if (!cfg.enabled || cfg.mode === "observe") {
    gate.releaseAll(true);
    unblurAll();
    overlay.showCover(null, "");
  }
  if (!cfg.enabled || !cfg.overlay) overlay.render(null);
};

// --- classification ---

const runClassifier = async (reqs: ClassifyRequest[]) => {
  if (reqs.length === 0) return;
  reqs.forEach((r) => verdicts.start(r.item.id));
  const out = await classifyWithPolicy(classifier, reqs, timeoutFor(cfg, classifier), cfg.failMode);
  for (const [id, v] of Object.entries(out)) {
    verdicts.set(id, v);
    if (v.reason === "timeout") stats.timeouts++;
    if (v.verdict === "block") stats.blocked++;
  }
  persistSoon();
};

// Media classifiers are slow, so clips run one at a time: the current video first, then the nearest upcoming one.
// Clips for videos already scrolled past are skipped (they run again if you scroll back to them).
const mediaReadyIds = new Set<string>();
const counted = new Set<string>();
let mediaBusy = false;
let currentIndex = -1;

const pumpMedia = () => {
  if (mediaBusy) return;
  for (const id of mediaReadyIds) if (verdicts.has(id)) mediaReadyIds.delete(id);
  const rank = (id: string) => {
    if (id === current?.id) return -1;
    const i = feed.order.indexOf(id);
    return i > currentIndex ? i - currentIndex : Infinity;
  };
  const next = [...mediaReadyIds].filter((id) => rank(id) !== Infinity).sort((a, b) => rank(a) - rank(b))[0];
  const item = next && feed.items.get(next);
  const clip = next && media.clip(next);
  if (!next || !item || !clip) return;
  mediaReadyIds.delete(next);
  mediaBusy = true;
  void runClassifier([{ item, media: clip }]).finally(() => {
    mediaBusy = false;
    pumpMedia();
  });
};

const classifyIfReady = (id: string) => {
  if (verdicts.has(id) || verdicts.isInFlight(id)) return;
  const item = feed.items.get(id);
  if (!item) return;
  if (classifier.needs === "metadata") return void runClassifier([{ item, media: null }]);
  if (!media.clip(id)) return;
  if (!counted.has(id)) (counted.add(id), stats.mediaReady++);
  mediaReadyIds.add(id);
  pumpMedia();
};

// --- page messages ---

const onFeed = (json: unknown, capturedAt: number, classify = true): FeedItem[] => {
  const fresh = feed.add(tiktokParser.parse(json, { capturedAt }));
  if (fresh.length) {
    stats.captured += fresh.length;
    stats.batches++;
    if (classify && classifier.needs === "metadata") void runClassifier(fresh.map((item) => ({ item, media: null })));
    else if (classify) fresh.forEach((i) => classifyIfReady(i.id));
    persistSoon();
  }
  return fresh;
};

const onMedia = (m: MediaChunkMessage) => {
  const hit = feed.byPath(m.path);
  if (!hit) return;
  media.add(hit.id, hit.kind, { start: m.start, total: m.total, complete: m.complete, bytes: new Uint8Array(m.bytes) });
  classifyIfReady(hit.id);
};

/** Drop path: the response is held in the page until we answer. Repeats reuse cached verdicts. */
const onDropRequest = async (m: DropRequestMessage) => {
  onFeed(m.json, m.capturedAt, false);
  const items = tiktokParser.parse(m.json, { capturedAt: m.capturedAt });
  const todo = items.filter((i) => !verdicts.has(i.id));
  todo.forEach((i) => verdicts.start(i.id));
  const out = await classifyWithPolicy(classifier, todo.map((item) => ({ item, media: null })), timeoutFor(cfg, classifier), cfg.failMode);
  for (const [id, v] of Object.entries(out)) {
    verdicts.set(id, v);
    if (v.verdict === "block") stats.blocked++;
  }
  // Only confident blocks are dropped; timeouts stay in the feed and are handled by skip mode.
  const blockIds = items.map((i) => i.id).filter((id) => {
    const v = verdicts.get(id);
    return v.verdict === "block" && v.reason !== "timeout" && v.reason !== "error" && v.reason !== "unknown";
  });
  stats.dropped += blockIds.length;
  blockIds.forEach((id) => dropped.add(id));
  window.postMessage({ type: MSG.dropResponse, reqId: m.reqId, blockIds }, location.origin);
  persistSoon();
};

window.addEventListener("message", (e) => {
  if (e.source !== window || !isPageMessage(e.data) || !cfg.enabled) return;
  const d = e.data;
  if (d.type === MSG.feed) onFeed(d.json, d.capturedAt);
  else if (d.type === MSG.media) onMedia(d);
  else if (d.type === MSG.dropRequest) void onDropRequest(d);
});

// --- playback control (pre-emptive skip + auto-scroll) ---

const SKIP_LOG_MAX = 8;
const holdStart = new Map<HTMLVideoElement, number>();
/** Id-less videos let through by failOpen after the hold timeout. */
const openedByTimeout = new WeakSet<HTMLVideoElement>();
const play = { video: null as HTMLVideoElement | null, playedMs: 0, lastTime: 0, ended: false, lastTick: Date.now() };
/** Ids skipped at least once; counted once, skipped again on every return. */
const skippedIds = new Set<string>();
const skipLog: SkipLogEntry[] = [];
let blurred = new Set<HTMLElement>();

const unblurAll = () => {
  blurred.forEach((e) => setBlur(e, false));
  blurred.clear();
};

const why = (id: string): string | null => {
  const item = feed.items.get(id);
  return item && classifier.explain ? classifier.explain(item) : null;
};

/** Advance right away (no delay, no cover). Back-to-back blocked videos chain via Navigator.notifyCurrent. */
const skipNow = (cur: Current) => {
  if (navigator_.busy) return;
  let entry: SkipLogEntry | null = null;
  if (cur.id && !skippedIds.has(cur.id)) {
    skippedIds.add(cur.id);
    stats.skipped++;
    const at = verdicts.atOf(cur.id);
    const v = verdicts.get(cur.id);
    entry = { id: cur.id, caption: feed.items.get(cur.id)?.caption ?? "", reason: v.reason ?? "?", why: why(cur.id), leadMs: at === null ? null : Date.now() - at, adapter: null, ms: null, ok: null, at: Date.now() };
    skipLog.unshift(entry);
    skipLog.length = Math.min(skipLog.length, SKIP_LOG_MAX);
  }
  navigator_.advance(cur, 0, (r) => entry && Object.assign(entry, { adapter: r.adapter, ms: r.ms, ok: r.ok }));
};

/** Upcoming videos: blocked ones are silenced and blurred before they reach the screen; pending ones are silenced. */
const prepareUpcoming = (all: Current[], cur: Current | null, blur: Set<HTMLElement>) => {
  for (const c of all) {
    if (c.video === cur?.video) continue;
    const v = c.id ? verdicts.get(c.id).verdict : "pending";
    if (v === "allow") gate.release(c.video, false);
    else gate.hold(c.video);
    if (v === "block") blur.add(blurTarget(c));
  }
};

const controlCurrent = (cur: Current, blur: Set<HTMLElement>): boolean => {
  const v = cur.video;
  const entry = cur.id ? verdicts.get(cur.id) : { verdict: "pending" as const };

  if (entry.verdict === "allow" || openedByTimeout.has(v)) {
    holdStart.delete(v);
    gate.release(v);
    overlay.showCover(null, "");
    return true;
  }

  gate.hold(v);
  if (entry.verdict === "block") {
    blur.add(blurTarget(cur));
    overlay.showCover(null, "");
    skipNow(cur);
    return false;
  }

  overlay.showCover(v.getBoundingClientRect(), "checking…");
  if (!holdStart.has(v)) (holdStart.set(v, Date.now()), stats.held++);
  if (Date.now() - holdStart.get(v)! > cfg.holdTimeoutMs) {
    const verdict = cfg.failMode === "failOpen" ? "allow" : "block";
    if (cur.id) verdicts.set(cur.id, { verdict, reason: "holdTimeout" });
    stats.timeouts++;
    if (verdict === "block") {
      blur.add(blurTarget(cur));
      overlay.showCover(null, "");
      skipNow(cur);
    } else {
      holdStart.delete(v);
      openedByTimeout.add(v);
      gate.release(v);
      overlay.showCover(null, "");
      return true;
    }
  }
  return false;
};

const autoScroll = (cur: Current, playing: boolean) => {
  const v = cur.video;
  const now = Date.now();
  if (play.video !== v) Object.assign(play, { video: v, playedMs: 0, lastTime: v.currentTime, ended: false });
  if (playing && !v.paused) play.playedMs += now - play.lastTick;
  play.lastTick = now;
  // TikTok loops videos, so "ended" shows up as currentTime wrapping back to the start.
  if (v.currentTime + 1 < play.lastTime && play.lastTime > (v.duration || Infinity) - 1.5) play.ended = true;
  if (v.ended) play.ended = true;
  play.lastTime = v.currentTime;
  if (!cfg.autoScroll || !playing || navigator_.busy) return;
  if (play.ended || (cfg.autoScrollSec > 0 && play.playedMs >= cfg.autoScrollSec * 1000)) navigator_.advance(cur, jitter(400, 1200));
};

const tick = () => {
  if (!cfg.enabled) return;
  const all = mapVideos(feed.items);
  for (const v of holdStart.keys()) if (!v.isConnected) holdStart.delete(v);
  gate.prune();
  current = pickCurrent(all, feed.items);
  navigator_.notifyCurrent(current?.video ?? null);
  const blur = new Set<HTMLElement>();
  if (cfg.mode === "skip") prepareUpcoming(all, current, blur);
  if (current) {
    if (current.id) {
      shown.add(current.id);
      currentIndex = feed.order.indexOf(current.id);
    }
    if (current.id && !verdicts.has(current.id)) classifyIfReady(current.id);
    const playing = cfg.mode === "skip" ? controlCurrent(current, blur) : true;
    autoScroll(current, playing);
  } else overlay.showCover(null, "");
  for (const e of blurred) if (!blur.has(e)) setBlur(e, false);
  for (const e of blur) setBlur(e, true);
  blurred = blur;
  if (cfg.overlay) {
    const visible = (id: string) => !dropped.has(id);
    const ids = current?.id ? [current.id, ...feed.ahead(current.id, cfg.queueSize, visible)] : feed.ahead(null, cfg.queueSize, visible);
    overlay.render({
      stats,
      classifier: classifier.name + (classifier.name === "tribe" && modelHost ? ` · ${hostLine(modelHost)}` : ""),
      mode: cfg.mode + (cfg.drop ? "+drop" : "") + (cfg.autoScroll ? "+auto" : ""),
      adapters: navigator_.order,
      skips: skipLog,
      rows: ids.map((id) => {
        const verdict = verdicts.get(id).verdict;
        return { item: feed.items.get(id)!, verdict, media: media.status(id), current: id === current?.id, skipped: skippedIds.has(id), why: why(id) };
      }),
    });
  }
};

const hostLine = (h: ModelHostClient): string => {
  const s = h.status;
  const parts = [`model ${s.status}${s.backend ? ` (${s.backend})` : ""}`];
  if (s.error) parts.push(s.error);
  parts.push(`done ${s.done ?? 0} · failed ${s.failed ?? 0} · queued ${s.queued ?? 0}${mediaBusy ? " · busy" : ""}`);
  if (s.stage) parts.push(`${s.stage} ${((s.stageMs ?? 0) / 1000).toFixed(1)}s`);
  if (s.lastMs !== null && s.lastMs !== undefined) parts.push(`last ${s.lastMs}ms`);
  if (s.lastError) parts.push(`err: ${s.lastError}`);
  return parts.join(" · ");
};

// --- persistence + export ---

const snapshot = (withRaw: boolean) =>
  feed.order.slice(-PERSIST_MAX).map((id) => {
    const { raw, ...rest } = feed.items.get(id)!;
    return { ...rest, ...(withRaw ? { raw } : {}), verdict: verdicts.get(id), why: why(id) };
  });

let persistTimer: ReturnType<typeof setTimeout> | undefined;
const persistSoon = () => {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => void chrome.storage.local.set({ items: snapshot(false), stats }), PERSIST_DEBOUNCE_MS);
};

const exportJson = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot(true), null, 2)], { type: "application/json" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `lnz-feed-${Date.now()}.json` });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
};

const overlay = new Overlay(exportJson);

// --- boot ---

classifier = createClassifier(cfg, { http: httpTransport, stressModel });
void loadConfig().then(applyConfig);
onConfigChange(applyConfig);
setInterval(tick, TICK_MS);
