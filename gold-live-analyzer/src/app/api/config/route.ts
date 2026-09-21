import { NextResponse } from 'next/server';

import { readAppConfig, readSession, resolveRedirectUri } from '@/lib/ctrader/oauth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Etat de configuration de l'app — jamais le clientSecret. */
export async function GET(request: Request) {
  const config = readAppConfig();
  const session = await readSession();

  return NextResponse.json({
    configured: config !== null,
    clientId: config?.clientId ?? null,
    redirectUri: resolveRedirectUri(request),
    connected: session !== null,
    env: session?.env ?? null,
    accountId: session?.accountId ?? null,
    accountLabel: session?.accountLabel ?? null,
    symbolName: session?.symbolName ?? null,
    preferredSymbol: process.env.GOLD_SYMBOL ?? null,
  });
}
