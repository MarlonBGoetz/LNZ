import { describe, expect, it } from "vitest";
import { FeedStore } from "../src/bridge/feed-store";
import { MediaStore } from "../src/bridge/media-store";
import { removeBlocked } from "../src/platforms/tiktok/drop";
import { mediaPathsOf } from "../src/platforms/tiktok/media";
import { normalizeTikTokItem } from "../src/platforms/tiktok/parser";

const rawItem = (id: string) => ({
  id,
  author: { uniqueId: "u" },
  video: {
    playAddr: `https://v16.tiktok.com/video/tos/a/${id}-play/?x=1`,
    cover: `https://p16.tiktok.com/video/cover-${id}.jpg`,
    bitrateInfo: [{ PlayAddr: { UrlList: [`https://v16.tiktok.com/video/tos/a/${id}-hd/`] } }],
    bitrateAudioInfo: [{ UrlList: { MainUrl: `https://v16.tiktok.com/video/tos/a/${id}-aud/`, BackupUrl: `https://v19.tiktok.com/video/tos/a/${id}-aud2/` } }],
  },
});

describe("mediaPathsOf", () => {
  it("collects video and audio paths, skips covers", () => {
    const paths = mediaPathsOf(rawItem("1"));
    expect(paths).toContainEqual({ path: "/video/tos/a/1-play/", kind: "video" });
    expect(paths).toContainEqual({ path: "/video/tos/a/1-hd/", kind: "video" });
    expect(paths).toContainEqual({ path: "/video/tos/a/1-aud/", kind: "audio" });
    expect(paths).toContainEqual({ path: "/video/tos/a/1-aud2/", kind: "audio" });
    expect(paths.some((p) => p.path.includes("cover"))).toBe(false);
  });
  it("tolerates junk", () => {
    expect(mediaPathsOf(null)).toEqual([]);
    expect(mediaPathsOf({ video: { playAddr: "not a url", bitrateInfo: [null, 3] } })).toEqual([]);
  });
});

describe("FeedStore", () => {
  const ctx = { capturedAt: 0 };
  it("dedupes, keeps order, and maps media paths", () => {
    const s = new FeedStore();
    const a = normalizeTikTokItem(rawItem("1"), 0, ctx);
    const b = normalizeTikTokItem(rawItem("2"), 1, ctx);
    expect(s.add([a, b])).toHaveLength(2);
    expect(s.add([b])).toHaveLength(0);
    expect(s.order).toEqual(["1", "2"]);
    expect(s.byPath("/video/tos/a/2-aud/")).toEqual({ id: "2", kind: "audio" });
    expect(s.ahead("1", 5)).toEqual(["2"]);
    expect(s.ahead("1", 5, (id) => id !== "2")).toEqual([]);
    expect(s.ahead(null, 1)).toEqual(["2"]);
  });
});

describe("MediaStore", () => {
  const bytes = (n: number, fill = 1) => new Uint8Array(n).fill(fill);

  it("muxed: ready only once the single file completes", () => {
    const m = new MediaStore();
    m.add("1", "video", { start: 0, total: null, complete: false, bytes: bytes(10) });
    expect(m.clip("1")).toBeNull();
    m.add("1", "video", { start: 0, total: null, complete: true, bytes: bytes(20) });
    expect(m.clip("1")).toMatchObject({ layout: "muxed", complete: true, audio: null });
  });

  it("muxed: accepts a 1 MB prefix when the download was aborted", () => {
    const m = new MediaStore();
    m.add("1", "video", { start: 0, total: null, complete: false, bytes: bytes(1024 * 1024) });
    expect(m.clip("1")).toMatchObject({ layout: "muxed", complete: false });
  });

  it("split: assembles contiguous ranges and pairs audio", async () => {
    const m = new MediaStore();
    const total = 400 * 1024;
    m.add("1", "video", { start: 0, total, complete: true, bytes: bytes(100, 7) });
    m.add("1", "video", { start: 100, total, complete: false, bytes: bytes(300 * 1024, 8) });
    expect(m.clip("1")).toBeNull();
    m.add("1", "audio", { start: 0, total: 5000, complete: true, bytes: bytes(5000) });
    const clip = m.clip("1")!;
    expect(clip.layout).toBe("split");
    expect(clip.complete).toBe(false);
    expect(clip.video.size).toBe(100 + 300 * 1024);
    const head = new Uint8Array(await clip.video.slice(0, 101).arrayBuffer());
    expect(head[0]).toBe(7);
    expect(head[100]).toBe(8);
  });

  it("ignores data after a gap", () => {
    const m = new MediaStore();
    m.add("1", "video", { start: 0, total: 1000, complete: true, bytes: bytes(10) });
    m.add("1", "video", { start: 500, total: 1000, complete: true, bytes: bytes(500) });
    m.add("1", "audio", { start: 0, total: 10, complete: true, bytes: bytes(10) });
    expect(m.clip("1")).toBeNull();
    expect(m.status("1")).toBe("partial");
  });
});

describe("removeBlocked", () => {
  const payload = { statusCode: 0, itemList: [{ id: "1" }, { id: "2" }, { id: "3" }], extra: { itemList: "not-an-array" } };

  it("removes blocked ids from itemList, wherever it is", () => {
    const { json, removed } = removeBlocked({ wrap: payload }, new Set(["2"]));
    expect((json as { wrap: typeof payload }).wrap.itemList.map((i) => i.id)).toEqual(["1", "3"]);
    expect(removed).toEqual(["2"]);
  });

  it("never empties a batch", () => {
    const { json } = removeBlocked(payload, new Set(["1", "2", "3"]));
    expect((json as typeof payload).itemList).toHaveLength(1);
  });

  it("leaves other fields intact and does not mutate input", () => {
    const { json } = removeBlocked(payload, new Set(["1"]));
    expect((json as typeof payload).extra).toEqual(payload.extra);
    expect(payload.itemList).toHaveLength(3);
  });
});
