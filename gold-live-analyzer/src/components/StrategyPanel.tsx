'use client';

import type { StrategyResult } from '@/lib/strategies/types';
import { Badge, Card, Meter } from './ui';

const FAMILY_LABEL: Record<StrategyResult['family'], string> = {
  SUIVI_TENDANCE: 'Suivi de tendance',
  CASSURE: 'Cassure',
  RETOURNEMENT: 'Retournement',
  SEANCE: 'Seance',
};

/** Etat de chaque strategie : ce qui est reuni, ce qui manque. */
export function StrategyPanel({ strategies }: { strategies: StrategyResult[] }) {
  return (
    <Card
      title="Strategies surveillees"
      subtitle="Chaque strategie est reevaluee a chaque tick du marche"
    >
      <div className="space-y-3">
        {strategies.length === 0 && (
          <p className="text-sm text-[var(--color-muted)]">En attente de donnees...</p>
        )}
        {strategies.map((strategy) => {
          const tone =
            strategy.direction === 'BUY' ? 'hausse' : strategy.direction === 'SELL' ? 'baisse' : 'neutre';
          return (
            <div
              key={strategy.id}
              className={`rounded-lg border p-3 ${
                strategy.triggered
                  ? 'border-[var(--color-gold)] bg-[rgba(240,180,41,0.06)]'
                  : 'border-[var(--color-border)] bg-[var(--color-surface-2)]'
              }`}
            >
              <header className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[13px] font-semibold">{strategy.name}</h3>
                  <p className="text-[11px] text-[var(--color-muted)]">{FAMILY_LABEL[strategy.family]}</p>
                </div>
                <div className="flex items-center gap-2">
                  {strategy.direction && <Badge tone={tone}>{strategy.direction === 'BUY' ? 'ACHAT' : 'VENTE'}</Badge>}
                  {strategy.triggered && <Badge tone="or">ARME</Badge>}
                </div>
              </header>

              <div className="mt-2">
                <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--color-muted)]">
                  <span>Conditions reunies</span>
                  <span className="num font-semibold">{Math.round(strategy.readiness * 100)} %</span>
                </div>
                <Meter value={strategy.readiness * 100} />
              </div>

              <p className="mt-2 text-[12px] leading-relaxed text-[var(--color-text)]/85">
                {strategy.watching}
              </p>

              {strategy.missing.length > 0 && !strategy.triggered && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-[11px] text-[var(--color-muted)] hover:text-[var(--color-text)]">
                    Ce qui manque ({strategy.missing.length})
                  </summary>
                  <ul className="mt-1.5 space-y-1">
                    {strategy.missing.map((item, i) => (
                      <li key={i} className="flex gap-1.5 text-[11px] text-[var(--color-muted)]">
                        <span>·</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
