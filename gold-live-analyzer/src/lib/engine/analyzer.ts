import type { CandleSeries } from '../market/candles';
import {
  adx as adxOf,
  atr as atrOf,
  bollinger as bollingerOf,
  ema as emaOf,
  last,
  macd as macdOf,
  rsi as rsiOf,
  sessionVwap,
} from '../market/indicators';
import { buildLevels, type LevelMap } from '../market/levels';
import { currentSession, type SessionWindow, sessionQuality } from '../market/sessions';
import { analyzeStructure } from '../market/structure';
import {
  type Bias,
  type Candle,
  type Quote,
  TIMEFRAMES,
  type Timeframe,
} from '../market/types';
import { runStrategies } from '../strategies';
import { percentileRank } from '../strategies/helpers';
import type { StrategyContext, StrategyResult, TimeframeAnalysis } from '../strategies/types';

export interface AnalyzerSettings {
  entryTf: Timeframe;
  contextTf: Timeframe;
  /** Score minimal pour qu'un setup devienne un signal diffuse. */
  minScore: number;
  /** Spread maximal tolere, en dollars. */
  maxSpread: number;
  /** ATR minimal sur le timeframe d'execution, en dollars. */
  minAtr: number;
  /** Autoriser les strategies contre-tendance. */
  allowCounterTrend: boolean;
  /** N'emettre des signaux que sur Londres / New York. */
  sessionFilter: boolean;
}

export const DEFAULT_SETTINGS: AnalyzerSettings = {
  entryTf: 'M15',
  contextTf: 'H1',
  minScore: 68,
  maxSpread: 0.60,
  minAtr: 0.80,
  allowCounterTrend: true,
  sessionFilter: false,
};

export interface MarketRead {
  ts: number;
  quote: Quote;
  session: SessionWindow;
  levels: LevelMap;
  tf: Record<Timeframe, TimeframeAnalysis>;
  /** Score global pondere multi-timeframe, -100 a +100. */
  globalScore: number;
  globalBias: Bias;
  /** 0 a 100 : a quel point les timeframes disent la meme chose. */
  alignment: number;
  strategies: StrategyResult[];
  /** Setups declenches ayant passe tous les filtres. */
  candidates: StrategyResult[];
  /** Raisons pour lesquelles aucun signal n'est emis. */
  blockers: string[];
  volatility: 'FAIBLE' | 'NORMALE' | 'ELEVEE';
}

const MIN_BARS: Record<Timeframe, number> = {
  M1: 60,
  M5: 60,
  M15: 55,
  H1: 50,
  H4: 40,
};

/** Poids de chaque timeframe dans le score global. */
const TF_WEIGHT: Record<Timeframe, number> = {
  M1: 0.5,
  M5: 1,
  M15: 1.6,
  H1: 2.2,
  H4: 1.8,
};

function analyzeTimeframe(tf: Timeframe, candles: Candle[]): TimeframeAnalysis {
  const closes = candles.map((c) => c.c);
  const ready = candles.length >= MIN_BARS[tf];

  const ema20Series = emaOf(closes, 20);
  const ema50Series = emaOf(closes, 50);
  const ema200Series = emaOf(closes, 200);
  const rsiSeries = rsiOf(closes, 14);
  const atrSeries = atrOf(candles, 14);
  const adxSeries = adxOf(candles, 14);
  const macdSeries = macdOf(closes);
  const bbSeries = bollingerOf(closes, 20, 2);
  const vwapSeries = sessionVwap(candles);

  const ema20 = last(ema20Series);
  const ema50 = last(ema50Series);
  const ema200 = last(ema200Series);
  const rsi = last(rsiSeries);
  const atr = last(atrSeries);
  const adx = last(adxSeries);
  const macd = last(macdSeries);
  const bollinger = last(bbSeries);

  const structure = analyzeStructure(candles.slice(0, -1), 2);
  const price = closes[closes.length - 1] ?? 0;

  // Score directionnel du timeframe : empilement d'EMA, structure, momentum.
  let score = 0;
  if (ema200 !== null) score += price > ema200 ? 20 : -20;
  if (ema20 !== null && ema50 !== null) score += ema20 > ema50 ? 15 : -15;
  if (ema50 !== null && ema200 !== null) score += ema50 > ema200 ? 15 : -15;
  if (structure.bias === 'HAUSSIER') score += 25;
  else if (structure.bias === 'BAISSIER') score -= 25;
  if (rsi !== null) score += ((rsi - 50) / 50) * 15;
  if (macd !== null) score += Math.sign(macd.histogram) * Math.min(Math.abs(macd.histogram) * 8, 10);

  score = Math.max(-100, Math.min(100, score));

  const bias: Bias = score >= 20 ? 'HAUSSIER' : score <= -20 ? 'BAISSIER' : 'NEUTRE';

  const bandwidthPercentile =
    bollinger !== null
      ? percentileRank(bbSeries.map((b) => (b ? b.bandwidth : null)), bollinger.bandwidth, 120)
      : null;

  return {
    tf,
    candles,
    lastClosed: candles.length > 1 ? candles[candles.length - 2] : null,
    forming: candles[candles.length - 1] ?? null,
    ema20,
    ema50,
    ema200,
    ema20Series,
    ema50Series,
    ema200Series,
    rsi,
    rsiSeries,
    atr,
    adx,
    macd,
    bollinger,
    bandwidthPercentile,
    vwap: last(vwapSeries),
    structure,
    bias,
    score: Math.round(score),
    ready,
  };
}

