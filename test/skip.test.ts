import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { Navigator, type AdvanceAdapter } from "../src/bridge/navigator";
import type { Current } from "../src/bridge/player";
import { VerdictCache } from "../src/bridge/verdicts";
import { StressLexiconClassifier } from "../src/classifier/stress-lexicon";
import { parseTikTok } from "../src/platforms/tiktok/parser";
import type { FeedItem } from "../src/shared/feed-item";

const base = parseTikTok(JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, "../fixtures/item_list_1.json"), "utf8")), { capturedAt: 0 })[0]!;
const item = (caption: string, hashtags: string[] = [], diversification: string[] = []): FeedItem => ({ ...base, id: "1", caption, hashtags, labels: { aigc: null, diversification } });

describe("StressLexiconClassifier", () => {
  const c = new StressLexiconClassifier();
  const verdict = async (i: FeedItem) => (await c.classify([{ item: i, media: null }]))["1"];

  it("blocks severe terms", async () => expect(await verdict(item("Breaking news: earthquake hits the city"))).toBe("block"));
  it("blocks via hashtags", async () => expect(await verdict(item("watch till the end", ["horror", "scary"]))).toBe("block"));
  it("allows calm content", async () => expect(await verdict(item("cute cat learns to sit 🐱 #cats #fyp", ["cats", "fyp"]))).toBe("allow"));
  it("matches whole words only", async () => expect(await verdict(item("warm skillet tips, a stripped-down recipe"))).toBe("allow"));
  it("sums mild terms up to the threshold", async () => {
    expect(await verdict(item("sad day"))).toBe("allow");
    expect(await verdict(item("sad day, crying"))).toBe("block");
  });
  it("matches multi-word phrases across whitespace", () => expect(c.score(item("he passed   away last night")).hits).toContain("passed away"));
  it("explains hits", () => expect(c.explain(item("war footage"))).toBe("war (3)"));
  it("labels every fixture item without throwing", async () => {
    const all = [1, 2, 3, 4, 5].flatMap((n) => parseTikTok(JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, `../fixtures/item_list_${n}.json`), "utf8")), { capturedAt: 0 }));
    const out = await c.classify(all.map((i) => ({ item: i, media: null })));
    expect(Object.values(out).every((v) => v === "allow" || v === "block")).toBe(true);
  });
});

describe("VerdictCache", () => {
  it("keeps the first final verdict and its time", () => {
    const v = new VerdictCache();
    v.set("1", { verdict: "block", reason: "classifier" });
    v.set("1", { verdict: "allow", reason: "classifier" });
    expect(v.get("1").verdict).toBe("block");
    expect(v.atOf("1")).toBeTypeOf("number");
  });
});

describe("Navigator", () => {
  const fakeVideo = () => ({}) as HTMLVideoElement;
  const cur = (video: HTMLVideoElement): Current => ({ video, container: {} as HTMLElement, id: "1" });
  const adapter = (name: string, onAdvance: () => void): AdvanceAdapter => ({ name, advance: onAdvance });

  it("finishes as soon as the current video changes and reports the adapter", () => {
    vi.useFakeTimers();
    const v1 = fakeVideo();
    const nav = new Navigator([adapter("a", () => {})]);
    const done = vi.fn();
    nav.advance(cur(v1), 0, done);
    vi.advanceTimersByTime(1);
    expect(nav.busy).toBe(true);
    nav.notifyCurrent(fakeVideo());
    expect(nav.busy).toBe(false);
    expect(done).toHaveBeenCalledWith(expect.objectContaining({ adapter: "a", ok: true }));
    vi.useRealTimers();
  });

  it("falls back to the next adapter and promotes the one that worked", () => {
    vi.useFakeTimers();
    const v1 = fakeVideo();
    const nav = new Navigator([adapter("broken", () => {}), adapter("works", () => {})]);
    nav.advance(cur(v1), 0);
    vi.advanceTimersByTime(1);
    vi.advanceTimersByTime(450);
    nav.notifyCurrent(fakeVideo());
    expect(nav.order).toEqual(["works", "broken"]);
    vi.useRealTimers();
  });

  it("reports failure when no adapter moves the feed", () => {
    vi.useFakeTimers();
    const nav = new Navigator([adapter("a", () => {})]);
    const done = vi.fn();
    nav.advance(cur(fakeVideo()), 0, done);
    vi.advanceTimersByTime(1000);
    expect(done).toHaveBeenCalledWith(expect.objectContaining({ ok: false }));
    expect(nav.busy).toBe(false);
    vi.useRealTimers();
  });

  it("ignores the same video and a second advance while busy", () => {
    vi.useFakeTimers();
    const v1 = fakeVideo();
    const calls = vi.fn();
    const nav = new Navigator([adapter("a", calls)]);
    nav.advance(cur(v1), 0);
    nav.advance(cur(v1), 0);
    vi.advanceTimersByTime(1);
    nav.notifyCurrent(v1);
    expect(nav.busy).toBe(true);
    expect(calls).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
