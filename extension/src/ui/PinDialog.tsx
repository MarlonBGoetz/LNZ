import { useEffect, useRef, useState } from 'react';
import { EyeIcon, LockIcon } from './icons';

interface Props {
  title: string;
  subtitle?: string;
  lockedUntil: number;
  onSubmit: (pin: string) => Promise<string | null>; // returns error message or null on success
  onCancel: () => void;
}

export function PinDialog({ title, subtitle, lockedUntil, onSubmit, onCancel }: Props) {
  const [pin, setPin] = useState('');
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    if (lockedUntil <= Date.now()) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [lockedUntil]);

  const wait = Math.max(0, Math.ceil((lockedUntil - now) / 1000));

  const submit = async () => {
    if (busy || wait > 0 || pin.length < 4) return;
    setBusy(true);
    const err = await onSubmit(pin);
    setBusy(false);
    if (err) {
      setError(err);
      setPin('');
      input.current?.focus();
    }
  };

  return (
    <div className="backdrop" onClick={onCancel}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="lnz-pin-title" onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === 'Escape' && onCancel()}>
        <div className="dialog-icon">
          <LockIcon size={22} />
        </div>
        <h2 id="lnz-pin-title">{title}</h2>
        {subtitle && <p className="sub">{subtitle}</p>}
        <div className={`pin-field ${error ? 'shake' : ''}`} key={error ?? 'ok'}>
          <input
            ref={input}
            type={show ? 'text' : 'password'}
            inputMode="numeric"
            autoComplete="off"
            pattern="\d*"
            maxLength={6}
            aria-label="PIN"
            aria-invalid={!!error}
            aria-describedby="lnz-pin-err"
            placeholder="••••"
            value={pin}
            disabled={wait > 0}
            onChange={(e) => {
              setPin(e.target.value.replace(/\D/g, '').slice(0, 6));
              setError(null);
            }}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
          <button type="button" className="icon-btn" aria-label={show ? 'Hide PIN' : 'Show PIN'} onClick={() => setShow((s) => !s)}>
            <EyeIcon size={16} off={show} />
          </button>
        </div>
        <p id="lnz-pin-err" className="pin-err" role="alert">
          {wait > 0 ? `Too many attempts. Try again in ${wait}s.` : error ?? '\u00a0'}
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn primary" disabled={busy || wait > 0 || pin.length < 4} onClick={submit}>
            {busy ? 'Checking…' : 'Unlock'}
          </button>
        </div>
      </div>
    </div>
  );
}
