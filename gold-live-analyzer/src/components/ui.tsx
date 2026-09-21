'use client';

import type { ReactNode } from 'react';

export function Card({
  title,
  subtitle,
  action,
  children,
  className = '',
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold tracking-wide text-[var(--color-text)]">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-[var(--color-muted)]">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Badge({
  tone = 'neutre',
  children,
}: {
  tone?: 'neutre' | 'hausse' | 'baisse' | 'alerte' | 'or';
  children: ReactNode;
}) {
  const tones: Record<string, string> = {
    neutre: 'bg-[var(--color-surface-2)] text-[var(--color-muted)] border-[var(--color-border)]',
    hausse: 'bg-[rgba(34,197,139,0.12)] text-[var(--color-bull)] border-[rgba(34,197,139,0.35)]',
    baisse: 'bg-[rgba(240,85,108,0.12)] text-[var(--color-bear)] border-[rgba(240,85,108,0.35)]',
    alerte: 'bg-[rgba(245,165,36,0.12)] text-[var(--color-warn)] border-[rgba(245,165,36,0.35)]',
    or: 'bg-[rgba(240,180,41,0.12)] text-[var(--color-gold)] border-[rgba(240,180,41,0.35)]',
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function Meter({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const color =
    pct >= 75 ? 'var(--color-bull)' : pct >= 45 ? 'var(--color-gold)' : 'var(--color-muted)';
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]">
      <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

/** Jauge -100 / +100 avec le zero au centre. */
export function BiasGauge({ score }: { score: number }) {
  const clamped = Math.max(-100, Math.min(100, score));
  const half = Math.abs(clamped) / 2;
  const bullish = clamped >= 0;
  return (
    <div className="relative h-2 w-full rounded-full bg-[var(--color-surface-2)]">
      <div className="absolute left-1/2 top-0 h-full w-px bg-[var(--color-border)]" />
      <div
        className="absolute top-0 h-full rounded-full transition-all duration-500"
        style={{
          width: `${half}%`,
          left: bullish ? '50%' : `${50 - half}%`,
          background: bullish ? 'var(--color-bull)' : 'var(--color-bear)',
        }}
      />
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">{label}</p>
      <p className="num mt-0.5 text-sm font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </p>
    </div>
  );
}
