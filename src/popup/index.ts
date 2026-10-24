import { loadConfig, saveConfig, type Config } from "../shared/config";

const form = document.getElementById("cfg") as HTMLFormElement;
const field = (name: keyof Config) => form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement;

const showDependent = (cfg: Config) => {
  for (const el of form.querySelectorAll<HTMLElement>("[data-for]")) el.hidden = el.dataset.for !== cfg.classifier;
  (field("drop") as HTMLInputElement).disabled = cfg.classifier === "mockStress" || cfg.classifier === "tribe";
};

const fill = (cfg: Config) => {
  for (const [k, v] of Object.entries(cfg) as [keyof Config, unknown][]) {
    const el = field(k);
    if (!el) continue;
    if (el instanceof HTMLInputElement && el.type === "checkbox") el.checked = Boolean(v);
    else el.value = String(v);
  }
  showDependent(cfg);
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

form.addEventListener("change", async (e) => {
  const el = e.target as HTMLInputElement | HTMLSelectElement;
  const key = el.name as keyof Config;
  if (key === "httpUrl" && el.value && !(await ensureHttpPermission(el.value))) return;
  showDependent(await saveConfig({ [key]: read(el) } as Partial<Config>));
});

const showStats = async () => {
  const { stats } = await chrome.storage.local.get("stats");
  if (stats) (document.getElementById("stats") as HTMLElement).textContent = Object.entries(stats).map(([k, v]) => `${k} ${v}`).join(" · ");
};

document.getElementById("export")!.addEventListener("click", async () => {
  const { items = [] } = await chrome.storage.local.get("items");
  const url = URL.createObjectURL(new Blob([JSON.stringify(items, null, 2)], { type: "application/json" }));
  Object.assign(document.createElement("a"), { href: url, download: `lnz-feed-${Date.now()}.json` }).click();
});

void loadConfig().then(fill);
void showStats();
