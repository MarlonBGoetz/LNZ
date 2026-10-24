import { loadConfig, onConfigChange, saveConfig, type Config } from "../shared/config";

type StoredItem = { id: string; caption: string; author: { handle: string }; verdict: { verdict: string; reason?: string }; why: string | null; score: number | null; shown?: boolean; skipped?: boolean };

const form = document.getElementById("cfg") as HTMLFormElement;
const field = (name: keyof Config) => document.querySelector<HTMLInputElement | HTMLSelectElement>(`[name="${name}"]`);

/** One-click setups. Video model: hold up to 6 s for the verdict, and play (not skip) if the model is late. */
const PRESETS: Record<string, Partial<Config>> = {
  video: { enabled: true, mode: "skip", classifier: "tribe", tribeThreshold: 0.72, tribeSeconds: 10, drop: false, failMode: "failOpen", holdTimeoutMs: 6000, overlay: true, autoScroll: false },
  text: { enabled: true, mode: "skip", classifier: "stressText", drop: true, failMode: "failClosed", holdTimeoutMs: 3000, overlay: true, autoScroll: false },
  observe: { enabled: true, mode: "observe", drop: false, overlay: true },
};

const presetOf = (c: Config): string | null => {
  for (const [name, p] of Object.entries(PRESETS)) if (Object.entries(p).every(([k, v]) => c[k as keyof Config] === v)) return name;
  return null;
};

const LABEL: Record<string, string> = { tribe: "TRIBE video model", stressText: "stress text model", keyword: "keyword", mockStress: "mock model", http: "HTTP endpoint", stub: "allow all" };

const fill = (cfg: Config) => {
  for (const [k, v] of Object.entries(cfg) as [keyof Config, unknown][]) {
    const el = field(k);
    if (!el) continue;
    if (el instanceof HTMLInputElement && el.type === "checkbox") el.checked = Boolean(v);
    else el.value = String(v);
  }
  for (const el of form.querySelectorAll<HTMLElement>("[data-for]")) el.hidden = el.dataset.for !== cfg.classifier;
  (field("drop") as HTMLInputElement).disabled = cfg.classifier === "mockStress" || cfg.classifier === "tribe";
  const p = presetOf(cfg);
  document.querySelectorAll<HTMLButtonElement>("[data-preset]").forEach((b) => b.classList.toggle("on", b.dataset.preset === p));
  document.getElementById("active")!.textContent = cfg.enabled
    ? `${cfg.mode === "skip" ? (cfg.drop ? "Dropping + skipping" : "Skipping") : "Observing"} with ${LABEL[cfg.classifier] ?? cfg.classifier}${cfg.classifier === "tribe" ? ` · threshold ${cfg.tribeThreshold}` : ""}`
    : "Disabled: TikTok behaves normally.";
};

const read = (el: HTMLInputElement | HTMLSelectElement): unknown => {
  if (el instanceof HTMLInputElement && el.type === "checkbox") return el.checked;
  if (el instanceof HTMLInputElement && el.type === "number") {
    const n = Math.max(0, Number(el.value) || 0);
    return el.max ? Math.min(Number(el.max), n) : n;
  }
  return el.value;
};

/** Optional host permission is requested only for the configured classifier origin. */
const ensureHttpPermission = async (url: string): Promise<boolean> => {
  try {
    const origin = `${new URL(url).origin}/*`;
    return (await chrome.permissions.contains({ origins: [origin] })) || (await chrome.permissions.request({ origins: [origin] }));
  } catch {
    return false;
  }
};

document.addEventListener("change", async (e) => {
  const el = e.target as HTMLInputElement | HTMLSelectElement;
  const key = el.name as keyof Config;
  if (!key) return;
  if (key === "httpUrl" && el.value && !(await ensureHttpPermission(el.value))) return;
  fill(await saveConfig({ [key]: read(el) } as Partial<Config>));
});

document.querySelectorAll<HTMLButtonElement>("[data-preset]").forEach((b) =>
  b.addEventListener("click", async () => fill(await saveConfig(PRESETS[b.dataset.preset!]!))),
);

const el = (tag: string, cls = "", text = "") => Object.assign(document.createElement(tag), { className: cls, textContent: text });

const render = async () => {
  const { stats = {}, items = [] } = (await chrome.storage.local.get(["stats", "items"])) as { stats?: Record<string, number>; items?: StoredItem[] };
  const tiles = document.getElementById("tiles")!;
  tiles.replaceChildren(
    ...[["captured", stats.captured], ["stressful", stats.blocked], ["skipped", stats.skipped], ["dropped", stats.dropped]].map(([k, v]) => {
      const t = el("div", "tile");
      t.append(el("b", "", String(v ?? 0)), el("span", "", String(k)));
      return t;
    }),
  );
  const done = items.filter((i) => i.verdict.verdict !== "pending").slice(-15).reverse();
  const list = document.getElementById("recent")!;
  if (!done.length) return;
  list.replaceChildren(
    ...done.map((i) => {
      const li = el("li");
      const v = i.verdict.verdict;
      const body = el("div");
      body.append(el("div", "cap", i.caption || `@${i.author.handle}`), el("div", "why", i.why ?? (i.verdict.reason ? `reason: ${i.verdict.reason}` : "")));
      if (i.score !== null && i.score !== undefined) {
        const bar = el("div", "bar");
        const fillEl = el("i");
        fillEl.style.width = `${Math.round(i.score * 100)}%`;
        fillEl.style.background = v === "block" ? "var(--stress)" : "var(--calm)";
        bar.append(fillEl);
        body.append(bar);
      }
      li.append(el("span", `pill ${v}`, v === "block" ? (i.skipped ? "skipped" : "stress") : "calm"), body);
      return li;
    }),
  );
};

document.getElementById("refresh")!.addEventListener("click", () => void render());
document.getElementById("export")!.addEventListener("click", async () => {
  const { items = [] } = await chrome.storage.local.get("items");
  const url = URL.createObjectURL(new Blob([JSON.stringify(items, null, 2)], { type: "application/json" }));
  Object.assign(document.createElement("a"), { href: url, download: `lnz-feed-${Date.now()}.json` }).click();
});

// Dev: opening popup.html?devReload reloads the unpacked extension after a rebuild.
if (new URLSearchParams(location.search).has("devReload")) chrome.runtime.reload();

void loadConfig().then(fill);
onConfigChange(fill);
void render();
setInterval(() => void render(), 2000);
