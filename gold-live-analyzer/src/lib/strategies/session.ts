import { LONDON_OPEN_MIN, NY_OPEN_MIN, minutesOfDayUtc, sessionOpenTs } from '../market/sessions';
import { anatomy, type Direction } from '../market/types';
import { buildTradeLevels, fmt } from './helpers';
import { Checklist, emptyResult, type Strategy, type StrategyResult } from './types';

/**
 * Cassure du range d'ouverture (Londres et New York).
 *
 * On fige les 30 premieres minutes de la session, puis on prend la sortie du
 * range dans l'heure qui suit. Sur l'or c'est l'ouverture de Londres qui
 * donne le plus souvent la direction de la journee.
 */

const RANGE_MINUTES = 30;
const VALID_WINDOW_MINUTES = 90;

export const openingRangeStrategy: Strategy = (ctx): StrategyResult => {
  const entry = ctx.tf[ctx.entryTf];
  const base = emptyResult(
    'range-ouverture',
    "Cassure du range d'ouverture (Londres / NY)",
    'SEANCE',
    "J'attends l'ouverture de Londres (07:00 UTC) ou de New York (13:30 UTC)."
  );

  if (!entry.ready || entry.atr === null) return base;

  const nowMin = minutesOfDayUtc(ctx.now);
  const candidates = [
    { name: 'Londres', openMin: LONDON_OPEN_MIN },
    { name: 'New York', openMin: NY_OPEN_MIN },
  ];

  const active = candidates
    .filter((s) => nowMin >= s.openMin + RANGE_MINUTES && nowMin <= s.openMin + VALID_WINDOW_MINUTES)
    .pop();

  if (!active) {
    const next = candidates.find((s) => nowMin < s.openMin);
    return {
      ...base,
      readiness: 0.05,
      watching: next
        ? `Hors fenetre — prochaine ouverture : ${next.name} dans ${Math.round(next.openMin - nowMin)} min.`
        : "Fenetre d'ouverture passee pour aujourd'hui.",
    };
  }

  const openTs = sessionOpenTs(ctx.now, active.openMin);
  const rangeEnd = openTs + RANGE_MINUTES * 60_000;

  const rangeBars = entry.candles.filter((c) => c.t >= openTs && c.t < rangeEnd);
  if (rangeBars.length < 2) {
    return { ...base, readiness: 0.1, watching: `Range d'ouverture ${active.name} en construction.` };
  }

  const rangeHigh = Math.max(...rangeBars.map((c) => c.h));
  const rangeLow = Math.min(...rangeBars.map((c) => c.l));
  const rangeWidth = rangeHigh - rangeLow;
  const atr = entry.atr;

  const afterBars = entry.candles.filter((c) => c.t >= rangeEnd).slice(0, -1);
  let direction: Direction | null = null;
  let breakBar = null;

  for (const c of afterBars) {
    const a = anatomy(c);
    if (c.c > rangeHigh && a.bodyRatio > 0.4) {
      direction = 'BUY';
      breakBar = c;
    } else if (c.c < rangeLow && a.bodyRatio > 0.4) {
      direction = 'SELL';
      breakBar = c;
    }
  }

  if (!direction || !breakBar) {
    return {
      ...base,
      readiness: 0.35,
      watching: `Range ${active.name} fige : ${fmt(rangeLow)} - ${fmt(rangeHigh)} (${fmt(rangeWidth)} $). J'attends la sortie.`,
    };
  }

  const bull = direction === 'BUY';
  const stillOutside = bull ? ctx.price > rangeHigh : ctx.price < rangeLow;
  const sensibleWidth = rangeWidth > atr * 0.6 && rangeWidth < atr * 6;
  const contextScore = ctx.tf[ctx.contextTf].score;
  const aligned = bull ? contextScore >= -20 : contextScore <= 20;
  const noOverextension = Math.abs(ctx.price - (bull ? rangeHigh : rangeLow)) < rangeWidth * 1.2;

  const list = new Checklist()
    .add(true, 2, `Range d'ouverture ${active.name} : ${fmt(rangeLow)} - ${fmt(rangeHigh)}`)
    .add(sensibleWidth, 1.5, `Largeur de range coherente (${fmt(rangeWidth)} $ pour un ATR de ${fmt(atr)} $)`,
      `Range ${rangeWidth < atr * 0.6 ? 'trop etroit' : 'trop large'} pour une cassure fiable`)
    .add(true, 2, `Cassure ${bull ? 'haussiere' : 'baissiere'} confirmee en cloture`)
    .add(stillOutside, 2, 'Prix maintenu hors du range',
      'Le prix est retombe dans le range : cassure invalidee')
    .add(noOverextension, 1.5, 'Entree encore proche du niveau casse',
      'Mouvement deja trop etendu : le rapport rendement/risque se degrade')
    .add(aligned, 1, `Cassure compatible avec le contexte ${ctx.contextTf}`,
      `Cassure a contre-courant du ${ctx.contextTf}`);

  const triggered = stillOutside && sensibleWidth && noOverextension;

  const levels = buildTradeLevels({
    direction,
    entry: bull ? ctx.quote.ask : ctx.quote.bid,
    structuralStop: bull ? rangeLow : rangeHigh,
    atr,
    // Projection classique : la largeur du range reportee au-dela de la cassure.
    structuralTarget: bull ? rangeHigh + rangeWidth : rangeLow - rangeWidth,
    cushion: 0.1,
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
      ? `Cassure ${direction} du range d'ouverture ${active.name}.`
      : `Cassure ${active.name} en cours — ${list.missing.filter(Boolean)[0] ?? 'attente de confirmation'}.`,
  };
};
