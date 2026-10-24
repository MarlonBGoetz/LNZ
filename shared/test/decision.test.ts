import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG, decide, demoOutput, normalizeConfig, type ClassifierResult, type FilterConfig } from '@lnz/shared';

const filters = (patch: Partial<FilterConfig> = {}): FilterConfig => ({ ...structuredClone(DEFAULT_CONFIG.filters), ...patch });

const score = (filterId: 'calm' | 'learn', s: number, videoId = 'v1'): ClassifierResult => ({
  filterId, videoId, state: 'ready', output: { kind: 'score', score: s }, provider: 'test', isDemo: false, receivedAt: 0,
});
const shield = (flagged: string[], videoId = 'v1'): ClassifierResult => ({
  filterId: 'shield', videoId, state: 'ready', output: { kind: 'categories', flagged }, provider: 'test', isDemo: false, receivedAt: 0,
});

describe('decide', () => {
  const all = filters({
    calm: { enabled: true, threshold: 0.6 },
    learn: { enabled: true, minScore: 0.5 },
    shield: { enabled: true, categories: ['S10'] },
  });

  it('keeps when every enabled filter passes', () => {
    const d = decide('v1', all, { calm: score('calm', 0.22), learn: score('learn', 0.81), shield: shield([]) });
    expect(d.verdict).toBe('keep');
    expect(d.rejectedBy).toEqual([]);
  });

  it('one confident rejection is enough to skip, even while others are pending', () => {
    const d = decide('v1', all, { calm: score('calm', 0.9) });
    expect(d.verdict).toBe('skip');
    expect(d.rejectedBy).toEqual(['calm']);
  });

  it('rejects low educational value and selected shield categories', () => {
    expect(decide('v1', all, { calm: score('calm', 0.1), learn: score('learn', 0.2), shield: shield([]) }).rejectedBy).toEqual(['learn']);
    expect(decide('v1', all, { calm: score('calm', 0.1), learn: score('learn', 0.9), shield: shield(['S10']) }).rejectedBy).toEqual(['shield']);
  });

  it('ignores flags outside the selected categories', () => {
    expect(decide('v1', all, { calm: score('calm', 0.1), learn: score('learn', 0.9), shield: shield(['S2']) }).verdict).toBe('keep');
  });

  it('never treats unavailable as a pass', () => {
    const unavailable: ClassifierResult = { filterId: 'learn', videoId: 'v1', state: 'unavailable', provider: 'x', isDemo: false, receivedAt: 0 };
    const d = decide('v1', all, { calm: score('calm', 0.1), learn: unavailable, shield: shield([]) });
    expect(d.verdict).toBe('keep-unverified');
    expect(d.rules.learn.verdict).toBe('unknown');
  });

  it('ignores stale results from another video', () => {
    const d = decide('v2', all, { calm: score('calm', 0.95, 'v1') });
    expect(d.verdict).toBe('pending');
  });

  it('disabled filters do not affect the decision', () => {
    const onlyCalm = filters({ calm: { enabled: true, threshold: 0.6 }, learn: { enabled: false, minScore: 0.9 }, shield: { enabled: false, categories: [] } });
    expect(decide('v1', onlyCalm, { calm: score('calm', 0.3), learn: score('learn', 0.0) }).verdict).toBe('keep');
  });
});

describe('demo provider', () => {
  it('is deterministic and in range', () => {
    const a = demoOutput('calm', 'abc');
    expect(a).toEqual(demoOutput('calm', 'abc'));
    if (a.kind !== 'score') throw new Error('expected score');
    expect(a.score).toBeGreaterThanOrEqual(0);
    expect(a.score).toBeLessThanOrEqual(1);
    expect(a.timeline?.length).toBeGreaterThan(0);
  });
});

describe('normalizeConfig', () => {
  it('fills defaults and clamps thresholds', () => {
    const c = normalizeConfig({ filters: { calm: { enabled: false, threshold: 7 } } });
    expect(c.filters.calm).toEqual({ enabled: false, threshold: 1 });
    expect(c.filters.learn).toEqual(DEFAULT_CONFIG.filters.learn);
    expect(c.providers.mode).toBe('demo');
  });
});
