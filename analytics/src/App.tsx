import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  ANALYTICS_STREAM_PATH,
  MASK_PATH,
  SHIELD_CATEGORIES,
  categoryLabel,
  decide,
  scoreLevel,
  verdictLabel,
  type AnalyticsEvent,
  type ClassifierResult,
  type FilterId,
} from '@lnz/shared';
import { REGION_META, REGION_ORDER } from './Brain';
import { DayView } from './Day';
import { Ring, SessionBars, type Bar } from './Charts';
import { emptyStore, filtersOf, reduce, startDemoStream, type Store } from './store';

type Action = { ev: AnalyticsEvent; demo: boolean } | { reset: true };
const reducer = (s: Store, a: Action): Store => ('reset' in a ? emptyStore() : reduce(s, a.ev, a.demo));

const params = new URLSearchParams(location.search);
const USER_NAME = params.get('user') ?? 'Marlon G.';
const USER_ROLE = params.get('role') ?? 'Session owner';
const initials = USER_NAME.split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase();

export function App() {
  const [store, dispatch] = useReducer(reducer, undefined, emptyStore);
  const [relay, setRelay] = useState<'connecting' | 'open' | 'down'>('connecting');
  const [demo, setDemo] = useState(params.get('demo') === '1');
  const [view, setView] = useState<'session' | 'day'>('session');
  const [now, setNow] = useState(Date.now());
  const started = useRef(Date.now());

  // Live events from the local relay.
  useEffect(() => {
    const es = new EventSource(ANALYTICS_STREAM_PATH);
    es.onopen = () => setRelay('open');
    es.onerror = () => setRelay('down');
    es.onmessage = (m) => {
      try {
        dispatch({ ev: JSON.parse(m.data) as AnalyticsEvent, demo: false });
      } catch {
        /* ignore malformed */
      }
    };
    return () => es.close();
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const linked = store.lastExtensionAt != null && now - store.lastExtensionAt < 60_000;

  // Demo stream stops automatically once the real extension is talking.
  useEffect(() => {
    if (linked && demo) setDemo(false);
  }, [linked, demo]);
  useEffect(() => {
    if (!demo) return;
    dispatch({ reset: true });
    return startDemoStream((ev) => dispatch({ ev, demo: true }));
  }, [demo]);

  const filters = filtersOf(store);
  const cur = store.currentId ? store.videos[store.currentId] : undefined;
  const calm = cur?.results.calm;
  const learn = cur?.results.learn;
  const shield = cur?.results.shield;
  const calmScore = calm?.state === 'ready' && calm.output?.kind === 'score' ? calm.output : undefined;
  const learnScore = learn?.state === 'ready' && learn.output?.kind === 'score' ? learn.output.score : undefined;
  const flagged = shield?.state === 'ready' && shield.output?.kind === 'categories' ? shield.output.flagged : undefined;
  const hot = calmScore != null && calmScore.score > filters.calm.threshold;
  const isDemo = demo || [calm, learn, shield].some((r) => r?.isDemo);

  const decision = useMemo(
    () => (cur ? cur.decision ?? decide(cur.video.videoId, filters, cur.results) : undefined),
    [cur, filters],
  );

  const bars: Bar[] = store.order.slice(-28).map((id) => {
    const v = store.videos[id];
    const o = v.results.calm?.output;
    return { id, value: o?.kind === 'score' ? o.score : undefined, skipped: !!v.skipped || v.decision?.verdict === 'skip', current: id === store.currentId };
  });

  const stats = useMemo(() => {
    const vs = store.order.map((id) => store.videos[id]);
    const scores = vs.map((v) => v.results.calm?.output).filter((o): o is { kind: 'score'; score: number } => o?.kind === 'score').map((o) => o.score);
    const lat = vs.flatMap((v) => Object.values(v.results)).map((r) => r?.latencyMs).filter((x): x is number => typeof x === 'number');
    const skipped = vs.filter((v) => v.skipped || v.decision?.verdict === 'skip').length;
    return {
      analyzed: vs.length,
      skipped,
      kept: vs.filter((v) => v.decision && v.decision.verdict !== 'skip' && v.decision.verdict !== 'pending').length,
      avg: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : undefined,
      lat: lat.length ? Math.round(lat.reduce((a, b) => a + b, 0) / lat.length) : undefined,
    };
  }, [store]);

  const elapsed = Math.floor((now - started.current) / 1000);
  const clock = `T+${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <svg viewBox="0 0 100 100" width="26" height="26" aria-hidden="true">
            <path d={MASK_PATH} fill="currentColor" fillRule="evenodd" />
          </svg>
          <b>LNZ</b>
          <span className="sep" />
          <span className="title">{view === 'day' ? 'Day Summary' : 'Live Analysis'}</span>
        </div>
        <nav className="platform-switch" aria-label="Demo surfaces">
          <a className="platform-link" href="/stage/tiktok.html" target="_blank" rel="noreferrer" title="TikTok stage" aria-label="TikTok stage">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M15 3v10.5a3.5 3.5 0 1 1-2.2-3.3V6.1A5.8 5.8 0 0 0 18 8V5.6A3.4 3.4 0 0 1 15 3Z" /></svg>
          </a>
          <a className="platform-link" href="/stage/x.html?platform=x" target="_blank" rel="noreferrer" title="X stage" aria-label="X stage">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M5 4l5.7 7.4L4.8 20h2.5l4.6-6 4.5 6h2.9l-6.2-8.1L19.7 4h-2.5l-4 5.4L9 4H5Z" /></svg>
          </a>
          <span className="platform-sep" aria-hidden="true" />
          <a className="platform-link live" href="https://www.tiktok.com/foryou" target="_blank" rel="noreferrer" title="Live on tiktok.com" aria-label="Live TikTok on tiktok.com">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M15 3v10.5a3.5 3.5 0 1 1-2.2-3.3V6.1A5.8 5.8 0 0 0 18 8V5.6A3.4 3.4 0 0 1 15 3Z" /></svg>
            <i className="live-dot" aria-hidden="true" />
          </a>
          <a className="platform-link live" href="https://x.com/home" target="_blank" rel="noreferrer" title="Live on x.com" aria-label="Live X on x.com">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M5 4l5.7 7.4L4.8 20h2.5l4.6-6 4.5 6h2.9l-6.2-8.1L19.7 4h-2.5l-4 5.4L9 4H5Z" /></svg>
            <i className="live-dot" aria-hidden="true" />
          </a>
        </nav>
        <div className="pills">
          <Pill on={relay === 'open'} label={relay === 'open' ? 'RELAY' : relay === 'down' ? 'RELAY DOWN' : 'RELAY …'} />
          <Pill on={linked} label={linked ? 'EXTENSION LINKED' : 'NO EXTENSION'} />
          {store.config && <Pill on={store.config.locked} label={store.config.locked ? 'PROTECTED' : 'EDIT MODE'} />}
          {view === 'session' && isDemo && <span className="pill demo">DEMO DATA</span>}
        </div>
        <div className="right">
          {view === 'session' ? (
            <>
              <span className="mono clock">{clock}</span>
              <button
                type="button"
                className={`ghost-btn ${demo ? 'on' : ''}`}
                onClick={() => setDemo((d) => !d)}
                disabled={linked}
                title={linked ? 'Live extension data is streaming' : 'Synthetic fixture stream for rehearsals'}
              >
                {demo ? 'Stop demo' : 'Run demo'}
              </button>
            </>
          ) : (
            <span className="pill on">
              <i />
              LOCAL ONLY
            </span>
          )}
          <div className="user">
            <span className="avatar">{initials}</span>
            <span className="who">
              <b>{USER_NAME}</b>
              <small>{USER_ROLE}</small>
            </span>
          </div>
        </div>
      </header>

      <nav className="view-tabs" role="tablist" aria-label="Dashboard view">
        <button
          type="button"
          role="tab"
          aria-selected={view === 'session'}
          className={view === 'session' ? 'on' : ''}
          onClick={() => setView('session')}
        >
          Session
        </button>
        <button type="button" role="tab" aria-selected={view === 'day'} className={view === 'day' ? 'on' : ''} onClick={() => setView('day')}>
          Day
        </button>
        <span className="view-spacer" />
        <span className="mono dim small">{view === 'day' ? 'LOCAL DAY LOG · AUTO 30s' : 'LIVE SESSION'}</span>
      </nav>

      {view === 'session' ? (
        <>
      <section className="card now-card">
        <div className="now-left">
          <span className="eyebrow">CURRENT VIDEO {cur?.video.index ? `· #${String(cur.video.index).padStart(3, '0')}` : ''}</span>
          <h1 title={cur?.video.title}>{cur ? cur.video.title || 'Untitled video' : 'Waiting for a video…'}</h1>
          <span className="mono dim">
            {cur ? `${cur.video.author ? '@' + cur.video.author.replace(/^@/, '') + '  ·  ' : ''}ID ${cur.video.videoId}` : 'Open TikTok in Chrome with LNZ enabled, or run the demo.'}
          </span>
        </div>
        <div className={`verdict ${decision?.verdict ?? 'none'}`}>
          <span className="eyebrow">DECISION</span>
          <b>{decision ? verdictLabel(decision.verdict) : '—'}</b>
          <small>
            {decision?.verdict === 'skip'
              ? decision.rejectedBy.map((id) => decision.rules[id].reason).join(' · ')
              : decision?.verdict === 'keep-unverified'
                ? 'Some enabled filters unavailable'
                : decision?.verdict === 'keep'
                  ? 'All enabled filters pass'
                  : ''}
          </small>
        </div>
      </section>

      <div className="quad">
        <section className="card brain-card">
          <div className="card-head">
            <span className="eyebrow">01 · NEURAL RESPONSE MODEL · CALM</span>
            <ModelTag r={calm} fallback="TRIBE v2-derived · distilled" />
          </div>
          <div className="calm-row">
            <div className={`calm-score mono ${hot ? 'hot' : ''}`}>
              {calmScore ? Math.round(calmScore.score * 100) : calm?.state === 'analyzing' ? <span className="skel" /> : '—'}
              {calmScore && <span className="unit">%</span>}
            </div>
            <div className="calm-meta">
              <div className="lvl-row">
                <span className={`lvl ${scoreLevel(calmScore?.score).toLowerCase()}`}>{scoreLevel(calmScore?.score).toUpperCase()}</span>
                <span className="dim small">
                  {stateText(calm)} · threshold {Math.round(filters.calm.threshold * 100)}%{filters.calm.enabled ? '' : ' · off'}
                </span>
              </div>
              <div className="meter">
                <i style={{ width: `${(calmScore?.score ?? 0) * 100}%` }} className={hot ? 'hot' : ''} />
                <b style={{ left: `${filters.calm.threshold * 100}%` }} />
              </div>
            </div>
          </div>
          <div className="region-grid" aria-label="Predicted regional response">
            {REGION_ORDER.slice(0, 4).map((k) => (
              <RegionTile key={k} label={REGION_META[k].label} value={calmScore?.regions?.[k]} hot={hot} />
            ))}
          </div>
          <div className="region-sub">
            {REGION_ORDER.slice(4).map((k) => {
              const v = calmScore?.regions?.[k];
              return (
                <div className="region-chip" key={k}>
                  <span>{REGION_META[k].label}</span>
                  <i><b style={{ width: `${(v ?? 0) * 100}%` }} /></i>
                  <b className="mono">{v == null ? '—' : Math.round(v * 100)}</b>
                </div>
              );
            })}
          </div>
          <p className="fine">Model prediction of the stimulus-driven response to this video. It is not a measurement of the viewer.</p>
        </section>

        <section className="card">
          <div className="card-head">
            <span className="eyebrow">02 · LEARN</span>
            <ModelTag r={learn} fallback="VLM · transcript" />
          </div>
          <Ring value={learnScore} label="EDUCATIONAL" sub={learn && learn.state !== 'ready' ? stateText(learn) : scoreLevel(learnScore).toUpperCase()} />
          <div className="rule-line">
            <span>Keep ≥ {Math.round(filters.learn.minScore * 100)}%</span>
            <RuleTag v={decision?.rules.learn.verdict} />
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <span className="eyebrow">03 · SHIELD</span>
            <ModelTag r={shield} fallback="Safety classifier" />
          </div>
          <div className="shield-state">
            {flagged == null ? (
              <span className="dim">{stateText(shield)}</span>
            ) : flagged.length === 0 ? (
              <b className="ok">No flagged categories</b>
            ) : (
              <b className="bad">Flagged · {flagged.map(categoryLabel).join(', ')}</b>
            )}
          </div>
          <div className="cat-grid">
            {SHIELD_CATEGORIES.map((c) => {
              const sel = filters.shield.categories.includes(c.id);
              const hit = flagged?.includes(c.id);
              return (
                <span key={c.id} className={`cat ${sel ? 'sel' : ''} ${hit ? 'hit' : ''}`} title={c.label}>
                  <i className="mono">{c.id}</i>
                  {c.label}
                </span>
              );
            })}
          </div>
          <div className="rule-line">
            <span>{filters.shield.categories.length} categories blocked</span>
            <RuleTag v={decision?.rules.shield.verdict} />
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <span className="eyebrow">04 · FILTER RULES</span>
          </div>
          <div className="rules">
            {(['calm', 'learn', 'shield'] as FilterId[]).map((id) => {
              const rule = decision?.rules[id];
              return (
                <div key={id} className="rule">
                  <span className="rname">{id.toUpperCase()}</span>
                  <RuleTag v={rule?.verdict} />
                  <small>{rule?.reason ?? (filters[id].enabled ? 'Waiting' : 'Filter off')}</small>
                </div>
              );
            })}
          </div>
          <div className="stats">
            <Stat k="ANALYZED" v={stats.analyzed} />
            <Stat k="SKIPPED" v={stats.skipped} />
            <Stat k="KEPT" v={stats.kept} />
            <Stat k="AVG LAT" v={stats.lat == null ? '—' : `${stats.lat}ms`} />
          </div>
        </section>
      </div>

      <section className="card session">
        <div className="card-head">
          <span className="eyebrow">05 · SESSION · PREDICTED STRESS PER VIDEO</span>
          <span className="mono dim small">AVG {stats.avg == null ? '—' : `${Math.round(stats.avg * 100)}%`}</span>
        </div>
        <SessionBars bars={bars} threshold={filters.calm.threshold} />
      </section>

      <section className="card log">
        <div className="card-head">
          <span className="eyebrow">06 · TELEMETRY</span>
        </div>
        <ol>
          {store.log.slice(0, 14).map((l, i) => (
            <li key={`${l.at}-${i}`} className={`mono k-${l.kind}`}>
              <time>{new Date(l.at).toLocaleTimeString([], { hour12: false })}</time>
              <span>{l.text}</span>
            </li>
          ))}
          {store.log.length === 0 && <li className="mono dim">No events yet.</li>}
        </ol>
      </section>
        </>
      ) : (
        <DayView />
      )}
    </div>
  );
}

