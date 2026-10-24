import {
  clamp01,
  pct,
  type ClassifierResult,
  type FilterConfig,
  type FilterId,
  type RuleOutcome,
} from '@lnz/shared';

/**
 * Collapsed-rail heat model.
 *
 * `level` is health, not severity: 1 = clear, 0 = bad. The ring fills clockwise
 * from empty to full, so a calm, low-stress clip is a nearly full green ring and
 * a high-stress clip is a short red arc.
 */
export type HeatTone = 'good' | 'warn' | 'bad' | 'idle';

export interface Heat {
  tone: HeatTone;
  /** 0..1 health. */
  level: number;
  /** Short value, e.g. "5% stress" or "No flags". */
  label: string;
  /** Full tooltip / accessible explanation. */
  detail: string;
}

const OFF: Heat = { tone: 'idle', level: 0, label: 'Off', detail: 'Filter off' };
const ANALYZING: Heat = { tone: 'warn', level: 0.22, label: 'Analyzing', detail: 'Analysis in progress' };

export function filterHeat(
  id: FilterId,
  result: ClassifierResult | undefined,
  rule: RuleOutcome | undefined,
  enabled: boolean,
): Heat {
  if (!enabled) return OFF;
  if (!result || result.state === 'waiting' || result.state === 'analyzing') return ANALYZING;

  if (result.state !== 'ready' || !result.output) {
    return result.state === 'error'
      ? { tone: 'idle', level: 0.18, label: 'Error', detail: result.error ?? 'Classifier error' }
      : { tone: 'idle', level: 0.18, label: 'Unknown', detail: 'Classifier unavailable' };
  }

  const out = result.output;
  let health: number;
  let label: string;

  if (id === 'calm' && out.kind === 'score') {
    health = 1 - out.score;
    label = `${pct(out.score)} stress`;
  } else if (id === 'learn' && out.kind === 'score') {
    health = out.score;
    label = `${pct(out.score)} learn`;
  } else if (id === 'shield' && out.kind === 'categories') {
    health = out.flagged.length === 0 ? 1 : rule?.verdict === 'reject' ? 0.05 : 0.38;
    label = out.flagged.length === 0 ? 'No flags' : `Flagged ${out.flagged.join(', ')}`;
  } else {
    return { tone: 'idle', level: 0.18, label: 'Unknown', detail: 'Unexpected classifier output' };
  }

  let tone: HeatTone = health >= 0.67 ? 'good' : health >= 0.34 ? 'warn' : 'bad';
  if (rule?.verdict === 'reject') tone = 'bad';
  else if (rule?.verdict === 'off') tone = 'idle';
  else if ((rule?.verdict === 'pending' || rule?.verdict === 'unknown') && tone === 'good') tone = 'warn';

  return { tone, level: clamp01(health), label, detail: rule?.reason ?? label };
}

/** One dot on the launcher: green when every active filter is clear. */
export function overallHeat(
  heats: Record<FilterId, Heat>,
  filters: FilterConfig,
  active: boolean,
): Heat {
  if (!active) return { tone: 'idle', level: 0, label: 'Off', detail: 'LNZ is off' };

  const enabled = (Object.keys(heats) as FilterId[]).filter((id) => filters[id].enabled);
  if (!enabled.length) return { tone: 'idle', level: 0, label: 'No filters', detail: 'No filters enabled' };

  const current = enabled.map((id) => heats[id]);
  if (current.some((h) => h.tone === 'bad')) {
    return { tone: 'bad', level: 0, label: 'Would skip', detail: 'At least one active filter rejects this video' };
  }
  if (current.some((h) => h.tone === 'warn' || h.tone === 'idle')) {
    return {
      tone: 'warn',
      level: 0.25,
      label: 'Check',
      detail: 'Analysis pending, uncertain, or a filter is unavailable',
    };
  }
  return { tone: 'good', level: 1, label: 'Clear', detail: 'All active filters clear' };
}
