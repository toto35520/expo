import { NextResponse } from 'next/server';

import type { Candle, Timeframe } from '@/lib/market/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 30;

/**
 * Source de secours, utilisee uniquement tant que cTrader n'est pas connecte.
 *
 * Elle sert a faire tourner le moteur et l'interface sans compte broker. Les
 * donnees sont indicatives (cotation de reference, pas le flux du broker) :
 * l'analyse officielle et les signaux diffuses s'appuient sur cTrader.
 */

const SOURCES = ['XAUUSD=X', 'GC=F'] as const;

const INTERVALS: { tf: Timeframe; interval: string; range: string }[] = [
  { tf: 'M1', interval: '1m', range: '1d' },
  { tf: 'M5', interval: '5m', range: '5d' },
  { tf: 'M15', interval: '15m', range: '1mo' },
  { tf: 'H1', interval: '1h', range: '3mo' },
  { tf: 'H4', interval: '1h', range: '6mo' },
];

interface YahooChart {
  chart?: {
    result?: {
      meta?: { regularMarketPrice?: number; symbol?: string };
      timestamp?: number[];
      indicators?: {
        quote?: {
          open?: (number | null)[];
          high?: (number | null)[];
          low?: (number | null)[];
          close?: (number | null)[];
          volume?: (number | null)[];
        }[];
      };
    }[];
    error?: { description?: string } | null;
  };
}

async function fetchSeries(
  symbol: string,
  interval: string,
  range: string
): Promise<{ candles: Candle[]; price: number | null }> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`;
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; gold-live-analyzer)' },
    cache: 'no-store',
    signal: AbortSignal.timeout(12_000),
  });
  if (!res.ok) throw new Error(`source indisponible (${res.status})`);

  const body = (await res.json()) as YahooChart;
  const result = body.chart?.result?.[0];
  const quote = result?.indicators?.quote?.[0];
  const stamps = result?.timestamp;
  if (!result || !quote || !stamps) throw new Error('reponse sans donnees exploitables');

  const candles: Candle[] = [];
  for (let i = 0; i < stamps.length; i++) {
    const o = quote.open?.[i];
    const h = quote.high?.[i];
    const l = quote.low?.[i];
    const c = quote.close?.[i];
    if (o == null || h == null || l == null || c == null) continue;
    candles.push({ t: stamps[i] * 1000, o, h, l, c, v: quote.volume?.[i] ?? 1 });
  }

  return { candles, price: result.meta?.regularMarketPrice ?? null };
}

/** Agrege des bougies H1 en H4 (Yahoo n'expose pas le 4 h). */
function toH4(candles: Candle[]): Candle[] {
  const out: Candle[] = [];
  for (const c of candles) {
    const bucket = Math.floor(c.t / 14_400_000) * 14_400_000;
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

export async function GET() {
  const errors: string[] = [];

  for (const symbol of SOURCES) {
    try {
      const candles: Partial<Record<Timeframe, Candle[]>> = {};
      let price: number | null = null;

      for (const spec of INTERVALS) {
        const series = await fetchSeries(symbol, spec.interval, spec.range);
        candles[spec.tf] = spec.tf === 'H4' ? toH4(series.candles) : series.candles;
        price ??= series.price;
      }

      const m1 = candles.M1 ?? [];
      const lastClose = m1.length > 0 ? m1[m1.length - 1].c : price;
      if (lastClose == null) throw new Error('aucun prix exploitable');

      return NextResponse.json({
        source: symbol,
        indicative: true,
        // Spread indicatif : la source publique ne cote pas bid/ask.
        quote: { bid: lastClose - 0.15, ask: lastClose + 0.15, ts: Date.now() },
        candles,
      });
    } catch (err) {
      errors.push(`${symbol} : ${err instanceof Error ? err.message : 'erreur'}`);
    }
  }

  return NextResponse.json(
    {
      error: "Aucune source de secours joignable. Connectez cTrader pour le flux reel.",
      details: errors,
    },
    { status: 503 }
  );
}
