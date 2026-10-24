import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CONFIG,
  type ClassifierOutput,
  type ClassifierResult,
  type FilterConfig,
  type FilterId,
  type RuleOutcome,
} from '@lnz/shared';
import { filterHeat, overallHeat } from '../src/ui/heat';

const ready = (filterId: FilterId, output: ClassifierOutput): ClassifierResult => ({
  filterId,
  videoId: 'v1',
  state: 'ready',
  output,
  provider: `demo:${filterId}`,
  isDemo: true,
  receivedAt: 0,
});
const state = (filterId: FilterId, s: ClassifierResult['state']): ClassifierResult => ({
  filterId,
  videoId: 'v1',
  state: s,
  provider: `demo:${filterId}`,
  isDemo: true,
  receivedAt: 0,
});
const verdict = (v: RuleOutcome['verdict']): RuleOutcome => ({ verdict: v });

const allEnabled: FilterConfig = {
  ...DEFAULT_CONFIG.filters,
  learn: { ...DEFAULT_CONFIG.filters.learn, enabled: true },
};

describe('collapsed rail heat', () => {
  it('shows a low-stress clip as a nearly full green ring', () => {
    const heat = filterHeat('calm', ready('calm', { kind: 'score', score: 0.05 }), verdict('pass'), true);
    expect(heat.tone).toBe('good');
    expect(heat.level).toBeCloseTo(0.95);
    expect(heat.label).toBe('5% stress');
  });

  it('turns Calm red for a high predicted stress response', () => {
    const heat = filterHeat('calm', ready('calm', { kind: 'score', score: 0.82 }), verdict('pass'), true);
    expect(heat.tone).toBe('bad');
    expect(heat.level).toBeCloseTo(0.18);
  });

  it('turns Learn green for high educational value and red for low', () => {
    expect(filterHeat('learn', ready('learn', { kind: 'score', score: 0.91 }), verdict('pass'), true)).toMatchObject({
      tone: 'good',
      level: 0.91,
      label: '91% learn',
    });
    expect(filterHeat('learn', ready('learn', { kind: 'score', score: 0.18 }), verdict('reject'), true)).toMatchObject({
      tone: 'bad',
      level: 0.18,
    });
  });

  it('distinguishes a blocked Shield flag from a flag outside the user selection', () => {
    expect(
      filterHeat('shield', ready('shield', { kind: 'categories', flagged: [] }), verdict('pass'), true),
    ).toMatchObject({ tone: 'good', level: 1, label: 'No flags' });

    expect(
      filterHeat('shield', ready('shield', { kind: 'categories', flagged: ['S1'] }), verdict('reject'), true),
    ).toMatchObject({ tone: 'bad', label: 'Flagged S1' });

    expect(
      filterHeat('shield', ready('shield', { kind: 'categories', flagged: ['S5'] }), verdict('pass'), true),
    ).toMatchObject({ tone: 'warn', label: 'Flagged S5' });
  });

  it('uses amber for pending work and grey for unavailable models', () => {
    expect(filterHeat('calm', state('calm', 'analyzing'), verdict('pending'), true)).toMatchObject({
      tone: 'warn',
      label: 'Analyzing',
    });
    expect(filterHeat('calm', state('calm', 'unavailable'), verdict('unknown'), true)).toMatchObject({
      tone: 'idle',
      label: 'Unknown',
    });
  });

  it('leaves disabled filters grey and lets a rejection override the score tone', () => {
    expect(filterHeat('calm', undefined, verdict('off'), false)).toMatchObject({ tone: 'idle', level: 0, label: 'Off' });
    expect(
      filterHeat('calm', ready('calm', { kind: 'score', score: 0.58 }), verdict('reject'), true).tone,
    ).toBe('bad');
  });

  it('is green overall only when every enabled filter is clear', () => {
    const good: Record<FilterId, ReturnType<typeof filterHeat>> = {
      calm: filterHeat('calm', ready('calm', { kind: 'score', score: 0.05 }), verdict('pass'), true),
      learn: filterHeat('learn', ready('learn', { kind: 'score', score: 0.9 }), verdict('pass'), true),
      shield: filterHeat('shield', ready('shield', { kind: 'categories', flagged: [] }), verdict('pass'), true),
    };
    expect(overallHeat(good, allEnabled, true).tone).toBe('good');

    const bad = {
      ...good,
      shield: filterHeat('shield', ready('shield', { kind: 'categories', flagged: ['S1'] }), verdict('reject'), true),
    };
    expect(overallHeat(bad, allEnabled, true).tone).toBe('bad');

    const pending = {
      ...good,
      learn: filterHeat('learn', state('learn', 'analyzing'), verdict('pending'), true),
    };
    expect(overallHeat(pending, allEnabled, true).tone).toBe('warn');

    const unavailable = {
      ...good,
      learn: filterHeat('learn', state('learn', 'unavailable'), verdict('unknown'), true),
    };
    expect(overallHeat(unavailable, allEnabled, true).tone).toBe('warn');
  });

  it('stays grey when LNZ is off or every filter is disabled', () => {
    const heats: Record<FilterId, ReturnType<typeof filterHeat>> = {
      calm: filterHeat('calm', undefined, verdict('off'), false),
      learn: filterHeat('learn', undefined, verdict('off'), false),
      shield: filterHeat('shield', undefined, verdict('off'), false),
    };
    expect(overallHeat(heats, allEnabled, false).tone).toBe('idle');
    expect(overallHeat(heats, { calm: { ...allEnabled.calm, enabled: false }, learn: { ...allEnabled.learn, enabled: false }, shield: { ...allEnabled.shield, enabled: false } }, true).tone).toBe('idle');
  });
});
