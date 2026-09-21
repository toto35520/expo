'use client';

import type { Signal, SignalStatus } from '@/lib/engine/signals';
import { Badge, Card, Meter } from './ui';

const STATUS_TONE: Record<SignalStatus, 'neutre' | 'hausse' | 'baisse' | 'alerte'> = {
  ACTIF: 'alerte',
  TP1: 'hausse',
  TP2: 'hausse',
  GAGNANT: 'hausse',
  PERDANT: 'baisse',
  EXPIRE: 'neutre',
};

const STATUS_LABEL: Record<SignalStatus, string> = {
  ACTIF: 'En cours',
  TP1: 'TP1 atteint',
  TP2: 'TP2 atteint',
  GAGNANT: 'Gagnant',
  PERDANT: 'Stop touche',
  EXPIRE: 'Expire',
};

export function SignalFeed({
  signals,
  stats,
}: {
  signals: Signal[];
  stats: { total: number; wins: number; losses: number; winRate: number; expectancy: number };
}) {
  return (
    <Card
      title="Signaux en direct"
      subtitle={
        stats.total > 0
          ? `${stats.total} clotures · ${stats.wins} gagnants · ${stats.winRate.toFixed(0)} % · esperance ${stats.expectancy >= 0 ? '+' : ''}${stats.expectancy.toFixed(2)} R`
          : "Aucun signal cloture pour l'instant"
      }
    >
      {signals.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--color-border)] p-6 text-center">
          <p className="text-sm text-[var(--color-muted)]">
            Aucun signal pour le moment. Le moteur surveille le marche en continu et
            affichera ici chaque opportunite des qu&apos;elle se presente.
          </p>
        </div>
      ) : (
        <div className="max-h-[560px] space-y-3 overflow-y-auto pr-1">
          {signals.map((signal) => (
            <SignalCard key={signal.id} signal={signal} />
          ))}
        </div>
      )}
    </Card>
  );
}

function SignalCard({ signal }: { signal: Signal }) {
  const buy = signal.direction === 'BUY';
  const color = buy ? 'var(--color-bull)' : 'var(--color-bear)';
  const risk = signal.risk;

  return (
    <article
      className="slide-in rounded-xl border bg-[var(--color-surface-2)] p-3"
      style={{ borderColor: `color-mix(in srgb, ${color} 40%, transparent)` }}
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className="rounded-md px-2 py-0.5 text-xs font-bold tracking-wide"
            style={{ background: color, color: '#0a0d14' }}
          >
            {buy ? 'ACHAT' : 'VENTE'}
          </span>
          <span className="text-[13px] font-semibold">{signal.strategyName}</span>
        </div>
        <Badge tone={STATUS_TONE[signal.status]}>{STATUS_LABEL[signal.status]}</Badge>
      </header>

      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <Field label="Entree" value={signal.entry.toFixed(2)} />
        <Field label="Stop" value={signal.stopLoss.toFixed(2)} tone="var(--color-bear)" />
        <Field
          label="Objectifs"
          value={signal.takeProfits.map((tp) => tp.toFixed(2)).join(' · ')}
          tone="var(--color-bull)"
        />
        <Field
          label="Rendement / risque"
          value={risk ? risk.rewardRisk.map((r) => `${r.toFixed(1)}R`).join(' · ') : '—'}
        />
      </div>

      {risk && (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          <Field label="Taille" value={`${risk.lots.toFixed(2)} lot`} />
          <Field label="Risque" value={`${risk.potentialLoss.toFixed(0)} $`} tone="var(--color-bear)" />
          <Field
            label="Gain potentiel"
            value={`${risk.potentialGain[risk.potentialGain.length - 1].toFixed(0)} $`}
            tone="var(--color-bull)"
          />
          <Field label="Distance stop" value={`${risk.stopDistance.toFixed(2)} $`} />
        </div>
      )}

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--color-muted)]">
          <span>Score du setup</span>
          <span className="num font-semibold">{signal.score}/100</span>
        </div>
        <Meter value={signal.score} />
      </div>

      {signal.reasons.length > 0 && (
        <ul className="mt-2.5 space-y-1">
          {signal.reasons.slice(0, 5).map((reason, i) => (
            <li key={i} className="flex gap-1.5 text-[12px] text-[var(--color-text)]/80">
              <span style={{ color }}>▸</span>
              {reason}
            </li>
          ))}
        </ul>
      )}

      <footer className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-border)] pt-2 text-[11px] text-[var(--color-muted)]">
        <span>{signal.note}</span>
        <span className="num">
          MFE {signal.maxFavorableR.toFixed(1)}R · MAE {signal.maxAdverseR.toFixed(1)}R
        </span>
      </footer>
    </article>
  );
}

function Field({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">{label}</p>
      <p className="num mt-0.5 text-[13px] font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </p>
    </div>
  );
}
