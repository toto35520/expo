import type { Level } from '../market/levels';
import { anatomy, type Direction } from '../market/types';
import { buildTradeLevels, extremeOf, fmt, rsiDivergence } from './helpers';
import { Checklist, emptyResult, type Strategy, type StrategyResult } from './types';

/**
 * Prise de liquidite (stop hunt) puis retournement.
 *
 * Schema tres frequent sur l'or : le prix va chercher les stops juste au-dessus
 * d'un plus-haut evident (plus haut de la veille, du jour, de la seance
 * asiatique), n'y trouve pas d'acheteurs, et revient sous le niveau dans la
 * foulee. On entre dans le sens du retour, stop au-dela de la meche.
 */
export const liquiditySweepStrategy: Strategy = (ctx): StrategyResult => {
  const entry = ctx.tf[ctx.entryTf];
  const base = emptyResult(
    'prise-liquidite',
    'Prise de liquidite + retournement',
    'RETOURNEMENT',
    "Je surveille les meches au-dela des plus hauts / plus bas de reference."
  );

  if (!entry.ready || entry.atr === null || entry.candles.length < 20) return base;

  const atr = entry.atr;
  const candles = entry.candles;
  const closedBars = candles.slice(0, -1);
  const window = closedBars.slice(-4);
  if (window.length < 3) return base;

  // Niveaux qui concentrent de la liquidite.
  const magnets = ctx.levels.all.filter(
    (l) =>
      l.kind === 'PLUS_HAUT_JOUR' ||
      l.kind === 'PLUS_BAS_JOUR' ||
      l.kind === 'PLUS_HAUT_VEILLE' ||
      l.kind === 'PLUS_BAS_VEILLE' ||
      l.kind === 'PLUS_HAUT_ASIE' ||
      l.kind === 'PLUS_BAS_ASIE'
  );
  if (magnets.length === 0) return base;

  let direction: Direction | null = null;
  let swept: Level | null = null;
  let wickExtreme = 0;

  for (const level of magnets) {
    const isHighSide =
      level.kind === 'PLUS_HAUT_JOUR' ||
      level.kind === 'PLUS_HAUT_VEILLE' ||
      level.kind === 'PLUS_HAUT_ASIE';

    for (const c of window) {
      if (isHighSide) {
        // Meche au-dessus puis cloture revenue sous le niveau.
        const pierced = c.h > level.price + 0.12 * atr;
        const rejected = c.c < level.price;
        if (pierced && rejected && ctx.price < level.price) {
          direction = 'SELL';
          swept = level;
          wickExtreme = Math.max(wickExtreme || 0, c.h);
        }
      } else {
        const pierced = c.l < level.price - 0.12 * atr;
        const rejected = c.c > level.price;
        if (pierced && rejected && ctx.price > level.price) {
          direction = 'BUY';
          swept = level;
          wickExtreme = wickExtreme === 0 ? c.l : Math.min(wickExtreme, c.l);
        }
      }
    }
  }

  if (!direction || !swept) {
    const nearestMagnet = magnets
      .slice()
      .sort((a, b) => Math.abs(a.price - ctx.price) - Math.abs(b.price - ctx.price))[0];
    return {
      ...base,
      readiness: 0.15,
      watching: nearestMagnet
        ? `Liquidite non prise sur ${nearestMagnet.label} (${fmt(nearestMagnet.price)}).`
        : base.watching,
    };
  }

  const bull = direction === 'BUY';
  const sweepCandle = window[window.length - 1];
  const a = anatomy(sweepCandle);

  const strongWick = bull ? a.lowerRatio >= 0.4 : a.upperRatio >= 0.4;
  const closedBack = bull ? ctx.price > swept.price : ctx.price < swept.price;
  const divergence = rsiDivergence(closedBars, entry.rsiSeries.slice(0, -1), direction, 24);

  // Un retournement contre une tendance tres forte est risque.
  const contextScore = ctx.tf[ctx.contextTf].score;
  const notAgainstStrongTrend = bull ? contextScore > -55 : contextScore < 55;

  const rsi = entry.rsi;
  const rsiExtreme = rsi !== null && (bull ? rsi < 45 : rsi > 55);

  const list = new Checklist()
    .add(true, 2.5, `Liquidite prise sur ${swept.label} (${fmt(swept.price)})`)
    .add(strongWick, 2, `Meche de rejet marquee (${Math.round((bull ? a.lowerRatio : a.upperRatio) * 100)} % de la bougie)`,
      'La meche de rejet est trop faible pour parler de prise de liquidite')
    .add(closedBack, 2.5, `Prix revenu ${bull ? 'au-dessus' : 'en dessous'} du niveau`,
      `Le prix ne s'est pas encore referme ${bull ? 'au-dessus' : 'en dessous'} du niveau`)
    .add(divergence, 1.5, 'Divergence RSI sur l extreme',
      'Pas de divergence RSI pour appuyer le retournement')
    .add(notAgainstStrongTrend, 1.5, 'Contexte superieur compatible avec un retournement',
      `Tendance ${ctx.contextTf} trop forte pour se mettre en travers`)
    .add(rsiExtreme, 1, `RSI a ${rsi?.toFixed(0)} coherent avec le retournement`,
      `RSI a ${rsi?.toFixed(0)} : momentum pas encore retourne`);

  const triggered = strongWick && closedBack && notAgainstStrongTrend;

  const structuralStop = bull
    ? Math.min(wickExtreme, extremeOf(candles, 4, 'LOW') ?? wickExtreme)
    : Math.max(wickExtreme, extremeOf(candles, 4, 'HIGH') ?? wickExtreme);

  const structuralTarget = bull
    ? entry.structure.lastHigh?.price ?? null
    : entry.structure.lastLow?.price ?? null;

  const levels = buildTradeLevels({
    direction,
    entry: bull ? ctx.quote.ask : ctx.quote.bid,
    structuralStop,
    atr,
    structuralTarget,
    cushion: 0.2,
  });

  return {
    ...base,
    direction,
    readiness: list.readiness,
    triggered,
    score: Math.round(list.readiness * 100),
    reasons: list.reasons.filter(Boolean),
    missing: list.missing.filter(Boolean),
    levels,
    watching: triggered
      ? `Retournement ${direction} apres prise de liquidite sur ${swept.label}.`
      : `Balayage repere sur ${swept.label} — ${list.missing.filter(Boolean)[0] ?? 'attente de confirmation'}.`,
  };
};
