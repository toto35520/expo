'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { analyze, type AnalyzerSettings, DEFAULT_SETTINGS, type MarketRead } from '@/lib/engine/analyzer';
import { buildNarrative, type Narrative } from '@/lib/engine/narrative';
import { DEFAULT_RISK, type RiskSettings } from '@/lib/engine/risk';
import { type Signal, SignalBook } from '@/lib/engine/signals';
import { CandleSeries } from '@/lib/market/candles';
import type { Candle, Quote, Timeframe } from '@/lib/market/types';

export type FeedSource = 'CTRADER' | 'SECOURS' | 'AUCUNE';

export type FeedStatus =
  | 'HORS_LIGNE'
  | 'CHARGEMENT_HISTORIQUE'
  | 'CONNEXION'
  | 'EN_DIRECT'
  | 'RECONNEXION'
  | 'ERREUR';

export interface EngineState {
  status: FeedStatus;
  source: FeedSource;
  symbolName: string | null;
  quote: Quote | null;
  read: MarketRead | null;
  narrative: Narrative | null;
  signals: Signal[];
  lastTickAt: number | null;
  ticksReceived: number;
  error: string | null;
}

const ANALYSIS_INTERVAL_MS = 1000;

/**
 * Moteur temps reel.
 *
 * Le flux arrive par SSE depuis /api/ctrader/stream (ou, a defaut, par
 * interrogation de la source de secours). Chaque tick met a jour les bougies ;
 * l'analyse complete tourne a cadence fixe pour rester fluide meme quand le
 * marche envoie des dizaines de ticks par seconde.
 */
