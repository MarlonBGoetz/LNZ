import type { ReactNode } from 'react';

export function Timeline({ data, threshold, hot }: { data?: number[]; threshold: number; hot: boolean }) {
  const W = 600;
  const H = 110;
  if (!data || data.length < 2) {
    return (
      <div className="timeline empty">
        <span>No per-timestep prediction for this video</span>
      </div>
    );
  }
  const x = (i: number) => (i / (data.length - 1)) * W;
  const y = (v: number) => H - 6 - v * (H - 12);
  const line = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${W} ${H} L0 ${H} Z`;
  const ty = y(threshold);
  const color = hot ? '#FF4D5E' : '#00DDEB';
  return (
    <div className="timeline">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label="Predicted stress response over the video">
        <defs>
          <linearGradient id="tl" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((g) => (
          <line key={g} x1="0" x2={W} y1={y(g)} y2={y(g)} className="grid" />
        ))}
        <path d={area} fill="url(#tl)" />
        <path d={line} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
        <line x1="0" x2={W} y1={ty} y2={ty} className="thresh" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="tl-axis">
        <span>T+0s</span>
        <span>THRESHOLD {Math.round(threshold * 100)}%</span>
        <span>END</span>
      </div>
    </div>
  );
}

export function Ring({ value, label, sub, accent = '#00DDEB', children }: { value?: number; label: string; sub?: string; accent?: string; children?: ReactNode }) {
  const R = 46;
  const C = 2 * Math.PI * R;
  const v = value ?? 0;
  return (
    <div className="ring">
      <svg viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={R} className="ring-bg" />
        {[...Array(40)].map((_, i) => {
          const a = (i / 40) * Math.PI * 2 - Math.PI / 2;
          return <line key={i} x1={60 + Math.cos(a) * 54} y1={60 + Math.sin(a) * 54} x2={60 + Math.cos(a) * 57} y2={60 + Math.sin(a) * 57} className="tick" />;
        })}
        {value != null && (
          <circle
            cx="60"
            cy="60"
            r={R}
            fill="none"
            stroke={accent}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${C * v} ${C}`}
            transform="rotate(-90 60 60)"
            className="ring-arc"
          />
        )}
      </svg>
      <div className="ring-center">
        <b className="mono">{value == null ? '—' : `${Math.round(v * 100)}%`}</b>
        <span>{label}</span>
        {sub && <small>{sub}</small>}
        {children}
      </div>
    </div>
  );
}

export interface Bar {
  id: string;
  value?: number;
  skipped: boolean;
  current: boolean;
}

export function SessionBars({ bars, threshold }: { bars: Bar[]; threshold: number }) {
  return (
    <div className="bars" role="img" aria-label="Predicted stress per video this session">
      <div className="bars-thresh" style={{ bottom: `${threshold * 100}%` }} />
      {bars.map((b) => (
        <div key={b.id} className={`bar ${b.skipped ? 'skip' : ''} ${b.current ? 'cur' : ''}`} title={b.value == null ? 'Unknown' : `${Math.round(b.value * 100)}%`}>
          <i style={{ height: `${Math.max(2, (b.value ?? 0) * 100)}%` }} className={b.value == null ? 'unk' : ''} />
        </div>
      ))}
      {bars.length === 0 && <span className="dim small">Waiting for the first video…</span>}
    </div>
  );
}
