import {
  DEFAULT_CONFIG,
  decide,
  demoOutput,
  type AnalyticsEvent,
  type ClassifierResult,
  type Decision,
  type FilterConfig,
  type FilterId,
  type ResultMap,
  type VideoRef,
} from '@lnz/shared';

export interface VideoState {
  video: VideoRef;
  results: ResultMap;
  decision?: Decision;
  skipped?: string;
  firstAt: number;
}

export interface LogLine {
  at: number;
  kind: 'video' | 'result' | 'decision' | 'skip' | 'config' | 'sys';
  text: string;
}

export type ConfigSnapshot = Extract<AnalyticsEvent, { type: 'config' }>['config'];

export interface Store {
  order: string[];
  videos: Record<string, VideoState>;
  currentId?: string;
  config?: ConfigSnapshot;
  lastExtensionAt?: number;
  log: LogLine[];
}

export const emptyStore = (): Store => ({ order: [], videos: {}, log: [] });

const MAX_VIDEOS = 60;
const MAX_LOG = 80;

function addLog(s: Store, line: LogLine): LogLine[] {
  const log = [line, ...s.log];
  return log.length > MAX_LOG ? log.slice(0, MAX_LOG) : log;
}

function fmtResult(r: ClassifierResult): string {
  if (r.state !== 'ready' || !r.output) return `${r.filterId.toUpperCase()} ${r.state.toUpperCase()}${r.error ? ` (${r.error})` : ''}`;
  if (r.output.kind === 'categories') return `SHIELD ${r.output.flagged.length ? `FLAGGED ${r.output.flagged.join(',')}` : 'CLEAR'} · ${r.latencyMs ?? '–'}ms`;
  return `${r.filterId.toUpperCase()} ${(r.output.score * 100).toFixed(1)}% · ${r.latencyMs ?? '–'}ms`;
}

export function reduce(s: Store, ev: AnalyticsEvent, fromDemo = false): Store {
  const ext = fromDemo ? s.lastExtensionAt : Date.now();
  switch (ev.type) {
    case 'hello':
      return { ...s, lastExtensionAt: ext, log: addLog(s, { at: ev.at, kind: 'sys', text: `HELLO ${ev.source}` }) };
    case 'config':
      return {
        ...s,
        config: ev.config,
        lastExtensionAt: ext,
        log: addLog(s, { at: ev.at, kind: 'config', text: `CONFIG ${ev.config.locked ? 'LOCKED' : 'EDIT'} · ${ev.config.active ? 'ACTIVE' : 'OFF'}` }),
      };
    case 'video': {
      const id = ev.video.videoId;
      const existing = s.videos[id];
      const videos = { ...s.videos, [id]: existing ? { ...existing, video: ev.video } : { video: ev.video, results: {}, firstAt: ev.at } };
      let order = existing ? s.order : [...s.order, id];
      if (order.length > MAX_VIDEOS) {
        const drop = order.slice(0, order.length - MAX_VIDEOS);
        order = order.slice(-MAX_VIDEOS);
        for (const d of drop) delete videos[d];
      }
      return {
        ...s,
        videos,
        order,
        currentId: id,
        lastExtensionAt: ext,
        log: addLog(s, { at: ev.at, kind: 'video', text: `VIDEO #${ev.video.index ?? '?'} ${ev.video.author ? '@' + ev.video.author : ''} ${id}` }),
      };
    }
    case 'result': {
      const v = s.videos[ev.result.videoId];
      if (!v) return s; // result for an unknown / evicted video
      const results = { ...v.results, [ev.result.filterId]: ev.result };
      const log = ev.result.state === 'analyzing' ? s.log : addLog(s, { at: ev.at, kind: 'result', text: fmtResult(ev.result) });
      return { ...s, videos: { ...s.videos, [v.video.videoId]: { ...v, results } }, lastExtensionAt: ext, log };
    }
    case 'decision': {
      const v = s.videos[ev.decision.videoId];
      if (!v) return s;
      return {
        ...s,
        videos: { ...s.videos, [v.video.videoId]: { ...v, decision: ev.decision } },
        lastExtensionAt: ext,
        log: addLog(s, { at: ev.at, kind: 'decision', text: `DECISION ${ev.decision.verdict.toUpperCase()}${ev.decision.rejectedBy.length ? ' · ' + ev.decision.rejectedBy.join(',') : ''}` }),
      };
    }
    case 'skip': {
      const v = s.videos[ev.videoId];
      if (!v) return s;
      return {
        ...s,
        videos: { ...s.videos, [ev.videoId]: { ...v, skipped: ev.reason } },
        lastExtensionAt: ext,
        log: addLog(s, { at: ev.at, kind: 'skip', text: `SKIP ${ev.reason}` }),
      };
    }
  }
}

/** Effective filters for evaluating rules: extension's config if known, else defaults. */
export function filtersOf(s: Store): FilterConfig {
  return s.config?.filters ?? DEFAULT_CONFIG.filters;
}

/**
 * DEMO STREAM — synthetic events so the dashboard can be shown without the extension.
 * Labelled DEMO everywhere in the UI. Values are fixtures, not predictions.
 */
export function startDemoStream(dispatch: (ev: AnalyticsEvent) => void, filters: FilterConfig = DEFAULT_CONFIG.filters): () => void {
  let n = 0;
  const timers: number[] = [];
  const authors = ['studio.nova', 'quantum.kate', 'dailyfit', 'cookwithsam', 'orbital.lab', 'mindful.min', 'streetclips', 'histories'];
  const titles = [
    'How black holes bend light — explained in 60s',
    'Morning routine that changed my life',
    'You will NOT believe what happened next',
    'Fourier transforms visualised',
    'Insane street fight caught on camera',
    'Learn 5 Spanish phrases in a minute',
    '3 ingredient pasta, ready in 10 min',
    'Breaking: chaos at the stadium tonight',
  ];

  const one = () => {
    n += 1;
    const videoId = `demo-${Date.now().toString(36)}-${n}`;
    const video: VideoRef = { videoId, url: 'https://www.tiktok.com/', index: n, author: authors[n % authors.length], title: titles[n % titles.length], durationSec: 20 + (n % 5) * 9 };
    dispatch({ type: 'video', video, at: Date.now() });
    const results: ResultMap = {};
    (['calm', 'learn', 'shield'] as FilterId[]).forEach((filterId, i) => {
      const base = { filterId, videoId, provider: `demo:${filterId}`, isDemo: true, model: 'demo-fixture' };
      dispatch({ type: 'result', result: { ...base, state: 'analyzing', receivedAt: Date.now() }, at: Date.now() });
      timers.push(
        window.setTimeout(() => {
          const r: ClassifierResult = { ...base, state: 'ready', output: demoOutput(filterId, videoId), latencyMs: 420 + i * 230, receivedAt: Date.now() };
          results[filterId] = r;
          dispatch({ type: 'result', result: r, at: Date.now() });
          if (Object.keys(results).length === 3) {
            const d = decide(videoId, filters, results);
            dispatch({ type: 'decision', decision: d, at: Date.now() });
            if (d.verdict === 'skip') dispatch({ type: 'skip', videoId, reason: d.rejectedBy.map((id) => d.rules[id].reason).join(' · '), at: Date.now() });
          }
        }, 500 + i * 300),
      );
    });
  };

  one();
  const iv = window.setInterval(one, 5200);
  return () => {
    clearInterval(iv);
    timers.forEach(clearTimeout);
  };
}
