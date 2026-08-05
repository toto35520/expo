import { realizedR } from './sizing';
import type { JournalTrade } from './types';

export interface Expectancy {
  n: number;
  wins: number;
  losses: number;
  winRate: number;
  avgWinR: number;
  avgLossR: number;
  /** (TR × gain moyen) − (TP × perte moyenne), exprimée en R. */
  expectancyR: number;
  totalR: number;
  profitFactor: number;
  /** Sous 100 trades, le taux de réussite n'a pas de valeur statistique. */
  significant: boolean;
}

export function tradeR(t: JournalTrade): number | null {
  if (t.status !== 'CLOSED' || t.exit === null) return null;
  return realizedR(t.entry, t.stop, t.exit, t.direction);
}

export function computeExpectancy(trades: JournalTrade[]): Expectancy {
  const rs = trades.map(tradeR).filter((r): r is number => r !== null);
  const n = rs.length;
  const winsArr = rs.filter((r) => r > 0);
  const lossArr = rs.filter((r) => r <= 0);

  const avgWinR = winsArr.length ? sum(winsArr) / winsArr.length : 0;
  const avgLossR = lossArr.length ? sum(lossArr) / lossArr.length : 0;
  const winRate = n ? winsArr.length / n : 0;

  const grossWin = sum(winsArr);
  const grossLoss = Math.abs(sum(lossArr));

  return {
    n,
    wins: winsArr.length,
    losses: lossArr.length,
    winRate: r2(winRate * 100),
    avgWinR: r2(avgWinR),
    avgLossR: r2(avgLossR),
    expectancyR: r2(winRate * avgWinR + (1 - winRate) * avgLossR),
    totalR: r2(sum(rs)),
    profitFactor: grossLoss > 0 ? r2(grossWin / grossLoss) : grossWin > 0 ? Infinity : 0,
    significant: n >= 100,
  };
}

export interface ExcursionStats {
  n: number;
  /** MAE moyenne des trades gagnants, en R. Dit si le stop est trop large. */
  avgMaeWinnersR: number;
  /** MFE moyenne des trades perdants, en R. Dit si on sort trop tard. */
  avgMfeLosersR: number;
  /** MFE moyenne des gagnants vs R capturé : dit si on sort trop tôt. */
  avgMfeWinnersR: number;
  avgCapturedR: number;
  verdicts: string[];
}

/**
 * Analyse MAE/MFE — le calcul le plus rentable d'un journal.
 * MAE = jusqu'où le prix est allé contre la position avant de repartir.
 * MFE = jusqu'où il est allé en faveur avant la sortie.
 */
export function computeExcursions(trades: JournalTrade[]): ExcursionStats {
  const closed = trades.filter((t) => t.status === 'CLOSED' && t.exit !== null);
  const withData = closed.filter((t) => t.mae !== null || t.mfe !== null);

  const toR = (t: JournalTrade, price: number | null) => {
    if (price === null) return null;
    const risk = Math.abs(t.entry - t.stop);
    return risk > 0 ? Math.abs(price) / risk : null;
  };

  const winners = withData.filter((t) => (tradeR(t) ?? 0) > 0);
  const losers = withData.filter((t) => (tradeR(t) ?? 0) <= 0);

  const maeWin = avg(winners.map((t) => toR(t, t.mae)));
  const mfeLose = avg(losers.map((t) => toR(t, t.mfe)));
  const mfeWin = avg(winners.map((t) => toR(t, t.mfe)));
  const captured = avg(winners.map((t) => tradeR(t)));

  const verdicts: string[] = [];
  if (winners.length >= 5) {
    if (maeWin < 0.5) {
      verdicts.push(
        `Tes gagnants ne vont jamais à plus de ${maeWin.toFixed(2)} R contre toi. Ton stop est trop large : tu peux le resserrer et augmenter la taille à risque égal.`,
      );
    }
    if (mfeWin - captured > 0.8) {
      verdicts.push(
        `Tes gagnants atteignent ${mfeWin.toFixed(2)} R mais tu n'en captures que ${captured.toFixed(2)} R. Ton problème n'est pas l'entrée, c'est la sortie.`,
      );
    }
  }
  if (losers.length >= 5 && mfeLose > 0.8) {
    verdicts.push(
      `Tes perdants passent en moyenne à +${mfeLose.toFixed(2)} R avant de tourner. Envisage une prise partielle ou un stop à l'équilibre à ce niveau.`,
    );
  }
  if (withData.length < 5) {
    verdicts.push(
      'Renseigne MAE et MFE à la clôture : sous 5 trades documentés, ces chiffres ne disent rien.',
    );
  }

  return {
    n: withData.length,
    avgMaeWinnersR: r2(maeWin),
    avgMfeLosersR: r2(mfeLose),
    avgMfeWinnersR: r2(mfeWin),
    avgCapturedR: r2(captured),
    verdicts,
  };
}

