import { cookies } from 'next/headers';

import { type CTraderEnv, OAUTH_TOKEN_URL } from './protocol';

/**
 * Flux OAuth2 cTrader (cote serveur uniquement).
 *
 * Le token d'acces vit dans un cookie httpOnly : il n'est jamais expose au
 * JavaScript de la page. Le navigateur ne parle jamais a cTrader directement,
 * il passe par les routes /api/ctrader/*.
 */

export const SESSION_COOKIE = 'gla_ct_session';

export interface StoredSession {
  accessToken: string;
  refreshToken: string;
  /** Epoch ms d'expiration de l'access token. */
  expiresAt: number;
  env: CTraderEnv;
  accountId?: number;
  accountLabel?: string;
  symbolId?: number;
  symbolName?: string;
}

export interface AppConfig {
  clientId: string;
  clientSecret: string;
}

export function readAppConfig(): AppConfig | null {
  const clientId = process.env.CTRADER_CLIENT_ID;
  const clientSecret = process.env.CTRADER_CLIENT_SECRET;
  if (!clientId || !clientSecret) return null;
  return { clientId, clientSecret };
}

/**
 * URL de redirection OAuth. On la deduit de la requete pour que l'app marche
 * telle quelle sur les preview deployments Vercel, sauf si elle est figee via
 * CTRADER_REDIRECT_URI (recommande en production : cTrader valide l'URI).
 */
export function resolveRedirectUri(request: Request): string {
  const explicit = process.env.CTRADER_REDIRECT_URI;
  if (explicit) return explicit;

  const url = new URL(request.url);
  const forwardedHost = request.headers.get('x-forwarded-host');
  const forwardedProto = request.headers.get('x-forwarded-proto');
  const host = forwardedHost ?? url.host;
  const proto = forwardedProto ?? (host.startsWith('localhost') ? 'http' : 'https');
  return `${proto}://${host}/api/ctrader/callback`;
}

interface TokenResponse {
  accessToken?: string;
  refreshToken?: string;
  expiresIn?: number;
  errorCode?: string | null;
  description?: string;
}

export interface TokenBundle {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

async function callTokenEndpoint(params: Record<string, string>): Promise<TokenBundle> {
  const url = new URL(OAUTH_TOKEN_URL);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }

  const res = await fetch(url, { method: 'POST', cache: 'no-store' });
  const text = await res.text();

  let body: TokenResponse;
  try {
    body = JSON.parse(text) as TokenResponse;
  } catch {
    throw new Error(`Reponse OAuth illisible (${res.status}): ${text.slice(0, 200)}`);
  }

  if (body.errorCode) {
    throw new Error(`${body.errorCode}: ${body.description ?? 'echec OAuth'}`);
  }
  if (!body.accessToken || !body.refreshToken) {
    throw new Error(`Reponse OAuth incomplete (${res.status})`);
  }

  return {
    accessToken: body.accessToken,
    refreshToken: body.refreshToken,
    // cTrader renvoie ~2 628 000 s (30 jours) ; on garde une valeur de repli.
    expiresIn: body.expiresIn ?? 2_628_000,
  };
}

export async function exchangeCode(
  code: string,
  redirectUri: string,
  config: AppConfig
): Promise<TokenBundle> {
  return callTokenEndpoint({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri,
    client_id: config.clientId,
    client_secret: config.clientSecret,
  });
}

export async function refreshAccessToken(
  refreshToken: string,
  config: AppConfig
): Promise<TokenBundle> {
  return callTokenEndpoint({
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
    client_id: config.clientId,
    client_secret: config.clientSecret,
  });
}

export async function readSession(): Promise<StoredSession | null> {
  const store = await cookies();
  const raw = store.get(SESSION_COOKIE)?.value;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8')) as StoredSession;
    if (!parsed.accessToken) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function serializeSession(session: StoredSession): string {
  return Buffer.from(JSON.stringify(session), 'utf8').toString('base64url');
}

export async function writeSession(session: StoredSession): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE, serializeSession(session), sessionCookieOptions());
}

export function sessionCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax' as const,
    path: '/',
    maxAge: 60 * 60 * 24 * 30,
  };
}

export async function clearSession(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}

/**
 * Renvoie une session avec un access token valide, en le rafraichissant si
 * besoin. Le cookie n'est pas reecrit ici (les routes GET streaming ne peuvent
 * pas toujours poser de cookie) : l'appelant s'en charge quand il le peut.
 */
export async function ensureFreshSession(
  session: StoredSession,
  config: AppConfig
): Promise<{ session: StoredSession; refreshed: boolean }> {
  const marginMs = 5 * 60_000;
  if (session.expiresAt - marginMs > Date.now()) {
    return { session, refreshed: false };
  }

  const tokens = await refreshAccessToken(session.refreshToken, config);
  return {
    session: {
      ...session,
      accessToken: tokens.accessToken,
      refreshToken: tokens.refreshToken,
      expiresAt: Date.now() + tokens.expiresIn * 1000,
    },
    refreshed: true,
  };
}
