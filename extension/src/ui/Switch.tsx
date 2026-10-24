interface SwitchProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  locked?: boolean;
}

/** Accessible toggle. When `locked`, it still receives clicks so the parent can open the PIN dialog. */
export function Switch({ checked, onChange, label, locked }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`switch ${checked ? 'on' : ''} ${locked ? 'locked' : ''}`}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
    >
      <span className="knob" />
    </button>
  );
}
