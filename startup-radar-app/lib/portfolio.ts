import type { Position, Quote } from "./types";

export interface Valued extends Position {
  value: number;
  pnl: number;
  pnlPct: number | null;
  quote: Quote | null;
  dayChangeEUR: number | null;
}

export function valuePosition(p: Position, quotes: Record<string, Quote>): Valued {
  const quote = p.ticker ? quotes[p.ticker] ?? null : null;
  let value = p.manualValue ?? p.invested;
  let dayChangeEUR: number | null = null;
  if (p.kind === "cote" && quote && p.quantity) {
    value = p.quantity * quote.priceEUR;
    if (quote.change1d != null) dayChangeEUR = value - value / (1 + quote.change1d / 100);
  }
  const pnl = value - p.invested;
  return { ...p, value, pnl, pnlPct: p.invested ? (pnl / p.invested) * 100 : null, quote, dayChangeEUR };
}

export function summarize(positions: Position[], quotes: Record<string, Quote>) {
  const valued = positions.map((p) => valuePosition(p, quotes));
  const value = valued.reduce((s, p) => s + p.value, 0);
  const invested = valued.reduce((s, p) => s + p.invested, 0);
  const day = valued.reduce((s, p) => s + (p.dayChangeEUR ?? 0), 0);
  return { valued, value, invested, pnl: value - invested, pnlPct: invested ? ((value - invested) / invested) * 100 : null, day };
}
