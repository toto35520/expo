import { type Candle, TF_MS, TIMEFRAMES, type Timeframe } from './types';

/**
 * Agregateur multi-timeframe.
 *
 * Il est alimente de deux facons complementaires :
 *  - `seed()` avec l'historique cTrader (trendbars) au demarrage ;
 *  - `pushTick()` avec chaque spot event, qui met a jour la bougie en cours.
 *
 * La bougie courante est donc toujours "vivante", ce qui permet a l'analyse de
 * reagir tick par tick sans attendre la cloture.
 */

const MAX_BARS = 1500;

export class CandleSeries {
  private readonly store = new Map<Timeframe, Candle[]>();

  constructor() {
    for (const tf of TIMEFRAMES) this.store.set(tf, []);
  }

  /** Remplace l'historique d'un timeframe (fusion sans doublon). */
  seed(tf: Timeframe, candles: Candle[]): void {
    if (candles.length === 0) return;
    const existing = this.store.get(tf) ?? [];
    const merged = new Map<number, Candle>();
    for (const c of candles) merged.set(c.t, c);
    // Les bougies deja construites en local priment : elles integrent les ticks
    // recus depuis, plus frais que l'historique renvoye par l'API.
    for (const c of existing) merged.set(c.t, c);

    const sorted = [...merged.values()].sort((a, b) => a.t - b.t);
    this.store.set(tf, sorted.slice(-MAX_BARS));
  }

  /** Integre un tick dans tous les timeframes. */
  pushTick(price: number, ts: number, volume = 1): void {
    for (const tf of TIMEFRAMES) {
      const bucket = Math.floor(ts / TF_MS[tf]) * TF_MS[tf];
      const bars = this.store.get(tf)!;
      const current = bars[bars.length - 1];

      if (current && current.t === bucket) {
        current.h = Math.max(current.h, price);
        current.l = Math.min(current.l, price);
        current.c = price;
        current.v += volume;
        continue;
      }

      if (current && bucket < current.t) continue; // tick en retard, on ignore

      bars.push({ t: bucket, o: current?.c ?? price, h: price, l: price, c: price, v: volume });
      if (bars.length > MAX_BARS) bars.splice(0, bars.length - MAX_BARS);
    }
  }

  /** Applique une bougie close renvoyee par cTrader (source de verite). */
  applyClosedBar(tf: Timeframe, candle: Candle): void {
    const bars = this.store.get(tf)!;
    const index = bars.findIndex((b) => b.t === candle.t);
    if (index >= 0) bars[index] = candle;
    else {
      bars.push(candle);
      bars.sort((a, b) => a.t - b.t);
      if (bars.length > MAX_BARS) bars.splice(0, bars.length - MAX_BARS);
    }
  }

  get(tf: Timeframe): Candle[] {
    return this.store.get(tf) ?? [];
  }

  /** Bougies closes uniquement : la derniere est en cours de formation. */
  closed(tf: Timeframe): Candle[] {
    const bars = this.get(tf);
    return bars.length > 1 ? bars.slice(0, -1) : [];
  }

  count(tf: Timeframe): number {
    return this.get(tf).length;
  }

  snapshot(): Record<Timeframe, Candle[]> {
    const out = {} as Record<Timeframe, Candle[]>;
    for (const tf of TIMEFRAMES) out[tf] = this.get(tf).map((c) => ({ ...c }));
    return out;
  }

  restore(snapshot: Partial<Record<Timeframe, Candle[]>>): void {
    for (const tf of TIMEFRAMES) {
      const bars = snapshot[tf];
      if (bars?.length) this.store.set(tf, bars.slice(-MAX_BARS));
    }
  }
}

/** Reconstruit un timeframe superieur a partir d'un inferieur. */
export function resample(candles: Candle[], targetMs: number): Candle[] {
  const out: Candle[] = [];
  for (const c of candles) {
    const bucket = Math.floor(c.t / targetMs) * targetMs;
    const current = out[out.length - 1];
    if (current && current.t === bucket) {
      current.h = Math.max(current.h, c.h);
      current.l = Math.min(current.l, c.l);
      current.c = c.c;
      current.v += c.v;
    } else {
      out.push({ t: bucket, o: c.o, h: c.h, l: c.l, c: c.c, v: c.v });
    }
  }
  return out;
}
