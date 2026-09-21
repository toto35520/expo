import { NextResponse } from 'next/server';

import {
  ensureFreshSession,
  readAppConfig,
  readSession,
  SESSION_COOKIE,
  serializeSession,
  sessionCookieOptions,
  writeSession,
} from '@/lib/ctrader/oauth';
import { CTraderSession } from '@/lib/ctrader/session';
import { num } from '@/lib/ctrader/protocol';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 60;

/** Liste les comptes de trading accessibles avec le token courant. */
export async function GET() {
  const config = readAppConfig();
  const stored = await readSession();
  if (!config) return NextResponse.json({ error: 'Application non configuree.' }, { status: 500 });
  if (!stored) return NextResponse.json({ error: 'Non connecte a cTrader.' }, { status: 401 });

  let session = stored;
  let refreshed = false;
  try {
    const fresh = await ensureFreshSession(stored, config);
    session = fresh.session;
    refreshed = fresh.refreshed;
  } catch (err) {
    return NextResponse.json(
      { error: `Impossible de rafraichir le token : ${err instanceof Error ? err.message : 'erreur'}` },
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
    const accounts = await client.listAccounts();

    const payload = accounts.map((a) => ({
      id: num(a.ctidTraderAccountId),
      isLive: a.isLive ?? false,
      login: num(a.traderLogin),
      broker: a.brokerTitleShort ?? 'Broker',
    }));

    const response = NextResponse.json({ accounts: payload, env: session.env });
    if (refreshed) {
      response.cookies.set(SESSION_COOKIE, serializeSession(session), sessionCookieOptions());
    }
    return response;
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Echec de la recuperation des comptes.' },
      { status: 502 }
    );
  } finally {
    client.close();
  }
}

/** Selectionne le compte a analyser (memorise dans le cookie de session). */
export async function POST(request: Request) {
  const stored = await readSession();
  if (!stored) return NextResponse.json({ error: 'Non connecte a cTrader.' }, { status: 401 });

  const body = (await request.json().catch(() => ({}))) as {
    accountId?: number;
    accountLabel?: string;
  };
  if (!body.accountId) {
    return NextResponse.json({ error: 'accountId manquant.' }, { status: 400 });
  }

  await writeSession({
    ...stored,
    accountId: body.accountId,
    accountLabel: body.accountLabel ?? `Compte ${body.accountId}`,
  });

  return NextResponse.json({ ok: true, accountId: body.accountId });
}
