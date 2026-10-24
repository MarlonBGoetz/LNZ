import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  decide,
  type FilterId,
  type LnzConfig,
  type PlaybackController,
  type ResultMap,
  type VideoNavigator,
  type VideoRef,
} from '@lnz/shared';
import { ANALYSIS_PORT, send, type LnzState, type PortIn, type PortOut } from '../lib/messages';
import type { TikTokDomVideoSource } from '../content/tiktok';
import { Launcher } from './Launcher';
import { Onboarding } from './Onboarding';
import { Panel } from './Panel';
import { PinDialog } from './PinDialog';

interface Props {
  source: TikTokDomVideoSource;
  navigator: VideoNavigator;
  playback: PlaybackController;
}

interface Anchor {
  top: number;
  right: number;
}

const LAUNCHER = 44;

export function App({ source, navigator, playback }: Props) {
  const [state, setState] = useState<LnzState | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<LnzConfig | null>(null);
  const [pinPrompt, setPinPrompt] = useState<string | null>(null);
  const [video, setVideo] = useState<VideoRef | null>(source.current());
  const [results, setResults] = useState<ResultMap>({});
  const [expanded, setExpanded] = useState<FilterId | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<Anchor>({ top: 88, right: 24 });

  const portRef = useRef<chrome.runtime.Port | null>(null);
  const videoRef = useRef<VideoRef | null>(video);
  const stateRef = useRef<LnzState | null>(null);
  const skippedRef = useRef<string | null>(null);
  const postedRef = useRef<string>('');
  stateRef.current = state;

  // ---- background state -------------------------------------------------
  useEffect(() => {
    void send({ type: 'getState' }).then((r) => r.state && setState(r.state));
  }, []);

  const post = useCallback((m: PortIn) => {
    try {
      portRef.current?.postMessage(m);
    } catch {
      /* reconnecting */
    }
  }, []);

  const analyze = useCallback(
    (v: VideoRef | null) => {
      if (v && stateRef.current?.config.active) post({ type: 'analyze', video: v });
    },
    [post],
  );

  // Port to the service worker; reconnect if the worker restarts.
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const connect = () => {
      const port = chrome.runtime.connect({ name: ANALYSIS_PORT });
      portRef.current = port;
      port.onMessage.addListener((m: PortOut) => {
        if (m.type === 'state') setState(m.state);
        if (m.type === 'result' && m.result.videoId === videoRef.current?.videoId) {
          setResults((prev) => ({ ...prev, [m.result.filterId]: m.result }));
        }
      });
      port.onDisconnect.addListener(() => {
        portRef.current = null;
        if (alive) timer = window.setTimeout(() => {
          connect();
          analyze(videoRef.current);
        }, 800);
      });
    };
    connect();
    return () => {
      alive = false;
      clearTimeout(timer);
      portRef.current?.disconnect();
    };
  }, [analyze]);

  // ---- active video -----------------------------------------------------
  useEffect(
    () =>
      source.onActiveVideoChange((v) => {
        videoRef.current = v;
        setVideo(v);
        setResults({}); // never show the previous video's results
        analyze(v);
      }),
    [source, analyze],
  );

  // Re-run analysis when protection is switched on or the classifier source changes.
  const active = state?.config.active ?? false;
  const providerKey = `${state?.config.providers.mode}|${state?.config.providers.baseUrl}`;
  useEffect(() => {
    if (!active) return setResults({});
    analyze(videoRef.current);
  }, [active, providerKey, analyze]);

  // ---- launcher placement: top-right of the active video -----------------
  useEffect(() => {
    const t = window.setInterval(() => {
      const el = source.element();
      if (!el) return setAnchor((a) => (a.top === 88 && a.right === 24 ? a : { top: 88, right: 24 }));
      const r = el.getBoundingClientRect();
      const top = Math.round(Math.min(Math.max(12, r.top + 14), innerHeight - LAUNCHER - 12));
      const right = Math.round(Math.max(12, innerWidth - r.right + 14));
      setAnchor((a) => (a.top === top && a.right === right ? a : { top, right }));
    }, 250);
    return () => clearInterval(t);
  }, [source]);

  // ---- edit mode / draft -----------------------------------------------
  const editing = !!state?.unlocked;
  useEffect(() => {
    if (!state) return;
    if (state.unlocked) {
      setDraft((d) => d ?? structuredClone(state.config));
      setOpen(true);
    } else setDraft(null);
  }, [state?.unlocked]);

  const shown: LnzConfig | null = editing && draft ? draft : state?.config ?? null;

  // ---- decision (always from the SAVED config) ----------------------------
  const decision = useMemo(
    () => (state && video ? decide(video.videoId, state.config.filters, results) : null),
    [state, video, results],
  );

  useEffect(() => {
    if (!decision || decision.verdict === 'pending') return;
    const key = `${decision.videoId}:${decision.verdict}:${decision.rejectedBy.join(',')}`;
    if (key === postedRef.current) return;
    postedRef.current = key;
    post({ type: 'decision', decision });
  }, [decision, post]);

  // ---- hold playback while the user is changing settings ------------------
  const holding = !!state && (!state.hasPin || !!pinPrompt || editing);
  useEffect(() => {
    if (holding) playback.hold();
    else playback.release();
  }, [holding, playback, video?.videoId]);

  // ---- auto-skip ------------------------------------------------------
  useEffect(() => {
    if (!state || !decision || !video || holding) return;
    if (!state.config.active || !state.config.autoSkip || decision.verdict !== 'skip') return;
    if (skippedRef.current === video.videoId) return;
    skippedRef.current = video.videoId;
    const reason = decision.rejectedBy.map((id) => decision.rules[id].reason).join(' · ');
    flash(`Skipped · ${reason}`);
    post({ type: 'skip', videoId: video.videoId, reason });
    // Not cleared on re-render: the skip is committed once skippedRef is set.
    window.setTimeout(() => {
      if (videoRef.current?.videoId === video.videoId) void navigator.skipToNext(reason);
    }, 650);
  }, [decision, state, video, holding, navigator, post]);

  const flash = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast((t) => (t === msg ? null : t)), 2600);
  };

  // ---- actions --------------------------------------------------------
  const requestUnlock = (reason: string) => setPinPrompt(reason);

  const onLockClick = async () => {
    if (!state) return;
    if (!editing) return requestUnlock('Unlock to edit your filters');
    const r = await send({ type: 'saveAndLock', config: draft ?? state.config });
    if (r.state) setState(r.state);
    if (r.ok) {
      flash('Saved · Protected');
      skippedRef.current = null;
    }
  };

  const onCancelEdit = async () => {
    const r = await send({ type: 'cancelEdit' });
    if (r.state) setState(r.state);
    setDraft(null);
  };

  const onPower = async (next: boolean) => {
    if (!state) return;
    if (editing) return setDraft((d) => ({ ...(d ?? state.config), active: next }));
    if (!next) return requestUnlock('Unlock to turn LNZ off');
    const r = await send({ type: 'setActive', active: true });
    if (r.state) setState(r.state);
  };

  const onUnlock = async (pin: string): Promise<string | null> => {
    const r = await send({ type: 'unlock', pin });
    if (r.state) setState(r.state);
    if (r.ok) {
      setPinPrompt(null);
      return null;
    }
    return r.error;
  };

  const onSetup = async (pin: string, config: LnzConfig): Promise<string | null> => {
    const r = await send({ type: 'setupPin', pin, config });
    if (r.state) setState(r.state);
    if (r.ok) flash('PIN set · Protected');
    return r.ok ? null : r.error;
  };

  if (!state || !shown) return null;

  return (
    <>
      <div className="anchor" style={{ top: anchor.top, right: anchor.right }}>
        <Launcher
          active={shown.active}
          locked={!editing}
          open={open}
          filters={shown.filters}
          onToggle={() => setOpen((o) => !o)}
          onFilter={(id) => {
            setExpanded(id);
            setOpen(true);
          }}
        />
        {open && (
          <Panel
            state={state}
            config={shown}
            editing={editing}
            video={video}
            results={results}
            decision={decision}
            expanded={expanded}
            setExpanded={setExpanded}
            onChange={setDraft}
            onLockClick={onLockClick}
            onCancelEdit={onCancelEdit}
            onCollapse={() => setOpen(false)}
            onLockedAttempt={requestUnlock}
            onPower={onPower}
          />
        )}
        {toast && (
          <div className="toast" role="status">
            {toast}
          </div>
        )}
      </div>

      {!state.hasPin && <Onboarding onComplete={onSetup} />}
      {state.hasPin && pinPrompt && (
        <PinDialog
          title="Enter your PIN"
          subtitle={pinPrompt}
          lockedUntil={state.throttle.lockedUntil}
          onSubmit={onUnlock}
          onCancel={() => setPinPrompt(null)}
        />
      )}
    </>
  );
}
