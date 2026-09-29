import type { Quote } from "./types";

const UA = "Mozilla/5.0 (compatible; RadarStartups/1.0)";

async function fetchWithTimeout(url: string, ms = 10000, init: RequestInit = {}): Promise<Response> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal, cache: "no-store", headers: { "User-Agent": UA, ...(init.headers || {}) } });
  } finally {
    clearTimeout(t);
  }
}

/** Taux de change BCE : combien de dollars et de livres pour 1 euro. */
export async function getFx(): Promise<{ USD: number; GBP: number }> {
  try {
    const r = await fetchWithTimeout("https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD,GBP");
    if (r.ok) {
      const j = (await r.json()) as { rates?: { USD?: number; GBP?: number } };
      if (j.rates?.USD && j.rates?.GBP) return { USD: j.rates.USD, GBP: j.rates.GBP };
    }
  } catch {
    /* on tente Yahoo ensuite */
  }
  const [usd, gbp] = await Promise.all([yahooChart("EURUSD=X"), yahooChart("EURGBP=X")]);
  if (!usd || !gbp) throw new Error("Taux de change indisponibles");
  return { USD: usd.price, GBP: gbp.price };
}

function toEUR(price: number, currency: string, fx: { USD: number; GBP: number }): number {
  if (currency === "EUR") return price;
  if (currency === "USD") return price / fx.USD;
  if (currency === "GBp" || currency === "GBX") return price / 100 / fx.GBP;
  if (currency === "GBP") return price / fx.GBP;
  return price / fx.USD;
}

interface RawQuote {
  price: number;
  currency: string;
  closes: number[];
  name?: string;
}

async function yahooChart(symbol: string): Promise<RawQuote | null> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=3mo&interval=1d`;
  const r = await fetchWithTimeout(url);
  if (!r.ok) return null;
  const j = (await r.json()) as {
    chart?: {
      result?: Array<{
        meta?: { regularMarketPrice?: number; currency?: string; longName?: string; shortName?: string };
        indicators?: { quote?: Array<{ close?: Array<number | null> }> };
      }>;
    };
  };
  const res = j.chart?.result?.[0];
  const price = res?.meta?.regularMarketPrice;
  if (!res || typeof price !== "number") return null;
  const closes = (res.indicators?.quote?.[0]?.close ?? []).filter((x): x is number => typeof x === "number");
  return { price, currency: res.meta?.currency ?? "USD", closes, name: res.meta?.longName || res.meta?.shortName };
}

/** Secours sans clé : Stooq (cours de clôture). */
async function stooq(symbol: string): Promise<RawQuote | null> {
  let s = symbol.toLowerCase();
  let currency = "USD";
  if (s.endsWith(".l")) {
    s = s.replace(/\.l$/, ".uk");
    currency = "GBp";
  } else if (s.endsWith(".pa")) {
    s = s.replace(/\.pa$/, ".fr");
    currency = "EUR";
  } else if (!s.includes(".")) s += ".us";
  const r = await fetchWithTimeout(`https://stooq.com/q/d/l/?s=${encodeURIComponent(s)}&i=d`);
  if (!r.ok) return null;
  const lines = (await r.text()).trim().split("\n").slice(1);
  const closes = lines
    .map((l) => Number(l.split(",")[4]))
    .filter((n) => Number.isFinite(n) && n > 0)
    .slice(-65);
  if (!closes.length) return null;
  return { price: closes[closes.length - 1], currency, closes };
}

function pct(a: number | undefined, b: number): number | null {
  if (!a || !Number.isFinite(a)) return null;
  return ((b - a) / a) * 100;
}

export async function getQuote(symbol: string, fx: { USD: number; GBP: number }): Promise<Quote> {
  let raw: RawQuote | null = null;
  let source: Quote["source"] = "yahoo";
  try {
    raw = await yahooChart(symbol);
  } catch {
    raw = null;
  }
  if (!raw) {
    source = "stooq";
    raw = await stooq(symbol).catch(() => null);
  }
  if (!raw) throw new Error(`Cours introuvable pour ${symbol}`);
  const c = raw.closes;
  const prev = c.length >= 2 ? c[c.length - 2] : undefined;
  const monthAgo = c.length >= 22 ? c[c.length - 22] : c[0];
  return {
    symbol,
    name: raw.name,
    price: raw.price,
    currency: raw.currency,
    priceEUR: toEUR(raw.price, raw.currency, fx),
    change1d: pct(prev, raw.price),
    change1m: pct(monthAgo, raw.price),
    closes: c.slice(-65),
    at: new Date().toISOString(),
    source,
  };
}

/** Trouve le symbole Yahoo d'un ISIN (utile après un import Trade Republic). */
export async function resolveIsin(isin: string): Promise<string | null> {
  try {
    const r = await fetchWithTimeout(
      `https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(isin)}&quotesCount=3&newsCount=0`,
    );
    if (!r.ok) return null;
    const j = (await r.json()) as { quotes?: Array<{ symbol?: string; quoteType?: string }> };
    const q = j.quotes?.find((x) => x.symbol && (x.quoteType === "EQUITY" || x.quoteType === "ETF")) ?? j.quotes?.[0];
    return q?.symbol ?? null;
  } catch {
    return null;
  }
}

export { fetchWithTimeout };
