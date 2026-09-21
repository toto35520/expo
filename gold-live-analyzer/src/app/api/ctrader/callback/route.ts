import { NextResponse } from 'next/server';

import {
  exchangeCode,
  readAppConfig,
  resolveRedirectUri,
  SESSION_COOKIE,
  serializeSession,
  sessionCookieOptions,
  type StoredSession,
} from '@/lib/ctrader/oauth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Retour OAuth : on echange le code contre un token et on pose le cookie. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get('code');
  const error = url.searchParams.get('error');
  const env = url.searchParams.get('state') === 'demo' ? 'demo' : 'live';

  const home = new URL('/', url.origin);

  if (error) {
    home.searchParams.set('erreur', `Connexion refusee par cTrader : ${error}`);
    return NextResponse.redirect(home);
  }
  if (!code) {
    home.searchParams.set('erreur', 'Code OAuth manquant dans la reponse cTrader.');
    return NextResponse.redirect(home);
  }

  const config = readAppConfig();
  if (!config) {
    home.searchParams.set('erreur', 'Application non configuree (identifiants cTrader absents).');
    return NextResponse.redirect(home);
  }

  try {
    const tokens = await exchangeCode(code, resolveRedirectUri(request), config);
    const session: StoredSession = {
      accessToken: tokens.accessToken,
      refreshToken: tokens.refreshToken,
      expiresAt: Date.now() + tokens.expiresIn * 1000,
      env,
    };

    home.searchParams.set('connecte', '1');
    const response = NextResponse.redirect(home);
    response.cookies.set(SESSION_COOKIE, serializeSession(session), sessionCookieOptions());
    return response;
  } catch (err) {
    home.searchParams.set(
      'erreur',
      err instanceof Error ? err.message : "Echec de l'echange du code OAuth."
    );
    return NextResponse.redirect(home);
  }
}
