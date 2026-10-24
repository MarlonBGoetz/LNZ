import { useState } from 'react';
import {
  FILTERS,
  verdictLabel,
  type ClassifierResult,
  type Decision,
  type FilterId,
  type LnzConfig,
  type VideoRef,
} from '@lnz/shared';
import type { ResultMap } from '@lnz/shared';
import type { LnzState } from '../lib/messages';
import { ChevronIcon, CloseIcon, GearIcon, LockIcon, MaskIcon, PowerIcon } from './icons';
import { ModeCard } from './ModeCard';
import { Switch } from './Switch';

interface Props {
  state: LnzState;
  config: LnzConfig; // draft while editing, saved config while locked
  editing: boolean;
  video: VideoRef | null;
  results: ResultMap;
  decision: Decision | null;
  expanded: FilterId | null;
  setExpanded: (id: FilterId | null) => void;
  onChange: (c: LnzConfig) => void;
  onLockClick: () => void;
  onCancelEdit: () => void;
  onCollapse: () => void;
  onLockedAttempt: (reason: string) => void;
  onPower: (active: boolean) => void;
}

export function Panel(p: Props) {
  const { state, config, editing, video, results, decision } = p;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const locked = !editing;
  const status = !config.active ? 'OFF' : editing ? 'EDIT MODE' : 'PROTECTED';
  const isDemo = Object.values(results).some((result) => result?.isDemo)
    || (Object.keys(results).length === 0 && config.providers.mode === 'demo');

  return (
    <section className={`panel ${editing ? 'is-editing' : 'is-locked'} ${config.active ? '' : 'is-off'}`} aria-label="LNZ panel">
      <header className="panel-head">
        <span className={`brand ${config.active ? 'on' : ''}`}>
          <MaskIcon size={20} filled={config.active} />
          <b>LNZ</b>
        </span>
        <span className={`status-chip ${status === 'EDIT MODE' ? 'edit' : status === 'OFF' ? 'off' : 'prot'}`}>{status}</span>
        <span className="grow" />
        <button
          type="button"
          className={`icon-btn lock-btn ${locked ? 'closed' : 'open'}`}
          aria-label={locked ? 'Unlock to edit' : 'Save and lock'}
          title={locked ? 'Unlock to edit' : 'Save & lock'}
          onClick={p.onLockClick}
        >
          <LockIcon size={17} open={!locked} />
        </button>
        <button type="button" className="icon-btn" aria-label="Collapse panel" title="Collapse" onClick={p.onCollapse}>
          <CloseIcon size={16} />
        </button>
      </header>

      <div className="power-row">
        <PowerIcon size={15} />
        <span>Filtering</span>
        <span className="grow" />
        <Switch
          checked={config.active}
          label="LNZ filtering"
          locked={locked && config.active}
          onChange={(v) => p.onPower(v)}
        />
      </div>

      <div className="now">
        <div className="now-top">
          <span className="eyebrow">NOW</span>
          <AnalysisChip results={results} video={video} active={config.active} />
          {isDemo && <span className="demo-tag" title="No models connected. Values are illustrative fixtures.">DEMO DATA</span>}
        </div>
        <div className="now-title" title={video?.title}>
          {video ? (video.title || video.videoId) : 'No video detected'}
        </div>
        {video?.author && <div className="now-sub">@{video.author.replace(/^@/, '')} · #{video.index ?? '–'}</div>}
      </div>

      <div className="modes">
        {FILTERS.map((f) => (
          <ModeCard
            key={f.id}
            meta={f}
            filters={config.filters}
            result={results[f.id]}
            rule={decision?.rules[f.id] ?? { verdict: 'off' }}
            availability={state.availability[f.id]}
            editing={editing}
            expanded={p.expanded === f.id}
            onExpand={() => p.setExpanded(p.expanded === f.id ? null : f.id)}
            onChange={(filters) => p.onChange({ ...config, filters })}
            onLockedAttempt={p.onLockedAttempt}
          />
        ))}
      </div>

      {decision && video && config.active && (
        <div className={`decision ${decision.verdict}`}>
          <span className="eyebrow">DECISION</span>
          <b>{verdictLabel(decision.verdict)}</b>
          {decision.verdict === 'skip' && (
            <span className="why">{decision.rejectedBy.map((id) => decision.rules[id].reason).join(' · ')}</span>
          )}
          {decision.verdict === 'keep-unverified' && <span className="why">Some enabled filters are unavailable</span>}
        </div>
      )}

      <div className="settings">
        <button type="button" className="settings-head" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((s) => !s)}>
          <GearIcon size={14} />
          <span>Settings</span>
          <span className="grow" />
          <span className={`chev ${settingsOpen ? 'up' : ''}`}>
            <ChevronIcon size={14} />
          </span>
        </button>
        {settingsOpen && (
          <div className="settings-body">
            <div className="set-row">
              <span>Auto-skip rejected videos</span>
              <Switch
                checked={config.autoSkip}
                label="Auto-skip"
                locked={locked}
                onChange={(autoSkip) => (editing ? p.onChange({ ...config, autoSkip }) : p.onLockedAttempt('Unlock to change auto-skip'))}
              />
            </div>
            <div className="set-row">
              <span>Classifiers</span>
              <div className="seg" role="radiogroup" aria-label="Classifier source">
                {(['demo', 'http'] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="radio"
                    aria-checked={config.providers.mode === m}
                    className={config.providers.mode === m ? 'on' : ''}
                    onClick={() =>
                      editing
                        ? p.onChange({ ...config, providers: { ...config.providers, mode: m } })
                        : p.onLockedAttempt('Unlock to change classifier source')
                    }
                  >
                    {m === 'demo' ? 'Demo' : 'Local service'}
                  </button>
                ))}
              </div>
            </div>
            {config.providers.mode === 'http' && (
              <TextRow
                label="Service URL"
                value={config.providers.baseUrl}
                editing={editing}
                onLocked={() => p.onLockedAttempt('Unlock to change the service URL')}
                onChange={(baseUrl) => p.onChange({ ...config, providers: { ...config.providers, baseUrl } })}
              />
            )}
            <TextRow
              label="Analytics URL"
              value={config.analyticsUrl}
              editing={editing}
              onLocked={() => p.onLockedAttempt('Unlock to change the analytics URL')}
              onChange={(analyticsUrl) => p.onChange({ ...config, analyticsUrl })}
            />
            <div className="set-row">
              <span className={`avail ${state.analyticsConnected ? 'connected' : 'unavailable'}`}>
                <i />
                {state.analyticsConnected ? 'Dashboard linked' : 'Dashboard not linked'}
              </span>
              <a className="link" href={config.analyticsUrl} target="_blank" rel="noreferrer">
                Open dashboard ↗
              </a>
            </div>
            <p className="fine">The PIN adds friction to changing settings. It can't stop the extension being removed in Chrome.</p>
          </div>
        )}
      </div>

      {editing ? (
        <footer className="panel-foot">
          <button type="button" className="btn ghost" onClick={p.onCancelEdit}>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={p.onLockClick}>
            <LockIcon size={14} /> Save & lock
          </button>
        </footer>
      ) : (
        <footer className="panel-foot muted">
          <LockIcon size={12} /> Locked · changes need your PIN
        </footer>
      )}
    </section>
  );
}

function AnalysisChip({ results, video, active }: { results: ResultMap; video: VideoRef | null; active: boolean }) {
  const list = Object.values(results).filter(Boolean) as ClassifierResult[];
  let s: 'Waiting' | 'Analyzing' | 'Ready' | 'Unavailable' | 'Error' = 'Waiting';
  if (active && video && list.length) {
    if (list.some((r) => r.state === 'analyzing' || r.state === 'waiting')) s = 'Analyzing';
    else if (list.some((r) => r.state === 'ready')) s = 'Ready';
    else if (list.some((r) => r.state === 'error')) s = 'Error';
    else s = 'Unavailable';
  }
  return (
    <span className={`a-chip ${s.toLowerCase()}`}>
      {s === 'Analyzing' && <span className="spinner" aria-hidden="true" />}
      {s}
    </span>
  );
}

function TextRow({ label, value, editing, onChange, onLocked }: { label: string; value: string; editing: boolean; onChange: (v: string) => void; onLocked: () => void }) {
  return (
    <label className="set-row col">
      <span>{label}</span>
      <input
        className="text"
        type="url"
        value={value}
        readOnly={!editing}
        onFocus={() => !editing && onLocked()}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
      />
    </label>
  );
}
