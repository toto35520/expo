import { NextResponse } from 'next/server';

import { readAppConfig, resolveRedirectUri } from '@/lib/ctrader/oauth';
import { OAUTH_AUTHORIZE_URL } from '@/lib/ctrader/protocol';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Redirige vers la page de consentement cTrader. */
export async function GET(request: Request) {
  const config = readAppConfig();
  if (!config) {
    return NextResponse.json(
      { error: 'CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET absents de la configuration.' },
      { status: 500 }
    );
  }

  const incoming = new URL(request.url);
  const env = incoming.searchParams.get('env') === 'demo' ? 'demo' : 'live';

  const url = new URL(OAUTH_AUTHORIZE_URL);
  url.searchParams.set('client_id', config.clientId);
  url.searchParams.set('redirect_uri', resolveRedirectUri(request));
  // `trading` donne acces aux donnees de marche temps reel du compte.
  url.searchParams.set('scope', 'trading');
  url.searchParams.set('state', env);

  return NextResponse.redirect(url.toString());
}