export function useGoldEngine(params: {
  accountId: number | null;
  symbolId: number | null;
  settings: AnalyzerSettings;
  risk: RiskSettings;
  enabled: boolean;
  onSignal?: (signal: Signal) => void;
}) {
  const { accountId, symbolId, settings, risk, enabled } = params;

  const seriesRef = useRef<CandleSeries>(new CandleSeries());
  const bookRef = useRef<SignalBook>(new SignalBook());
  const quoteRef = useRef<Quote | null>(null);
  const settingsRef = useRef(settings);
  const riskRef = useRef(risk);
  const onSignalRef = useRef(params.onSignal);
  const tickCountRef = useRef(0);
  const seededRef = useRef(false);

  const [state, setState] = useState<EngineState>({
    status: 'HORS_LIGNE',
    source: 'AUCUNE',
    symbolName: null,
    quote: null,
    read: null,
    narrative: null,
    signals: [],
    lastTickAt: null,
    ticksReceived: 0,
    error: null,
  });

  settingsRef.current = settings;
  riskRef.current = risk;
  onSignalRef.current = params.onSignal;

  const applyQuote = useCallback((bid: number | null, ask: number | null, ts: number) => {
    const previous = quoteRef.current;
    const nextBid = bid ?? previous?.bid ?? ask ?? 0;
    const nextAsk = ask ?? previous?.ask ?? bid ?? 0;
    if (nextBid <= 0 || nextAsk <= 0) return;

    const quote: Quote = {
      bid: nextBid,
      ask: nextAsk,
      mid: (nextBid + nextAsk) / 2,
      spread: Math.max(nextAsk - nextBid, 0),
      ts,
    };
    quoteRef.current = quote;
    tickCountRef.current += 1;
    seriesRef.current.pushTick(quote.mid, ts);
  }, []);

  /** Boucle d'analyse : elle tourne meme sans nouveau tick, pour le temps. */
  useEffect(() => {
    if (!enabled) return;

    const timer = setInterval(() => {
      const quote = quoteRef.current;
      if (!quote) return;

      const read = analyze(seriesRef.current, quote, settingsRef.current, Date.now());
      const emitted = bookRef.current.ingest(read, riskRef.current);
      for (const signal of emitted) onSignalRef.current?.(signal);

      const narrative = buildNarrative(read, settingsRef.current.entryTf, settingsRef.current.contextTf);

      setState((prev) => ({
        ...prev,
        quote,
        read,
        narrative,
        signals: [...bookRef.current.all],
        lastTickAt: quote.ts,
        ticksReceived: tickCountRef.current,
      }));
    }, ANALYSIS_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [enabled]);

  /** Amorcage de l'historique + flux SSE cTrader. */
  useEffect(() => {
    if (!enabled || !accountId) return;

    let cancelled = false;
    let source: EventSource | null = null;

    const seed = async () => {
      setState((prev) => ({ ...prev, status: 'CHARGEMENT_HISTORIQUE', error: null }));
      try {
        const res = await fetch(`/api/ctrader/history?accountId=${accountId}`, { cache: 'no-store' });
        const body = (await res.json()) as {
          error?: string;
          symbol?: { id: number; name: string };
          candles?: Partial<Record<Timeframe, Candle[]>>;
        };
        if (!res.ok) throw new Error(body.error ?? 'Historique indisponible.');
        if (cancelled) return null;

        for (const [tf, candles] of Object.entries(body.candles ?? {})) {
          if (candles && candles.length > 0) seriesRef.current.seed(tf as Timeframe, candles);
        }
        seededRef.current = true;

        const m1 = seriesRef.current.get('M1');
        const lastBar = m1[m1.length - 1];
        if (lastBar && !quoteRef.current) {
          applyQuote(lastBar.c - 0.1, lastBar.c + 0.1, lastBar.t);
        }

        setState((prev) => ({ ...prev, symbolName: body.symbol?.name ?? prev.symbolName }));
        return body.symbol?.id ?? symbolId ?? null;
      } catch (err) {
        if (!cancelled) {
          setState((prev) => ({
            ...prev,
            status: 'ERREUR',
            error: err instanceof Error ? err.message : 'Historique indisponible.',
          }));
        }
        return null;
      }
    };

    const open = (resolvedSymbolId: number | null) => {
      if (cancelled) return;
      const query = new URLSearchParams({ accountId: String(accountId) });
      if (resolvedSymbolId) query.set('symbolId', String(resolvedSymbolId));

      setState((prev) => ({ ...prev, status: 'CONNEXION', source: 'CTRADER' }));
      source = new EventSource(`/api/ctrader/stream?${query.toString()}`);

      source.addEventListener('hello', (event) => {
        const data = JSON.parse((event as MessageEvent<string>).data) as { symbolName?: string };
        setState((prev) => ({
          ...prev,
          status: 'EN_DIRECT',
          source: 'CTRADER',
          symbolName: data.symbolName ?? prev.symbolName,
          error: null,
        }));
      });

      source.addEventListener('tick', (event) => {
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          bid: number | null;
          ask: number | null;
          ts: number;
        };
        applyQuote(data.bid, data.ask, data.ts);
      });

      source.addEventListener('bar', (event) => {
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          tf: Timeframe;
          candle: Candle;
        };
        seriesRef.current.applyClosedBar(data.tf, data.candle);
      });

      source.addEventListener('fatal', (event) => {
        const data = JSON.parse((event as MessageEvent<string>).data) as { reason?: string };
        setState((prev) => ({ ...prev, status: 'ERREUR', error: data.reason ?? 'Flux interrompu.' }));
        source?.close();
      });

      // 'reconnect' est emis avant la rotation planifiee : EventSource
      // rouvre tout seul, on signale juste l'etat a l'interface.
      source.addEventListener('reconnect', () => {
        setState((prev) => ({ ...prev, status: 'RECONNEXION' }));
      });

      source.onerror = () => {
        setState((prev) => ({
          ...prev,
          status: prev.status === 'EN_DIRECT' ? 'RECONNEXION' : 'CONNEXION',
        }));
      };
    };

    void seed().then(open);

    return () => {
      cancelled = true;
      source?.close();
    };
  }, [enabled, accountId, symbolId, applyQuote]);

  /** Source de secours quand aucun compte n'est connecte. */
  useEffect(() => {
    if (!enabled || accountId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      try {
        const res = await fetch('/api/market/fallback', { cache: 'no-store' });
        const body = (await res.json()) as {
          error?: string;
          source?: string;
          quote?: { bid: number; ask: number; ts: number };
          candles?: Partial<Record<Timeframe, Candle[]>>;
        };
        if (cancelled) return;
        if (!res.ok || !body.quote) throw new Error(body.error ?? 'Source de secours indisponible.');

        if (!seededRef.current) {
          for (const [tf, candles] of Object.entries(body.candles ?? {})) {
            if (candles && candles.length > 0) seriesRef.current.seed(tf as Timeframe, candles);
          }
          seededRef.current = true;
        }

        applyQuote(body.quote.bid, body.quote.ask, body.quote.ts);
        setState((prev) => ({
          ...prev,
          status: 'EN_DIRECT',
          source: 'SECOURS',
          symbolName: body.source ?? 'XAU/USD (indicatif)',
          error: null,
        }));
      } catch (err) {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          status: 'ERREUR',
          source: 'SECOURS',
          error: err instanceof Error ? err.message : 'Source de secours indisponible.',
        }));
      }
    };

    setState((prev) => ({ ...prev, status: 'CHARGEMENT_HISTORIQUE', source: 'SECOURS' }));
    void poll();
    timer = setInterval(poll, 20_000);

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [enabled, accountId, applyQuote]);

  const stats = useMemo(() => bookRef.current.stats(), [state.signals]);

  const reset = useCallback(() => {
    seriesRef.current = new CandleSeries();
    bookRef.current = new SignalBook();
    quoteRef.current = null;
    tickCountRef.current = 0;
    seededRef.current = false;
    setState((prev) => ({ ...prev, read: null, narrative: null, signals: [], quote: null }));
  }, []);

  return { ...state, stats, reset, settings: settingsRef.current, defaults: { DEFAULT_SETTINGS, DEFAULT_RISK } };
}
