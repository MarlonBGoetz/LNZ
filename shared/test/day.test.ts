import { describe, expect, it } from 'vitest';
import type { AnalyticsEvent } from '../src/events';
import type { ClassifierOutput, DecisionVerdict, FilterId } from '../src/contracts';
import { summarizeDay } from '../src/day';

const at = (hour: number, minute = 0) => new Date(2026, 9, 24, hour, minute).getTime();

const video = (id: string, hour: number, platform?: 'tiktok' | 'x', minute = 0): AnalyticsEvent => ({
  type: 'video',
  at: at(hour, minute),
  video: {
    videoId: id,
    url: platform === 'x' ? `https://x.com/someone/status/${id}` : `https://www.tiktok.com/@someone/video/${id}`,
    title: platform === 'x' ? `X post ${id}` : `TikTok clip ${id}`,
    author: 'someone',
    ...(platform ? { platform } : {}),
  },
});

const result = (id: string, filterId: FilterId, output: ClassifierOutput, hour: number, minute = 0, platform?: 'tiktok' | 'x'): AnalyticsEvent => ({
  type: 'result',
  at: at(hour, minute),
  result: {
    filterId,
    videoId: id,
    ...(platform ? { platform } : {}),
    state: 'ready',
    output,
    provider: `demo:${filterId}`,
    isDemo: true,
    receivedAt: at(hour, minute),
  },
});

const decision = (id: string, verdict: DecisionVerdict, hour: number, minute = 0, platform?: 'tiktok' | 'x'): AnalyticsEvent => ({
  type: 'decision',
  at: at(hour, minute),
  decision: {
    videoId: id,
    ...(platform ? { platform } : {}),
    verdict,
    rules: { calm: { verdict: 'pass' }, learn: { verdict: 'pass' }, shield: { verdict: 'pass' } },
    rejectedBy: verdict === 'skip' ? ['calm'] : [],
  },
});

const skip = (id: string, hour: number, minute = 0, platform?: 'tiktok' | 'x'): AnalyticsEvent => ({
  type: 'skip',
  at: at(hour, minute),
  videoId: id,
  ...(platform ? { platform } : {}),
  reason: 'test',
});

