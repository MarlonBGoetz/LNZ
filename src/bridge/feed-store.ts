import type { FeedItem } from "../shared/feed-item";
import { mediaPathsOf, type MediaKind } from "../platforms/tiktok/media";

/** All items seen this session, in first-seen order, plus a media path → item index. */
export class FeedStore {
  readonly items = new Map<string, FeedItem>();
  readonly order: string[] = [];
  private readonly paths = new Map<string, { id: string; kind: MediaKind }>();

  /** Returns only items not seen before. Repeats refresh their media paths (URLs are re-signed). */
  add(batch: FeedItem[]): FeedItem[] {
    const fresh: FeedItem[] = [];
    for (const it of batch) {
      for (const p of mediaPathsOf(it.raw)) this.paths.set(p.path, { id: it.id, kind: p.kind });
      if (this.items.has(it.id)) continue;
      this.items.set(it.id, it);
      this.order.push(it.id);
      fresh.push(it);
    }
    return fresh;
  }

  byPath(path: string): { id: string; kind: MediaKind } | null {
    return this.paths.get(path) ?? null;
  }

  /** Next n ids after `id` (or the last n if id is unknown) that pass `keep`. */
  ahead(id: string | null, n: number, keep: (id: string) => boolean = () => true): string[] {
    const i = id ? this.order.indexOf(id) : -1;
    const rest = i < 0 ? this.order : this.order.slice(i + 1);
    const kept = rest.filter(keep);
    return i < 0 ? kept.slice(-n) : kept.slice(0, n);
  }
}
