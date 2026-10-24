import {
  FILTERS,
  type Decision,
  type FilterConfig,
  type FilterId,
  type ResultMap,
} from '@lnz/shared';
import { FILTER_ICONS, LockIcon, MaskIcon } from './icons';
import { filterHeat, overallHeat, type Heat } from './heat';

interface Props {
  active: boolean;
  locked: boolean;
  open: boolean;
  filters: FilterConfig;
  results: ResultMap;
  decision: Decision | null;
  onToggle: () => void;
  onFilter: (id: FilterId) => void;
}

/**
 * Compact floating launcher.
 *  ON  -> mask filled electric cyan with a soft glow, filter sub-icons shown below.
 *  OFF -> mask as grey outline only, no fill.
 *
 * The collapsed rail is a live heat barometer: each icon carries a health ring
 * (green clear, amber pending/moderate/uncertain, red would reject) and a dot on
 * the launcher summarises the current video.
 */
export function Launcher({ active, locked, open, filters, results, decision, onToggle, onFilter }: Props) {
  const heats = Object.fromEntries(
    FILTERS.map((f) => [
      f.id,
      filterHeat(
        f.id,
        results[f.id],
        decision?.rules[f.id] ?? { verdict: filters[f.id].enabled ? 'pending' : 'off' },
        filters[f.id].enabled,
      ),
    ]),
  ) as Record<FilterId, Heat>;
  const overall = overallHeat(heats, filters, active);

  return (
    <div className="launcher-wrap">
      <button
        type="button"
        className={`launcher ${active ? 'active' : 'inactive'} ${open ? 'open' : ''}`}
        aria-label={`LNZ ${active ? 'on' : 'off'}, ${locked ? 'locked' : 'unlocked'}. ${overall.label}. ${open ? 'Collapse' : 'Open'} panel`}
        aria-expanded={open}
        onClick={onToggle}
      >
        <MaskIcon size={27} filled={active} />
        {active && <span className={`launcher-heat tone-${overall.tone}`} title={overall.detail} aria-hidden="true" />}
        <span className={`launcher-lock ${locked ? 'closed' : 'open'}`}>
          <LockIcon size={10} open={!locked} />
        </span>
      </button>

      {active && !open && (
        <div className="rail" role="toolbar" aria-label="LNZ filters, current video heat">
          {FILTERS.map((f) => {
            const Icon = FILTER_ICONS[f.id];
            const on = filters[f.id].enabled;
            const heat = heats[f.id];
            const analyzing = heat.label === 'Analyzing';
            const title = `${f.name} · ${heat.label}${heat.detail && heat.detail !== heat.label ? ` · ${heat.detail}` : ''}`;
            return (
              <button
                key={f.id}
                type="button"
                className={`rail-btn ${on ? 'on' : ''} tone-${heat.tone} ${analyzing ? 'is-analyzing' : ''}`}
                aria-label={`${f.name}: ${on ? 'on' : 'off'}, ${heat.label}. ${heat.detail}`}
                title={title}
                onClick={() => onFilter(f.id)}
              >
                <HeatRing heat={heat} />
                <span className="rail-icon">
                  <Icon size={16} />
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** 34px ring with a 2px health arc; pathLength makes the arithmetic simple. */
function HeatRing({ heat }: { heat: Heat }) {
  const dash = heat.tone === 'idle' ? 0 : Math.max(heat.tone === 'bad' ? 7 : 0, Math.round(heat.level * 100));
  return (
    <svg className={`heat-ring tone-${heat.tone}`} viewBox="0 0 34 34" aria-hidden="true">
      <circle className="heat-track" cx="17" cy="17" r="15" />
      {dash > 0 && (
        <circle
          className="heat-arc"
          cx="17"
          cy="17"
          r="15"
          pathLength={100}
          strokeDasharray={`${dash} 100`}
        />
      )}
    </svg>
  );
}