function RegionTile({ label, value, hot }: { label: string; value?: number; hot: boolean }) {
  const v = value ?? 0;
  const tone = hot ? '255, 77, 94' : '0, 221, 235';
  return (
    <div
      className={`region-tile ${value != null && value >= 0.5 ? 'strong' : ''} ${value == null ? 'empty' : ''}`}
      style={{
        background: `linear-gradient(155deg, rgba(${tone}, ${0.035 + v * 0.22}), rgba(10, 14, 18, 0.94))`,
        borderColor: `rgba(${tone}, ${0.12 + v * 0.42})`,
        boxShadow: `inset 0 0 ${Math.round(6 + v * 28)}px rgba(${tone}, ${0.05 + v * 0.22})`,
      }}
    >
      <span>{label}</span>
      <b className="mono">{value == null ? '—' : Math.round(value * 100)}</b>
      <i><span style={{ width: `${v * 100}%`, background: `rgb(${tone})` }} /></i>
    </div>
  );
}

function stateText(r?: ClassifierResult): string {
  if (!r) return 'Waiting';
  switch (r.state) {
    case 'waiting':
      return 'Waiting';
    case 'analyzing':
      return 'Analyzing';
    case 'ready':
      return 'Ready';
    case 'unavailable':
      return 'Unavailable';
    case 'error':
      return 'Error';
  }
}

function Pill({ on, label }: { on: boolean; label: string }) {
  return (
    <span className={`pill ${on ? 'on' : ''}`}>
      <i />
      {label}
    </span>
  );
}

function ModelTag({ r, fallback }: { r?: ClassifierResult; fallback: string }) {
  return (
    <span className="model mono">
      {r?.isDemo ? 'DEMO FIXTURE' : r?.model ?? fallback}
      {r?.latencyMs != null && ` · ${r.latencyMs}ms`}
    </span>
  );
}

function RuleTag({ v }: { v?: string }) {
  const t = v ?? 'pending';
  return <span className={`rtag ${t}`}>{t === 'reject' ? 'REJECT' : t === 'pass' ? 'PASS' : t === 'off' ? 'OFF' : t === 'unknown' ? 'UNKNOWN' : '…'}</span>;
}

function Stat({ k, v }: { k: string; v: number | string }) {
  return (
    <div className="stat">
      <b className="mono">{v}</b>
      <span>{k}</span>
    </div>
  );
}
