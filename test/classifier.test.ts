import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { KeywordClassifier, StubClassifier } from "../src/classifier/basic";
import { MockStressClassifier } from "../src/classifier/mock-stress";
import { classifyWithPolicy } from "../src/classifier/policy";
import { isStressful } from "../src/classifier/stress-rule";
import type { Classifier, ClassifyRequest } from "../src/classifier/types";
import { parseTikTok } from "../src/platforms/tiktok/parser";

const fixture = (f: string) => JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, "../fixtures", f), "utf8"));
const items = parseTikTok(fixture("item_list_1.json"), { capturedAt: 0 });
const reqs: ClassifyRequest[] = items.map((item) => ({ item, media: null }));
const withCaption = (caption: string, hashtags: string[] = []): ClassifyRequest => ({ item: { ...items[0]!, id: "9", caption, hashtags }, media: null });

describe("StubClassifier", () => {
  it("allows everything", async () => {
    const out = await new StubClassifier().classify(reqs);
    expect(Object.values(out).every((v) => v === "allow")).toBe(true);
    expect(Object.keys(out)).toHaveLength(items.length);
  });
});

describe("KeywordClassifier", () => {
  const k = new KeywordClassifier("#test");
  it("blocks caption containing #test", async () => expect((await k.classify([withCaption("hello #Test video")]))["9"]).toBe("block"));
  it("blocks matching hashtag", async () => expect((await k.classify([withCaption("hi", ["TEST"])]))["9"]).toBe("block"));
  it("matches as a substring in captions", async () => expect((await k.classify([withCaption("#testing123 nope")]))["9"]).toBe("block"));
  it("allows unrelated", async () => expect((await k.classify([withCaption("calm cats")]))["9"]).toBe("allow"));
});

describe("classifyWithPolicy", () => {
  const slow: Classifier = { name: "slow", needs: "metadata", defaultTimeoutMs: 10, classify: () => new Promise((r) => setTimeout(() => r({}), 200)) };
  const broken: Classifier = { name: "broken", needs: "metadata", defaultTimeoutMs: 10, classify: () => Promise.reject(new Error("boom")) };
  const partial: Classifier = { name: "p", needs: "metadata", defaultTimeoutMs: 10, classify: async () => ({ [items[0]!.id]: "block", [items[1]!.id]: "unknown" }) };

  it("failClosed blocks on timeout", async () => {
    const out = await classifyWithPolicy(slow, reqs, 20, "failClosed");
    expect(Object.values(out).every((v) => v.verdict === "block" && v.reason === "timeout")).toBe(true);
  });
  it("failOpen allows on timeout", async () => {
    const out = await classifyWithPolicy(slow, reqs, 20, "failOpen");
    expect(Object.values(out).every((v) => v.verdict === "allow")).toBe(true);
  });
  it("never rejects on classifier error", async () => {
    const out = await classifyWithPolicy(broken, reqs, 50, "failClosed");
    expect(out[items[0]!.id]).toEqual({ verdict: "block", reason: "error" });
  });
  it("maps unknown and missing answers through failMode", async () => {
    const out = await classifyWithPolicy(partial, reqs, 50, "failOpen");
    expect(out[items[0]!.id]).toEqual({ verdict: "block", reason: "classifier" });
    expect(out[items[1]!.id]!.verdict).toBe("allow");
    expect(out[items[2]!.id]!.verdict).toBe("allow");
  });
});

describe("stress rule", () => {
  it("max over the first window", () => {
    expect(isStressful([0.1, 0.7, 0.2], { windowSec: 1, hz: 4, threshold: 0.6, aggregate: "max" })).toBe(true);
    expect(isStressful([0.1, 0.2, 0.2, 0.2, 0.9], { windowSec: 1, hz: 4, threshold: 0.6, aggregate: "max" })).toBe(false);
  });
  it("mean", () => expect(isStressful([0.7, 0.7, 0.1, 0.1], { windowSec: 1, hz: 4, threshold: 0.5, aggregate: "mean" })).toBe(false));
});

describe("MockStressClassifier", () => {
  const m = new MockStressClassifier(undefined, [0, 1]);
  const clip = { layout: "muxed" as const, video: new Blob(["x"]), audio: null, complete: true };
  it("returns unknown without media", async () => expect(Object.values(await m.classify(reqs)).every((v) => v === "unknown")).toBe(true));
  it("is deterministic per id", async () => {
    const a = await m.classify(reqs.map((r) => ({ ...r, media: clip })));
    const b = await m.classify(reqs.map((r) => ({ ...r, media: clip })));
    expect(a).toEqual(b);
  });
});
