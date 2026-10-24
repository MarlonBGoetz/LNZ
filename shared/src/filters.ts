import type { FilterId, LnzConfig } from './contracts';

export interface FilterMeta {
  id: FilterId;
  name: string;
  tagline: string;
  description: string;
  modelHint: string;
}

/** The three primary modes. Add a fourth here (plus contracts + decision rule) to extend. */
export const FILTERS: readonly FilterMeta[] = [
  {
    id: 'calm',
    name: 'Calm',
    tagline: 'Skip high-stress content',
    description:
      'Skips videos with a high predicted stress-related response. This is a model prediction about the video, not a measurement of you.',
    modelHint: 'TRIBE v2-derived distilled classifier',
  },
  {
    id: 'learn',
    name: 'Learn',
    tagline: 'Keep educational content',
    description: 'Keeps videos whose estimated educational value meets your minimum.',
    modelHint: 'Vision-language model (e.g. Qwen3-VL) + transcript',
  },
  {
    id: 'shield',
    name: 'Shield',
    tagline: 'Block flagged categories',
    description: 'Skips videos a safety classifier flags in the categories you choose.',
    modelHint: 'Safety classifier (e.g. Llama Guard 4)',
  },
] as const;

/** Llama Guard 4 hazard taxonomy (S1–S13; S14 code-interpreter abuse omitted for video). */
export const SHIELD_CATEGORIES: readonly { id: string; label: string }[] = [
  { id: 'S1', label: 'Violent crimes' },
  { id: 'S2', label: 'Non-violent crimes' },
  { id: 'S3', label: 'Sex-related crimes' },
  { id: 'S4', label: 'Child exploitation' },
  { id: 'S5', label: 'Defamation' },
  { id: 'S6', label: 'Specialized advice' },
  { id: 'S7', label: 'Privacy' },
  { id: 'S8', label: 'Intellectual property' },
  { id: 'S9', label: 'Indiscriminate weapons' },
  { id: 'S10', label: 'Hate' },
  { id: 'S11', label: 'Suicide & self-harm' },
  { id: 'S12', label: 'Sexual content' },
  { id: 'S13', label: 'Elections' },
];

export function categoryLabel(id: string): string {
  return SHIELD_CATEGORIES.find((c) => c.id === id)?.label ?? id;
}

export type ScoreLevel = 'Low' | 'Moderate' | 'High' | 'Unknown';

export function scoreLevel(score: number | undefined | null): ScoreLevel {
  if (score == null || !Number.isFinite(score)) return 'Unknown';
  if (score < 0.34) return 'Low';
  if (score < 0.67) return 'Moderate';
  return 'High';
}

export function pct(score: number): string {
  return `${Math.round(clamp01(score) * 100)}%`;
}

export function clamp01(n: number): number {
  return Math.min(1, Math.max(0, n));
}

export const DEFAULT_CONFIG: LnzConfig = {
  version: 1,
  active: true,
  filters: {
    calm: { enabled: true, threshold: 0.6 },
    learn: { enabled: false, minScore: 0.5 },
    shield: { enabled: true, categories: ['S1', 'S3', 'S4', 'S9', 'S10', 'S11'] },
  },
  autoSkip: true,
  providers: { mode: 'demo', baseUrl: 'http://localhost:8000' },
  analyticsUrl: 'http://localhost:5174',
};

/** Fill any missing fields from defaults (forward-compatible storage reads). */
export function normalizeConfig(raw: unknown): LnzConfig {
  const r = (raw ?? {}) as Partial<LnzConfig>;
  const f = (r.filters ?? {}) as Partial<LnzConfig['filters']>;
  const d = DEFAULT_CONFIG;
  return {
    version: 1,
    active: typeof r.active === 'boolean' ? r.active : d.active,
    filters: {
      calm: {
        enabled: f.calm?.enabled ?? d.filters.calm.enabled,
        threshold: clamp01(f.calm?.threshold ?? d.filters.calm.threshold),
      },
      learn: {
        enabled: f.learn?.enabled ?? d.filters.learn.enabled,
        minScore: clamp01(f.learn?.minScore ?? d.filters.learn.minScore),
      },
      shield: {
        enabled: f.shield?.enabled ?? d.filters.shield.enabled,
        categories: Array.isArray(f.shield?.categories)
          ? f.shield!.categories.filter((c) => typeof c === 'string')
          : [...d.filters.shield.categories],
      },
    },
    autoSkip: typeof r.autoSkip === 'boolean' ? r.autoSkip : d.autoSkip,
    providers: {
      mode: r.providers?.mode === 'http' ? 'http' : 'demo',
      baseUrl: typeof r.providers?.baseUrl === 'string' ? r.providers.baseUrl : d.providers.baseUrl,
    },
    analyticsUrl: typeof r.analyticsUrl === 'string' ? r.analyticsUrl : d.analyticsUrl,
  };
}
