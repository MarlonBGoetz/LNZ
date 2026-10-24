import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { findVideoObjects, normalizeTikTokItem, parseTikTok, tiktokParser } from "../src/platforms/tiktok/parser";

const FIXTURES = path.resolve(import.meta.dirname, "../fixtures");
const load = (f: string): unknown => JSON.parse(fs.readFileSync(path.join(FIXTURES, f), "utf8"));
const ctx = { capturedAt: 1_000 };

// Expected counts from FINDINGS.md.
const CASES: [string, number][] = [
  ["item_list_1.json", 6],
  ["item_list_2.json", 6],
  ["item_list_3.json", 6],
  ["item_list_4.json", 7],
  ["item_list_5.json", 7],
  ["rehydration_foryou.json", 3],
];

describe.each(CASES)("fixture %s", (file, count) => {
  const items = parseTikTok(load(file), ctx);

  it("finds every video item", () => expect(items).toHaveLength(count));

  it("produces well-formed FeedItems", () => {
    items.forEach((it, i) => {
      expect(it.platform).toBe("tiktok");
      expect(it.id).toMatch(/^\d+$/);
      expect(it.feedPosition).toBe(i);
      expect(it.capturedAt).toBe(1_000);
      expect(typeof it.caption).toBe("string");
      expect(it.author.handle).not.toBe("");
      expect(it.video.durationSec).toBeGreaterThan(0);
      expect(it.video.playUrl).not.toBeNull();
      expect(it.stats.plays).not.toBeNull();
      expect(it.createdAt).toBeGreaterThan(Date.UTC(2015, 0, 1));
      expect(it.raw).toBeTypeOf("object");
    });
  });

  it("is JSON-serializable", () => expect(() => JSON.stringify(items)).not.toThrow());
});

describe("field mapping", () => {
  const items = CASES.flatMap(([f]) => parseTikTok(load(f), ctx));

  it("flags the ad", () => {
    const ads = items.filter((i) => i.isAd);
    expect(ads.length).toBeGreaterThan(0);
    expect(ads.every((a) => a.language === null && a.author.verified === false)).toBe(true);
  });

  it("prefers exact statsV2 over rounded stats", () => {
    const raw = items[0]!.raw as { statsV2: Record<string, string> };
    expect(items[0]!.stats.likes).toBe(Number(raw.statsV2.diggCount));
  });

  it("reads followers from item-level authorStats", () => {
    expect(items.filter((i) => i.author.followers !== null).length).toBe(items.length);
  });

  it("collects hashtags from challenges and textExtra, deduped", () => {
    const tagged = items.filter((i) => i.hashtags.length > 0);
    expect(tagged.length).toBeGreaterThan(0);
    for (const i of tagged) expect(new Set(i.hashtags.map((h) => h.toLowerCase())).size).toBe(i.hashtags.length);
  });

  it("reads diversification labels from embedded items", () => {
    const embedded = parseTikTok(load("rehydration_foryou.json"), ctx);
    expect(embedded.some((i) => i.labels.diversification.length > 0)).toBe(true);
  });

  it("ignores the ShowAIGC UI flag and uses moderation labels", () => {
    expect(items.filter((i) => i.labels.aigc === "moderation:1").length).toBeGreaterThan(0);
    expect(items.filter((i) => i.labels.aigc !== null).length).toBeLessThan(items.length);
  });
});

describe("missing fields", () => {
  const base = (load("item_list_1.json") as { itemList: Record<string, unknown>[] }).itemList[0]!;

  it("fills nulls for a minimal item", () => {
    const it = normalizeTikTokItem({ id: "123", video: {}, author: {} }, 0, ctx);
    expect(it).toMatchObject({
      id: "123",
      createdAt: null,
      isAd: false,
      caption: "",
      hashtags: [],
      language: null,
      author: { handle: "", name: "", verified: false, followers: null },
      video: { durationSec: null, width: null, height: null, coverUrl: null, playUrl: null, subtitles: [] },
      music: { id: null, title: null, author: null },
      stats: { plays: null, likes: null, comments: null, shares: null, saves: null },
      labels: { aigc: null, diversification: [] },
    });
  });

  it.each(["desc", "stats", "statsV2", "music", "challenges", "textExtra", "authorStats", "textLanguage", "createTime"])(
    "does not throw when %s is removed",
    (key) => {
      const copy = structuredClone(base);
      delete copy[key];
      expect(() => normalizeTikTokItem(copy, 0, ctx)).not.toThrow();
    },
  );

  it("does not throw on wrong types", () => {
    const bad = { id: "1", video: { duration: "abc", subtitleInfos: "x" }, author: { verified: "yes" }, challenges: [null, 5, { title: 7 }], textExtra: "no", stats: null, music: [] };
    const it = normalizeTikTokItem(bad, 0, ctx);
    expect(it.video.durationSec).toBeNull();
    expect(it.video.subtitles).toEqual([]);
    expect(it.author.verified).toBe(false);
    expect(it.hashtags).toEqual([]);
  });

  it.each([null, undefined, 42, "text", [], {}, { itemList: null }, { itemList: [{ id: "x" }] }])("returns [] for %j", (input) => {
    expect(parseTikTok(input, ctx)).toEqual([]);
  });

  it("survives cyclic input", () => {
    const a: Record<string, unknown> = {};
    a.self = a;
    expect(parseTikTok(a, ctx)).toEqual([]);
  });
});

describe("JSON walking", () => {
  it("finds items regardless of path", () => {
    const item = (load("item_list_1.json") as { itemList: unknown[] }).itemList[0];
    expect(findVideoObjects({ some: { renamed: { list: [item] } } })).toHaveLength(1);
  });

  it("dedupes repeated ids within one payload", () => {
    const item = (load("item_list_1.json") as { itemList: unknown[] }).itemList[0];
    expect(parseTikTok({ a: [item], b: [item] }, ctx)).toHaveLength(1);
  });
});

describe("tiktokParser.matches", () => {
  it.each([
    ["https://www.tiktok.com/api/recommend/item_list/?count=6", true],
    ["https://www.tiktok.com/", true],
    ["https://evil.com/?tiktok.com", false],
    ["not a url", false],
  ])("%s → %s", (url, ok) => expect(tiktokParser.matches(url)).toBe(ok));
});
