import { createRoot } from 'react-dom/client';
import { App } from '../ui/App';
import css from '../ui/overlay.css?inline';
import { TikTokDomNavigator, TikTokDomVideoSource, TikTokPlayback, XDomNavigator } from './tiktok';

/**
 * Content script entry. Mounts the LNZ overlay in a closed Shadow DOM so the
 * host page's styles cannot leak in and ours cannot leak out.
 *
 * `?platform=x` is only used by the local stage preview; the real pages are
 * selected by hostname.
 */
function detectPlatform(): 'tiktok' | 'x' {
  if (new URLSearchParams(location.search).get('platform') === 'x') return 'x';
  return /(^|\.)(x|twitter)\.com$/i.test(location.hostname) ? 'x' : 'tiktok';
}

function mount() {
  if (document.getElementById('lnz-root')) return;
  const host = document.createElement('div');
  host.id = 'lnz-root';
  host.style.cssText = 'all: initial; position: fixed; inset: 0; pointer-events: none; z-index: 2147483646;';
  document.documentElement.appendChild(host);
  const shadow = host.attachShadow({ mode: 'closed' });
  const style = document.createElement('style');
  style.textContent = css;
  shadow.appendChild(style);
  const container = document.createElement('div');
  container.className = 'lnz';
  // Keep TikTok's keyboard shortcuts (like, scroll, mute) from firing while typing a PIN.
  for (const t of ['keydown', 'keyup', 'keypress'] as const) {
    container.addEventListener(t, (e) => e.stopPropagation());
  }
  shadow.appendChild(container);

  const platform = detectPlatform();
  const source = new TikTokDomVideoSource(platform);
  source.start();
  const nav = platform === 'x' ? new XDomNavigator(source) : new TikTokDomNavigator();
  const playback = new TikTokPlayback(source);

  const root = createRoot(container);
  root.render(<App source={source} navigator={nav} playback={playback} />);

  // Release React effects, runtime ports, polling and playback guards on navigation.
  // A page restored from the back/forward cache receives a fresh overlay below.
  window.addEventListener('pagehide', () => {
    root.unmount();
    playback.dispose();
    source.stop();
    host.remove();
  }, { once: true });
}

mount();
window.addEventListener('pageshow', (event) => {
  if (event.persisted) mount();
});
