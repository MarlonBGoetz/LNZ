import type { DecisionVerdict, VideoRef } from './contracts';
import type { AnalyticsEvent } from './events';

export type DayPlatform = 'tiktok' | 'x';

export interface DayHour {
  hour: number;
  watched: number;
  kept: number;
  skipped: number;
  pending: number;
}

export interface DayVideo {
  videoId: string;
  title: string;
  author?: string;
  platform: DayPlatform;
  at: number;
  calm?: number;
  learn?: number;
  flagged: string[];
  decision: DecisionVerdict;
  skipped: boolean;
}

export interface DaySummary {
  date: string;
  watched: number;
  analyzed: number;
  kept: number;
  skipped: number;
  pending: number;
  avgCalm: number | null;
  avgLearn: number | null;
  flagged: { id: string; count: number }[];
  platforms: { tiktok: number; x: number };
  hours: DayHour[];
  sessions: number;
  firstAt: number | null;
  lastAt: number | null;
  recent: DayVideo[];
  /** True when any classifier result in the day came from the demo provider. */
  demo: boolean;
}

interface Working {
  videoId: string;
  title: string;
  author?: string;
  platform: DayPlatform;
  at: number;
  calm?: number;
  learn?: number;
  flags: Set<string>;
  decision: DecisionVerdict;
  skipped: boolean;
  analyzed: boolean;
  demo: boolean;
}

function platformOf(video: VideoRef): DayPlatform {
  if (video.platform === 'x') return 'x';
  if (video.platform === 'tiktok') return 'tiktok';
  try {
    const host = new URL(video.url).hostname;
    if (/(^|\.)(x|twitter)\.com$/i.test(host)) return 'x';
  } catch {
    /* relative or malformed URL: treat as TikTok */
  }
  return 'tiktok';
}

function avg(values: number[]): number | null {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

/**
 * Compress one local day of raw analytics events into the dashboard summary.
 *
 * Unique videos are keyed by platform + video id. Results may arrive more than
 * once for a video after a config change; the latest ready scores win. A video
 * is "kept" only when a decision says keep/keep-unverified and it was not
 * skipped; pending videos are reported separately.
 */
export function summarizeDay(events: AnalyticsEvent[], date: string): DaySummary {
  const videos = new Map<string, Working>();
  const byVideoId = new Map<string, Working[]>();

  const ensure = (video: VideoRef, at: number): Working => {
    const platform = platformOf(video);
    const key = `${platform}:${video.videoId}`;
    let item = videos.get(key);
    if (!item) {
      item = {
        videoId: video.videoId,
        title: video.title || video.videoId,
        author: video.author,
        platform,
        at,
        flags: new Set<string>(),
        decision: 'pending',
        skipped: false,
        analyzed: false,
        demo: false,
      };
      videos.set(key, item);
      const list = byVideoId.get(video.videoId) ?? [];
      list.push(item);
      byVideoId.set(video.videoId, list);
    } else {
      if (!item.title || item.title === item.videoId) item.title = video.title || item.title;
      item.author ??= video.author;
    }
    return item;
  };

  const find = (videoId: string, platform?: DayPlatform): Working | undefined => {
    const matches = byVideoId.get(videoId);
    if (!matches?.length) return undefined;
    return (platform ? matches.find((item) => item.platform === platform) : undefined) ?? matches[0];
  };

  for (const event of events) {
    if (event.type === 'video') {
      ensure(event.video, event.at);
    } else if (event.type === 'result') {
      const item = find(event.result.videoId, event.result.platform);
      if (!item || event.result.state !== 'ready' || !event.result.output) continue;
      item.analyzed = true;
      if (event.result.isDemo) item.demo = true;
      const output = event.result.output;
      if (event.result.filterId === 'calm' && output.kind === 'score') item.calm = output.score;
      if (event.result.filterId === 'learn' && output.kind === 'score') item.learn = output.score;
      if (event.result.filterId === 'shield' && output.kind === 'categories') item.flags = new Set(output.flagged);
    } else if (event.type === 'decision') {
      const item = find(event.decision.videoId, event.decision.platform);
      if (!item) continue;
      item.decision = event.decision.verdict;
      if (event.decision.verdict === 'skip') item.skipped = true;
    } else if (event.type === 'skip') {
      const item = find(event.videoId, event.platform);
      if (!item) continue;
      item.skipped = true;
      if (item.decision === 'pending') item.decision = 'skip';
    }
  }

  const list = [...videos.values()];
  const hours: DayHour[] = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    watched: 0,
    kept: 0,
    skipped: 0,
    pending: 0,
  }));

  let kept = 0;
  let skipped = 0;
  const platforms = { tiktok: 0, x: 0 };
  const flaggedCounts = new Map<string, number>();

  for (const item of list) {
    platforms[item.platform] += 1;
    const hour = hours[new Date(item.at).getHours()];
    hour.watched += 1;
    if (item.skipped || item.decision === 'skip') {
      skipped += 1;
      hour.skipped += 1;
    } else if (item.decision === 'keep' || item.decision === 'keep-unverified') {
      kept += 1;
      hour.kept += 1;
    } else {
      hour.pending += 1;
    }
    for (const flag of item.flags) flaggedCounts.set(flag, (flaggedCounts.get(flag) ?? 0) + 1);
  }

  const sorted = [...list].sort((a, b) => a.at - b.at);
  let sessions = 0;
  let previous = 0;
  for (const item of sorted) {
    if (!previous || item.at - previous > 30 * 60_000) sessions += 1;
    previous = item.at;
  }

  const recent: DayVideo[] = [...list]
    .sort((a, b) => b.at - a.at)
    .slice(0, 12)
    .map((item) => ({
      videoId: item.videoId,
      title: item.title,
      author: item.author,
      platform: item.platform,
      at: item.at,
      calm: item.calm,
      learn: item.learn,
      flagged: [...item.flags],
      decision: item.decision,
      skipped: item.skipped,
    }));

  return {
    date,
    watched: list.length,
    analyzed: list.filter((item) => item.analyzed).length,
    kept,
    skipped,
    pending: list.length - kept - skipped,
    avgCalm: avg(list.flatMap((item) => (item.calm == null ? [] : [item.calm]))),
    avgLearn: avg(list.flatMap((item) => (item.learn == null ? [] : [item.learn]))),
    flagged: [...flaggedCounts.entries()]
      .map(([id, count]) => ({ id, count }))
      .sort((a, b) => b.count - a.count || a.id.localeCompare(b.id)),
    platforms,
    hours,
    sessions,
    firstAt: sorted[0]?.at ?? null,
    lastAt: sorted[sorted.length - 1]?.at ?? null,
    recent,
    demo: list.some((item) => item.demo),
  };
}
