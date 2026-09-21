import { formatUtcTime } from '../market/sessions';
import type { Direction } from '../market/types';
import type { StrategyResult } from '../strategies/types';
import type { MarketRead } from './analyzer';
import { computeRisk, isRewardAcceptable, type RiskPlan, type RiskSettings } from './risk';

/**
 * Fabrique et suit les signaux.
 *
 * Un signal n'est emis qu'une fois par setup : tant que la meme strategie reste
 * armee dans le meme sens, on ne repete pas l'alerte. Chaque signal est ensuite
 * suivi tick par tick jusqu'au stop, a l'objectif, ou a son invalidation.
 */

export type SignalStatus = 'ACTIF' | 'TP1' | 'TP2' | 'GAGNANT' | 'PERDANT' | 'EXPIRE';

export interface Signal {
  id: string;
  createdAt: number;
  strategyId: string;
  strategyName: string;
  family: StrategyResult['family'];
  direction: Direction;
  entry: number;
  stopLoss: number;
  takeProfits: number[];
  score: number;
  reasons: string[];
  risk: RiskPlan | null;
  session: string;
  globalScore: number;
  alignment: number;
  status: SignalStatus;
  /** Meilleur gain atteint, en multiples de risque. */
  maxFavorableR: number;
  /** Pire excursion, en multiples de risque. */
  maxAdverseR: number;
  closedAt: number | null;
  resultR: number | null;
  note: string;
}

const COOLDOWN_MS = 5 * 60_000;
const MAX_LIFETIME_MS = 6 * 60 * 60_000;

export class SignalBook {
  private readonly signals: Signal[] = [];
  private readonly lastEmit = new Map<string, number>();

  /** Signaux encore ouverts. */
  get open(): Signal[] {
    return this.signals.filter((s) => s.closedAt === null);
  }

  get all(): Signal[] {
    return this.signals;
  }

  /** Evalue une lecture de marche et emet les nouveaux signaux. */
  ingest(read: MarketRead, risk: RiskSettings, minRR = 1.2): Signal[] {
    this.track(read.quote.mid, read.ts);

    const emitted: Signal[] = [];
    for (const candidate of read.candidates) {
      if (!candidate.direction || !candidate.levels) continue;

      const key = `${candidate.id}:${candidate.direction}`;
      const previous = this.lastEmit.get(key);
      if (previous !== undefined && read.ts - previous < COOLDOWN_MS) continue;

      // Un seul signal ouvert par strategie et par sens.
      const duplicate = this.open.some(
        (s) => s.strategyId === candidate.id && s.direction === candidate.direction
      );
      if (duplicate) continue;

      const plan = computeRisk(candidate.direction, candidate.levels, risk);
      if (!plan || !isRewardAcceptable(plan, minRR)) continue;

      const signal: Signal = {
        id: `${candidate.id}-${read.ts}`,
        createdAt: read.ts,
        strategyId: candidate.id,
        strategyName: candidate.name,
        family: candidate.family,
        direction: candidate.direction,
        entry: candidate.levels.entry,
        stopLoss: candidate.levels.stopLoss,
        takeProfits: candidate.levels.takeProfits,
        score: candidate.score,
        reasons: candidate.reasons,
        risk: plan,
        session: read.session.label,
        globalScore: read.globalScore,
        alignment: read.alignment,
        status: 'ACTIF',
        maxFavorableR: 0,
        maxAdverseR: 0,
        closedAt: null,
        resultR: null,
        note: `Emis a ${formatUtcTime(read.ts)} — ${read.session.label}`,
      };

      this.signals.unshift(signal);
      this.lastEmit.set(key, read.ts);
      emitted.push(signal);
    }

    if (this.signals.length > 80) this.signals.length = 80;
    return emitted;
  }

  /** Met a jour le sort des signaux ouverts au prix courant. */
  private track(price: number, now: number): void {
    for (const signal of this.signals) {
      if (signal.closedAt !== null) continue;

      const risk = Math.abs(signal.entry - signal.stopLoss);
      if (risk <= 0) continue;

      const sign = signal.direction === 'BUY' ? 1 : -1;
      const moveR = ((price - signal.entry) * sign) / risk;
      signal.maxFavorableR = Math.max(signal.maxFavorableR, moveR);
      signal.maxAdverseR = Math.min(signal.maxAdverseR, moveR);

      const hitStop =
        signal.direction === 'BUY' ? price <= signal.stopLoss : price >= signal.stopLoss;
      if (hitStop) {
        signal.status = 'PERDANT';
        signal.closedAt = now;
        signal.resultR = -1;
        signal.note = `Stop touche a ${signal.stopLoss.toFixed(2)}`;
        continue;
      }

      const [tp1, tp2, tp3] = signal.takeProfits;
      const reached = (target: number) =>
        signal.direction === 'BUY' ? price >= target : price <= target;

      if (tp3 !== undefined && reached(tp3)) {
        signal.status = 'GAGNANT';
        signal.closedAt = now;
        signal.resultR = Math.abs(tp3 - signal.entry) / risk;
        signal.note = `Objectif final atteint a ${tp3.toFixed(2)}`;
        continue;
      }
      if (tp2 !== undefined && reached(tp2)) {
        signal.status = 'TP2';
        signal.note = `TP2 atteint — stop a proteger`;
      } else if (tp1 !== undefined && reached(tp1)) {
        signal.status = 'TP1';
        signal.note = `TP1 atteint — passage a breakeven conseille`;
      }

      if (now - signal.createdAt > MAX_LIFETIME_MS) {
        signal.status = 'EXPIRE';
        signal.closedAt = now;
        signal.resultR = moveR;
        signal.note = 'Signal expire apres 6 h sans resolution';
      }
    }
  }

  stats(): { total: number; wins: number; losses: number; winRate: number; expectancy: number } {
    const closed = this.signals.filter((s) => s.resultR !== null);
    const wins = closed.filter((s) => (s.resultR ?? 0) > 0).length;
    const losses = closed.length - wins;
    const expectancy =
      closed.length > 0
        ? closed.reduce((acc, s) => acc + (s.resultR ?? 0), 0) / closed.length
        : 0;
    return {
      total: closed.length,
      wins,
      losses,
      winRate: closed.length > 0 ? (wins / closed.length) * 100 : 0,
      expectancy,
    };
  }

  restore(signals: Signal[]): void {
    this.signals.splice(0, this.signals.length, ...signals);
  }
}