export function analyze(
  series: CandleSeries,
  quote: Quote,
  settings: AnalyzerSettings,
  now = Date.now()
): MarketRead {
  const tf = {} as Record<Timeframe, TimeframeAnalysis>;
  for (const name of TIMEFRAMES) {
    tf[name] = analyzeTimeframe(name, series.get(name));
  }

  const session = currentSession(now);
  const levels = buildLevels(
    series.get('M15').length > 0 ? series.get('M15') : series.get('M5'),
    series.get('H1'),
    quote.mid
  );

  // Score global : moyenne ponderee des timeframes prets.
  let weighted = 0;
  let totalWeight = 0;
  const signs: number[] = [];
  for (const name of TIMEFRAMES) {
    const analysis = tf[name];
    if (!analysis.ready) continue;
    weighted += analysis.score * TF_WEIGHT[name];
    totalWeight += TF_WEIGHT[name];
    signs.push(Math.sign(analysis.score));
  }
  const globalScore = totalWeight > 0 ? Math.round(weighted / totalWeight) : 0;
  const globalBias: Bias =
    globalScore >= 20 ? 'HAUSSIER' : globalScore <= -20 ? 'BAISSIER' : 'NEUTRE';

  const dominant = Math.sign(globalScore);
  const agreeing = signs.filter((s) => s === dominant && s !== 0).length;
  const alignment = signs.length > 0 ? Math.round((agreeing / signs.length) * 100) : 0;

  const entry = tf[settings.entryTf];
  const atr = entry.atr;

  const volatility: MarketRead['volatility'] =
    atr === null ? 'FAIBLE' : atr < settings.minAtr ? 'FAIBLE' : atr > settings.minAtr * 3.5 ? 'ELEVEE' : 'NORMALE';

  const ctx: StrategyContext = {
    price: quote.mid,
    quote,
    now,
    session,
    levels,
    tf,
    entryTf: settings.entryTf,
    contextTf: settings.contextTf,
  };

  const strategies = runStrategies(ctx).sort((a, b) => b.score - a.score);

  // Filtres de diffusion.
  const blockers: string[] = [];
  if (!entry.ready) blockers.push(`Historique ${settings.entryTf} incomplet (chauffe des indicateurs).`);
  if (quote.spread > settings.maxSpread) {
    blockers.push(`Spread trop large : ${quote.spread.toFixed(2)} $ (max ${settings.maxSpread.toFixed(2)} $).`);
  }
  if (atr !== null && atr < settings.minAtr) {
    blockers.push(`Volatilite insuffisante : ATR ${atr.toFixed(2)} $ (min ${settings.minAtr.toFixed(2)} $).`);
  }
  if (session.name === 'HORS_SESSION') blockers.push('Hors session : liquidite trop faible.');
  if (settings.sessionFilter && !['LONDRES', 'NEW_YORK', 'LONDRES_NY'].includes(session.name)) {
    blockers.push('Filtre de seance actif : signaux limites a Londres / New York.');
  }

  const candidates = strategies.filter((s) => {
    if (!s.triggered || !s.direction || !s.levels) return false;
    if (s.score < settings.minScore) return false;
    if (blockers.length > 0) return false;
    if (!settings.allowCounterTrend && s.family === 'RETOURNEMENT') {
      const against = s.direction === 'BUY' ? globalScore < -20 : globalScore > 20;
      if (against) return false;
    }
    return true;
  });

  return {
    ts: now,
    quote,
    session,
    levels,
    tf,
    globalScore,
    globalBias,
    alignment,
    strategies,
    candidates,
    blockers,
    volatility,
  };
}

export { sessionQuality };
