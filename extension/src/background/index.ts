import {
  ANALYTICS_EVENTS_PATH,
  normalizeConfig,
  type AnalyticsEvent,
  type ClassifierProvider,
  type ClassifierResult,
  type FilterId,
  type LnzConfig,
  type ProviderAvailability,
} from '@lnz/shared';
import { ANALYSIS_PORT, type LnzState, type PortIn, type PortOut, type Request, type Response } from '../lib/messages';
import { createPinVerifier, isValidPin, nextThrottle, verifyPin } from '../lib/pin';
import {
  readConfig,
  readPin,
  readThrottle,
  readUnlocked,
  writeConfig,
  writePin,
  writeThrottle,
  writeUnlocked,
} from '../lib/storage';
import { buildProviders } from './providers';
import './toolbar';
import { classifierKey } from '../lib/analysis';
import { createSerialQueue } from '../lib/serialQueue';

/**
 * LNZ background service worker.
 * - Single authority for config writes: changes require an unlocked session (PIN).
 * - Runs classifier providers and streams results to the overlay over a port.
 * - Mirrors events to the local analytics dashboard (best-effort).
 */

const FILTER_IDS: FilterId[] = ['calm', 'learn', 'shield'];
let providers: ClassifierProvider[] = [];
let providerKey = '';
let availability: Record<FilterId, ProviderAvailability> = { calm: 'unavailable', learn: 'unavailable', shield: 'unavailable' };
let analyticsConnected = false;
const ports = new Set<chrome.runtime.Port>();

async function ensureProviders(config: LnzConfig): Promise<ClassifierProvider[]> {
  const key = classifierKey(config);
  let selected = providers;
  if (key !== providerKey) {
    selected = buildProviders(config);
    providers = selected;
    providerKey = key;
    await refreshAvailability(selected);
  }
  return selected;
}

async function refreshAvailability(selected = providers): Promise<void> {
  const entries = await Promise.all(selected.map(async (p) => [p.filterId, await p.availability()] as const));
  if (selected === providers) availability = Object.fromEntries(entries) as Record<FilterId, ProviderAvailability>;
}

async function getState(): Promise<LnzState> {
  const [config, pin, unlocked, throttle] = await Promise.all([readConfig(), readPin(), readUnlocked(), readThrottle()]);
  await ensureProviders(config);
  return { config, hasPin: pin !== null, unlocked, throttle, availability, analyticsConnected };
}

