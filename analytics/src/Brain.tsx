import { useMemo } from 'react';
import type { BrainRegion } from '@lnz/shared';

/**
 * Stylised lateral brain view. Region intensities come from the Calm classifier's
 * optional `regions` summary. This is a visual summary of a MODEL PREDICTION,
 * not a recording of the viewer's brain.
 */

const CORTEX =
  'M70 160C58 112 92 62 150 46C205 31 275 36 322 70C356 94 372 132 364 168C358 196 338 214 312 218C300 232 278 240 256 236C240 250 214 254 192 246C168 252 136 248 112 234C86 220 74 192 70 160Z';
const CEREBELLUM = 'M262 232C280 220 318 218 336 230C352 242 348 262 326 270C304 278 276 272 264 258C256 250 256 240 262 232Z';
const STEM = 'M236 238C240 256 242 276 238 294L258 294C256 276 258 256 264 240Z';
const SULCI = [
  'M118 196C150 176 196 168 248 172C268 174 282 168 292 160',
  'M236 44C230 78 222 108 214 140C210 152 206 160 202 168',
  'M150 58C160 84 158 110 146 138',
  'M100 120C124 116 150 120 174 132',
  'M280 52C270 82 268 110 276 140',
  'M300 120C318 126 336 140 352 158',
  'M160 214C190 208 220 210 248 204',
  'M190 92C200 104 202 120 198 134',
  'M318 84C312 104 316 122 330 136',
];

export const REGION_META: Record<BrainRegion, { label: string; x: number; y: number }> = {
  frontal: { label: 'Frontal', x: 130, y: 125 },
  parietal: { label: 'Parietal', x: 270, y: 92 },
  temporal: { label: 'Temporal', x: 200, y: 206 },
  occipital: { label: 'Occipital', x: 336, y: 165 },
  limbic: { label: 'Limbic', x: 216, y: 160 },
  cerebellum: { label: 'Cerebellum', x: 304, y: 248 },
};

const ORDER: BrainRegion[] = ['frontal', 'parietal', 'temporal', 'occipital', 'limbic', 'cerebellum'];

interface Props {
  regions?: Partial<Record<BrainRegion, number>>;
  hot: boolean; // score above the user's Calm threshold
  analyzing: boolean;
}

export function Brain({ regions, hot, analyzing }: Props) {
  const dots = useMemo(() => {
    const out: { x: number; y: number; i: number; cb: boolean }[] = [];
    for (let y = 40; y <= 290; y += 10) {
      for (let x = 64; x <= 370; x += 10) {
        const cb = y > 222 && x > 252;
        let sum = 0;
        let w = 0;
        for (const k of ORDER) {
          if (cb !== (k === 'cerebellum')) continue;
          const m = REGION_META[k];
          const d2 = (x - m.x) ** 2 + (y - m.y) ** 2;
          const g = Math.exp(-d2 / (2 * 48 ** 2));
          sum += (regions?.[k] ?? 0) * g;
          w += g;
        }
        out.push({ x, y, i: w > 0 ? sum / w : 0, cb });
      }
    }
    return out;
  }, [regions]);

  const color = hot ? '#FF4D5E' : '#00DDEB';

  return (
    <svg className={`brain ${analyzing ? 'scanning' : ''}`} viewBox="40 24 350 276" role="img" aria-label="Predicted response by brain region">
      <defs>
        <clipPath id="cx">
          <path d={CORTEX} />
        </clipPath>
        <clipPath id="cb">
          <path d={CEREBELLUM} />
        </clipPath>
        <radialGradient id="heat">
          <stop offset="0%" stopColor={color} stopOpacity="0.9" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </radialGradient>
        <linearGradient id="scan" x1="0" x2="1">
          <stop offset="0%" stopColor="#00DDEB" stopOpacity="0" />
          <stop offset="50%" stopColor="#00DDEB" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#00DDEB" stopOpacity="0" />
        </linearGradient>
      </defs>

      <path d={CORTEX} className="b-fill" />
      <path d={CEREBELLUM} className="b-fill" />
      <path d={STEM} className="b-fill stem" />

      <g clipPath="url(#cx)">
        {ORDER.filter((k) => k !== 'cerebellum').map((k) => (
          <circle key={k} cx={REGION_META[k].x} cy={REGION_META[k].y} r={95} fill="url(#heat)" opacity={(regions?.[k] ?? 0) * 0.55} className="heat" />
        ))}
        {dots.filter((d) => !d.cb).map((d) => (
          <circle key={`${d.x}-${d.y}`} cx={d.x} cy={d.y} r={1.5} fill={color} opacity={0.1 + d.i * 0.9} />
        ))}
        {SULCI.map((s, i) => (
          <path key={i} d={s} className="sulcus" />
        ))}
        {analyzing && <rect className="scanbar" x="40" y="24" width="60" height="276" fill="url(#scan)" />}
      </g>
      <g clipPath="url(#cb)">
        <circle cx={REGION_META.cerebellum.x} cy={REGION_META.cerebellum.y} r={60} fill="url(#heat)" opacity={(regions?.cerebellum ?? 0) * 0.55} />
        {dots.filter((d) => d.cb).map((d) => (
          <circle key={`c${d.x}-${d.y}`} cx={d.x} cy={d.y} r={1.3} fill={color} opacity={0.1 + d.i * 0.9} />
        ))}
        <path d="M268 246C290 240 318 240 342 248M272 258C292 254 316 254 334 260" className="sulcus" />
      </g>

      <path d={CORTEX} className="b-edge" />
      <path d={CEREBELLUM} className="b-edge" />
      <path d={STEM} className="b-edge" />

      {ORDER.map((k) => {
        const v = regions?.[k];
        const m = REGION_META[k];
        if (v == null) return null;
        return (
          <g key={k} className="r-tag" transform={`translate(${m.x} ${m.y})`}>
            <circle r={3} fill={color} />
            <circle r={7} fill="none" stroke={color} strokeOpacity={0.4} className={v > 0.6 ? 'ping' : ''} />
          </g>
        );
      })}
    </svg>
  );
}

export { ORDER as REGION_ORDER };
