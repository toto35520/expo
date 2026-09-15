/**
 * Definitions des messages cTrader Open API.
 *
 * ── NIVEAU DE CONFIANCE DES NUMEROS DE CHAMP ─────────────────────────────
 * Les numeros ci-dessous proviennent des fichiers .proto publics de l'Open
 * API. Ceux marques (*) sont surs (utilises par tous les clients, stables
 * depuis des annees). Ceux marques (?) sont moins certains et peuvent varier
 * selon la version du broker.
 *
 * Le decodeur REFUSE de lire un champ dont le type de fil ne correspond pas
 * au schema (voir protobuf.js) : un numero errone se traduit par une valeur
 * absente et une entree dans `__wireMismatch`, jamais par une valeur fausse.
 *
 * Pour verifier la realite d'un broker : `gs-live discover --symbol XAUUSD`
 * affiche les champs reellement recus avec leur numero et leur type.
 */

/** Types de payload (ProtoOAPayloadType / ProtoPayloadType). */
export const PT = {
  PROTO_MESSAGE: 5,
  ERROR_RES: 50,
  HEARTBEAT_EVENT: 51,

  APPLICATION_AUTH_REQ: 2100,
  APPLICATION_AUTH_RES: 2101,
  ACCOUNT_AUTH_REQ: 2102,
  ACCOUNT_AUTH_RES: 2103,
  VERSION_REQ: 2104,
  VERSION_RES: 2105,
  NEW_ORDER_REQ: 2106,
  TRAILING_SL_CHANGED_EVENT: 2107,
  CANCEL_ORDER_REQ: 2108,
  AMEND_ORDER_REQ: 2109,
  AMEND_POSITION_SLTP_REQ: 2110,
  CLOSE_POSITION_REQ: 2111,
  ASSET_LIST_REQ: 2112,
  ASSET_LIST_RES: 2113,
  SYMBOLS_LIST_REQ: 2114,
  SYMBOLS_LIST_RES: 2115,
  SYMBOL_BY_ID_REQ: 2116,
  SYMBOL_BY_ID_RES: 2117,
  TRADER_REQ: 2121,
  TRADER_RES: 2122,
  TRADER_UPDATE_EVENT: 2123,
  RECONCILE_REQ: 2124,
  RECONCILE_RES: 2125,
  EXECUTION_EVENT: 2126,
  SUBSCRIBE_SPOTS_REQ: 2127,
  SUBSCRIBE_SPOTS_RES: 2128,
  UNSUBSCRIBE_SPOTS_REQ: 2129,
  UNSUBSCRIBE_SPOTS_RES: 2130,
  SPOT_EVENT: 2131,
  ORDER_ERROR_EVENT: 2132,
  SUBSCRIBE_LIVE_TRENDBAR_REQ: 2135,
  UNSUBSCRIBE_LIVE_TRENDBAR_REQ: 2136,
  GET_TRENDBARS_REQ: 2137,
  GET_TRENDBARS_RES: 2138,
  ERROR_RES_OA: 2142,
  ACCOUNTS_TOKEN_INVALIDATED_EVENT: 2147,
  CLIENT_DISCONNECT_EVENT: 2148,
  GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ: 2149,
  GET_ACCOUNTS_BY_ACCESS_TOKEN_RES: 2150,
  REFRESH_TOKEN_REQ: 2173,
  REFRESH_TOKEN_RES: 2174,
};

/** Nom lisible d'un type de payload (pour les journaux). */
export const PT_NAME = Object.fromEntries(Object.entries(PT).map(([k, v]) => [v, k]));

/** ProtoOATrendbarPeriod. */
export const PERIOD = {
  M1: 1, M2: 2, M3: 3, M4: 4, M5: 5, M10: 6, M15: 7, M30: 8,
  H1: 9, H4: 10, H12: 11, D1: 12, W1: 13, MN1: 14,
};

/** ProtoOAOrderType. */
export const ORDER_TYPE = { MARKET: 1, LIMIT: 2, STOP: 3, STOP_LIMIT: 4, MARKET_RANGE: 5, STOP_LOSS_TAKE_PROFIT: 6 };
/** ProtoOATradeSide. */
export const TRADE_SIDE = { BUY: 1, SELL: 2 };
/** ProtoOATimeInForce. */
export const TIF = { GOOD_TILL_DATE: 1, GOOD_TILL_CANCEL: 2, IMMEDIATE_OR_CANCEL: 3, MARKET_ON_OPEN: 4, FILL_OR_KILL: 5 };

