import type { ClassifierResult, Decision, FilterConfig, FilterId, RuleOutcome } from './contracts';
import { categoryLabel, pct } from './filters';

export type ResultMap = Partial<Record<FilterId, ClassifierResult>>;

/**
 * Combine independent filter results into one keep/skip recommendation.
 *
 * - A video is kept only if it satisfies every enabled filter that produced a result.
 * - One confident rejection from an enabled filter is enough to recommend skipping.
 * - Missing / unavailable results are reported, never treated as a pass score.
 * - Results for a different videoId are ignored (stale).
 */
export function decide(videoId: string, filters: FilterConfig, results: ResultMap): Decision {
  const rules: Record<FilterId, RuleOutcome> = {
    calm: evalRule('calm', videoId, filters, results.calm),
    learn: evalRule('learn', videoId, filters, results.learn),
    shield: evalRule('shield', videoId, filters, results.shield),
  };
  const ids = Object.keys(rules) as FilterId[];
  const rejectedBy = ids.filter((id) => rules[id].verdict === 'reject');
  let verdict: Decision['verdict'];
  if (rejectedBy.length > 0) verdict = 'skip';
  else if (ids.some((id) => rules[id].verdict === 'pending')) verdict = 'pending';
  else if (ids.some((id) => rules[id].verdict === 'unknown')) verdict = 'keep-unverified';
  else verdict = 'keep';
  return { videoId, verdict, rules, rejectedBy };
}

function evalRule(
  id: FilterId,
  videoId: string,
  filters: FilterConfig,
  result: ClassifierResult | undefined,
): RuleOutcome {
  if (!filters[id].enabled) return { verdict: 'off' };
  if (!result || result.videoId !== videoId) return { verdict: 'pending', reason: 'Waiting' };
  if (result.state === 'waiting' || result.state === 'analyzing') return { verdict: 'pending', reason: 'Analyzing' };
  if (result.state !== 'ready' || !result.output) {
    return { verdict: 'unknown', reason: result.state === 'error' ? 'Classifier error' : 'Classifier unavailable' };
  }
  const out = result.output;
  switch (id) {
    case 'calm': {
      if (out.kind !== 'score') return { verdict: 'unknown', reason: 'Unexpected output' };
      const t = filters.calm.threshold;
      return out.score > t
        ? { verdict: 'reject', reason: `Stress ${pct(out.score)} > ${pct(t)}` }
        : { verdict: 'pass', reason: `Stress ${pct(out.score)} ≤ ${pct(t)}` };
    }
    case 'learn': {
      if (out.kind !== 'score') return { verdict: 'unknown', reason: 'Unexpected output' };
      const m = filters.learn.minScore;
      return out.score < m
        ? { verdict: 'reject', reason: `Learn ${pct(out.score)} < ${pct(m)}` }
        : { verdict: 'pass', reason: `Learn ${pct(out.score)} ≥ ${pct(m)}` };
    }
    case 'shield': {
      if (out.kind !== 'categories') return { verdict: 'unknown', reason: 'Unexpected output' };
      const hit = out.flagged.filter((c) => filters.shield.categories.includes(c));
      return hit.length > 0
        ? { verdict: 'reject', reason: `Flagged: ${hit.map(categoryLabel).join(', ')}` }
        : { verdict: 'pass', reason: out.flagged.length ? 'Flags outside your selection' : 'No categories flagged' };
    }
  }
}

export function verdictLabel(v: Decision['verdict']): string {
  switch (v) {
    case 'keep':
      return 'KEEP';
    case 'skip':
      return 'SKIP';
    case 'pending':
      return 'ANALYZING';
    case 'keep-unverified':
      return 'KEEP · UNVERIFIED';
  }
}