export interface Attribution {
  key: string;
  n: number;
  totalR: number;
  expectancyR: number;
}

/**
 * Découpe du P&L par setup / session / grade. Le résultat typique : un seul
 * setup génère tout le profit et les autres saignent.
 */
export function attribute(
  trades: JournalTrade[],
  by: 'setupName' | 'session' | 'grade' | 'direction',
): Attribution[] {
  const groups = new Map<string, JournalTrade[]>();
  for (const t of trades) {
    if (t.status !== 'CLOSED' || t.exit === null) continue;
    const key = String(t[by] || '—');
    groups.set(key, [...(groups.get(key) ?? []), t]);
  }
  return [...groups.entries()]
    .map(([key, ts]) => {
      const e = computeExpectancy(ts);
      return { key, n: e.n, totalR: e.totalR, expectancyR: e.expectancyR };
    })
    .sort((a, b) => b.totalR - a.totalR);
}

/**
 * Monte-Carlo sur la séquence réelle de trades : remélange l'ordre pour
 * estimer le drawdown maximum réaliste. La plupart des traders découvrent que
 * leur drawdown « impossible » est en fait probable.
 */
export function monteCarloDrawdown(
  trades: JournalTrade[],
  runs = 2000,
): { median: number; p95: number; worst: number; n: number } {
  const rs = trades.map(tradeR).filter((r): r is number => r !== null);
  if (rs.length < 10) return { median: 0, p95: 0, worst: 0, n: rs.length };

  const dds: number[] = [];
  for (let i = 0; i < runs; i++) {
    const shuffled = shuffle(rs);
    let equity = 0;
    let peak = 0;
    let maxDd = 0;
    for (const r of shuffled) {
      equity += r;
      peak = Math.max(peak, equity);
      maxDd = Math.max(maxDd, peak - equity);
    }
    dds.push(maxDd);
  }
  dds.sort((a, b) => a - b);
  return {
    median: r2(dds[Math.floor(dds.length * 0.5)]),
    p95: r2(dds[Math.floor(dds.length * 0.95)]),
    worst: r2(dds[dds.length - 1]),
    n: rs.length,
  };
}

/**
 * Kelly fractionnaire. Kelly plein suppose des paramètres connus avec
 * certitude — ce qui n'est jamais le cas — et est psychologiquement
 * intenable, d'où la fraction 1/4.
 */
export function kelly(e: Expectancy): { full: number; quarter: number } | null {
  if (e.n < 30 || e.avgLossR === 0) return null;
  const b = Math.abs(e.avgWinR / e.avgLossR);
  const p = e.winRate / 100;
  const full = (b * p - (1 - p)) / b;
  return { full: r2(full * 100), quarter: r2((full / 4) * 100) };
}

function sum(a: number[]) {
  return a.reduce((s, x) => s + x, 0);
}
function avg(a: (number | null)[]) {
  const v = a.filter((x): x is number => x !== null && Number.isFinite(x));
  return v.length ? sum(v) / v.length : 0;
}
function r2(n: number) {
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0;
}
function shuffle<T>(a: T[]): T[] {
  const out = [...a];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
