/**
 * cTrader Open API — constantes de protocole.
 *
 * Source : spotware/openapi-proto-messages (OpenApiModelMessages.proto,
 * OpenApiCommonModelMessages.proto). Le proxy accepte le meme protocole en
 * Protobuf binaire (port 5035) ou en JSON (port 5036). On utilise le JSON :
 * enveloppe { clientMsgId, payloadType, payload }.
 */

export const PayloadType = {
  // Commun
  HEARTBEAT_EVENT: 51,

  // Authentification
  APPLICATION_AUTH_REQ: 2100,
  APPLICATION_AUTH_RES: 2101,
  ACCOUNT_AUTH_REQ: 2102,
  ACCOUNT_AUTH_RES: 2103,
  VERSION_REQ: 2104,
  VERSION_RES: 2105,

  // Referentiel symboles
  SYMBOLS_LIST_REQ: 2114,
  SYMBOLS_LIST_RES: 2115,
  SYMBOL_BY_ID_REQ: 2116,
  SYMBOL_BY_ID_RES: 2117,

  // Compte
  TRADER_REQ: 2121,
  TRADER_RES: 2122,

  // Flux temps reel
  SUBSCRIBE_SPOTS_REQ: 2127,
  SUBSCRIBE_SPOTS_RES: 2128,
  UNSUBSCRIBE_SPOTS_REQ: 2129,
  UNSUBSCRIBE_SPOTS_RES: 2130,
  SPOT_EVENT: 2131,
  SUBSCRIBE_LIVE_TRENDBAR_REQ: 2135,
  UNSUBSCRIBE_LIVE_TRENDBAR_REQ: 2136,
  SUBSCRIBE_LIVE_TRENDBAR_RES: 2165,
  UNSUBSCRIBE_LIVE_TRENDBAR_RES: 2166,

  // Historique
  GET_TRENDBARS_REQ: 2137,
  GET_TRENDBARS_RES: 2138,

  // Erreurs / cycle de vie
  ERROR_RES: 2142,
  ACCOUNTS_TOKEN_INVALIDATED_EVENT: 2147,
  CLIENT_DISCONNECT_EVENT: 2148,
  GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ: 2149,
  GET_ACCOUNTS_BY_ACCESS_TOKEN_RES: 2150,
  ACCOUNT_LOGOUT_REQ: 2162,
  ACCOUNT_LOGOUT_RES: 2163,
  ACCOUNT_DISCONNECT_EVENT: 2164,
  REFRESH_TOKEN_REQ: 2173,
  REFRESH_TOKEN_RES: 2174,
} as const;

/** ProtoOATrendbarPeriod */
export const TrendbarPeriod = {
  M1: 1,
  M5: 5,
  M15: 7,
  M30: 8,
  H1: 9,
  H4: 10,
  D1: 12,
} as const;

export type TrendbarPeriodName = keyof typeof TrendbarPeriod;

/**
 * Les prix "relatifs" de l'API (trendbars) sont exprimes en 1/100000 d'unite
 * de prix. Les spots (bid/ask) sont eux exprimes selon `digits` du symbole.
 */
export const RELATIVE_PRICE_SCALE = 100_000;

export const CTRADER_HOSTS = {
  live: 'live.ctraderapi.com',
  demo: 'demo.ctraderapi.com',
} as const;

/** Port du proxy en mode JSON (le 5035 est reserve au Protobuf binaire). */
export const CTRADER_JSON_PORT = 5036;

export type CTraderEnv = keyof typeof CTRADER_HOSTS;

export function wsUrl(env: CTraderEnv): string {
  return `wss://${CTRADER_HOSTS[env]}:${CTRADER_JSON_PORT}`;
}

export const OAUTH_AUTHORIZE_URL = 'https://openapi.ctrader.com/apps/auth';
export const OAUTH_TOKEN_URL = 'https://openapi.ctrader.com/apps/token';

/** Enveloppe JSON du proxy cTrader. */
export interface CTraderMessage<T = Record<string, unknown>> {
  clientMsgId?: string;
  payloadType: number;
  payload: T;
}

export interface CTraderErrorPayload {
  errorCode?: string;
  description?: string;
  maintenanceEndTimestamp?: number;
}

/** ProtoOACtidTraderAccount */
export interface CTraderAccount {
  ctidTraderAccountId: number | string;
  isLive?: boolean;
  traderLogin?: number | string;
  brokerTitleShort?: string;
}

/** ProtoOALightSymbol */
export interface CTraderLightSymbol {
  symbolId: number | string;
  symbolName?: string;
  enabled?: boolean;
  description?: string;
}

/** ProtoOATrendbar — open/high/close sont encodes en delta depuis `low`. */
export interface CTraderTrendbar {
  volume: number | string;
  period?: number;
  low?: number | string;
  deltaOpen?: number | string;
  deltaClose?: number | string;
  deltaHigh?: number | string;
  utcTimestampInMinutes?: number;
}

export interface CTraderSpotPayload {
  ctidTraderAccountId?: number | string;
  symbolId?: number | string;
  bid?: number | string;
  ask?: number | string;
  timestamp?: number | string;
  trendbar?: CTraderTrendbar[];
}

/** Le JSON du proxy renvoie les int64 en nombre ou en chaine selon les champs. */
export function num(value: number | string | undefined | null, fallback = 0): number {
  if (value === undefined || value === null) return fallback;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Reconstitue une bougie OHLC a partir d'une trendbar encodee en deltas. */
export function decodeTrendbar(bar: CTraderTrendbar): {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
} {
  const low = num(bar.low);
  const o = (low + num(bar.deltaOpen)) / RELATIVE_PRICE_SCALE;
  const h = (low + num(bar.deltaHigh)) / RELATIVE_PRICE_SCALE;
  const c = (low + num(bar.deltaClose)) / RELATIVE_PRICE_SCALE;
  return {
    t: num(bar.utcTimestampInMinutes) * 60_000,
    o,
    h,
    l: low / RELATIVE_PRICE_SCALE,
    c,
    v: num(bar.volume),
  };
}
