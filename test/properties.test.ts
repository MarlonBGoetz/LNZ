import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { MediaStore } from "../src/bridge/media-store";
import { removeBlocked } from "../src/platforms/tiktok/drop";
import { normalizeTikTokItem, parseTikTok } from "../src/platforms/tiktok/parser";
import { stressCurve } from "../src/model/tribe/features";
import { isStressful } from "../src/classifier/stress-rule";

const ctx = { capturedAt: 1 };
const numericId = fc.bigInt({ min: 1n, max: 10n ** 19n }).map(String);

describe("PBT: parser never throws on untrusted JSON", () => {
  it("parseTikTok returns well-formed items for any JSON value", () => {
    fc.assert(
      fc.property(fc.jsonValue(), (json) => {
        const items = parseTikTok(json, ctx);
        for (const it of items) {
          expect(it.id).toMatch(/^\d+$/);
          expect(typeof it.caption).toBe("string");
          expect(Array.isArray(it.hashtags)).toBe(true);
        }
      }),
      { numRuns: 500 },
    );
  });

  it("normalizeTikTokItem never throws when fields have arbitrary types", () => {
    fc.assert(
      fc.property(numericId, fc.dictionary(fc.string(), fc.jsonValue()), fc.jsonValue(), fc.jsonValue(), (id, extra, video, author) => {
        const raw = { ...extra, id, video: typeof video === "object" && video && !Array.isArray(video) ? video : {}, author: typeof author === "object" && author && !Array.isArray(author) ? author : {} };
        const it = normalizeTikTokItem(raw, 0, ctx);
        expect(it.id).toBe(id);
        for (const v of Object.values(it.stats)) expect(v === null || Number.isFinite(v)).toBe(true);
      }),
      { numRuns: 500 },
    );
  });

  it("finds every injected video object regardless of nesting", () => {
    fc.assert(
      fc.property(fc.uniqueArray(numericId, { minLength: 1, maxLength: 8 }), fc.array(fc.string({ minLength: 1 }), { minLength: 1, maxLength: 4 }), (ids, path) => {
        let root: unknown = ids.map((id) => ({ id, video: {}, author: {} }));
        for (const k of path) root = { [k]: root };
        expect(parseTikTok(root, ctx).map((i) => i.id).sort()).toEqual([...ids].sort());
      }),
    );
  });
});

describe("PBT: drop filter invariants", () => {
  it("removes exactly the blocked ids, keeps order, never empties a batch", () => {
    fc.assert(
      fc.property(fc.uniqueArray(numericId, { minLength: 1, maxLength: 12 }), fc.array(fc.boolean(), { minLength: 12, maxLength: 12 }), (ids, flags) => {
        const blocked = new Set(ids.filter((_, i) => flags[i]));
        const { json, removed } = removeBlocked({ itemList: ids.map((id) => ({ id })) }, blocked);
        const kept = (json as { itemList: { id: string }[] }).itemList.map((i) => i.id);
        expect(kept.length).toBeGreaterThan(0);
        expect(kept).toEqual(blocked.size === ids.length ? ids.slice(0, 1) : ids.filter((id) => !blocked.has(id)));
        expect(new Set([...kept, ...removed])).toEqual(new Set(ids));
      }),
    );
  });
});

describe("PBT: media assembly", () => {
  it("any chunking of a file reassembles to the same bytes, in any arrival order", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.uint8Array({ minLength: 2048, maxLength: 4096 }),
        fc.array(fc.integer({ min: 1, max: 4095 }), { maxLength: 6 }),
        fc.boolean(),
        async (file, cuts, reverse) => {
          const points = [...new Set(cuts.filter((c) => c < file.length))].sort((a, b) => a - b);
          const bounds = [0, ...points, file.length];
          const chunks = bounds.slice(0, -1).map((s, i) => ({ start: s, bytes: file.slice(s, bounds[i + 1]), total: file.length, complete: true }));
          const m = new MediaStore();
          for (const c of reverse ? [...chunks].reverse() : chunks) m.add("1", "video", c);
          const clip = m.clip("1");
          expect(clip?.complete).toBe(true);
          expect(new Uint8Array(await clip!.video.arrayBuffer())).toEqual(file);
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe("PBT: stress readout", () => {
  const readout = { roi_names: ["a", "b", "c", "d", "e", "f"], weights: Array.from({ length: 12 }, (_, i) => (i % 3) - 1), bias: 0.2 };
  const roiRows = fc.array(fc.array(fc.double({ min: -50, max: 50, noNaN: true }), { minLength: 6, maxLength: 6 }), { minLength: 1, maxLength: 30 });

  it("is one probability per second and depends only on the past (causal)", () => {
    fc.assert(
      fc.property(roiRows, roiRows, (a, b) => {
        const full = stressCurve([...a, ...b], readout);
        expect(full).toHaveLength(a.length + b.length);
        for (const s of full) expect(s >= 0 && s <= 1).toBe(true);
        expect(full.slice(0, a.length)).toEqual(stressCurve(a, readout));
      }),
    );
  });

  it("isStressful(max) is monotonic: raising any score never turns block into allow", () => {
    fc.assert(
      fc.property(fc.array(fc.double({ min: 0, max: 1, noNaN: true }), { minLength: 1, maxLength: 60 }), fc.nat(59), fc.double({ min: 0, max: 1, noNaN: true }), (curve, i, bump) => {
        const rule = { windowSec: 10, hz: 4, threshold: 0.6, aggregate: "max" as const };
        const raised = curve.map((v, j) => (j === i % curve.length ? Math.min(1, v + bump) : v));
        if (isStressful(curve, rule)) expect(isStressful(raised, rule)).toBe(true);
      }),
    );
  });
});
