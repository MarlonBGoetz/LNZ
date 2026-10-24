import type { ClassifierResult, Decision, LnzConfig, ProviderAvailability, FilterId, VideoRef } from '@lnz/shared';

/** Snapshot the background service worker hands to the overlay. */
export interface LnzState {
  config: LnzConfig;
  hasPin: boolean;
  unlocked: boolean;
  throttle: { failures: number; lockedUntil: number };
  availability: Record<FilterId, ProviderAvailability>;
  analyticsConnected: boolean;
}

/** One-shot requests (chrome.runtime.sendMessage). */
export type Request =
  | { type: 'getState' }
  | { type: 'setupPin'; pin: string; config: LnzConfig }
  | { type: 'unlock'; pin: string }
  | { type: 'saveAndLock'; config: LnzConfig }
  | { type: 'cancelEdit' }
  | { type: 'setActive'; active: boolean };

export type Response =
  | { ok: true; state: LnzState }
  | { ok: false; error: string; state?: LnzState };

/** Long-lived port 'lnz-analysis': content -> background. */
export type PortIn =
  | { type: 'analyze'; video: VideoRef; requestId: number; providerKey: string }
  | { type: 'cancelAnalysis' }
  | { type: 'decision'; decision: Decision }
  | { type: 'skip'; videoId: string; reason: string };

/** Long-lived port 'lnz-analysis': background -> content. */
export type PortOut = { type: 'result'; result: ClassifierResult; requestId: number; providerKey: string } | { type: 'state'; state: LnzState };

export const ANALYSIS_PORT = 'lnz-analysis';

export async function send(req: Request): Promise<Response> {
  try {
    const res = (await chrome.runtime.sendMessage(req)) as Response | undefined;
    return res ?? { ok: false, error: 'No response from LNZ background' };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
