import type { ClassifierResult, Decision, FilterConfig, VideoRef } from './contracts';

/**
 * Events the extension (or any teammate service) POSTs to the analytics relay
 * at `${analyticsUrl}/api/events`. The dashboard receives them over SSE at /api/stream.
 */
export type AnalyticsEvent =
  | { type: 'hello'; source: string; at: number }
  | { type: 'video'; video: VideoRef; at: number }
  | { type: 'result'; result: ClassifierResult; at: number }
  | { type: 'decision'; decision: Decision; at: number }
  | { type: 'skip'; videoId: string; reason: string; at: number }
  | {
      type: 'config';
      config: { active: boolean; locked: boolean; autoSkip: boolean; filters: FilterConfig; providerMode: 'demo' | 'http' };
      at: number;
    };

export const ANALYTICS_EVENTS_PATH = '/api/events';
export const ANALYTICS_STREAM_PATH = '/api/stream';
export const ANALYTICS_HISTORY_PATH = '/api/history';
