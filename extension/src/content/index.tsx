import { createRoot } from 'react-dom/client';
import { App } from '../ui/App';
import css from '../ui/overlay.css?inline';
import { TikTokDomNavigator, TikTokDomVideoSource, TikTokPlayback } from './tiktok';

/**
 * Content script entry. Mounts the LNZ overlay in a closed Shadow DOM so TikTok's
 * styles cannot leak in and ours cannot leak out.
 */
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

  const source = new TikTokDomVideoSource();
  source.start();
  const nav = new TikTokDomNavigator();
  const playback = new TikTokPlayback(source);

  createRoot(container).render(<App source={source} navigator={nav} playback={playback} />);
}

mount();
