/**
 * LNZ X stage controller.
 *
 * The real content script is loaded with ?platform=x, so it uses the X DOM
 * adapter: post text, @handle and /status/<id> become the VideoRef. This file
 * only drives the synthetic timeline and the manual "next post" control. The
 * overlay's own XDomNavigator handles auto-skip.
 */
(() => {
  const timeline = document.getElementById('timeline');
  if (!timeline) return;
  const posts = [...timeline.querySelectorAll('article.post')];
  const next = document.getElementById('next-post');
  if (!posts.length) return;

  const activeIndex = () => {
    const top = timeline.getBoundingClientRect().top;
    let best = 0;
    let bestScore = -Infinity;
    posts.forEach((post, i) => {
      const r = post.getBoundingClientRect();
      const visible = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, top));
      const distance = Math.abs(r.top - top);
      const score = visible * 1000 - distance;
      if (score > bestScore) {
        bestScore = score;
        best = i;
      }
    });
    return best;
  };

  next?.addEventListener('click', () => {
    const target = posts[Math.min(posts.length - 1, activeIndex() + 1)];
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });

  addEventListener(
    'keydown',
    (e) => {
      if (e.key === 'ArrowDown' || e.key === 'PageDown') {
        e.preventDefault();
        posts[Math.min(posts.length - 1, activeIndex() + 1)].scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
        e.preventDefault();
        posts[Math.max(0, activeIndex() - 1)].scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    },
    { capture: true },
  );

  // One playing video at a time. The overlay can pause the active video; this
  // observer does not resume on pause, so the edit-mode hold is respected.
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const video = entry.target;
        if (!(video instanceof HTMLVideoElement)) continue;
        if (entry.isIntersecting) void video.play().catch(() => {});
        else video.pause();
      }
    },
    { root: timeline, threshold: 0.5 },
  );
  posts.forEach((post) => {
    const video = post.querySelector('video');
    if (video) observer.observe(video);
  });

  void posts[0].querySelector('video')?.play().catch(() => {});
})();
