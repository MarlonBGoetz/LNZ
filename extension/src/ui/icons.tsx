import type { SVGProps } from 'react';
import { MASK_PATH } from '@lnz/shared';

type P = SVGProps<SVGSVGElement> & { size?: number };

export function MaskIcon({ size = 24, filled = true, ...rest }: P & { filled?: boolean }) {
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden="true" {...rest}>
      <path
        d={MASK_PATH}
        fillRule="evenodd"
        fill={filled ? 'currentColor' : 'none'}
        stroke={filled ? 'none' : 'currentColor'}
        strokeWidth={filled ? 0 : 4.5}
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Line({ size = 18, children, ...rest }: P) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

/** Calm: minimal brain with a calm wave through it. */
export const CalmIcon = (p: P) => (
  <Line {...p}>
    <path d="M12 5.2c-1-1.4-3.4-1.6-4.6-.2-1.6-.2-3 1.2-2.8 2.8-1.6.8-2 3-.8 4.2-.8 1.6 0 3.6 1.8 4 .4 1.8 2.4 2.8 4 2 .9.9 1.8 1 2.4.6" />
    <path d="M12 5.2c1-1.4 3.4-1.6 4.6-.2 1.6-.2 3 1.2 2.8 2.8 1.6.8 2 3 .8 4.2.8 1.6 0 3.6-1.8 4-.4 1.8-2.4 2.8-4 2-.9.9-1.8 1-2.4.6" />
    <path d="M12 5.2v13.4" />
    <path d="M6.6 12.2c1-1 1.9-1 2.8 0s1.8 1 2.6 0 1.8-1 2.6 0 1.8 1 2.8 0" />
  </Line>
);

/** Learn: open book. */
export const LearnIcon = (p: P) => (
  <Line {...p}>
    <path d="M12 6.5C10.3 5.3 7.6 4.8 4 5v12.8c3.6-.2 6.3.3 8 1.5 1.7-1.2 4.4-1.7 8-1.5V5c-3.6-.2-6.3.3-8 1.5z" />
    <path d="M12 6.5v12.8" />
  </Line>
);

/** Shield: minimal shield. */
export const ShieldIcon = (p: P) => (
  <Line {...p}>
    <path d="M12 3.5 5 6v5.6c0 4.3 2.9 7.5 7 8.9 4.1-1.4 7-4.6 7-8.9V6l-7-2.5z" />
  </Line>
);

export const LockIcon = ({ open = false, ...p }: P & { open?: boolean }) => (
  <Line {...p}>
    <rect x="5" y="10.5" width="14" height="9.5" rx="2.2" />
    {open ? <path d="M8.5 10.5V7.8a3.5 3.5 0 0 1 6.8-1.2" /> : <path d="M8.5 10.5V7.8a3.5 3.5 0 0 1 7 0v2.7" />}
    <path d="M12 14.4v2" />
  </Line>
);

export const ChevronIcon = (p: P) => (
  <Line {...p}>
    <path d="m8 10 4 4 4-4" />
  </Line>
);

export const CloseIcon = (p: P) => (
  <Line {...p}>
    <path d="M7 7l10 10M17 7 7 17" />
  </Line>
);

export const PowerIcon = (p: P) => (
  <Line {...p}>
    <path d="M12 4v7" />
    <path d="M7.4 6.8a7 7 0 1 0 9.2 0" />
  </Line>
);

export const EyeIcon = ({ off = false, ...p }: P & { off?: boolean }) => (
  <Line {...p}>
    <path d="M2.8 12S6.2 6 12 6s9.2 6 9.2 6-3.4 6-9.2 6-9.2-6-9.2-6z" />
    <circle cx="12" cy="12" r="2.6" />
    {off && <path d="M4 4l16 16" />}
  </Line>
);

export const CheckIcon = (p: P) => (
  <Line {...p}>
    <path d="m6 12.5 4 4 8-9" />
  </Line>
);

export const GearIcon = (p: P) => (
  <Line {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M18 6l-1.6 1.6M7.6 16.4 6 18M18 18l-1.6-1.6M7.6 7.6 6 6" />
  </Line>
);

export const FILTER_ICONS = { calm: CalmIcon, learn: LearnIcon, shield: ShieldIcon } as const;
