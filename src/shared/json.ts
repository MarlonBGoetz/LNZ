// Defensive readers for untrusted JSON. Never throw.

export type Obj = Record<string, unknown>;

export const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

export const obj = (v: unknown): Obj => (isObj(v) ? v : {});

export const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

export const str = (v: unknown): string | null => (typeof v === "string" && v !== "" ? v : null);

/** Accepts numbers and numeric strings (TikTok's statsV2 uses strings). */
export const num = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
};

export const first = <T>(...vals: (T | null | undefined)[]): T | null => {
  for (const v of vals) if (v !== null && v !== undefined) return v;
  return null;
};
