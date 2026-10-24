/**
 * PIN verifier using Web Crypto PBKDF2-SHA256. Only a salted, slow-derived
 * verifier is stored — never the raw PIN.
 *
 * Note: a 4–6 digit PIN has at most 10^6 values, so this is configuration
 * friction for self-control, not protection against someone with access to
 * the extension's storage or the ability to remove the extension.
 */

export interface PinVerifier {
  algo: 'PBKDF2-SHA256';
  iterations: number;
  salt: string; // base64
  hash: string; // base64
}

export const PIN_ITERATIONS = 310_000;
const KEY_BITS = 256;

export function isValidPin(pin: string): boolean {
  return /^\d{4,6}$/.test(pin);
}

function toB64(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

function fromB64(b64: string): Uint8Array {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

async function derive(pin: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(pin), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations }, key, KEY_BITS);
  return new Uint8Array(bits);
}

export async function createPinVerifier(pin: string, iterations = PIN_ITERATIONS): Promise<PinVerifier> {
  if (!isValidPin(pin)) throw new Error('PIN must be 4–6 digits');
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const hash = await derive(pin, salt, iterations);
  return { algo: 'PBKDF2-SHA256', iterations, salt: toB64(salt), hash: toB64(hash) };
}

export async function verifyPin(pin: string, v: PinVerifier): Promise<boolean> {
  if (!isValidPin(pin)) return false;
  const expected = fromB64(v.hash);
  const actual = await derive(pin, fromB64(v.salt), v.iterations);
  if (actual.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < actual.length; i++) diff |= actual[i] ^ expected[i];
  return diff === 0;
}

/** Retry throttling: 3 free attempts, then 30s doubling, capped at 15 min. */
export interface Throttle {
  failures: number;
  lockedUntil: number;
}

export const FREE_ATTEMPTS = 3;

export function nextThrottle(t: Throttle, now: number): Throttle {
  const failures = t.failures + 1;
  if (failures < FREE_ATTEMPTS) return { failures, lockedUntil: 0 };
  const delay = Math.min(30_000 * 2 ** (failures - FREE_ATTEMPTS), 15 * 60_000);
  return { failures, lockedUntil: now + delay };
}
