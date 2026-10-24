import { afterEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG, decide, type ClassifierResult } from '@lnz/shared';
import { AnalysisSession, classifierKey, visibleResults } from '../src/lib/analysis';
import { DelayedAutoSkip } from '../src/lib/autoSkip';

const video = { videoId: 'v1', url: 'https://www.tiktok.com/video/1' };
const result: ClassifierResult = { filterId: 'calm', videoId: 'v1', state: 'ready', output: { kind: 'score', score: 0.99 }, isDemo: true, provider: 'demo:calm', receivedAt: 1 };

afterEach(() => vi.useRealTimers());

describe('analysis generations', () => {
  it('rejects a late response from an earlier request for the same video and provider', () => {
    const session = new AnalysisSession();
    const old = session.begin(video, DEFAULT_CONFIG).request!;
    const current = session.begin(video, DEFAULT_CONFIG).request!;
    expect(session.accept(old.requestId, old.providerKey, result)).toBeNull();
    expect(session.snapshot.results).toEqual({});
    expect(session.accept(current.requestId, current.providerKey, result)?.results.calm).toEqual(result);
  });

  it('masks demo results immediately when saved providers change, before reanalysis starts', () => {
    const session = new AnalysisSession();
    const request = session.begin(video, DEFAULT_CONFIG).request!;
    session.accept(request.requestId, request.providerKey, result);
    const http = { ...DEFAULT_CONFIG, providers: { mode: 'http' as const, baseUrl: 'http://localhost:8000' } };
    expect(visibleResults(session.snapshot, 'v1', DEFAULT_CONFIG).calm).toEqual(result);
    const displayed = visibleResults(session.snapshot, 'v1', http);
    expect(displayed).toEqual({});
    expect(decide('v1', http.filters, displayed).verdict).toBe('pending');
    const fresh = session.begin(video, http).request!;
    expect(session.accept(request.requestId, request.providerKey, result)).toBeNull();
    expect(session.accept(fresh.requestId, classifierKey(DEFAULT_CONFIG), result)).toBeNull();
  });

  it('invalidates on no active video, disabling filtering, and another video', () => {
    const session = new AnalysisSession();
    const old = session.begin(video, DEFAULT_CONFIG).request!;
    session.accept(old.requestId, old.providerKey, result);
    expect(visibleResults(session.snapshot, 'v2', DEFAULT_CONFIG)).toEqual({});
    expect(visibleResults(session.snapshot, 'v1', { ...DEFAULT_CONFIG, active: false })).toEqual({});
    session.begin(null, DEFAULT_CONFIG);
    expect(session.accept(old.requestId, old.providerKey, result)).toBeNull();
    expect(session.begin(video, { ...DEFAULT_CONFIG, active: false }).request).toBeNull();
  });
});

describe('delayed auto-skip', () => {
  it('rechecks eligibility when the delay expires', () => {
    vi.useFakeTimers();
    const skip = new DelayedAutoSkip();
    const navigate = vi.fn();
    let eligible = true;
    skip.schedule('v1', () => eligible, navigate);
    eligible = false; // PIN opened, protection disabled, or result no longer rejects.
    vi.advanceTimersByTime(1000);
    expect(navigate).not.toHaveBeenCalled();
    eligible = true;
    skip.schedule('v1', () => eligible, navigate);
    vi.advanceTimersByTime(650);
    expect(navigate).toHaveBeenCalledOnce();
  });

  it('cancels pending work for source changes and unmount, without consuming the video', () => {
    vi.useFakeTimers();
    const skip = new DelayedAutoSkip();
    const navigate = vi.fn();
    skip.schedule('v1', () => true, navigate);
    skip.cancel();
    vi.advanceTimersByTime(1000);
    expect(navigate).not.toHaveBeenCalled();
    skip.schedule('v1', () => true, navigate);
    vi.advanceTimersByTime(650);
    expect(navigate).toHaveBeenCalledOnce();
  });

  it('replaces pending work and never requests an already skipped video again', () => {
    vi.useFakeTimers();
    const skip = new DelayedAutoSkip();
    const first = vi.fn();
    const replacement = vi.fn();
    skip.schedule('v1', () => true, first);
    vi.advanceTimersByTime(300);
    skip.schedule('v1', () => true, replacement);
    vi.advanceTimersByTime(650);
    expect(first).not.toHaveBeenCalled();
    expect(replacement).toHaveBeenCalledOnce();
    skip.schedule('v2', () => true, first);
    vi.advanceTimersByTime(650);
    skip.schedule('v1', () => true, replacement);
    vi.advanceTimersByTime(650);
    expect(first).toHaveBeenCalledOnce();
    expect(replacement).toHaveBeenCalledOnce();
  });
});
