import type { BrainRegion, ClassifierOutput, ClassifierProvider, FilterId, ProviderAvailability, VideoRef } from './contracts';
import { SHIELD_CATEGORIES, clamp01 } from './filters';

/**
 * DEMO PROVIDER — clearly-labelled fixture data so the UI works with no models connected.
 * Values are a deterministic hash of the video id. They are NOT predictions.
 */

export function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function seededRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(t);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

/** Pure fixture generator, also used by the analytics dashboard's demo stream. */
export function demoOutput(filterId: FilterId, videoId: string): ClassifierOutput {
  const r = seededRandom(hashString(`${filterId}:${videoId}`));
  if (filterId === 'shield') {
    const flagged: string[] = [];
    if (r() < 0.18) flagged.push(SHIELD_CATEGORIES[Math.floor(r() * SHIELD_CATEGORIES.length)].id);
    return { kind: 'categories', flagged };
  }
  // Skewed so most clips are low/moderate, some are high.
  const base = clamp01(Math.pow(r(), 1.35) * 0.95 + 0.03);
  if (filterId === 'learn') return { kind: 'score', score: base };
  const steps = 32;
  const timeline: number[] = [];
  let v = base;
  for (let i = 0; i < steps; i++) {
    v = clamp01(v + (r() - 0.5) * 0.18 + (base - v) * 0.25);
    timeline.push(Number(v.toFixed(3)));
  }
  const score = Number((timeline.reduce((a, b) => a + b, 0) / steps).toFixed(3));
  const regions: Record<BrainRegion, number> = {
    frontal: clamp01(score * (0.8 + r() * 0.4)),
    parietal: clamp01(score * (0.5 + r() * 0.5)),
    temporal: clamp01(score * (0.7 + r() * 0.5)),
    occipital: clamp01(0.35 + r() * 0.5),
    limbic: clamp01(score * (0.9 + r() * 0.3)),
    cerebellum: clamp01(0.2 + r() * 0.4),
  };
  return { kind: 'score', score, timeline, regions };
}

export class DemoClassifierProvider implements ClassifierProvider {
  readonly isDemo = true;
  readonly id: string;
  readonly model = 'demo-fixture';
  constructor(readonly filterId: FilterId) {
    this.id = `demo:${filterId}`;
  }
  async availability(): Promise<ProviderAvailability> {
    return 'connected';
  }
  async classify(video: VideoRef, signal: AbortSignal): Promise<ClassifierOutput> {
    const r = seededRandom(hashString(`lat:${this.filterId}:${video.videoId}`));
    await sleep(350 + Math.floor(r() * 900), signal);
    return demoOutput(this.filterId, video.videoId);
  }
}

export function createDemoProviders(): ClassifierProvider[] {
  return (['calm', 'learn', 'shield'] as FilterId[]).map((id) => new DemoClassifierProvider(id));
}
