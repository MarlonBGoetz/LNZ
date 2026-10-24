import type { MediaClip } from "../classifier/types";
import type { MediaKind } from "../platforms/tiktok/media";

type Chunk = { start: number; bytes: Uint8Array; total: number | null; complete: boolean };
type Track = { chunks: Chunk[]; total: number | null };

/** Minimum contiguous prefix before a partial (split) track counts as usable. */
const MIN_PREFIX = 256 * 1024;
/** Single-file MP4s put `moov` first, so a prefix this large is decodable when TikTok aborts the download. */
const MIN_MUXED_PREFIX = 1024 * 1024;

const contiguous = (t: Track): { bytes: Uint8Array[]; length: number; full: boolean } => {
  const sorted = [...t.chunks].sort((a, b) => a.start - b.start);
  const parts: Uint8Array[] = [];
  let end = 0;
  for (const c of sorted) {
    if (c.start > end) break;
    const skip = end - c.start;
    if (skip >= c.bytes.byteLength) continue;
    parts.push(skip ? c.bytes.subarray(skip) : c.bytes);
    end = c.start + c.bytes.byteLength;
  }
  const full = t.total !== null ? end >= t.total : sorted.some((c) => c.complete && c.start === 0);
  return { bytes: parts, length: end, full };
};

/** Assembles media chunks per item into a MediaClip once enough has arrived. */
export class MediaStore {
  private readonly tracks = new Map<string, Partial<Record<MediaKind, Track>>>();

  add(id: string, kind: MediaKind, chunk: Chunk): void {
    const byKind = this.tracks.get(id) ?? {};
    const t = (byKind[kind] ??= { chunks: [], total: null });
    t.chunks.push(chunk);
    t.total ??= chunk.total;
    this.tracks.set(id, byKind);
  }

  /** muxed: a video track that is a complete single file and no separate audio. split: video+audio prefixes. */
  clip(id: string): MediaClip | null {
    const byKind = this.tracks.get(id);
    if (!byKind?.video) return null;
    const v = contiguous(byKind.video);
    const blob = (parts: Uint8Array[]) => new Blob(parts as BlobPart[], { type: "video/mp4" });
    if (!byKind.audio) {
      if (v.full) return { layout: "muxed", video: blob(v.bytes), audio: null, complete: true };
      return v.length >= MIN_MUXED_PREFIX ? { layout: "muxed", video: blob(v.bytes), audio: null, complete: false } : null;
    }
    const a = contiguous(byKind.audio);
    const ready = (x: { length: number; full: boolean }) => x.full || x.length >= MIN_PREFIX;
    if (!ready(v) || !(a.full || a.length > 1024)) return null;
    return { layout: "split", video: blob(v.bytes), audio: blob(a.bytes), complete: v.full && a.full };
  }

  status(id: string): "none" | "partial" | "ready" {
    if (this.clip(id)) return "ready";
    return this.tracks.has(id) ? "partial" : "none";
  }

  delete(id: string): void {
    this.tracks.delete(id);
  }
}
