/**
 * Client cTrader Open API sur TLS.
 *
 * Trame reseau : [longueur uint32 big-endian][ProtoMessage serialise]
 * Les lectures TCP arrivent fragmentees : le tampon est accumule et les
 * messages sont extraits un par un.
 *
 * Cycle de vie gere ici :
 *   - authentification application puis compte
 *   - heartbeat periodique (la session est coupee sans lui)
 *   - correlation requete/reponse par clientMsgId, avec timeout
 *   - reconnexion automatique a backoff exponentiel + re-abonnement
 *   - rafraichissement du jeton d'acces
 */

import { EventEmitter } from 'node:events';
import tls from 'node:tls';
import { randomUUID } from 'node:crypto';
import { decode, decodeUnknown, encode } from '../protobuf.js';
import * as M from './messages.js';

export const ENDPOINTS = {
  demo: { host: 'demo.ctraderapi.com', port: 5035 },
  live: { host: 'live.ctraderapi.com', port: 5035 },
};

export class CTraderClient extends EventEmitter {
  /**
   * @param {object} opts
   * @param {'demo'|'live'} opts.env
   * @param {string} opts.clientId
   * @param {string} opts.clientSecret
   * @param {string} opts.accessToken
   * @param {string} [opts.refreshToken]
   * @param {number|string} [opts.accountId] ctidTraderAccountId
   * @param {number} [opts.heartbeatMs]
   * @param {number} [opts.requestTimeoutMs]
   * @param {(level:string,msg:string,extra?:any)=>void} [opts.log]
   */
  constructor(opts) {
    super();
    const ep = ENDPOINTS[opts.env];
    if (!ep) throw new Error(`env invalide : ${opts.env} (attendu 'demo' ou 'live')`);
    this.env = opts.env;
    this.host = opts.host || ep.host;
    this.port = opts.port || ep.port;
    this.clientId = opts.clientId;
    this.clientSecret = opts.clientSecret;
    this.accessToken = opts.accessToken;
    this.refreshToken = opts.refreshToken || null;
    this.accountId = opts.accountId != null ? Number(opts.accountId) : null;
    this.heartbeatMs = opts.heartbeatMs ?? 10_000;
    this.requestTimeoutMs = opts.requestTimeoutMs ?? 20_000;
    this.log = opts.log || (() => {});

    /** @type {import('node:tls').TLSSocket|null} */
    this.socket = null;
    this.buffer = Buffer.alloc(0);
    /** @type {Map<string, {resolve:Function, reject:Function, timer:NodeJS.Timeout, expect:number[]}>} */
    this.pending = new Map();
    this.heartbeatTimer = null;
    this.reconnectAttempt = 0;
    this.closing = false;
    this.authenticated = false;
    /** Abonnements a rejouer apres reconnexion. */
    this.subscriptions = { spots: new Set(), trendbars: new Set() };
    /** Cache des symboles resolus. */
    this.symbolsByName = new Map();
    this.symbolsById = new Map();
  }

  // ─────────────────────────── CONNEXION ───────────────────────────

  async connect() {
    this.closing = false;
    await this._openSocket();
    await this.authenticate();
    this._startHeartbeat();
    this.reconnectAttempt = 0;
    return this;
  }

  _openSocket() {
    return new Promise((resolve, reject) => {
      this.log('info', `connexion TLS a ${this.host}:${this.port}`);
      const socket = tls.connect(
        { host: this.host, port: this.port, servername: this.host, rejectUnauthorized: true },
        () => {
          if (!socket.authorized && socket.authorizationError) {
            reject(new Error(`certificat TLS refuse : ${socket.authorizationError}`));
            return;
          }
          this.log('info', 'TLS etabli');
          resolve();
        }
      );
      socket.setNoDelay(true);
      socket.on('data', (chunk) => this._onData(chunk));
      socket.on('error', (err) => {
        this.log('error', `erreur socket : ${err.message}`);
        this.emit('error', err);
        reject(err);
      });
      socket.on('close', () => {
        this.log('warn', 'socket ferme');
        this.authenticated = false;
        this._stopHeartbeat();
        this._failAllPending(new Error('socket ferme'));
        this.emit('disconnected');
        if (!this.closing) this._scheduleReconnect();
      });
      this.socket = socket;
      this.buffer = Buffer.alloc(0);
    });
  }