async function postAnalytics(ev: AnalyticsEvent): Promise<void> {
  const { analyticsUrl } = await readConfig();
  try {
    const res = await fetch(`${analyticsUrl.replace(/\/$/, '')}${ANALYTICS_EVENTS_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(ev),
      signal: AbortSignal.timeout(1500),
    });
    analyticsConnected = res.ok;
  } catch {
    analyticsConnected = false;
  }
}

async function publishConfig(): Promise<void> {
  const s = await getState();
  void postAnalytics({
    type: 'config',
    at: Date.now(),
    config: {
      active: s.config.active,
      locked: !s.unlocked,
      autoSkip: s.config.autoSkip,
      filters: s.config.filters,
      providerMode: s.config.providers.mode,
    },
  });
  const msg: PortOut = { type: 'state', state: s };
  for (const p of ports) p.postMessage(msg);
}

async function handle(req: Request): Promise<Response> {
  switch (req.type) {
    case 'getState':
      return { ok: true, state: await getState() };

    case 'setupPin': {
      if (await readPin()) return { ok: false, error: 'A PIN already exists', state: await getState() };
      if (!isValidPin(req.pin)) return { ok: false, error: 'PIN must be 4–6 digits' };
      await writePin(await createPinVerifier(req.pin));
      await writeConfig(normalizeConfig(req.config));
      await writeUnlocked(false);
      await publishConfig();
      return { ok: true, state: await getState() };
    }

    case 'unlock': {
      const now = Date.now();
      const t = await readThrottle();
      if (t.lockedUntil > now) return { ok: false, error: 'Too many attempts. Try again shortly.', state: await getState() };
      const pin = await readPin();
      if (!pin) return { ok: false, error: 'No PIN set', state: await getState() };
      if (await verifyPin(req.pin, pin)) {
        await writeThrottle({ failures: 0, lockedUntil: 0 });
        await writeUnlocked(true);
        await publishConfig();
        return { ok: true, state: await getState() };
      }
      await writeThrottle(nextThrottle(t, now));
      return { ok: false, error: 'Incorrect PIN', state: await getState() };
    }

    case 'saveAndLock': {
      if (!(await readUnlocked())) return { ok: false, error: 'Locked', state: await getState() };
      await writeConfig(normalizeConfig(req.config));
      await writeUnlocked(false);
      await publishConfig();
      return { ok: true, state: await getState() };
    }

    case 'cancelEdit': {
      await writeUnlocked(false);
      await publishConfig();
      return { ok: true, state: await getState() };
    }

    case 'setActive': {
      // Turning protection ON is always allowed. Turning it OFF needs an unlocked session.
      if (!req.active && !(await readUnlocked())) return { ok: false, error: 'Locked', state: await getState() };
      const c = await readConfig();
      await writeConfig({ ...c, active: req.active });
      await publishConfig();
      return { ok: true, state: await getState() };
    }
  }
}

const serialize = createSerialQueue();

chrome.runtime.onMessage.addListener((req: Request, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  if (!req || !['getState', 'setupPin', 'unlock', 'saveAndLock', 'cancelEdit', 'setActive'].includes(req.type)) return false;
  serialize(() => handle(req)).then(sendResponse, (e) => sendResponse({ ok: false, error: String(e) } satisfies Response));
  return true;
});

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== ANALYSIS_PORT || port.sender?.id !== chrome.runtime.id) return;
  ports.add(port);
  let controller: AbortController | null = null;

  port.onMessage.addListener(async (msg: PortIn) => {
    if (msg.type === 'decision') return void postAnalytics({ type: 'decision', decision: msg.decision, at: Date.now() });
    if (msg.type === 'skip') return void postAnalytics({ type: 'skip', videoId: msg.videoId, reason: msg.reason, at: Date.now() });
    if (msg.type === 'cancelAnalysis') {
      controller?.abort();
      controller = null;
      return;
    }
    if (msg.type !== 'analyze') return;

    controller?.abort();
    const ctrl = new AbortController();
    controller = ctrl;
    const video = msg.video;
    const config = await readConfig();
    if (ctrl.signal.aborted || !config.active || msg.providerKey !== classifierKey(config)) return;
    const list = await ensureProviders(config);
    if (ctrl.signal.aborted) return;
    void postAnalytics({ type: 'video', video, at: Date.now() });

    const emit = (result: ClassifierResult) => {
      if (ctrl.signal.aborted) return; // stale: a newer video is active
      try {
        port.postMessage({ type: 'result', result, requestId: msg.requestId, providerKey: msg.providerKey } satisfies PortOut);
      } catch {
        /* port closed */
      }
      void postAnalytics({ type: 'result', result, at: Date.now() });
    };

    // Analyze all three, independent of which filters are enabled, so the dashboard shows every score.
    await Promise.all(
      FILTER_IDS.map(async (filterId) => {
        const p = list.find((x) => x.filterId === filterId);
        const base = { filterId, videoId: video.videoId, provider: p?.id ?? 'none', isDemo: p?.isDemo ?? false, model: p?.model };
        if (!p) return emit({ ...base, state: 'unavailable', receivedAt: Date.now() });
        emit({ ...base, state: 'analyzing', receivedAt: Date.now() });
        const t0 = performance.now();
        try {
          const output = await p.classify(video, ctrl.signal);
          if (ctrl.signal.aborted) return;
          if (list === providers) availability[filterId] = 'connected';
          emit({ ...base, model: p.model, state: 'ready', output, latencyMs: Math.round(performance.now() - t0), receivedAt: Date.now() });
        } catch (e) {
          if (ctrl.signal.aborted) return;
          const network = e instanceof TypeError;
          if (network && list === providers) availability[filterId] = 'unavailable';
          emit({ ...base, state: network ? 'unavailable' : 'error', error: e instanceof Error ? e.message : String(e), receivedAt: Date.now() });
        }
      }),
    );
  });

  port.onDisconnect.addListener(() => {
    controller?.abort();
    ports.delete(port);
  });
});

chrome.runtime.onInstalled.addListener(() => {
  void postAnalytics({ type: 'hello', source: 'lnz-extension', at: Date.now() });
});

// Re-check provider health periodically while the worker is alive.
setInterval(() => {
  if (providers.length) void refreshAvailability();
}, 15_000);
