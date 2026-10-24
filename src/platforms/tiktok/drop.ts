import { isObj } from "../../shared/json";

/**
 * Removes blocked ids from every `itemList` array found in the payload. Keeps at least one item per list
 * so TikTok never receives an empty batch (an empty batch makes it fetch again immediately).
 */
export const removeBlocked = (json: unknown, blockIds: ReadonlySet<string>): { json: unknown; removed: string[] } => {
  const removed: string[] = [];
  const walk = (node: unknown, depth: number): unknown => {
    if (depth > 8 || typeof node !== "object" || node === null) return node;
    if (Array.isArray(node)) return node.map((v) => walk(v, depth + 1));
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node)) {
      if (k === "itemList" && Array.isArray(v)) {
        const kept = v.filter((it) => !(isObj(it) && typeof it.id === "string" && blockIds.has(it.id)));
        const final = kept.length > 0 ? kept : v.slice(0, 1);
        for (const it of v) if (!final.includes(it) && isObj(it)) removed.push(String(it.id));
        out[k] = final;
      } else out[k] = walk(v, depth + 1);
    }
    return out;
  };
  return { json: walk(json, 0), removed };
};
