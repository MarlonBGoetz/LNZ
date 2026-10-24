/**
 * LNZ shared integration contracts.
 *
 * These types are the stable seam between the LNZ UI (overlay + analytics
 * dashboard) and the modules other teammates own:
 *   - classifiers (TRIBE v2-derived Calm model, Learn model, Shield model)
 *   - TikTok video detection / preloading / navigation
 *
 * Change these carefully: both the extension and the analytics app import them.
 */

export type FilterId = 'calm' | 'learn' | 'shield';

/** Per-video, per-classifier analysis lifecycle. */
export type AnalysisState = 'waiting' | 'analyzing' | 'ready' | 'unavailable' | 'error';

/** Provider health as shown in the UI. */
export type ProviderAvailability = 'connected' | 'analyzing' | 'unavailable';

/** Coarse cortical regions used only for visual summaries in the dashboard. */
export type BrainRegion = 'frontal' | 'parietal' | 'temporal' | 'occipital' | 'limbic' | 'cerebellum';

/** A video the user is currently looking at. */
export interface VideoRef {
  /** Stable id. TikTok numeric id when known, otherwise a derived hash. */
  videoId: string;
  url: string;
  title?: string;
  author?: string;
  durationSec?: number;
  /** Position in this browsing session (1-based), set by the detector. */
  index?: number;
}

/** Continuous 0..1 score (Calm: predicted stress-related response; Learn: educational value). */
export interface ScoreOutput {
  kind: 'score';
  /** Normalised 0..1. Never invented: providers that cannot score must throw / report unavailable. */
  score: number;
  /** Optional per-time-step score across the clip (0..1), e.g. TRIBE per-TR predictions. */
  timeline?: number[];
  /** Optional coarse region summary (0..1) for the dashboard brain view. */
  regions?: Partial<Record<BrainRegion, number>>;
}

/** Categorical safety labels (e.g. Llama Guard 4). No probabilities are implied. */
export interface CategoryOutput {
  kind: 'categories';
  /** Category ids from SHIELD_CATEGORIES that the classifier flagged. Empty = none flagged. */
  flagged: string[];
}

export type ClassifierOutput = ScoreOutput | CategoryOutput;

/** One classifier's result for one video, as delivered to the UI. */
export interface ClassifierResult {
  filterId: FilterId;
  videoId: string;
  state: AnalysisState;
  output?: ClassifierOutput;
  /** Provider id, e.g. "demo:calm" or "http:calm". */
  provider: string;
  /** True for the built-in demo provider. The UI must label these as demo data. */
  isDemo: boolean;
  model?: string;
  latencyMs?: number;
  error?: string;
  receivedAt: number;
}

/**
 * A classifier implementation. Teammates implement this (or expose the HTTP
 * contract in docs/INTEGRATION.md, which the built-in HttpClassifierProvider wraps).
 */
export interface ClassifierProvider {
  readonly id: string;
  readonly filterId: FilterId;
  readonly isDemo: boolean;
  readonly model?: string;
  availability(): Promise<ProviderAvailability>;
  /** Must reject (throw) when it cannot produce a real result. Never fabricate a score. */
  classify(video: VideoRef, signal: AbortSignal): Promise<ClassifierOutput>;
}

/** Reports which video is active. Owned by the TikTok detection teammate; a DOM default ships here. */
export interface VideoSource {
  current(): VideoRef | null;
  onActiveVideoChange(cb: (video: VideoRef | null) => void): () => void;
}

/** Moves the feed. Owned by the navigation/preloading teammate; a DOM default ships here. */
export interface VideoNavigator {
  skipToNext(reason: string): Promise<void>;
}

/** Holds playback while the user is changing settings. */
export interface PlaybackController {
  hold(): void;
  release(): void;
}

export interface FilterConfig {
  calm: { enabled: boolean; /** skip when score > threshold */ threshold: number };
  learn: { enabled: boolean; /** skip when score < minScore */ minScore: number };
  shield: { enabled: boolean; /** skip when any of these is flagged */ categories: string[] };
}

export interface LnzConfig {
  version: 1;
  /** Master switch: launcher lit cyan when true, grey outline when false. */
  active: boolean;
  filters: FilterConfig;
  autoSkip: boolean;
  providers: { mode: 'demo' | 'http'; baseUrl: string };
  /** Local analytics dashboard (relay) base URL. */
  analyticsUrl: string;
}

export type RuleVerdict = 'off' | 'pass' | 'reject' | 'pending' | 'unknown';

export interface RuleOutcome {
  verdict: RuleVerdict;
  reason?: string;
}

/**
 * keep            – every enabled filter has a result and all pass
 * skip            – at least one enabled filter confidently rejects
 * pending         – nothing rejects yet, but results are still arriving
 * keep-unverified – nothing rejects, but at least one enabled filter is unavailable/errored
 */
export type DecisionVerdict = 'keep' | 'skip' | 'pending' | 'keep-unverified';

export interface Decision {
  videoId: string;
  verdict: DecisionVerdict;
  rules: Record<FilterId, RuleOutcome>;
  rejectedBy: FilterId[];
}
