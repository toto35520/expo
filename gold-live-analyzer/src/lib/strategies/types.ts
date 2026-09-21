import type { BollingerPoint, MacdPoint } from '../market/indicators';
import type { LevelMap } from '../market/levels';
import type { SessionWindow } from '../market/sessions';
import type { StructureRead } from '../market/structure';
import type { Bias, Candle, Direction, Quote, Timeframe } from '../market/types';

/** Tout ce qui est calcule une fois par timeframe, puis partage aux strategies. */
export interface TimeframeAnalysis {
  tf: Timeframe;
  candles: Candle[];
  /** Derniere bougie close (celle sur laquelle on valide un signal). */
  lastClosed: Candle | null;
  /** Bougie en cours de formation. */
  forming: Candle | null;
  ema20: number | null;
  ema50: number | null;
  ema200: number | null;
  ema20Series: (number | null)[];
  ema50Series: (number | null)[];
  ema200Series: (number | null)[];
  rsi: number | null;
  rsiSeries: (number | null)[];
  atr: number | null;
  adx: number | null;
  macd: MacdPoint | null;
  bollinger: BollingerPoint | null;
  bandwidthPercentile: number | null;
  vwap: number | null;
  structure: StructureRead;
  bias: Bias;
  /** -100 a +100 : synthese directionnelle du timeframe. */
  score: number;
  ready: boolean;
}

export interface StrategyContext {
  price: number;
  quote: Quote;
  now: number;
  session: SessionWindow;
  levels: LevelMap;
  tf: Record<Timeframe, TimeframeAnalysis>;
  /** Timeframe d'execution choisi par l'utilisateur. */
  entryTf: Timeframe;
  /** Timeframe de contexte (superieur). */
  contextTf: Timeframe;
}

export interface StrategyLevels {
  entry: number;
  stopLoss: number;
  takeProfits: number[];
}

export interface StrategyResult {
  id: string;
  name: string;
  /** Description courte affichee dans l'UI. */
  family: 'SUIVI_TENDANCE' | 'CASSURE' | 'RETOURNEMENT' | 'SEANCE';
  direction: Direction | null;
  /** 0 a 1 : proportion des conditions reunies. */
  readiness: number;
  /** true quand le declencheur est tombe sur la derniere bougie close. */
  triggered: boolean;
  /** 0 a 100 : qualite du setup. */
  score: number;
  reasons: string[];
  missing: string[];
  levels: StrategyLevels | null;
  /** Message affiche quand la strategie est en veille. */
  watching: string;
}

export type Strategy = (ctx: StrategyContext) => StrategyResult;

export function emptyResult(
  id: string,
  name: string,
  family: StrategyResult['family'],
  watching: string
): StrategyResult {
  return {
    id,
    name,
    family,
    direction: null,
    readiness: 0,
    triggered: false,
    score: 0,
    reasons: [],
    missing: [],
    levels: null,
    watching,
  };
}

/** Additionne des conditions ponderees et produit readiness + score. */
export class Checklist {
  private readonly items: { ok: boolean; weight: number; label: string; whenMissing?: string }[] = [];

  add(ok: boolean, weight: number, label: string, whenMissing?: string): this {
    this.items.push({ ok, weight, label, whenMissing });
    return this;
  }

  get reasons(): string[] {
    return this.items.filter((i) => i.ok).map((i) => i.label);
  }

  get missing(): string[] {
    return this.items.filter((i) => !i.ok).map((i) => i.whenMissing ?? i.label);
  }

  get readiness(): number {
    const total = this.items.reduce((acc, i) => acc + i.weight, 0);
    if (total === 0) return 0;
    const got = this.items.filter((i) => i.ok).reduce((acc, i) => acc + i.weight, 0);
    return got / total;
  }

  /** Vrai si toutes les conditions marquees obligatoires sont remplies. */
  allRequired(...labels: string[]): boolean {
    return labels.every((label) => this.items.find((i) => i.label === label)?.ok ?? false);
  }
}
