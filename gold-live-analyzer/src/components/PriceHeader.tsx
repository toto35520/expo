'use client';

import type { EngineState, FeedStatus } from '@/hooks/useGoldEngine';
import { Badge } from './ui';

const STATUS_LABEL: Record<FeedStatus, string> = {
  HORS_LIGNE: 'Hors ligne',
  CHARGEMENT_HISTORIQUE: 'Chargement historique',
  CONNEXION: 'Connexion',
  EN_DIRECT: 'En direct',
  RECONNEXION: 'Reconnexion',
  ERREUR: 'Erreur',
};

export function PriceHeader({ state }: { state: EngineState }) {
  const quote = state.quote;
  const read = state.read;

  const dayChange = (() => {
    if (!read || read.levels.prevDayClose === null || !quote) return null;
    const delta = quote.mid - read.levels.prevDayClose;
    return { delta, pct: (delta / read.levels.prevDayClose) * 100 };
  })();

  const live = state.status === 'EN_DIRECT';
  const tone = !dayChange ? 'var(--color-muted)' : dayChange.delta >= 0 ? 'var(--color-bull)' : 'var(--color-bear)';

  return (
    <header className="card flex flex-wrap items-center gap-x-8 gap-y-4 p-4">
      <div className="min-w-[180px]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-widest text-[var(--color-gold)]">
            {state.symbolName ?? 'XAU/USD'}
          </span>
          <span
            className={`h-1.5 w-1.5 rounded-full ${live ? 'pulse-dot' : ''}`}
            style={{ background: live ? 'var(--color-bull)' : 'var(--color-warn)' }}
          />
        </div>
        <div className="num mt-1 text-3xl font-bold leading-none" style={{ color: tone }}>
          {quote ? quote.mid.toFixed(2) : '—'}
        </div>
        {dayChange && (
          <div className="num mt-1 text-xs" style={{ color: tone }}>
            {dayChange.delta >= 0 ? '+' : ''}
            {dayChange.delta.toFixed(2)} $ ({dayChange.pct >= 0 ? '+' : ''}
            {dayChange.pct.toFixed(2)} %) depuis la cloture de la veille
          </div>
        )}
      </div>

      <div className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Field label="Vente (bid)" value={quote ? quote.bid.toFixed(2) : '—'} />
        <Field label="Achat (ask)" value={quote ? quote.ask.toFixed(2) : '—'} />
        <Field
          label="Spread"
          value={quote ? `${quote.spread.toFixed(2)} $` : '—'}
          tone={quote && quote.spread > 0.5 ? 'var(--color-warn)' : undefined}
        />
        <Field label="Volatilite" value={read ? read.volatility.toLowerCase() : '—'} />
      </div>

      <div className="flex flex-col items-end gap-2">
        <Badge tone={live ? 'hausse' : state.status === 'ERREUR' ? 'baisse' : 'alerte'}>
          {STATUS_LABEL[state.status]}
        </Badge>
        <span className="text-[11px] text-[var(--color-muted)]">
          {state.source === 'CTRADER'
            ? 'Flux cTrader'
            : state.source === 'SECOURS'
              ? 'Source de secours (indicative)'
              : 'Aucune source'}
        </span>
        {state.lastTickAt && (
          <span className="num text-[11px] text-[var(--color-muted)]">
            {state.ticksReceived} ticks · {new Date(state.lastTickAt).toLocaleTimeString('fr-FR')}
          </span>
        )}
      </div>
    </header>
  );
}

function Field({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">{label}</p>
      <p className="num mt-0.5 text-sm font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </p>
    </div>
  );
}
