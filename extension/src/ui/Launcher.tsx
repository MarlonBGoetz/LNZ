import { FILTERS, type FilterConfig, type FilterId } from '@lnz/shared';
import { FILTER_ICONS, LockIcon, MaskIcon } from './icons';

interface Props {
  active: boolean;
  locked: boolean;
  open: boolean;
  filters: FilterConfig;
  onToggle: () => void;
  onFilter: (id: FilterId) => void;
}

/**
 * Compact floating launcher.
 *  ON  -> mask filled electric cyan with a soft glow, filter sub-icons shown below.
 *  OFF -> mask as grey outline only, no fill.
 */
export function Launcher({ active, locked, open, filters, onToggle, onFilter }: Props) {
  return (
    <div className="launcher-wrap">
      <button
        type="button"
        className={`launcher ${active ? 'active' : 'inactive'} ${open ? 'open' : ''}`}
        aria-label={`LNZ ${active ? 'on' : 'off'}, ${locked ? 'locked' : 'unlocked'}. ${open ? 'Collapse' : 'Open'} panel`}
        aria-expanded={open}
        onClick={onToggle}
      >
        <MaskIcon size={28} filled={active} />
        <span className={`launcher-lock ${locked ? 'closed' : 'open'}`}>
          <LockIcon size={10} open={!locked} />
        </span>
      </button>

      {active && !open && (
        <div className="rail" role="toolbar" aria-label="LNZ filters">
          {FILTERS.map((f) => {
            const Icon = FILTER_ICONS[f.id];
            const on = filters[f.id].enabled;
            return (
              <button
                key={f.id}
                type="button"
                className={`rail-btn ${on ? 'on' : ''}`}
                aria-label={`${f.name}: ${on ? 'on' : 'off'}`}
                title={`${f.name} · ${on ? 'On' : 'Off'}`}
                onClick={() => onFilter(f.id)}
              >
                <Icon size={15} />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
