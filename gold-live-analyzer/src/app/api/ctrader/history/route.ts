import { NextResponse } from 'next/server';

import {
  ensureFreshSession,
  readAppConfig,
  readSession,
  SESSION_COOKIE,
  serializeSession,
  sessionCookieOptions,
} from '@/lib/ctrader/oauth';
import { num } from '@/lib/ctrader/protocol';
import { type Candle, CTraderSession } from '@/lib/ctrader/session';
import type { Timeframe } from '@/lib/market/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 60;

/**
 * Historique multi-timeframe pour amorcer le moteur.
 *
 * Les quantites sont calibrees pour rester sous les limites de plage du proxy
 * cTrader (les petites unites de temps sont bornees a quelques jours).
 */
const REQUESTS: { tf: Timeframe; count: number }[] = [
  { tf: 'M1', count: 300 },
  { tf: 'M5', count: 400 },
  { tf: 'M15', count: 400 },
  { tf: 'H1', count: 400 },
  { tf: 'H4', count: 180 },
];

export async function GET(request: Request) {
  const config = readAppConfig();
  const stored = await readSession();
  if (!config) return NextResponse.json({ error: 'Application non configuree.' }, { status: 500 });
  if (!stored) return NextResponse.json({ error: 'Non connecte a cTrader.' }, { status: 401 });

  const url = new URL(request.url);
  const accountId = Number(url.searchParams.get('accountId') ?? stored.accountId ?? 0);
  if (!accountId) {
    return NextResponse.json({ error: 'Aucun compte selectionne.' }, { status: 400 });
  }

  let session = stored;
  let refreshed = false;
  try {
    const fresh = await ensureFreshSession(stored, config);
    session = fresh.session;
    refreshed = fresh.refreshed;
  } catch (err) {
    return NextResponse.json(
      { error: `Token invalide : ${err instanceof Error ? err.message : 'erreur'}` },
      { status: 401 }
    );
  }

  const client = new CTraderSession({
    env: session.env,
    clientId: config.clientId,
    clientSecret: config.clientSecret,
    accessToken: session.accessToken,
  });

  try {
    await client.connect();
    await client.authorizeAccount(accountId);

    const symbols = await client.listSymbols(accountId);
    const gold = CTraderSession.pickGoldSymbol(symbols, process.env.GOLD_SYMBOL);
    if (!gold) {
      return NextResponse.json(
        { error: "Aucun symbole or (XAU/USD) trouve sur ce compte." },
        { status: 404 }
      );
    }

    const symbolId = num(gold.symbolId);
    const candles: Partial<Record<Timeframe, Candle[]>> = {};

    for (const req of REQUESTS) {
      try {
        candles[req.tf] = await client.getTrendbars(accountId, symbolId, req.tf, req.count);
      } catch {
        // Un timeframe indisponible ne doit pas casser l'amorcage complet.
        candles[req.tf] = [];
      }
    }

    const response = NextResponse.json({
      symbol: { id: symbolId, name: gold.symbolName ?? 'XAUUSD' },
      candles,
    });
    if (refreshed) {
      response.cookies.set(SESSION_COOKIE, serializeSession(session), sessionCookieOptions());
    }
    return response;
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Echec de la recuperation de l'historique." },
      { status: 502 }
    );
  } finally {
    client.close();
  }
}
