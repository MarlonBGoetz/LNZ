import { isObj, type Obj } from "../../shared/json";

export type MediaKind = "video" | "audio";
export type MediaPath = { path: string; kind: MediaKind };

const pathOf = (u: string): string | null => {
  try {
    return new URL(u).pathname;
  } catch {
    return null;
  }
};

/** Every media URL path an item may be downloaded from. Audio tracks live under bitrateAudioInfo. */
export const mediaPathsOf = (raw: unknown): MediaPath[] => {
  const video = isObj(raw) && isObj(raw.video) ? raw.video : null;
  if (!video) return [];
  const out = new Map<string, MediaKind>();
  const walk = (node: unknown, kind: MediaKind, depth: number): void => {
    if (depth > 6) return;
    if (typeof node === "string") {
      if (/^https?:\/\//.test(node)) {
        const p = pathOf(node);
        if (p && p.includes("/video/")) out.set(p, kind);
      }
      return;
    }
    if (Array.isArray(node)) return node.forEach((v) => walk(v, kind, depth + 1));
    if (isObj(node)) for (const [k, v] of Object.entries(node as Obj)) walk(v, k === "bitrateAudioInfo" || kind === "audio" ? "audio" : "video", depth + 1);
  };
  for (const [k, v] of Object.entries(video)) {
    if (k === "cover" || k === "originCover" || k === "dynamicCover" || k === "zoomCover" || k === "subtitleInfos") continue;
    walk(v, k === "bitrateAudioInfo" ? "audio" : "video", 0);
  }
  return [...out].map(([path, kind]) => ({ path, kind }));
};

export const isMediaUrl = (url: string): boolean => /\/video\/tos\//.test(url);
