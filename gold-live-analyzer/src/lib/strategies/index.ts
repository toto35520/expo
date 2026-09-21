import { breakoutRetestStrategy } from './breakout';
import { pullbackStrategy } from './pullback';
import { meanReversionStrategy } from './reversion';
import { openingRangeStrategy } from './session';
import { liquiditySweepStrategy } from './sweep';
import type { Strategy, StrategyContext, StrategyResult } from './types';

/** Registre des strategies, evaluees a chaque tick. */
export const STRATEGIES: Strategy[] = [
  pullbackStrategy,
  breakoutRetestStrategy,
  liquiditySweepStrategy,
  openingRangeStrategy,
  meanReversionStrategy,
];

export function runStrategies(ctx: StrategyContext): StrategyResult[] {
  return STRATEGIES.map((strategy) => {
    try {
      return strategy(ctx);
    } catch (error) {
      return {
        id: 'erreur',
        name: 'Strategie en erreur',
        family: 'SUIVI_TENDANCE' as const,
        direction: null,
        readiness: 0,
        triggered: false,
        score: 0,
        reasons: [],
        missing: [error instanceof Error ? error.message : 'erreur inconnue'],
        levels: null,
        watching: 'Strategie indisponible sur ce tick.',
      };
    }
  });
}

export * from './types';
