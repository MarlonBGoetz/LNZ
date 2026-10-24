import {
  SHIELD_CATEGORIES,
  categoryLabel,
  pct,
  scoreLevel,
  type ClassifierResult,
  type FilterConfig,
  type FilterId,
  type FilterMeta,
  type ProviderAvailability,
  type RuleOutcome,
} from '@lnz/shared';
import { CheckIcon, ChevronIcon, FILTER_ICONS } from './icons';
import { Switch } from './Switch';

interface Props {
  meta: FilterMeta;
  filters: FilterConfig;
  result?: ClassifierResult;
  rule: RuleOutcome;
  availability: ProviderAvailability;
  editing: boolean;
  expanded: boolean;
  onExpand: () => void;
  onChange: (next: FilterConfig) => void;
  onLockedAttempt: (reason: string) => void;
}

export function ModeCard({ meta, filters, result, rule, availability, editing, expanded, onExpand, onChange, onLockedAttempt }: Props) {
  const id = meta.id as FilterId;
  const cfg = filters[id];
  const Icon = FILTER_ICONS[id];
  const analyzing = result?.state === 'analyzing' || result?.state === 'waiting';
  const avail: ProviderAvailability = analyzing ? 'analyzing' : availability;

  const setEnabled = (enabled: boolean) => {
    if (!editing) return onLockedAttempt(`Unlock to ${enabled ? 'enable' : 'disable'} ${meta.name}`);
    onChange({ ...filters, [id]: { ...cfg, enabled } } as FilterConfig);
  };

  return (
    <div className={`mode ${cfg.enabled ? 'enabled' : 'disabled'} ${editing ? 'editing' : ''} ${rule.verdict === 'reject' ? 'rejecting' : ''}`}>
      <div className="mode-row" onClick={onExpand} role="button" tabIndex={0} aria-expanded={expanded}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onExpand())}>
        <span className="mode-icon">
          <Icon size={18} />
          {editing && cfg.enabled && (
            <span className="mode-check">
              <CheckIcon size={9} />
            </span>
          )}
        </span>
        <span className="mode-main">
          <span className="mode-name">{meta.name}</span>
          <span className="mode-value">{valueText(id, result)}</span>
        </span>
        <span className={`avail ${avail}`} title={`Model ${avail}`}>
          <i />
          {avail === 'connected' ? 'Connected' : avail === 'analyzing' ? 'Analyzing' : 'Unavailable'}
        </span>
        <Switch checked={cfg.enabled} onChange={setEnabled} label={`${meta.name} filter`} locked={!editing} />
        <span className={`chev ${expanded ? 'up' : ''}`}>
          <ChevronIcon size={14} />
        </span>
      </div>

      {expanded && (
        <div className="mode-body">
          <p className="mode-desc">{meta.description}</p>
          {id === 'calm' && (
            <Slider
              label="Skip when predicted stress is above"
              value={filters.calm.threshold}
              editing={editing}
              onLocked={() => onLockedAttempt('Unlock to change the Calm threshold')}
              onChange={(threshold) => onChange({ ...filters, calm: { ...filters.calm, threshold } })}
            />
          )}
          {id === 'learn' && (
            <Slider
              label="Keep when educational value is at least"
              value={filters.learn.minScore}
              editing={editing}
              onLocked={() => onLockedAttempt('Unlock to change the Learn minimum')}
              onChange={(minScore) => onChange({ ...filters, learn: { ...filters.learn, minScore } })}
            />
          )}
          {id === 'shield' && (
            <div className="cats" role="group" aria-label="Shield categories">
              {SHIELD_CATEGORIES.map((c) => {
                const on = filters.shield.categories.includes(c.id);
                const flagged = result?.output?.kind === 'categories' && result.output.flagged.includes(c.id);
                return (
                  <button
                    key={c.id}
                    type="button"
                    aria-pressed={on}
                    className={`cat ${on ? 'on' : ''} ${flagged ? 'flagged' : ''}`}
                    onClick={() => {
                      if (!editing) return onLockedAttempt('Unlock to change Shield categories');
                      const categories = on ? filters.shield.categories.filter((x) => x !== c.id) : [...filters.shield.categories, c.id];
                      onChange({ ...filters, shield: { ...filters.shield, categories } });
                    }}
                  >
                    {c.label}
                  </button>
                );
              })}
            </div>
          )}
          <div className="mode-foot">
            <span>{meta.modelHint}</span>
            {result?.isDemo && <span className="demo-tag">DEMO</span>}
          </div>
          {rule.reason && rule.verdict !== 'off' && <div className={`rule ${rule.verdict}`}>{rule.reason}</div>}
        </div>
      )}
    </div>
  );
}

function valueText(id: FilterId, r?: ClassifierResult) {
  if (!r || r.state === 'waiting') return <span className="dim">Waiting</span>;
  if (r.state === 'analyzing') return <span className="skeleton" aria-label="Analyzing" />;
  if (r.state === 'unavailable') return <span className="dim">Unknown · unavailable</span>;
  if (r.state === 'error') return <span className="err">Unknown · error</span>;
  const o = r.output;
  if (!o) return <span className="dim">Unknown</span>;
  if (o.kind === 'categories') {
    return o.flagged.length === 0 ? (
      <span>No flagged categories</span>
    ) : (
      <span className="err">Flagged · {o.flagged.map(categoryLabel).join(', ')}</span>
    );
  }
  const lvl = scoreLevel(o.score);
  return (
    <span>
      <b className="num">{pct(o.score)}</b> <span className={`lvl ${lvl.toLowerCase()} ${id}`}>{lvl.toUpperCase()}</span>
    </span>
  );
}

function Slider({ label, value, editing, onChange, onLocked }: { label: string; value: number; editing: boolean; onChange: (v: number) => void; onLocked: () => void }) {
  return (
    <label className={`slider ${editing ? '' : 'ro'}`} onPointerDown={() => !editing && onLocked()}>
      <span className="slider-top">
        <span>{label}</span>
        <b className="num">{pct(value)}</b>
      </span>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={value}
        disabled={!editing}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ ['--v' as string]: `${value * 100}%` }}
      />
    </label>
  );
}
