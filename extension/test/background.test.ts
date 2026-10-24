import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG, type ClassifierOutput, type ClassifierProvider } from '@lnz/shared';
import { classifierKey } from '../src/lib/analysis';
import type { PortIn, PortOut, Request, Response } from '../src/lib/messages';

const mocks = vi.hoisted(() => ({ verify: vi.fn(), create: vi.fn(), providers: vi.fn() }));
vi.mock('../src/background/toolbar', () => ({}));
vi.mock('../src/background/providers', () => ({ buildProviders: mocks.providers }));
vi.mock('../src/lib/pin', async (original) => ({
  ...await original<typeof import('../src/lib/pin')>(),
  verifyPin: mocks.verify,
  createPinVerifier: mocks.create,
}));

let local: Record<string, unknown>;
let session: Record<string, unknown>;
let onMessage: (req: Request, sender: chrome.runtime.MessageSender, respond: (response: Response) => void) => unknown;
let onConnect: (port: chrome.runtime.Port) => void;

const send = (request: Request) => new Promise<Response>((resolve) => onMessage(request, { id: 'lnz-test' }, resolve));
const flush = async () => { for (let i = 0; i < 30; i += 1) await Promise.resolve(); };

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  local = { 'lnz:config': structuredClone(DEFAULT_CONFIG), 'lnz:pin': { hash: 'existing' } };
  session = {};
  const storage = (data: Record<string, unknown>) => ({
    get: async (key: string) => ({ [key]: data[key] }),
    set: async (patch: Record<string, unknown>) => { Object.assign(data, patch); },
  });
  mocks.verify.mockReset().mockResolvedValue(false);
  mocks.create.mockReset().mockImplementation(async (pin: string) => ({ hash: `verifier-${pin}` }));
  mocks.providers.mockReset().mockReturnValue([]);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
  vi.stubGlobal('chrome', {
    storage: { local: storage(local), session: storage(session) },
    runtime: {
      id: 'lnz-test',
      onMessage: { addListener: (listener: typeof onMessage) => { onMessage = listener; } },
      onConnect: { addListener: (listener: typeof onConnect) => { onConnect = listener; } },
      onInstalled: { addListener: vi.fn() },
    },
  });
  await import('../src/background/index');
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('background PIN/config authority across tabs', () => {
  it('counts simultaneous wrong PINs and throttles remaining attempts', async () => {
    const responses = await Promise.all(Array.from({ length: 6 }, () => send({ type: 'unlock', pin: '9999' })));
    expect(responses.every((response) => !response.ok)).toBe(true);
    expect(mocks.verify).toHaveBeenCalledTimes(3);
    expect(local['lnz:throttle']).toEqual({ failures: 3, lockedUntil: Date.now() + 30_000 });
    expect(session['lnz:unlocked']).not.toBe(true);
  });

  it('allows only one initial PIN setup even when two tabs submit together', async () => {
    delete local['lnz:pin'];
    const [first, second] = await Promise.all([
      send({ type: 'setupPin', pin: '1111', config: DEFAULT_CONFIG }),
      send({ type: 'setupPin', pin: '2222', config: DEFAULT_CONFIG }),
    ]);
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(false);
    expect(mocks.create).toHaveBeenCalledOnce();
    expect(local['lnz:pin']).toEqual({ hash: 'verifier-1111' });
    expect(session['lnz:unlocked']).toBe(false);
  });

  it('rejects a concurrent save after the first save has relocked', async () => {
    session['lnz:unlocked'] = true;
    const [first, second] = await Promise.all([
      send({ type: 'saveAndLock', config: { ...DEFAULT_CONFIG, autoSkip: false } }),
      send({ type: 'saveAndLock', config: { ...DEFAULT_CONFIG, autoSkip: true } }),
    ]);
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(false);
    expect(local['lnz:config']).toMatchObject({ autoSkip: false });
    expect(session['lnz:unlocked']).toBe(false);
  });
});

describe('background analysis generations', () => {
  it('echoes tokens and ignores late same-video work even if a provider ignores abort', async () => {
    const pending: Array<(value: ClassifierOutput) => void> = [];
    const provider: ClassifierProvider = {
      id: 'controlled', filterId: 'calm', isDemo: false,
      availability: async () => 'connected',
      classify: () => new Promise((resolve) => pending.push(resolve)),
    };
    mocks.providers.mockReturnValue([provider]);
    let receive!: (message: PortIn) => Promise<void>;
    const sent: PortOut[] = [];
    onConnect({
      name: 'lnz-analysis', sender: { id: 'lnz-test' },
      onMessage: { addListener: (listener: typeof receive) => { receive = listener; } },
      onDisconnect: { addListener: vi.fn() },
      postMessage: (message: PortOut) => sent.push(message),
    } as unknown as chrome.runtime.Port);
    const base = { type: 'analyze' as const, video: { videoId: 'v1', url: 'https://www.tiktok.com/' }, providerKey: classifierKey(DEFAULT_CONFIG) };
    const old = receive({ ...base, requestId: 1 });
    await flush();
    const current = receive({ ...base, requestId: 2 });
    await flush();
    expect(pending).toHaveLength(2);
    pending[1]({ kind: 'score', score: 0.2 });
    pending[0]({ kind: 'score', score: 0.99 });
    await Promise.all([old, current]);
    const ready = sent.filter((message) => message.type === 'result' && message.result.state === 'ready');
    expect(ready).toHaveLength(1);
    expect(ready[0]).toMatchObject({ requestId: 2, providerKey: base.providerKey, result: { output: { score: 0.2 } } });
  });
});