/** Enveloppe de transport. (*) */
export const ProtoMessage = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'payload', type: 'bytes' },
  3: { name: 'clientMsgId', type: 'string' },
};

/** (*) */
export const ProtoHeartbeatEvent = {
  1: { name: 'payloadType', type: 'uint32' },
};

/** (*) */
export const ProtoOAApplicationAuthReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'clientId', type: 'string' },
  3: { name: 'clientSecret', type: 'string' },
};

/** (*) */
export const ProtoOAAccountAuthReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'accessToken', type: 'string' },
};

/** (*) */
export const ProtoOAAccountAuthRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
};

/** (*) */
export const ProtoOAErrorRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'errorCode', type: 'string' },
  4: { name: 'description', type: 'string' },
  5: { name: 'maintenanceEndTimestamp', type: 'int64' },
  6: { name: 'retryAfter', type: 'uint64' },
};

/** (*) */
export const ProtoOAGetAccountListByAccessTokenReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'accessToken', type: 'string' },
};

/** (?) seuls les champs 1-3 sont exploites par ce client. */
export const ProtoOACtidTraderAccount = {
  1: { name: 'ctidTraderAccountId', type: 'uint64' },
  2: { name: 'isLive', type: 'bool' },
  3: { name: 'traderLogin', type: 'uint64' },
};

/** (*) */
export const ProtoOAGetAccountListByAccessTokenRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'accessToken', type: 'string' },
  3: { name: 'permissionScope', type: 'enum' },
  4: { name: 'ctidTraderAccount', type: 'message', message: ProtoOACtidTraderAccount, repeated: true },
};

/** (*) */
export const ProtoOASymbolsListReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'includeArchivedSymbols', type: 'bool' },
};

/** (*) */
export const ProtoOALightSymbol = {
  1: { name: 'symbolId', type: 'int64' },
  2: { name: 'symbolName', type: 'string' },
  3: { name: 'enabled', type: 'bool' },
  4: { name: 'baseAssetId', type: 'int64' },
  5: { name: 'quoteAssetId', type: 'int64' },
  6: { name: 'symbolCategoryId', type: 'int64' },
  7: { name: 'description', type: 'string' },
};

/** (*) */
export const ProtoOASymbolsListRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'symbol', type: 'message', message: ProtoOALightSymbol, repeated: true },
};

/** (*) */
export const ProtoOASymbolByIdReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'symbolId', type: 'int64', repeated: true },
};

/**
 * (?) ProtoOASymbol est un message tres large dont seuls `symbolId`,
 * `digits` et `pipPosition` sont ici consideres comme fiables.
 * Les tailles de lot / volumes min-pas doivent etre CONFIRMEES via
 * `gs-live discover`, pas devinees : c'est du code qui dimensionne
 * des positions.
 */
export const ProtoOASymbol = {
  1: { name: 'symbolId', type: 'int64' },
  2: { name: 'digits', type: 'int64' },
  3: { name: 'pipPosition', type: 'int64' },
};

/** (*) */
export const ProtoOASymbolByIdRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'symbol', type: 'message', message: ProtoOASymbol, repeated: true },
};

/**
 * (*) Barre de tendance. Les prix sont en 1/100000 d'unite de cotation.
 * `low` est absolu ; open/high/close sont des DELTAS positifs a ajouter.
 */
export const ProtoOATrendbar = {
  3: { name: 'volume', type: 'uint64' },
  4: { name: 'period', type: 'enum' },
  5: { name: 'low', type: 'int64' },
  6: { name: 'deltaOpen', type: 'uint64' },
  7: { name: 'deltaClose', type: 'uint64' },
  8: { name: 'deltaHigh', type: 'uint64' },
  9: { name: 'utcTimestampInMinutes', type: 'uint32' },
};

