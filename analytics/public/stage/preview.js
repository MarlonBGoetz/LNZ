/**
 * LNZ stage preview controller.
 *
 * The real content script mounts the real overlay in a closed Shadow DOM and
 * detects the active <video> exactly as it does on TikTok. This file only drives
 * the synthetic feed: scroll snapping, one playing clip, and the next/previous
 * controls. `data-e2e="feed-video-next"` is also what the overlay's default
 * TikTok navigator clicks, so auto-skip exercises the real navigation path.
 */
(() => {
  const feed = document.getElementById('feed');
  if (!feed) return;
  const clips = [...feed.querySelectorAll('.clip')];
  const next = document.querySelector('[data-e2e="feed-video-next"]');
  const restart = document.getElementById('restart');
  const caption = document.querySelector('.phone-caption span');
  if (!clips.length) return;

  let index = 0;

  const current = () => {
    const n = Math.round(feed.scrollTop / Math.max(1, feed.clientHeight));
    return Math.max(0, Math.min(clips.length - 1, n));
  };

  const go = (n) => {
    const target = (n + clips.length) % clips.length;
    index = target;
    clips[target].scrollIntoView({ behavior: 'smooth', block: 'start' });
    updateCaption();
  };

  function updateCaption() {
    if (caption) caption.textContent = `Clip ${index + 1} / ${clips.length}`;
  }

  next?.addEventListener('click', () => go(current() + 1));
  restart?.addEventListener('click', () => go(0));

  feed.addEventListener(
    'scroll',
    () => {
      const n = current();
      if (n !== index) {
        index = n;
        updateCaption();
      }
    },
    { passive: true },
  );

  addEventListener(
    'keydown',
    (e) => {
      if (e.key === 'ArrowDown' || e.key === 'PageDown') {
        e.preventDefault();
        go(current() + 1);
      } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
        e.preventDefault();
        go(current() - 1);
      } else if (e.key === 'Home') {
        e.preventDefault();
        go(0);
      } else if (e.key === 'End') {
        e.preventDefault();
        go(clips.length - 1);
      }
    },
    { capture: true },
  );

  // Play only the visible clip. The overlay can still pause the active element;
  // this observer does not resume on pause, so the editing hold is respected.
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const video = entry.target.querySelector('video');
        if (!video) continue;
        if (entry.isIntersecting) void video.play().catch(() => {});
        else video.pause();
      }
    },
    { root: feed, threshold: 0.55 },
  );
  clips.forEach((clip) => observer.observe(clip));

  updateCaption();
  void clips[0].querySelector('video')?.play().catch(() => {});
})();
