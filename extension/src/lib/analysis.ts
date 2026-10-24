import type { ClassifierResult, LnzConfig, ResultMap, VideoRef } from '@lnz/shared';

export interface AnalysisRequest {
  requestId: number;
  providerKey: string;
  videoId: string;
}

export interface AnalysisSnapshot {
  request: AnalysisRequest | null;
  results: ResultMap;
}

export function classifierKey(config: LnzConfig): string {
  return JSON.stringify([config.providers.mode, config.providers.baseUrl]);
}

/** A generation distinguishes separate analyses of the same video and provider. */
export class AnalysisSession {
  private generation = 0;
  snapshot: AnalysisSnapshot = { request: null, results: {} };

  begin(video: VideoRef | null, config: LnzConfig | undefined): AnalysisSnapshot {
    this.generation += 1;
    this.snapshot = {
      request: video && config?.active
        ? { requestId: this.generation, providerKey: classifierKey(config), videoId: video.videoId }
        : null,
      results: {},
    };
    return this.snapshot;
  }

  accept(requestId: number, providerKey: string, result: ClassifierResult): AnalysisSnapshot | null {
    const request = this.snapshot.request;
    if (!request || request.requestId !== requestId || request.providerKey !== providerKey || request.videoId !== result.videoId) return null;
    this.snapshot = { request, results: { ...this.snapshot.results, [result.filterId]: result } };
    return this.snapshot;
  }
}

/** Mask old values during the render before the new analysis effect runs. */
export function visibleResults(snapshot: AnalysisSnapshot, videoId: string | undefined, config: LnzConfig | undefined): ResultMap {
  return config?.active && snapshot.request?.videoId === videoId && snapshot.request?.providerKey === classifierKey(config)
    ? snapshot.results
    : {};
}
