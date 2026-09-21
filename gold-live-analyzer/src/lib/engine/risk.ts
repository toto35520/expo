import type { Direction } from '../market/types';
import type { StrategyLevels } from '../strategies/types';

/**
 * Dimensionnement de position pour XAU/USD.
 *
 * Contrat standard : 1 lot = 100 onces, donc 1 $ de mouvement = 100 $ de P&L
 * par lot. Le calcul part du risque en euros/dollars accepte et de la distance
 * au stop, jamais l'inverse.
 */

export const OUNCES_PER_LOT = 100;

export interface RiskSettings {
  /** Capital de reference du compte. */
  balance: number;
  /** Risque par trade, en pourcentage du capital. */
  riskPercent: number;
  /** Devise affichee (informatif). */
  currency: string;
}

export const DEFAULT_RISK: RiskSettings = {
  balance: 10_000,
  riskPercent: 0.5,
  currency: 'USD',
};

export interface RiskPlan {
  riskAmount: number;
  stopDistance: number;
  lots: number;
  /** Valeur d'un dollar de mouvement pour la taille calculee. */
  valuePerDollarMove: number;
  rewardRisk: number[];
  potentialGain: number[];
  potentialLoss: number;
}

export function computeRisk(
  direction: Direction,
  levels: StrategyLevels,
  risk: RiskSettings
): RiskPlan | null {
  const stopDistance = Math.abs(levels.entry - levels.stopLoss);
  if (!Number.isFinite(stopDistance) || stopDistance <= 0) return null;

  const riskAmount = (risk.balance * risk.riskPercent) / 100;
  const rawLots = riskAmount / (stopDistance * OUNCES_PER_LOT);
  // Les brokers cTrader acceptent le centieme de lot sur l'or.
  const lots = Math.max(0.01, Math.round(rawLots * 100) / 100);
  const valuePerDollarMove = lots * OUNCES_PER_LOT;

  const rewardRisk = levels.takeProfits.map(
    (tp) => Math.abs(tp - levels.entry) / stopDistance
  );
  const potentialGain = levels.takeProfits.map(
    (tp) => Math.abs(tp - levels.entry) * valuePerDollarMove
  );

  return {
    riskAmount,
    stopDistance,
    lots,
    valuePerDollarMove,
    rewardRisk,
    potentialGain,
    potentialLoss: stopDistance * valuePerDollarMove,
  };
}

/** Verifie que le trade vaut la peine d'etre pris. */
export function isRewardAcceptable(plan: RiskPlan, minRR = 1.2): boolean {
  const best = plan.rewardRisk[plan.rewardRisk.length - 1] ?? 0;
  return best >= minRR;
}
