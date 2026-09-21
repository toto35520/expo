import { levelConfluence } from '../market/levels';
import { fibZone } from '../market/structure';
import type { Direction } from '../market/types';
import { buildTradeLevels, confirmationCandle, extremeOf, fmt } from './helpers';
import { Checklist, emptyResult, type Strategy, type StrategyResult } from './types';

/**
 * Pullback de tendance — la strategie de base sur l'or.
 *
 * On ne prend jamais le contre-pied de la tendance superieure : on attend que
 * le prix respire vers sa zone dynamique (EMA20/EMA50) ou vers le retracement
 * 38,2-61,8 % de la derniere impulsion, que le RSI se refroidisse sans casser,
 * puis on entre sur la bougie qui repart dans le sens de la tendance.
 */
export const pullbackStrategy: Strategy = (ctx): StrategyResult => {
  const entry = ctx.tf[ctx.entryTf];
  const context = ctx.tf[ctx.contextTf];
  const base = emptyResult(
    'pullback-tendance',
    'Pullback de tendance (EMA / Fibonacci)',
    'SUIVI_TENDANCE',
    "J'attends un repli vers l'EMA20/50 dans le sens de la tendance H1."
  );

  if (!entry.ready || !context.ready || entry.atr === null || entry.ema20 === null || entry.ema50 === null) {
    return base;
  }

  const direction: Direction | null =
    context.score >= 15 ? 'BUY' : context.score <= -15 ? 'SELL' : null;

  if (!direction) {
    return { ...base, watching: "Pas de tendance nette en H1 : le pullback n'a rien a suivre." };
  }

  const atr = entry.atr;
  const price = ctx.price;
  const bull = direction === 'BUY';
  const candles = entry.candles;
  const closed = entry.lastClosed;
  if (!closed) return base;

  // 1. Zone de repli : entre EMA20 et EMA50, avec une tolerance ATR.
  const zoneHigh = Math.max(entry.ema20, entry.ema50) + 0.3 * atr;
  const zoneLow = Math.min(entry.ema20, entry.ema50) - 0.3 * atr;
  const inEmaZone = price >= zoneLow && price <= zoneHigh;

  // 2. Zone de Fibonacci de la derniere jambe.
  const leg = entry.structure.lastLeg;
  const legMatches = leg ? (bull ? leg.direction === 'UP' : leg.direction === 'DOWN') : false;
  const fib = leg && legMatches ? fibZone(leg) : null;
  const inFibZone = fib ? fib.inZone(price) : false;

  // 3. Le repli doit rester un repli : la structure n'est pas cassee.
  const structureIntact = bull
    ? entry.structure.choch?.direction !== 'DOWN'
    : entry.structure.choch?.direction !== 'UP';

  // 4. Refroidissement du RSI sans rupture.
  const rsi = entry.rsi;
  const rsiCooled =
    rsi !== null && (bull ? rsi >= 36 && rsi <= 60 : rsi >= 40 && rsi <= 64);
  const rsiPrev = entry.rsiSeries[entry.rsiSeries.length - 3] ?? null;
  const rsiTurning =
    rsi !== null && rsiPrev !== null && (bull ? rsi > rsiPrev : rsi < rsiPrev);

  // 5. Tendance encore portante.
  const trendForce = entry.adx !== null && entry.adx >= 18;

  // 6. Bougie de confirmation sur la derniere cloture.
  const confirmation = confirmationCandle(candles.slice(0, -1), direction, atr);

  // 7. Confluence avec un niveau de reference.
  const level = levelConfluence(ctx.levels, price, 0.6 * atr);

  const list = new Checklist()
    .add(true, 2, `Tendance ${ctx.contextTf} ${bull ? 'haussiere' : 'baissiere'} (${context.structure.label})`)
    .add(inEmaZone || inFibZone, 2,
      inEmaZone
        ? `Repli dans la zone dynamique EMA20 ${fmt(entry.ema20)} / EMA50 ${fmt(entry.ema50)}`
        : `Repli dans la zone Fibonacci 38-62 % de la derniere impulsion`,
      "Le prix n'est pas encore revenu dans la zone de repli")
    .add(structureIntact, 1.5, 'Structure de tendance intacte (pas de CHoCH contraire)',
      'Structure cassee dans le sens oppose : le repli devient un retournement')
    .add(rsiCooled, 1.5, `RSI refroidi a ${rsi?.toFixed(0)} sans rupture`,
      `RSI a ${rsi?.toFixed(0)} : ni assez refroidi ni exploitable`)
    .add(rsiTurning, 1, `Momentum qui repart dans le sens de la tendance`,
      'Le momentum ne repart pas encore')
    .add(trendForce, 1, `Force de tendance confirmee (ADX ${entry.adx?.toFixed(0)})`,
      `Tendance molle (ADX ${entry.adx?.toFixed(0) ?? '?'}) : risque de range`)
    .add(confirmation.ok, 2.5, `Declencheur : ${confirmation.label}`,
      'Pas encore de bougie de confirmation a la cloture')
    .add(level !== null, 1, level ? `Confluence avec ${level.label} (${fmt(level.price)})` : '',
      'Aucun niveau de reference a proximite immediate');

  const triggered =
    confirmation.ok && (inEmaZone || inFibZone) && structureIntact && rsiCooled;

  const structuralStop = bull
    ? Math.min(extremeOf(candles, 8, 'LOW') ?? price - atr, entry.ema50)
    : Math.max(extremeOf(candles, 8, 'HIGH') ?? price + atr, entry.ema50);

  const structuralTarget = bull
    ? entry.structure.lastHigh?.price ?? null
    : entry.structure.lastLow?.price ?? null;

  const levels = buildTradeLevels({
    direction,
    entry: bull ? ctx.quote.ask : ctx.quote.bid,
    structuralStop,
    atr,
    structuralTarget,
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
      ? `Setup ${direction} arme sur ${ctx.entryTf}.`
      : `Repli en cours de construction — il manque : ${list.missing.filter(Boolean)[0] ?? 'la confirmation'}.`,
  };
};
