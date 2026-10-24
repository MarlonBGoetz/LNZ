import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TikTokDomVideoSource, TikTokPlayback } from '../src/content/tiktok';

class FakeVideo extends EventTarget {
  paused = false;
  isConnected = true;
  parentElement = null;
  duration = 20;
  poster = '';
  currentSrc = '';
  constructor(readonly id: string) {
    super();
  }
  closest() { return null; }
  querySelector() { return null; }
  getBoundingClientRect() {
    return { top: 0, left: 0, right: 400, bottom: 600, width: 400, height: 600 };
  }
  pause = vi.fn(() => { this.paused = true; });
  play = vi.fn(async () => {
    this.paused = false;
    this.dispatchEvent(new Event('play'));
  });
}

let videos: FakeVideo[];
let viewport: EventTarget;
let source: TikTokDomVideoSource;
let playback: TikTokPlayback;

function activate(video: FakeVideo | null) {
  videos = video ? [video] : [];
  viewport.dispatchEvent(new Event('scroll'));
}

beforeEach(() => {
  vi.useFakeTimers();
  videos = [];
  viewport = new EventTarget();
  vi.stubGlobal('window', { setInterval });
  vi.stubGlobal('innerWidth', 1000);
  vi.stubGlobal('innerHeight', 1000);
  vi.stubGlobal('addEventListener', vi.fn(viewport.addEventListener.bind(viewport)));
  vi.stubGlobal('removeEventListener', vi.fn(viewport.removeEventListener.bind(viewport)));
  vi.stubGlobal('document', { querySelectorAll: () => videos, title: 'Feed | TikTok' });
  vi.stubGlobal('location', { pathname: '/foryou', href: 'https://www.tiktok.com/foryou' });
  source = new TikTokDomVideoSource();
  playback = new TikTokPlayback(source);
  source.start();
});

afterEach(() => {
  playback.dispose();
  source.stop();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('playback holds', () => {
  it('retargets to a new video and restores only that video on release', async () => {
    const first = new FakeVideo('111111111111111');
    const second = new FakeVideo('222222222222222');
    activate(first);
    playback.hold();
    playback.hold();
    activate(second);
    expect(first.play).not.toHaveBeenCalled();
    expect(second.paused).toBe(true);
    await second.play();
    expect(second.paused).toBe(true);
    playback.release();
    expect(second.paused).toBe(false);
    expect(first.play).not.toHaveBeenCalled();
    expect(first.paused).toBe(true);
    // The old element's autoplay guard was detached on retarget.
    await first.play();
    expect(first.paused).toBe(false);
    const playCount = second.play.mock.calls.length;
    playback.release();
    expect(second.play).toHaveBeenCalledTimes(playCount);
  });

  it('preserves a user-paused video after retargeting', () => {
    const first = new FakeVideo('111111111111111');
    const second = new FakeVideo('222222222222222');
    second.paused = true;
    activate(first);
    playback.hold();
    activate(second);
    playback.release();
    expect(first.play).not.toHaveBeenCalled();
    expect(second.play).not.toHaveBeenCalled();
    expect(second.paused).toBe(true);
  });

  it('holds a video that appears after the hold began', () => {
    playback.hold();
    const video = new FakeVideo('111111111111111');
    activate(video);
    expect(video.paused).toBe(true);
    playback.release();
    expect(video.play).toHaveBeenCalledOnce();
  });

  it('follows a replacement element with the same video ID', () => {
    const first = new FakeVideo('111111111111111');
    activate(first);
    const index = source.current()?.index;
    playback.hold();
    const replacement = new FakeVideo(first.id);
    activate(replacement);
    expect(source.current()?.index).toBe(index);
    expect(replacement.paused).toBe(true);
    playback.release();
    expect(replacement.play).toHaveBeenCalledOnce();
    expect(first.play).not.toHaveBeenCalled();
  });

  it('does not resume a video that has left the feed', async () => {
    const video = new FakeVideo('111111111111111');
    activate(video);
    playback.hold();
    activate(null);
    playback.release();
    expect(video.play).not.toHaveBeenCalled();
    await video.play();
    expect(video.paused).toBe(false);
  });

  it('does not resume an inactive video before the next source poll', () => {
    const video = new FakeVideo('111111111111111');
    activate(video);
    playback.hold();
    videos = [new FakeVideo('222222222222222')];
    playback.release();
    expect(video.play).not.toHaveBeenCalled();
  });

  it('does not resume a disconnected video before the next source poll', () => {
    const video = new FakeVideo('111111111111111');
    activate(video);
    playback.hold();
    video.isConnected = false;
    playback.release();
    expect(video.play).not.toHaveBeenCalled();
  });

  it('disposes the subscription and autoplay guard without resuming media', async () => {
    const video = new FakeVideo('111111111111111');
    activate(video);
    playback.hold();
    playback.dispose();
    expect(video.play).not.toHaveBeenCalled();
    expect(video.paused).toBe(true);
    await video.play();
    expect(video.paused).toBe(false);
    const next = new FakeVideo('222222222222222');
    activate(next);
    expect(next.pause).not.toHaveBeenCalled();
  });
});

describe('video source lifecycle', () => {
  it('starts once, removes polling and scroll listeners, and retains subscriptions for restart', () => {
    const changed = vi.fn();
    source.onActiveVideoChange(changed);
    source.start();
    source.start();
    expect(vi.getTimerCount()).toBe(1);
    expect(addEventListener).toHaveBeenCalledTimes(1);
    source.stop();
    source.stop();
    expect(vi.getTimerCount()).toBe(0);
    expect(removeEventListener).toHaveBeenCalledTimes(1);
    const video = new FakeVideo('111111111111111');
    activate(video);
    vi.advanceTimersByTime(1200);
    expect(changed).not.toHaveBeenCalled();
    source.start();
    expect(changed).toHaveBeenCalledOnce();
    expect(source.current()?.videoId).toBe(video.id);
    expect(vi.getTimerCount()).toBe(1);
  });
});
