import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  decide,
  type FilterId,
  type LnzConfig,
  type PlaybackController,
  type VideoNavigator,
  type VideoRef,
} from '@lnz/shared';
import { ANALYSIS_PORT, send, type LnzState, type PortIn, type PortOut } from '../lib/messages';
import type { TikTokDomVideoSource } from '../content/tiktok';
import { Launcher } from './Launcher';
import { Onboarding } from './Onboarding';
import { Panel } from './Panel';
import { PinDialog } from './PinDialog';
import { AnalysisSession, classifierKey, visibleResults } from '../lib/analysis';
import { DelayedAutoSkip } from '../lib/autoSkip';

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
  const [analysisSession] = useState(() => new AnalysisSession());
  const [analysis, setAnalysis] = useState(analysisSession.snapshot);
  const [autoSkip] = useState(() => new DelayedAutoSkip());
  const [expanded, setExpanded] = useState<FilterId | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<Anchor>({ top: 88, right: 24 });

  const portRef = useRef<chrome.runtime.Port | null>(null);
  const videoRef = useRef<VideoRef | null>(video);
  const stateRef = useRef<LnzState | null>(null);
  const holdingRef = useRef(false);
  const toastTimer = useRef<number | undefined>(undefined);
  const postedRef = useRef<string>('');
  stateRef.current = state;
  const results = useMemo(() => visibleResults(analysis, video?.videoId, state?.config), [analysis, video?.videoId, state?.config]);

  const flash = useCallback((msg: string) => {
    clearTimeout(toastTimer.current);
    setToast(msg);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);

  useEffect(() => () => {
    autoSkip.cancel();
    clearTimeout(toastTimer.current);
  }, [autoSkip]);

  const applyState = useCallback((next: LnzState) => {
    stateRef.current = next;
    autoSkip.cancel();
    setState(next);
  }, [autoSkip]);

  // ---- background state -------------------------------------------------
  useEffect(() => {
    let alive = true;
    void send({ type: 'getState' }).then((r) => alive && r.state && applyState(r.state));
    return () => { alive = false; };
  }, [applyState]);

  useEffect(() => {
    const onMessage = (message: { type?: string }, sender: chrome.runtime.MessageSender, sendResponse: (response: { ok: boolean }) => void) => {
      if (sender.id !== chrome.runtime.id || message?.type !== 'openOverlay') return false;
      setOpen(true);
      sendResponse({ ok: true });
      return false;
    };
    chrome.runtime.onMessage.addListener(onMessage);
    return () => chrome.runtime.onMessage.removeListener(onMessage);
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
      autoSkip.cancel();
      const snapshot = analysisSession.begin(v, stateRef.current?.config);
      setAnalysis(snapshot);
      if (v && snapshot.request) post({ type: 'analyze', video: v, requestId: snapshot.request.requestId, providerKey: snapshot.request.providerKey });
      else post({ type: 'cancelAnalysis' });
    },
    [post, analysisSession, autoSkip],
  );

  // Port to the service worker; reconnect if the worker restarts.
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const connect = () => {
      const port = chrome.runtime.connect({ name: ANALYSIS_PORT });
      portRef.current = port;
      port.onMessage.addListener((m: PortOut) => {
        if (!alive) return;
        if (m.type === 'state') applyState(m.state);
        if (m.type === 'result') {
          const snapshot = analysisSession.accept(m.requestId, m.providerKey, m.result);
          if (snapshot) setAnalysis(snapshot);
        }
      });
      port.onDisconnect.addListener(() => {
        if (!alive) return;
        portRef.current = null;
        autoSkip.cancel();
        const cleared = analysisSession.begin(null, stateRef.current?.config);
        setAnalysis(cleared);
        timer = window.setTimeout(() => {
          connect();
          analyze(videoRef.current);
        }, 800);
      });
    };
    connect();
    return () => {
      alive = false;
      clearTimeout(timer);
      autoSkip.cancel();
      analysisSession.begin(null, stateRef.current?.config);
      portRef.current?.disconnect();
    };
  }, [analyze, analysisSession, autoSkip, applyState]);

  // ---- active video -----------------------------------------------------
  useEffect(
    () =>
      source.onActiveVideoChange((v) => {
        videoRef.current = v;
        setVideo(v);
        analyze(v);
      }),
    [source, analyze],
  );

  // Re-run analysis when protection is switched on or the classifier source changes.
  const active = state?.config.active ?? false;
  const providerKey = state ? classifierKey(state.config) : '';
  useEffect(() => {
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
  holdingRef.current = holding;
  useEffect(() => {
    if (holding) playback.hold();
    else playback.release();
  }, [holding, playback, video?.videoId]);

  // ---- auto-skip ------------------------------------------------------
  useEffect(() => {
    autoSkip.cancel();
    if (!state || !decision || !video || holding || !analysis.request) return;
    if (!state.config.active || !state.config.autoSkip || decision.verdict !== 'skip') return;
    const request = analysis.request;
    const videoId = video.videoId;
    autoSkip.schedule(videoId, () => {
      const latest = stateRef.current;
      const current = analysisSession.snapshot;
      return !!latest && latest.config.active && latest.config.autoSkip && !holdingRef.current
        && videoRef.current?.videoId === videoId
        && current.request?.requestId === request.requestId
        && current.request?.providerKey === classifierKey(latest.config)
        && decide(videoId, latest.config.filters, current.results).verdict === 'skip';
    }, () => {
      const latest = stateRef.current!;
      const current = decide(videoId, latest.config.filters, analysisSession.snapshot.results);
      const reason = current.rejectedBy.map((id) => current.rules[id].reason).join(' · ');
      flash(`Skipping · ${reason}`);
      post({ type: 'skip', videoId, reason });
      void navigator.skipToNext(reason).catch(() => flash('Could not skip this video'));
    });
    return () => autoSkip.cancel();
  }, [decision, state, video, holding, navigator, post, analysis.request, analysisSession, autoSkip, flash]);

  // ---- actions --------------------------------------------------------
  const requestUnlock = (reason: string) => {
    autoSkip.cancel();
    holdingRef.current = true;
    setPinPrompt(reason);
  };

  const onLockClick = async () => {
    if (!state) return;
    if (!editing) return requestUnlock('Unlock to edit your filters');
    const r = await send({ type: 'saveAndLock', config: draft ?? state.config });
    if (r.state) applyState(r.state);
    if (r.ok) {
      flash('Saved · Protected');
    }
  };

  const onCancelEdit = async () => {
    const r = await send({ type: 'cancelEdit' });
    if (r.state) applyState(r.state);
    setDraft(null);
  };

  const onPower = async (next: boolean) => {
    if (!state) return;
    if (editing) return setDraft((d) => ({ ...(d ?? state.config), active: next }));
    if (!next) return requestUnlock('Unlock to turn LNZ off');
    const r = await send({ type: 'setActive', active: true });
    if (r.state) applyState(r.state);
  };

  const onUnlock = async (pin: string): Promise<string | null> => {
    const r = await send({ type: 'unlock', pin });
    if (r.state) applyState(r.state);
    if (r.ok) {
      setPinPrompt(null);
      return null;
    }
    return r.error;
  };

  const onSetup = async (pin: string, config: LnzConfig): Promise<string | null> => {
    const r = await send({ type: 'setupPin', pin, config });
    if (r.state) applyState(r.state);
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
          results={results}
          decision={decision}
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
