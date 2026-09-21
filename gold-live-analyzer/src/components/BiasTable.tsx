'use client';

import type { MarketRead } from '@/lib/engine/analyzer';
import { TIMEFRAMES } from '@/lib/market/types';
import { BiasGauge, Card, Badge } from './ui';

/** Alignement des unites de temps : le contexte avant l'execution. */
export function BiasTable({ read }: { read: MarketRead | null }) {
  if (!read) {
    return (
      <Card title="Alignement multi-unites de temps">
        <p className="text-sm text-[var(--color-muted)]">En attente de donnees...</p>
      </Card>
    );
  }

  const tone = read.globalBias === 'HAUSSIER' ? 'hausse' : read.globalBias === 'BAISSIER' ? 'baisse' : 'neutre';

  return (
    <Card
      title="Alignement multi-unites de temps"
      subtitle={`${read.alignment} % des unites de temps d'accord`}
      action={<Badge tone={tone}>{read.globalBias}</Badge>}
    >
      <div className="mb-4">
        <div className="mb-1.5 flex items-baseline justify-between">
          <span className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">Score global</span>
          <span
            className="num text-sm font-bold"
            style={{
              color:
                read.globalScore > 0
                  ? 'var(--color-bull)'
                  : read.globalScore < 0
                    ? 'var(--color-bear)'
                    : 'var(--color-muted)',
            }}
          >
            {read.globalScore > 0 ? '+' : ''}
            {read.globalScore}
          </span>
        </div>
        <BiasGauge score={read.globalScore} />
      </div>

      <div className="space-y-2.5">
        {TIMEFRAMES.map((tf) => {
          const analysis = read.tf[tf];
          const color =
            analysis.score > 0 ? 'var(--color-bull)' : analysis.score < 0 ? 'var(--color-bear)' : 'var(--color-muted)';
          return (
            <div key={tf} className="grid grid-cols-[40px_1fr_46px] items-center gap-3">
              <span className="num text-xs font-semibold text-[var(--color-muted)]">{tf}</span>
              <div>
                <BiasGauge score={analysis.ready ? analysis.score : 0} />
                <p className="mt-1 truncate text-[11px] text-[var(--color-muted)]">
                  {analysis.ready ? analysis.structure.label : 'historique en cours de chargement'}
                </p>
              </div>
              <span className="num text-right text-xs font-semibold" style={{ color }}>
                {analysis.ready ? `${analysis.score > 0 ? '+' : ''}${analysis.score}` : '—'}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