describe('day summary', () => {
  it('summarises a mixed TikTok/X day with unique videos and flags', () => {
    const summary = summarizeDay(
      [
        video('100000000000001', 9, 'tiktok'),
        result('100000000000001', 'calm', { kind: 'score', score: 0.2 }, 9, 1),
        result('100000000000001', 'learn', { kind: 'score', score: 0.8 }, 9, 1),
        result('100000000000001', 'shield', { kind: 'categories', flagged: [] }, 9, 1),
        decision('100000000000001', 'keep', 9, 2),

        video('200000000000002', 9, 'x', 30),
        result('200000000000002', 'calm', { kind: 'score', score: 0.8 }, 9, 31),
        result('200000000000002', 'learn', { kind: 'score', score: 0.2 }, 9, 31),
        result('200000000000002', 'shield', { kind: 'categories', flagged: ['S1'] }, 9, 31),
        decision('200000000000002', 'skip', 9, 32),
        skip('200000000000002', 9, 32),

        video('200000000000003', 9, 'x', 45),
        result('200000000000003', 'calm', { kind: 'score', score: 0.4 }, 9, 46),
        result('200000000000003', 'learn', { kind: 'score', score: 0.6 }, 9, 46),
        decision('200000000000003', 'keep-unverified', 9, 47),
      ],
      '2026-10-24',
    );

    expect(summary.date).toBe('2026-10-24');
    expect(summary.demo).toBe(true);
    expect(summary.watched).toBe(3);
    expect(summary.analyzed).toBe(3);
    expect(summary.kept).toBe(2);
    expect(summary.skipped).toBe(1);
    expect(summary.pending).toBe(0);
    expect(summary.platforms).toEqual({ tiktok: 1, x: 2 });
    expect(summary.avgCalm).toBeCloseTo((0.2 + 0.8 + 0.4) / 3);
    expect(summary.avgLearn).toBeCloseTo((0.8 + 0.2 + 0.6) / 3);
    expect(summary.flagged).toEqual([{ id: 'S1', count: 1 }]);
    expect(summary.hours[9]).toMatchObject({ watched: 3, kept: 2, skipped: 1, pending: 0 });
    expect(summary.sessions).toBe(1);
    expect(summary.firstAt).toBe(at(9));
    expect(summary.lastAt).toBe(at(9, 45));
    expect(summary.recent.map((v) => v.videoId)).toEqual(['200000000000003', '200000000000002', '100000000000001']);
  });

  it('returns an empty, stable summary for a day with no events', () => {
    const summary = summarizeDay([], '2026-10-24');
    expect(summary).toMatchObject({
      watched: 0,
      analyzed: 0,
      kept: 0,
      skipped: 0,
      pending: 0,
      avgCalm: null,
      avgLearn: null,
      flagged: [],
      platforms: { tiktok: 0, x: 0 },
      sessions: 0,
      firstAt: null,
      lastAt: null,
      recent: [],
      demo: false,
    });
    expect(summary.hours).toHaveLength(24);
    expect(summary.hours.every((h) => h.watched === 0)).toBe(true);
  });

  it('counts unique videos once and keeps the latest ready score', () => {
    const summary = summarizeDay(
      [
        video('300000000000001', 10, 'tiktok'),
        result('300000000000001', 'calm', { kind: 'score', score: 0.5 }, 10, 1),
        result('300000000000001', 'calm', { kind: 'score', score: 0.1 }, 10, 2),
        decision('300000000000001', 'keep', 10, 3),
        video('300000000000001', 10, 'tiktok', 4),
      ],
      '2026-10-24',
    );

    expect(summary.watched).toBe(1);
    expect(summary.avgCalm).toBeCloseTo(0.1);
    expect(summary.platforms).toEqual({ tiktok: 1, x: 0 });
  });

  it('infers an X platform from the URL when the producer omits platform', () => {
    const xPost: AnalyticsEvent = {
      type: 'video',
      at: at(10),
      video: { videoId: '300000000000002', url: 'https://x.com/someone/status/300000000000002', title: 'An X post' },
    };
    const summary = summarizeDay([xPost], '2026-10-24');
    expect(summary.platforms).toEqual({ tiktok: 0, x: 1 });
    expect(summary.recent[0].platform).toBe('x');
  });

  it('counts separate sessions across a long gap', () => {
    const summary = summarizeDay(
      [video('400000000000001', 8), video('400000000000002', 9), video('400000000000003', 9, 'x', 20)],
      '2026-10-24',
    );
    expect(summary.sessions).toBe(2);
    expect(summary.pending).toBe(3);
  });

  it('counts a skip verdict even without a skip event and keeps keep-unverified', () => {
    const summary = summarizeDay(
      [
        video('500000000000001', 11),
        decision('500000000000001', 'skip', 11, 1),
        video('500000000000002', 11, 'x', 10),
        decision('500000000000002', 'keep-unverified', 11, 11),
      ],
      '2026-10-24',
    );
    expect(summary.skipped).toBe(1);
    expect(summary.kept).toBe(1);
    expect(summary.pending).toBe(0);
  });

  it('separates colliding TikTok and X ids using the platform on results and decisions', () => {
    const id = '700000000000001';
    const summary = summarizeDay(
      [
        video(id, 12, 'tiktok'),
        video(id, 12, 'x'),
        result(id, 'calm', { kind: 'score', score: 0.2 }, 12, 1, 'tiktok'),
        result(id, 'learn', { kind: 'score', score: 0.9 }, 12, 1, 'tiktok'),
        result(id, 'shield', { kind: 'categories', flagged: [] }, 12, 1, 'tiktok'),
        decision(id, 'keep', 12, 2, 'tiktok'),
        result(id, 'calm', { kind: 'score', score: 0.9 }, 12, 3, 'x'),
        result(id, 'learn', { kind: 'score', score: 0.2 }, 12, 3, 'x'),
        result(id, 'shield', { kind: 'categories', flagged: ['S1'] }, 12, 3, 'x'),
        decision(id, 'skip', 12, 4, 'x'),
      ],
      '2026-10-24',
    );

    expect(summary.watched).toBe(2);
    expect(summary.kept).toBe(1);
    expect(summary.skipped).toBe(1);
    expect(summary.pending).toBe(0);
    expect(summary.platforms).toEqual({ tiktok: 1, x: 1 });
    expect(summary.avgCalm).toBeCloseTo((0.2 + 0.9) / 2);
    expect(summary.flagged).toEqual([{ id: 'S1', count: 1 }]);
    expect(summary.recent.find((item) => item.platform === 'tiktok')?.decision).toBe('keep');
    expect(summary.recent.find((item) => item.platform === 'x')?.decision).toBe('skip');
  });
});
