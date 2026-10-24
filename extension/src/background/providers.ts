import {
  DemoClassifierProvider,
  type ClassifierOutput,
  type ClassifierProvider,
  type FilterId,
  type LnzConfig,
  type ProviderAvailability,
  type VideoRef,
} from '@lnz/shared';

/**
 * Wraps a teammate's local classifier service. HTTP contract (see docs/INTEGRATION.md):
 *   GET  {baseUrl}/health              -> { "calm": true, "learn": false, "shield": true }
 *   POST {baseUrl}/classify/{filterId} -> body { video: VideoRef }
 *        calm/learn : { "score": 0..1, "timeline"?: number[], "regions"?: {...}, "model"?: string }
 *        shield     : { "flagged": ["S1", ...], "model"?: string }
 */
export class HttpClassifierProvider implements ClassifierProvider {
  readonly isDemo = false;
  readonly id: string;
  model?: string;
  constructor(
    readonly filterId: FilterId,
    private readonly baseUrl: string,
  ) {
    this.id = `http:${filterId}`;
  }

  async availability(): Promise<ProviderAvailability> {
    try {
      const res = await fetch(`${this.baseUrl.replace(/\/$/, '')}/health`, { signal: AbortSignal.timeout(1500) });
      if (!res.ok) return 'unavailable';
      const j = (await res.json()) as Record<string, unknown>;
      return j[this.filterId] === true ? 'connected' : 'unavailable';
    } catch {
      return 'unavailable';
    }
  }

  async classify(video: VideoRef, signal: AbortSignal): Promise<ClassifierOutput> {
    const res = await fetch(`${this.baseUrl.replace(/\/$/, '')}/classify/${this.filterId}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ video }),
      signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const j = (await res.json()) as Record<string, unknown>;
    if (typeof j.model === 'string') this.model = j.model;
    return parseOutput(this.filterId, j);
  }
}

/** Validate a provider payload. Throws rather than inventing values. */
export function parseOutput(filterId: FilterId, j: Record<string, unknown>): ClassifierOutput {
  if (filterId === 'shield') {
    if (!Array.isArray(j.flagged) || !j.flagged.every((x) => typeof x === 'string')) {
      throw new Error('Shield response missing "flagged" string[]');
    }
    return { kind: 'categories', flagged: j.flagged as string[] };
  }
  const s = j.score;
  if (typeof s !== 'number' || !Number.isFinite(s) || s < 0 || s > 1) {
    throw new Error(`${filterId} response missing "score" in [0,1]`);
  }
  const timeline = Array.isArray(j.timeline) ? (j.timeline as unknown[]).filter((x): x is number => typeof x === 'number') : undefined;
  const regions = j.regions && typeof j.regions === 'object' ? (j.regions as Record<string, number>) : undefined;
  return { kind: 'score', score: s, timeline, regions };
}

export function buildProviders(config: LnzConfig): ClassifierProvider[] {
  const ids: FilterId[] = ['calm', 'learn', 'shield'];
  if (config.providers.mode === 'http') return ids.map((id) => new HttpClassifierProvider(id, config.providers.baseUrl));
  return ids.map((id) => new DemoClassifierProvider(id));
}
