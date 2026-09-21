import { levelConfluence, nextLevel } from '../market/levels';
import { anatomy, type Direction } from '../market/types';
import { buildTradeLevels, extremeOf, fmt, isMomentum } from './helpers';
import { Checklist, emptyResult, type Strategy, type StrategyResult } from './types';

/**
 * Cassure de range puis retest.
 *
 * On repere une compression (bandes de Bollinger resserrees + range etroit),
 * on attend une cloture franche hors du range, puis le retour sur le niveau
 * casse. L'entree se fait sur le retest tenu, pas sur la cassure elle-meme :
 * c'est ce qui evite la majorite des faux signaux sur l'or.
 */
export const breakoutRetestStrategy: Strategy = (ctx): StrategyResult => {
  const entry = ctx.tf[ctx.entryTf];
  const base = emptyResult(
    'cassure-retest',
    'Cassure de range + retest',
    'CASSURE',
    "Je surveille une compression puis une cassure franche avec retest."
  );

  if (!entry.ready || entry.atr === null || entry.candles.length < 40) return base;

  const atr = entry.atr;
  const price = ctx.price;
  const candles = entry.candles;
  const closedBars = candles.slice(0, -1);

  // Range de reference : les 20 bougies precedant les 5 dernieres.
  const rangeWindow = closedBars.slice(-25, -5);
  if (rangeWindow.length < 12) return base;

  const rangeHigh = Math.max(...rangeWindow.map((c) => c.h));
  const rangeLow = Math.min(...rangeWindow.map((c) => c.l));
  const rangeWidth = rangeHigh - rangeLow;
  if (rangeWidth <= 0) return base;

  // Compression : largeur du range faible par rapport a l'ATR, et bandes de
  // Bollinger dans le bas de leur distribution recente.
  const compressed = rangeWidth < atr * 3.2;
  const bandwidthRank =
    entry.bollinger !== null && entry.bandwidthPercentile !== null
      ? entry.bandwidthPercentile
      : null;
  const squeeze = bandwidthRank !== null && bandwidthRank < 0.35;

  // Cassure : une des 5 dernieres clotures sort du range avec du corps.
  const recent = closedBars.slice(-5);
  let direction: Direction | null = null;
  let breakoutLevel = 0;
  let breakoutIndex = -1;

  for (let i = 0; i < recent.length; i++) {
    const c = recent[i];
    const a = anatomy(c);
    if (c.c > rangeHigh && a.bodyRatio > 0.45) {
      direction = 'BUY';
      breakoutLevel = rangeHigh;
      breakoutIndex = i;
    } else if (c.c < rangeLow && a.bodyRatio > 0.45) {
      direction = 'SELL';
      breakoutLevel = rangeLow;
      breakoutIndex = i;
    }
  }

  if (!direction) {
    return {
      ...base,
      readiness: compressed ? (squeeze ? 0.45 : 0.3) : 0.1,
      watching: compressed
        ? `Compression detectee entre ${fmt(rangeLow)} et ${fmt(rangeHigh)} — j'attends la cassure.`
        : "Pas de compression exploitable pour l'instant.",
    };
  }

  const bull = direction === 'BUY';

  // Retest : apres la cassure le prix revient au contact du niveau casse
  // sans le refermer.
  const sinceBreak = recent.slice(breakoutIndex + 1);
  const cameBack = sinceBreak.some((c) =>
    bull ? c.l <= breakoutLevel + 0.4 * atr : c.h >= breakoutLevel - 0.4 * atr
  );
  const stillHolding = bull ? price > breakoutLevel : price < breakoutLevel;
  const retestDone = cameBack && stillHolding;

  const lastClosed = entry.lastClosed;
  const momentumBack =
    lastClosed !== null && isMomentum(lastClosed, direction, atr);

  const volumeOk =
    rangeWindow.length > 0 &&
    recent[breakoutIndex].v >=
      (rangeWindow.reduce((acc, c) => acc + c.v, 0) / rangeWindow.length) * 1.1;

  const alignedWithContext = bull
    ? ctx.tf[ctx.contextTf].score >= -10
    : ctx.tf[ctx.contextTf].score <= 10;

  const level = levelConfluence(ctx.levels, breakoutLevel, 0.5 * atr);

  const list = new Checklist()
    .add(compressed, 1.5, `Range de compression ${fmt(rangeLow)} - ${fmt(rangeHigh)} (${fmt(rangeWidth)} $)`,
      'Le range de depart est trop large pour une vraie cassure')
    .add(squeeze, 1, 'Bandes de Bollinger resserrees (energie accumulee)',
      'Volatilite pas assez comprimee avant la cassure')
    .add(true, 2, `Cloture hors du range a ${fmt(breakoutLevel)} (${bull ? 'par le haut' : 'par le bas'})`)
    .add(volumeOk, 1, 'Cassure accompagnee par une activite superieure a la moyenne',
      'Cassure sans regain d activite : mefiance')
    .add(retestDone, 2.5, `Retest du niveau ${fmt(breakoutLevel)} tenu`,
      "Le retest n'a pas encore eu lieu ou n'a pas tenu")
    .add(momentumBack, 2, 'Reprise du momentum apres le retest',
      'Pas encore de reprise franche apres le retest')
    .add(alignedWithContext, 1, `Cassure compatible avec le contexte ${ctx.contextTf}`,
      `Cassure a contre-courant du ${ctx.contextTf}`)
    .add(level !== null, 0.5, level ? `Le niveau casse correspond a ${level.label}` : '',
      'Le niveau casse ne correspond a aucun repere majeur');

  const triggered = retestDone && momentumBack;

  const structuralStop = bull
    ? Math.min(breakoutLevel - 0.2 * atr, extremeOf(candles, 4, 'LOW') ?? breakoutLevel)
    : Math.max(breakoutLevel + 0.2 * atr, extremeOf(candles, 4, 'HIGH') ?? breakoutLevel);

  const target = nextLevel(ctx.levels, price, bull ? 'UP' : 'DOWN', atr);

  const levels = buildTradeLevels({
    direction,
    entry: bull ? ctx.quote.ask : ctx.quote.bid,
    structuralStop,
    atr,
    structuralTarget: target?.price ?? (bull ? price + rangeWidth : price - rangeWidth),
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
      ? `Cassure ${direction} validee par le retest de ${fmt(breakoutLevel)}.`
      : `Cassure ${bull ? 'haussiere' : 'baissiere'} en cours — ${list.missing.filter(Boolean)[0] ?? 'attente du retest'}.`,
  };
};