/** (*) */
export const ProtoOAGetTrendbarsReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'fromTimestamp', type: 'int64' },
  4: { name: 'toTimestamp', type: 'int64' },
  5: { name: 'period', type: 'enum' },
  6: { name: 'symbolId', type: 'int64' },
  7: { name: 'count', type: 'uint32' },
};

/** (*) */
export const ProtoOAGetTrendbarsRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'period', type: 'enum' },
  4: { name: 'timestamp', type: 'int64' },
  5: { name: 'trendbar', type: 'message', message: ProtoOATrendbar, repeated: true },
  6: { name: 'symbolId', type: 'int64' },
};

/** (*) */
export const ProtoOASubscribeSpotsReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'symbolId', type: 'int64', repeated: true },
  4: { name: 'subscribeToSpotTimestamp', type: 'bool' },
};

/** (*) bid/ask en 1/100000 d'unite de cotation. */
export const ProtoOASpotEvent = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'symbolId', type: 'int64' },
  4: { name: 'bid', type: 'uint64' },
  5: { name: 'ask', type: 'uint64' },
  6: { name: 'trendbar', type: 'message', message: ProtoOATrendbar, repeated: true },
  7: { name: 'sessionClose', type: 'uint64' },
  8: { name: 'timestamp', type: 'int64' },
};

/** (*) */
export const ProtoOASubscribeLiveTrendbarReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'period', type: 'enum' },
  4: { name: 'symbolId', type: 'int64' },
};

/**
 * (*) pour les champs 1-13. Les prix (limitPrice, stopLoss, takeProfit) sont
 * des `double` en unites de cotation reelles — PAS en 1/100000.
 * `volume` est en centiemes d'unite de base (a confirmer via discover).
 */
export const ProtoOANewOrderReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'symbolId', type: 'int64' },
  4: { name: 'orderType', type: 'enum' },
  5: { name: 'tradeSide', type: 'enum' },
  6: { name: 'volume', type: 'int64' },
  7: { name: 'limitPrice', type: 'double' },
  8: { name: 'stopPrice', type: 'double' },
  9: { name: 'timeInForce', type: 'enum' },
  10: { name: 'expirationTimestamp', type: 'int64' },
  11: { name: 'stopLoss', type: 'double' },
  12: { name: 'takeProfit', type: 'double' },
  13: { name: 'comment', type: 'string' },
  16: { name: 'label', type: 'string' },
  18: { name: 'clientOrderId', type: 'string' },
};

/** (*) */
export const ProtoOATraderReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
};

/** (?) `balance` est en 1/100 d'unite monetaire sauf si moneyDigits dit autre chose. */
export const ProtoOATrader = {
  1: { name: 'ctidTraderAccountId', type: 'int64' },
  2: { name: 'balance', type: 'int64' },
  8: { name: 'depositAssetId', type: 'int64' },
};

/** (*) */
export const ProtoOATraderRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'ctidTraderAccountId', type: 'int64' },
  3: { name: 'trader', type: 'message', message: ProtoOATrader },
};

/** (*) */
export const ProtoOARefreshTokenReq = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'refreshToken', type: 'string' },
};

/** (?) */
export const ProtoOARefreshTokenRes = {
  1: { name: 'payloadType', type: 'uint32' },
  2: { name: 'accessToken', type: 'string' },
  3: { name: 'tokenType', type: 'string' },
  4: { name: 'expiresIn', type: 'int64' },
  5: { name: 'refreshToken', type: 'string' },
};

/** Facteur de conversion des prix entiers de l'API vers les unites reelles. */
export const PRICE_SCALE = 100_000;

/** @param {number|bigint} raw */
export function toPrice(raw) {
  return Number(raw) / PRICE_SCALE;
}

/**
 * Convertit une ProtoOATrendbar en barre OHLCV exploitable.
 * @param {object} tb
 * @returns {{time:number, open:number, high:number, low:number, close:number, volume:number}}
 */
export function trendbarToBar(tb) {
  const low = Number(tb.low);
  return {
    time: Number(tb.utcTimestampInMinutes) * 60_000,
    open: toPrice(low + Number(tb.deltaOpen || 0)),
    high: toPrice(low + Number(tb.deltaHigh || 0)),
    low: toPrice(low),
    close: toPrice(low + Number(tb.deltaClose || 0)),
    volume: Number(tb.volume || 0),
  };
}