  _scheduleReconnect() {
    this.reconnectAttempt++;
    const delay = Math.min(60_000, 1000 * 2 ** Math.min(this.reconnectAttempt - 1, 6));
    this.log('warn', `reconnexion dans ${delay}ms (tentative ${this.reconnectAttempt})`);
    setTimeout(async () => {
      if (this.closing) return;
      try {
        await this._openSocket();
        await this.authenticate();
        this._startHeartbeat();
        await this._replaySubscriptions();
        this.reconnectAttempt = 0;
        this.emit('reconnected');
      } catch (e) {
        this.log('error', `reconnexion echouee : ${e.message}`);
        this._scheduleReconnect();
      }
    }, delay).unref?.();
  }

  async close() {
    this.closing = true;
    this._stopHeartbeat();
    this._failAllPending(new Error('client ferme'));
    if (this.socket) {
      await new Promise((r) => this.socket.end(r));
      this.socket.destroy();
      this.socket = null;
    }
  }

  // ─────────────────────────── TRAMAGE ────────────────────────────

  _onData(chunk) {
    this.buffer = this.buffer.length ? Buffer.concat([this.buffer, chunk]) : chunk;
    // Extraction de tous les messages complets disponibles.
    for (;;) {
      if (this.buffer.length < 4) return;
      const len = this.buffer.readUInt32BE(0);
      if (len > 64 * 1024 * 1024) {
        this.log('error', `longueur de trame aberrante (${len}) — tampon reinitialise`);
        this.buffer = Buffer.alloc(0);
        this.socket?.destroy(new Error('trame invalide'));
        return;
      }
      if (this.buffer.length < 4 + len) return;
      const body = this.buffer.subarray(4, 4 + len);
      this.buffer = this.buffer.subarray(4 + len);
      try {
        this._onMessage(decode(M.ProtoMessage, body));
      } catch (e) {
        this.log('error', `message illisible : ${e.message}`);
      }
    }
  }

  _onMessage(msg) {
    const type = msg.payloadType;
    const payload = msg.payload || Buffer.alloc(0);
    this.emit('message', { type, name: M.PT_NAME[type] || String(type), payload, clientMsgId: msg.clientMsgId });

    // Reponse attendue ?
    if (msg.clientMsgId && this.pending.has(msg.clientMsgId)) {
      const p = this.pending.get(msg.clientMsgId);
      this.pending.delete(msg.clientMsgId);
      clearTimeout(p.timer);
      if (type === M.PT.ERROR_RES_OA || type === M.PT.ERROR_RES) {
        const err = decode(M.ProtoOAErrorRes, payload);
        p.reject(
          Object.assign(new Error(`${err.errorCode}: ${err.description || '(sans description)'}`), {
            errorCode: err.errorCode,
            retryAfter: err.retryAfter,
          })
        );
      } else {
        p.resolve({ type, payload });
      }
      return;
    }

    // Evenements non sollicites.
    switch (type) {
      case M.PT.HEARTBEAT_EVENT:
        break;
      case M.PT.SPOT_EVENT:
        this.emit('spot', decode(M.ProtoOASpotEvent, payload));
        break;
      case M.PT.EXECUTION_EVENT:
        this.emit('execution', { raw: payload, fields: decodeUnknown(payload, 1) });
        break;
      case M.PT.ORDER_ERROR_EVENT:
        this.emit('orderError', { fields: decodeUnknown(payload, 1) });
        break;
      case M.PT.ACCOUNTS_TOKEN_INVALIDATED_EVENT:
        this.log('error', 'jeton invalide — rafraichissement necessaire');
        this.emit('tokenInvalidated');
        break;
      case M.PT.CLIENT_DISCONNECT_EVENT:
        this.log('warn', 'deconnexion demandee par le serveur');
        this.emit('serverDisconnect', { fields: decodeUnknown(payload, 0) });
        break;
      case M.PT.ERROR_RES_OA:
      case M.PT.ERROR_RES: {
        const err = decode(M.ProtoOAErrorRes, payload);
        this.log('error', `erreur non sollicitee : ${err.errorCode} ${err.description || ''}`);
        this.emit('apiError', err);
        break;
      }
      default:
        this.emit('event', { type, name: M.PT_NAME[type] || String(type), payload });
    }
  }

  // ─────────────────────────── ENVOI ──────────────────────────────

  _write(payloadType, payload, clientMsgId) {
    if (!this.socket || this.socket.destroyed) throw new Error('socket indisponible');
    const env = encode(M.ProtoMessage, { payloadType, payload, clientMsgId });
    const head = Buffer.allocUnsafe(4);
    head.writeUInt32BE(env.length, 0);
    this.socket.write(Buffer.concat([head, env]));
  }

