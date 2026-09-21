import { NextResponse } from 'next/server';

import { readSession } from '@/lib/ctrader/oauth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Etat de la session, sans jamais exposer les tokens. */
export async function GET() {
  const session = await readSession();
  if (!session) return NextResponse.json({ connected: false });

  return NextResponse.json({
    connected: true,
    env: session.env,
    expiresAt: session.expiresAt,
    accountId: session.accountId ?? null,
    accountLabel: session.accountLabel ?? null,
    symbolId: session.symbolId ?? null,
    symbolName: session.symbolName ?? null,
  });
}
