'use client';

import type { LevelMap } from '@/lib/market/levels';
import { Card } from './ui';

/** Carte des niveaux : ou le prix va chercher de la liquidite. */
export function LevelsPanel({ levels, price }: { levels: LevelMap | null; price: number | null }) {
  if (!levels || price === null) {
    return (
      <Card title="Niveaux de reference">
        <p className="text-sm text-[var(--color-muted)]">En attente de donnees...</p>
      </Card>
    );
  }

  const above = levels.above.slice(0, 5).reverse();
  const below = levels.below.slice(0, 5);

  return (
    <Card title="Niveaux de reference" subtitle="Obstacles et appuis les plus proches">
      <div className="space-y-1">
        {above.map((level) => (
          <Row key={`a-${level.kind}-${level.price}`} label={level.label} price={level.price} distance={level.price - price} side="haut" />
        ))}

        <div className="my-1.5 flex items-center gap-2 rounded-md bg-[rgba(240,180,41,0.1)] px-2 py-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-gold)]">
            Prix
          </span>
          <span className="num ml-auto text-sm font-bold text-[var(--color-gold)]">{price.toFixed(2)}</span>
        </div>

        {below.map((level) => (
          <Row key={`b-${level.kind}-${level.price}`} label={level.label} price={level.price} distance={level.price - price} side="bas" />
        ))}
      </div>
    </Card>
  );
}

function Row({
  label,
  price,
  distance,
  side,
}: {
  label: string;
  price: number;
  distance: number;
  side: 'haut' | 'bas';
}) {
  const color = side === 'haut' ? 'var(--color-bear)' : 'var(--color-bull)';
  return (
    <div className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-[var(--color-surface-2)]">
      <span className="h-1 w-1 shrink-0 rounded-full" style={{ background: color }} />
      <span className="truncate text-[12px] text-[var(--color-text)]/85">{label}</span>
      <span className="num ml-auto text-[12px] font-semibold">{price.toFixed(2)}</span>
      <span className="num w-16 text-right text-[11px] text-[var(--color-muted)]">
        {distance >= 0 ? '+' : ''}
        {distance.toFixed(2)}
      </span>
    </div>
  );
}