  /** Envoie un message sans attendre de reponse. */
  send(payloadType, schema, obj) {
    this._write(payloadType, encode(schema, { ...obj, payloadType }));
  }

  /**
   * Envoie une requete et attend la reponse correlee.
   * @returns {Promise<{type:number, payload:Buffer}>}
   */
  request(payloadType, schema, obj, { timeoutMs } = {}) {
    const id = randomUUID();
    const payload = encode(schema, { ...obj, payloadType });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`timeout sur ${M.PT_NAME[payloadType] || payloadType} (${timeoutMs ?? this.requestTimeoutMs}ms)`));
      }, timeoutMs ?? this.requestTimeoutMs);
      timer.unref?.();
      this.pending.set(id, { resolve, reject, timer });
      try {
        this._write(payloadType, payload, id);
      } catch (e) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(e);
      }
    });
  }

  _failAllPending(err) {
    for (const [, p] of this.pending) {
      clearTimeout(p.timer);
      p.reject(err);
    }
    this.pending.clear();
  }

  _startHeartbeat() {
    this._stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      try {
        this._write(M.PT.HEARTBEAT_EVENT, encode(M.ProtoHeartbeatEvent, { payloadType: M.PT.HEARTBEAT_EVENT }));
      } catch {
        /* la fermeture du socket declenchera la reconnexion */
      }
    }, this.heartbeatMs);
    this.heartbeatTimer.unref?.();
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  // ───────────────────── AUTHENTIFICATION ─────────────────────────

  async authenticate() {
    await this.request(M.PT.APPLICATION_AUTH_REQ, M.ProtoOAApplicationAuthReq, {
      clientId: this.clientId,
      clientSecret: this.clientSecret,
    });
    this.log('info', 'application authentifiee');

    if (this.accountId == null) {
      const accounts = await this.listAccounts();
      const wantLive = this.env === 'live';
      const match = accounts.find((a) => a.isLive === wantLive) || accounts[0];
      if (!match) throw new Error('aucun compte accessible avec ce jeton');
      this.accountId = Number(match.ctidTraderAccountId);
      this.log(
        'info',
        `compte selectionne automatiquement : ${this.accountId} (${match.isLive ? 'LIVE' : 'DEMO'})`
      );
    }

    await this.request(M.PT.ACCOUNT_AUTH_REQ, M.ProtoOAAccountAuthReq, {
      ctidTraderAccountId: this.accountId,
      accessToken: this.accessToken,
    });
    this.authenticated = true;
    this.log('info', `compte ${this.accountId} authentifie`);
    this.emit('authenticated', { accountId: this.accountId });
  }

  async listAccounts() {
    const res = await this.request(
      M.PT.GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ,
      M.ProtoOAGetAccountListByAccessTokenReq,
      { accessToken: this.accessToken }
    );
    return decode(M.ProtoOAGetAccountListByAccessTokenRes, res.payload).ctidTraderAccount;
  }

  /** Rafraichit le jeton d'acces (necessite refreshToken). */
  async refreshAccessToken() {
    if (!this.refreshToken) throw new Error('aucun refreshToken configure');
    const res = await this.request(M.PT.REFRESH_TOKEN_REQ, M.ProtoOARefreshTokenReq, {
      refreshToken: this.refreshToken,
    });
    const r = decode(M.ProtoOARefreshTokenRes, res.payload);
    if (r.accessToken) {
      this.accessToken = r.accessToken;
      if (r.refreshToken) this.refreshToken = r.refreshToken;
      this.log('info', 'jeton d acces rafraichi');
      this.emit('tokenRefreshed', { accessToken: r.accessToken, refreshToken: r.refreshToken, expiresIn: r.expiresIn });
    }
    return r;
  }

  // ─────────────────────────── SYMBOLES ───────────────────────────

  async loadSymbols() {
    const res = await this.request(M.PT.SYMBOLS_LIST_REQ, M.ProtoOASymbolsListReq, {
      ctidTraderAccountId: this.accountId,
      includeArchivedSymbols: false,
    });
    const list = decode(M.ProtoOASymbolsListRes, res.payload).symbol;
    this.symbolsByName.clear();
    this.symbolsById.clear();
    for (const sym of list) {
      if (sym.symbolName) this.symbolsByName.set(sym.symbolName.toUpperCase(), sym);
      this.symbolsById.set(Number(sym.symbolId), sym);
    }
    this.log('info', `${list.length} symboles charges`);
    return list;
  }

  /**
   * Resout un symbole par nom, avec tolerance aux suffixes de broker
   * (XAUUSD, XAUUSD.r, GOLD, XAUUSD-5 ...).
   * @param {string} name
   */
  resolveSymbol(name) {
    const want = name.toUpperCase();
    const direct = this.symbolsByName.get(want);
    if (direct) return direct;
    // Correspondance par prefixe puis par inclusion.
    const all = [...this.symbolsByName.values()];
    const pref = all.filter((s) => s.symbolName.toUpperCase().startsWith(want));
    if (pref.length === 1) return pref[0];
    const inc = all.filter((s) => s.symbolName.toUpperCase().includes(want));
    if (inc.length === 1) return inc[0];
    const candidates = (pref.length ? pref : inc).map((s) => s.symbolName);
    throw new Error(
      candidates.length
        ? `symbole "${name}" ambigu. Candidats : ${candidates.join(', ')}`
        : `symbole "${name}" introuvable sur ce compte (${this.symbolsByName.size} symboles). ` +
          `Utilisez "gs-live symbols" pour lister.`
    );
  }

  /** Details d'un symbole (digits, pipPosition) + champs bruts pour inspection. */
  async symbolDetails(symbolId) {
    const res = await this.request(M.PT.SYMBOL_BY_ID_REQ, M.ProtoOASymbolByIdReq, {
      ctidTraderAccountId: this.accountId,
      symbolId: [Number(symbolId)],
    });
    const parsed = decode(M.ProtoOASymbolByIdRes, res.payload);
    return { parsed, raw: decodeUnknown(res.payload, 2) };
  }

  // ─────────────────────── DONNEES DE MARCHE ──────────────────────

  /**
   * Historique de barres.
   * @param {number} symbolId
   * @param {number} period valeur de M.PERIOD
   * @param {number} fromTs epoch ms
   * @param {number} toTs epoch ms
   */
  async getTrendbars(symbolId, period, fromTs, toTs) {
    const res = await this.request(M.PT.GET_TRENDBARS_REQ, M.ProtoOAGetTrendbarsReq, {
      ctidTraderAccountId: this.accountId,
      symbolId: Number(symbolId),
      period,
      fromTimestamp: Math.floor(fromTs),
      toTimestamp: Math.floor(toTs),
    });
    const r = decode(M.ProtoOAGetTrendbarsRes, res.payload);
    return r.trendbar.map(M.trendbarToBar).sort((a, b) => a.time - b.time);
  }

  async subscribeSpots(symbolIds) {
    const ids = symbolIds.map(Number);
    await this.request(M.PT.SUBSCRIBE_SPOTS_REQ, M.ProtoOASubscribeSpotsReq, {
      ctidTraderAccountId: this.accountId,
      symbolId: ids,
      subscribeToSpotTimestamp: true,
    });
    for (const id of ids) this.subscriptions.spots.add(id);
    this.log('info', `abonne aux cotations : ${ids.join(', ')}`);
  }

  async subscribeTrendbars(symbolId, period) {
    await this.request(M.PT.SUBSCRIBE_LIVE_TRENDBAR_REQ, M.ProtoOASubscribeLiveTrendbarReq, {
      ctidTraderAccountId: this.accountId,
      symbolId: Number(symbolId),
      period,
    });
    this.subscriptions.trendbars.add(`${symbolId}:${period}`);
    this.log('info', `abonne aux barres live : symbole ${symbolId} periode ${period}`);
  }

  async _replaySubscriptions() {
    if (this.subscriptions.spots.size) {
      await this.subscribeSpots([...this.subscriptions.spots]);
    }
    for (const key of this.subscriptions.trendbars) {
      const [id, period] = key.split(':').map(Number);
      await this.subscribeTrendbars(id, period);
    }
  }

  // ──────────────────────────── COMPTE ────────────────────────────

  async getTrader() {
    const res = await this.request(M.PT.TRADER_REQ, M.ProtoOATraderReq, {
      ctidTraderAccountId: this.accountId,
    });
    return { parsed: decode(M.ProtoOATraderRes, res.payload), raw: decodeUnknown(res.payload, 2) };
  }

  /**
   * Place un ordre. Volume en unites brutes de l'API (centiemes d'unite de
   * base chez la plupart des brokers) — a confirmer via `discover`.
   *
   * @param {object} o
   */
  async newOrder(o) {
    const res = await this.request(M.PT.NEW_ORDER_REQ, M.ProtoOANewOrderReq, {
      ctidTraderAccountId: this.accountId,
      ...o,
    });
    return { type: res.type, fields: decodeUnknown(res.payload, 1) };
  }
}
