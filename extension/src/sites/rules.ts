import type { FeedItem, FeedVerdict } from './types';

/**
 * Synchronous rule tier. Runs in the page (MAIN world) at response time, so items
 * matching a rule are removed from the feed before the app ever renders them, on
 * both fetch and XHR paths, with zero added latency.
 *
 * These are the user's explicit rules (blocked words, hashtags, creators). They
 * complement — never replace — the async classifier verdicts.
 */
export interface FeedRules {
  keywords: string[];
  hashtags: string[];
  creators: string[];
  /** Skip promoted items. */
  blockAds: boolean;
  /** On X, only judge items with video/GIF (text tweets always pass). */
  videoOnly: boolean;
}

export const DEFAULT_RULES: FeedRules = { keywords: [], hashtags: [], creators: [], blockAds: false, videoOnly: true };

const norm = (s: string) => s.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/^[#@]/, '').trim();

export interface CompiledRules {
  match(item: FeedItem): string | null; // reason or null
}

export function compileRules(r: FeedRules): CompiledRules {
  const tags = new Set(r.hashtags.map(norm).filter(Boolean));
  const creators = new Set(r.creators.map(norm).filter(Boolean));
  const words = r.keywords.map(norm).filter(Boolean);
  const wordRe = words.length
    ? new RegExp(`(^|[^\\p{L}\\p{N}])(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?=$|[^\\p{L}\\p{N}])`, 'iu')
    : null;
  return {
    match(item) {
      if (r.blockAds && item.isAd) return 'Promoted';
      if (item.author && creators.has(norm(item.author))) return `Creator @${item.author}`;
      for (const h of item.hashtags ?? []) if (tags.has(norm(h))) return `#${h}`;
      if (wordRe) {
        const hay = norm([item.text, item.soundTitle, ...(item.hashtags ?? [])].filter(Boolean).join(' '));
        const m = hay.match(wordRe);
        if (m) return `Keyword "${m[2]}"`;
      }
      return null;
    },
  };
}

/** Combine rule tier + classifier verdict. A rule hit always blocks. */
export function combine(rule: string | null, classifier: FeedVerdict | undefined): FeedVerdict {
  if (rule) return 'block';
  return classifier ?? 'unknown';
}

/** Items the classifier tier should judge. */
export function wantsJudging(item: FeedItem, rules: FeedRules): boolean {
  if (item.site === 'x' && rules.videoOnly && !item.isVideo) return false;
  return true;
}
