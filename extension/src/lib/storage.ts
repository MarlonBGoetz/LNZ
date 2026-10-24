import { normalizeConfig, type LnzConfig } from '@lnz/shared';
import type { PinVerifier, Throttle } from './pin';

/**
 * Persistent state lives in chrome.storage.local (survives reloads and restarts).
 * The unlocked flag lives in chrome.storage.session, which content scripts cannot
 * read or write by default, and which resets to LOCKED when the browser restarts.
 */
const K = {
  config: 'lnz:config',
  pin: 'lnz:pin',
  throttle: 'lnz:throttle',
  unlocked: 'lnz:unlocked',
} as const;

export async function readConfig(): Promise<LnzConfig> {
  const r = await chrome.storage.local.get(K.config);
  return normalizeConfig(r[K.config]);
}

export async function writeConfig(c: LnzConfig): Promise<void> {
  await chrome.storage.local.set({ [K.config]: normalizeConfig(c) });
}

export async function readPin(): Promise<PinVerifier | null> {
  const r = await chrome.storage.local.get(K.pin);
  return (r[K.pin] as PinVerifier | undefined) ?? null;
}

export async function writePin(v: PinVerifier): Promise<void> {
  await chrome.storage.local.set({ [K.pin]: v });
}

export async function readThrottle(): Promise<Throttle> {
  const r = await chrome.storage.local.get(K.throttle);
  return (r[K.throttle] as Throttle | undefined) ?? { failures: 0, lockedUntil: 0 };
}

export async function writeThrottle(t: Throttle): Promise<void> {
  await chrome.storage.local.set({ [K.throttle]: t });
}

export async function readUnlocked(): Promise<boolean> {
  const r = await chrome.storage.session.get(K.unlocked);
  return r[K.unlocked] === true;
}

export async function writeUnlocked(v: boolean): Promise<void> {
  await chrome.storage.session.set({ [K.unlocked]: v });
}

export const STORAGE_KEYS = K;
