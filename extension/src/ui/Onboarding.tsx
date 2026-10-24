import { useState } from 'react';
import { DEFAULT_CONFIG, FILTERS, pct, type FilterId, type LnzConfig } from '@lnz/shared';
import { isValidPin } from '../lib/pin';
import { EyeIcon, FILTER_ICONS, MaskIcon } from './icons';
import { Switch } from './Switch';

interface Props {
  onComplete: (pin: string, config: LnzConfig) => Promise<string | null>;
}

export function Onboarding({ onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [pin, setPin] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [config, setConfig] = useState<LnzConfig>(structuredClone(DEFAULT_CONFIG));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const pinOk = isValidPin(pin) && pin === confirm;
  const digits = (v: string) => v.replace(/\D/g, '').slice(0, 6);

  const finish = async () => {
    setBusy(true);
    const err = await onComplete(pin, config);
    setBusy(false);
    if (err) setError(err);
  };

  return (
    <div className="backdrop solid">
      <div className="dialog onboarding" role="dialog" aria-modal="true" aria-labelledby="lnz-ob-title">
        <div className="steps" aria-label={`Step ${step + 1} of 3`}>
          {[0, 1, 2].map((i) => (
            <i key={i} className={i <= step ? 'on' : ''} />
          ))}
        </div>

        {step === 0 && (
          <>
            <div className="hero-mask">
              <MaskIcon size={56} />
            </div>
            <h2 id="lnz-ob-title">Welcome to LNZ</h2>
            <p className="sub">Take control of your feed. Pick what you want to see, then lock it with a PIN.</p>
            <ul className="ob-filters">
              {FILTERS.map((f) => {
                const Icon = FILTER_ICONS[f.id];
                return (
                  <li key={f.id}>
                    <span className="mode-icon on">
                      <Icon size={18} />
                    </span>
                    <span>
                      <b>{f.name}</b>
                      <small>{f.tagline}</small>
                    </span>
                  </li>
                );
              })}
            </ul>
            <p className="fine">Calm uses a model prediction about the video. It does not measure your stress.</p>
            <div className="dialog-actions">
              <button type="button" className="btn primary wide" onClick={() => setStep(1)}>
                Get started
              </button>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <h2 id="lnz-ob-title">Create your PIN</h2>
            <p className="sub">4–6 digits. You'll need it to change filters or turn LNZ off.</p>
            <div className="pin-field">
              <input
                type={show ? 'text' : 'password'}
                inputMode="numeric"
                autoComplete="new-password"
                aria-label="New PIN"
                placeholder="New PIN"
                value={pin}
                autoFocus
                onChange={(e) => setPin(digits(e.target.value))}
              />
              <button type="button" className="icon-btn" aria-label={show ? 'Hide PIN' : 'Show PIN'} onClick={() => setShow((s) => !s)}>
                <EyeIcon size={16} off={show} />
              </button>
            </div>
            <div className="pin-field">
              <input
                type={show ? 'text' : 'password'}
                inputMode="numeric"
                autoComplete="new-password"
                aria-label="Confirm PIN"
                placeholder="Confirm PIN"
                value={confirm}
                onChange={(e) => setConfirm(digits(e.target.value))}
                onKeyDown={(e) => e.key === 'Enter' && pinOk && setStep(2)}
              />
            </div>
            <p className="pin-err" role="alert">
              {confirm.length >= 4 && pin !== confirm ? 'PINs do not match' : '\u00a0'}
            </p>
            <div className="dialog-actions">
              <button type="button" className="btn ghost" onClick={() => setStep(0)}>
                Back
              </button>
              <button type="button" className="btn primary" disabled={!pinOk} onClick={() => setStep(2)}>
                Continue
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h2 id="lnz-ob-title">Choose your filters</h2>
            <p className="sub">You can change these later with your PIN.</p>
            <div className="ob-config">
              {FILTERS.map((f) => {
                const id = f.id as FilterId;
                const Icon = FILTER_ICONS[id];
                const fc = config.filters[id];
                const set = (patch: object) =>
                  setConfig((c) => ({ ...c, filters: { ...c.filters, [id]: { ...c.filters[id], ...patch } } }));
                return (
                  <div key={id} className={`ob-row ${fc.enabled ? 'on' : ''}`}>
                    <div className="ob-row-top">
                      <span className={`mode-icon ${fc.enabled ? 'on' : ''}`}>
                        <Icon size={18} />
                      </span>
                      <b>{f.name}</b>
                      <Switch checked={fc.enabled} onChange={(enabled) => set({ enabled })} label={`${f.name} filter`} />
                    </div>
                    {fc.enabled && id === 'calm' && (
                      <Range label="Skip above" value={config.filters.calm.threshold} onChange={(threshold) => set({ threshold })} />
                    )}
                    {fc.enabled && id === 'learn' && (
                      <Range label="Keep at least" value={config.filters.learn.minScore} onChange={(minScore) => set({ minScore })} />
                    )}
                    {fc.enabled && id === 'shield' && (
                      <small className="dim">{config.filters.shield.categories.length} categories selected · edit later in the panel</small>
                    )}
                  </div>
                );
              })}
              <div className="ob-row on">
                <div className="ob-row-top">
                  <b>Auto-skip</b>
                  <Switch checked={config.autoSkip} onChange={(autoSkip) => setConfig((c) => ({ ...c, autoSkip }))} label="Auto-skip" />
                </div>
              </div>
            </div>
            <p className="pin-err" role="alert">
              {error ?? '\u00a0'}
            </p>
            <div className="dialog-actions">
              <button type="button" className="btn ghost" onClick={() => setStep(1)}>
                Back
              </button>
              <button type="button" className="btn primary" disabled={busy} onClick={finish}>
                {busy ? 'Locking…' : 'Save & lock'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Range({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="slider">
      <span className="slider-top">
        <span>{label}</span>
        <b className="num">{pct(value)}</b>
      </span>
      <input type="range" min={0} max={1} step={0.01} value={value} onChange={(e) => onChange(Number(e.target.value))}
        style={{ ['--v' as string]: `${value * 100}%` }} />
    </label>
  );
}
