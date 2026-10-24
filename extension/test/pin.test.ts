import { describe, expect, it } from 'vitest';
import { createPinVerifier, isValidPin, nextThrottle, verifyPin } from '../src/lib/pin';
import { parseOutput } from '../src/background/providers';

describe('PIN verifier', () => {
  it('accepts only 4–6 digits', () => {
    expect(isValidPin('1234')).toBe(true);
    expect(isValidPin('123456')).toBe(true);
    expect(isValidPin('123')).toBe(false);
    expect(isValidPin('1234567')).toBe(false);
    expect(isValidPin('12a4')).toBe(false);
  });

  it('stores a salted hash, not the PIN, and verifies', async () => {
    const v = await createPinVerifier('4821', 1000);
    expect(JSON.stringify(v)).not.toContain('4821');
    expect(v.salt).not.toEqual((await createPinVerifier('4821', 1000)).salt);
    expect(await verifyPin('4821', v)).toBe(true);
    expect(await verifyPin('4822', v)).toBe(false);
    expect(await verifyPin('', v)).toBe(false);
  });

  it('throttles after 3 failures with doubling delay', () => {
    let t = { failures: 0, lockedUntil: 0 };
    t = nextThrottle(t, 0);
    t = nextThrottle(t, 0);
    expect(t.lockedUntil).toBe(0);
    t = nextThrottle(t, 0);
    expect(t.lockedUntil).toBe(30_000);
    t = nextThrottle(t, 0);
    expect(t.lockedUntil).toBe(60_000);
  });
});

describe('HTTP provider payload validation', () => {
  it('rejects missing or out-of-range scores instead of inventing one', () => {
    expect(() => parseOutput('calm', {})).toThrow();
    expect(() => parseOutput('learn', { score: 1.4 })).toThrow();
    expect(parseOutput('calm', { score: 0.3 })).toEqual({ kind: 'score', score: 0.3, timeline: undefined, regions: undefined });
  });
  it('requires categorical labels for shield', () => {
    expect(() => parseOutput('shield', { score: 0.2 })).toThrow();
    expect(parseOutput('shield', { flagged: ['S1'] })).toEqual({ kind: 'categories', flagged: ['S1'] });
  });
});
