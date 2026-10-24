export type Mode = "observe" | "skip";
export type FailMode = "failOpen" | "failClosed";
export type ClassifierKind = "stub" | "keyword" | "stressText" | "tribe" | "mockStress" | "http";

export type Config = {
  enabled: boolean;
  mode: Mode;
  /** Text-only pre-render removal. Only for metadata classifiers. */
  drop: boolean;
  classifier: ClassifierKind;
  keywordPattern: string;
  /** TRIBE: block when final stress ≥ this. 0.67 = best balanced accuracy on the demo set. */
  tribeThreshold: number;
  /** TRIBE: seconds of each video analyzed (training used 10 s). */
  tribeSeconds: number;
  httpUrl: string;
  /** 0 = use the classifier's own default. */
  classifierTimeoutMs: number;
  failMode: FailMode;
  /** Max time a pending video is held (paused + covered). */
  holdTimeoutMs: number;
  autoScroll: boolean;
  /** 0 = advance only when the video ends. */
  autoScrollSec: number;
  overlay: boolean;
  queueSize: number;
};

export const DEFAULT_CONFIG: Config = {
  enabled: true,
  mode: "skip",
  drop: false,
  classifier: "stub",
  keywordPattern: "#test",
  tribeThreshold: 0.67,
  tribeSeconds: 10,
  httpUrl: "",
  classifierTimeoutMs: 0,
  failMode: "failClosed",
  holdTimeoutMs: 3000,
  autoScroll: false,
  autoScrollSec: 0,
  overlay: false,
  queueSize: 8,
};

const KEY = "config";

export const loadConfig = async (): Promise<Config> => {
  const got = await chrome.storage.local.get(KEY);
  return { ...DEFAULT_CONFIG, ...(got[KEY] as Partial<Config> | undefined) };
};

export const saveConfig = async (patch: Partial<Config>): Promise<Config> => {
  const next = { ...(await loadConfig()), ...patch };
  await chrome.storage.local.set({ [KEY]: next });
  return next;
};

export const onConfigChange = (fn: (c: Config) => void): void => {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes[KEY]) fn({ ...DEFAULT_CONFIG, ...(changes[KEY].newValue as Partial<Config>) });
  });
};
