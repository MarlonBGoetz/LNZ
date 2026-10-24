import type { Verdict } from "../classifier/types";
import { DEFAULT_CONFIG, loadConfig, saveConfig } from "../shared/config";
import type { HttpClassifyResponse, RuntimeRequest } from "../shared/runtime";

const VERDICTS = new Set<Verdict>(["allow", "block", "unknown"]);

/** Accepts `{ "<id>": "allow" | "block" | "unknown" }` or `{ verdicts: {...} }`; drops anything else. */
const sanitize = (body: unknown): Record<string, Verdict> => {
  const src = (body as { verdicts?: unknown })?.verdicts ?? body;
  const out: Record<string, Verdict> = {};
  if (src && typeof src === "object") for (const [k, v] of Object.entries(src)) if (VERDICTS.has(v as Verdict)) out[k] = v as Verdict;
  return out;
};

const httpClassify = async (url: string, items: unknown[], timeoutMs: number): Promise<HttpClassifyResponse> => {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ items }),
      signal: AbortSignal.timeout(timeoutMs),
      credentials: "omit",
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    return { ok: true, verdicts: sanitize(await res.json()) };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
};

chrome.runtime.onMessage.addListener((msg: RuntimeRequest, sender, reply) => {
  if (sender.id !== chrome.runtime.id) return false;
  if (msg.kind === "httpClassify") {
    void httpClassify(msg.url, msg.items, msg.timeoutMs).then(reply);
    return true;
  }
  return false;
});

chrome.runtime.onInstalled.addListener(async () => {
  const cur = await loadConfig();
  await saveConfig({ ...DEFAULT_CONFIG, ...cur });
});

chrome.commands.onCommand.addListener(async (cmd) => {
  const cfg = await loadConfig();
  if (cmd === "toggle-autoscroll") await saveConfig({ autoScroll: !cfg.autoScroll });
  if (cmd === "toggle-overlay") await saveConfig({ overlay: !cfg.overlay });
});
