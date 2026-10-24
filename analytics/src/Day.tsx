import { useEffect, useMemo, useState } from 'react';
import {
  ANALYTICS_DAY_PATH,
  categoryLabel,
  summarizeDay,
  type AnalyticsEvent,
  type DaySummary as DayData,
  type DayVideo,
} from '@lnz/shared';

const pad = (n: number) => String(n).padStart(2, '0');
const localDay = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const prettyDate = (date: string) =>
  new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
const time = (at: number | null) =>
  at == null ? '—' : new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const pct = (value: number | null | undefined) => (value == null ? '—' : `${Math.round(value * 100)}%`);
const decisionLabel = (v: DayVideo['decision']) =>
  v === 'keep' ? 'KEEP' : v === 'skip' ? 'SKIP' : v === 'keep-unverified' ? 'KEEP · UNVERIFIED' : 'PENDING';

export function DayView() {
  const today = localDay();
  const [date, setDate] = useState(today);
  const [events, setEvents] = useState<AnalyticsEvent[] | null>(null);
  const [error, setError] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setError(false);
    fetch(`${ANALYTICS_DAY_PATH}?date=${encodeURIComponent(date)}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ date: string; events: AnalyticsEvent[] }>;
      })
      .then((payload) => {
        if (alive) setEvents(payload.events);
      })
      .catch(() => {
        if (alive) {
          setEvents([]);
          setError(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [date, tick]);

  useEffect(() => {
    const interval = setInterval(() => setTick((n) => n + 1), 30_000);
    return () => clearInterval(interval);
  }, []);

  const summary: DayData | null = useMemo(() => (events ? summarizeDay(events, date) : null), [events, date]);
  const maxHour = summary ? Math.max(1, ...summary.hours.map((h) => h.watched)) : 1;
  const platformTotal = summary ? summary.platforms.tiktok + summary.platforms.x : 0;
  const totalFlags = summary ? summary.flagged.reduce((sum, flag) => sum + flag.count, 0) : 0;

  return (
    <div className="day">
      {error && (
        <div className="day-banner" role="status">
          Local relay unavailable. Start it with <span className="mono">npm run dev:analytics</span>; the day log lives in
          <span className="mono"> analytics/.data</span>.
        </div>
      )}

      <section className="card day-head">
        <div className="day-head-main">
          <div className="day-head-badges">
            <span className="eyebrow">LOCAL DAY SUMMARY · NO CLOUD</span>
            {summary?.demo && <span className="pill demo">DEMO DATA</span>}
          </div>
          <h1>{summary && summary.watched === 0 ? 'A quiet day so far' : 'Day at a glance'}</h1>
          <p className="dim small">
            {prettyDate(date)} · {summary?.watched ?? 0} unique videos · {summary?.sessions ?? 0} sessions · stored only in
            <span className="mono"> analytics/.data</span>
          </p>
        </div>
        <div className="day-controls">
          <label className="day-date">
            <span>Day</span>
            <input type="date" value={date} max={today} onChange={(e) => e.target.value && setDate(e.target.value)} />
          </label>
          <button type="button" className="ghost-btn" onClick={() => setTick((n) => n + 1)}>
            Refresh
          </button>
          <button type="button" className="ghost-btn" onClick={() => setDate(today)} disabled={date === today}>
            Today
          </button>
        </div>
      </section>

      {!summary ? (
        <div className="card day-loading" role="status">
          <span className="skel" /> <span className="dim">Loading the local day log…</span>
        </div>
      ) : (
        <>
          <div className="day-stats">
            <DayStat label="WATCHED" value={summary.watched} />
            <DayStat label="KEPT" value={summary.kept} tone="good" />
            <DayStat label="SKIPPED" value={summary.skipped} tone="bad" />
            <DayStat label="ANALYZED" value={summary.analyzed} />
            <DayStat label="AVG STRESS" value={pct(summary.avgCalm)} />
            <DayStat label="AVG LEARNING" value={pct(summary.avgLearn)} />
          </div>

          <section className="card day-timeline">
            <div className="card-head">
              <span className="eyebrow">WATCHED BY HOUR</span>
              <span className="mono dim small">
                {summary.watched} videos · max {maxHour}
              </span>
            </div>
            {summary.watched === 0 ? (
              <div className="day-empty">No videos recorded for {prettyDate(date)}. Open TikTok or X with LNZ running.</div>
            ) : (
              <div className="day-chart">
                {summary.hours.map((hour) => (
                  <div className="day-col" key={hour.hour}>
                    <div className="day-track">
                      <div
                        className={`day-stack ${hour.watched ? '' : 'empty'}`}
                        style={{ height: `${hour.watched ? Math.max(6, (hour.watched / maxHour) * 112) : 2}px` }}
                        title={`${pad(hour.hour)}:00 · ${hour.watched} watched · ${hour.kept} kept · ${hour.skipped} skipped`}
                      >
                        {hour.kept > 0 && <i className="kept" style={{ flex: hour.kept }} />}
                        {hour.skipped > 0 && <i className="skipped" style={{ flex: hour.skipped }} />}
                        {hour.pending > 0 && <i className="pending" style={{ flex: hour.pending }} />}
                      </div>
                    </div>
                    <span className={hour.hour % 3 === 0 ? 'on' : ''}>{pad(hour.hour)}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="day-legend">
              <span><i className="kept" /> kept</span>
              <span><i className="skipped" /> skipped</span>
              <span><i className="pending" /> pending</span>
            </div>
          </section>

          <div className="day-split">
            <section className="card">
              <div className="card-head">
                <span className="eyebrow">PLATFORMS</span>
                <span className="mono dim small">{platformTotal} videos</span>
              </div>
              <div className="day-platform">
                <span>TikTok</span>
                <span className="day-platform-bar">
                  <i style={{ width: `${platformTotal ? (summary.platforms.tiktok / platformTotal) * 100 : 0}%` }} />
                </span>
                <b className="mono">{summary.platforms.tiktok}</b>
              </div>
              <div className="day-platform">
                <span>X</span>
                <span className="day-platform-bar x">
                  <i style={{ width: `${platformTotal ? (summary.platforms.x / platformTotal) * 100 : 0}%` }} />
                </span>
                <b className="mono">{summary.platforms.x}</b>
              </div>
              <p className="fine">Unique videos per platform. X posts and TikTok clips share the same filters.</p>
            </section>

            <section className="card">
              <div className="card-head">
                <span className="eyebrow">SHIELD FLAGS</span>
                <span className="mono dim small">{totalFlags} total</span>
              </div>
              {summary.flagged.length === 0 ? (
                <div className="day-quiet">No flagged categories today.</div>
              ) : (
                <div className="day-flags">
                  {summary.flagged.slice(0, 6).map((flag) => (
                    <div className="day-flag" key={flag.id}>
                      <span className="mono">{flag.id}</span>
                      <span>{categoryLabel(flag.id)}</span>
                      <b className="mono">{flag.count}</b>
                    </div>
                  ))}
                </div>
              )}
              <p className="fine">Categorical safety labels; no probabilities are implied.</p>
            </section>

            <section className="card">
              <div className="card-head">
                <span className="eyebrow">SESSIONS</span>
              </div>
              <div className="day-big">
                <b>{summary.sessions}</b>
                <span>sessions</span>
              </div>
              <div className="day-meta">
                <span>First activity</span>
                <b className="mono">{time(summary.firstAt)}</b>
              </div>
              <div className="day-meta">
                <span>Last activity</span>
                <b className="mono">{time(summary.lastAt)}</b>
              </div>
              <div className="day-meta">
                <span>Pending analysis</span>
                <b className="mono">{summary.pending}</b>
              </div>
              <p className="fine">A new session starts after a 30-minute gap.</p>
            </section>
          </div>

          <section className="card day-recent">
            <div className="card-head">
              <span className="eyebrow">RECENTLY WATCHED</span>
              <span className="mono dim small">latest {summary.recent.length}</span>
            </div>
            {summary.recent.length === 0 ? (
              <div className="day-quiet">Nothing recorded for this day yet.</div>
            ) : (
              <ol className="day-recent-list">
                {summary.recent.map((video) => (
                  <li key={`${video.platform}:${video.videoId}`}>
                    <span className={`platform-tag ${video.platform}`}>{video.platform === 'x' ? 'X' : 'TikTok'}</span>
                    <div className="recent-main">
                      <b title={video.title}>{video.title}</b>
                      <small>
                        {video.author ? `@${video.author.replace(/^@/, '')} · ` : ''}
                        {time(video.at)}
                      </small>
                    </div>
                    <span className="recent-scores mono">
                      C {pct(video.calm)} · L {pct(video.learn)}
                    </span>
                    <span className={`rtag ${video.decision}`}>{decisionLabel(video.decision)}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <p className="day-footnote">
            Day totals are computed from the local JSONL log in <span className="mono">analytics/.data</span>. Keeping the
            dashboard relay running is what records the day; nothing leaves this machine.
          </p>
        </>
      )}
    </div>
  );
}

function DayStat({ label, value, tone }: { label: string; value: number | string; tone?: 'good' | 'bad' }) {
  return (
    <div className={`day-stat ${tone ?? ''}`}>
      <b className="mono">{value}</b>
      <span>{label}</span>
    </div>
  );
}
