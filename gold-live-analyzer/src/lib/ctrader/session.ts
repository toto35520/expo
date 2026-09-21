import WebSocket from 'ws';

import {
  type CTraderAccount,
  type CTraderEnv,
  type CTraderErrorPayload,
  type CTraderLightSymbol,
  type CTraderMessage,
  type CTraderSpotPayload,
  PayloadType,
  TrendbarPeriod,
  type TrendbarPeriodName,
  decodeTrendbar,
  num,
  wsUrl,
} from './protocol';

/**
 * Session cTrader cote serveur.
 *
 * Elle vit dans une route handler Node (jamais dans le navigateur) : c'est ce
 * qui permet de garder `clientSecret` hors du client. L'app auth (2100) exige
 * le secret, donc le pont WebSocket doit rester serveur.
 */

export class CTraderError extends Error {
  readonly code: string;

  constructor(code: string, description?: string) {
    super(description ? `${code}: ${description}` : code);
    this.name = 'CTraderError';
    this.code = code;
  }
}

export interface SessionOptions {
  env: CTraderEnv;
  clientId: string;
  clientSecret: string;
  accessToken: string;
  /** Delai max d'une requete unitaire. */
  requestTimeoutMs?: number;
}

type Pending = {
  resolve: (payload: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  expect: number;
  timer: ReturnType<typeof setTimeout>;
};

export interface Candle {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export class CTraderSession {
  private ws: WebSocket | null = null;
  private readonly pending = new Map<string, Pending>();
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private msgSeq = 0;
  private closed = false;
  private readonly timeout: number;

  onSpot: ((spot: CTraderSpotPayload) => void) | null = null;
  onClose: ((reason: string) => void) | null = null;

  constructor(private readonly opts: SessionOptions) {
    this.timeout = opts.requestTimeoutMs ?? 15_000;
  }

  /** Ouvre la socket et authentifie l'application. */
  async connect(): Promise<void> {
    const url = wsUrl(this.opts.env);
    const ws = new WebSocket(url, { handshakeTimeout: 15_000 });
    this.ws = ws;

    await new Promise<void>((resolve, reject) => {
      const onOpen = () => {
        cleanup();
        resolve();
      };
      const onError = (err: Error) => {
        cleanup();
        reject(new CTraderError('CONNECTION_FAILED', err.message));
      };
      const cleanup = () => {
        ws.off('open', onOpen);
        ws.off('error', onError);
      };
      ws.on('open', onOpen);
      ws.on('error', onError);
    });

    ws.on('message', (raw) => this.handleMessage(raw.toString()));
    ws.on('close', (code, reason) => {
      this.teardown(`socket fermee (${code}) ${reason.toString()}`.trim());
    });
    ws.on('error', (err) => {
      this.teardown(err.message);
    });

    // Le proxy coupe les sessions silencieuses : on garde un heartbeat a 10 s.
    this.heartbeat = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.send({ payloadType: PayloadType.HEARTBEAT_EVENT, payload: {} });
      }
    }, 10_000);

    await this.request(
      PayloadType.APPLICATION_AUTH_REQ,
      { clientId: this.opts.clientId, clientSecret: this.opts.clientSecret },
      PayloadType.APPLICATION_AUTH_RES
    );
  }

  /** Liste les comptes de trading rattaches au token OAuth. */
  async listAccounts(): Promise<CTraderAccount[]> {
    const res = await this.request(
      PayloadType.GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ,
      { accessToken: this.opts.accessToken },
      PayloadType.GET_ACCOUNTS_BY_ACCESS_TOKEN_RES
    );
    return (res.ctidTraderAccount as CTraderAccount[] | undefined) ?? [];
  }

  /** Authentifie un compte precis (obligatoire avant toute donnee marche). */
  async authorizeAccount(ctidTraderAccountId: number): Promise<void> {
    await this.request(
      PayloadType.ACCOUNT_AUTH_REQ,
      { ctidTraderAccountId, accessToken: this.opts.accessToken },
      PayloadType.ACCOUNT_AUTH_RES
    );
  }

  async listSymbols(ctidTraderAccountId: number): Promise<CTraderLightSymbol[]> {
    const res = await this.request(
      PayloadType.SYMBOLS_LIST_REQ,
      { ctidTraderAccountId, includeArchivedSymbols: false },
      PayloadType.SYMBOLS_LIST_RES
    );
    return (res.symbol as CTraderLightSymbol[] | undefined) ?? [];
  }

  /**
   * Retrouve l'identifiant du symbole or. Les brokers nomment XAU/USD de
   * facons variees (XAUUSD, XAU/USD, GOLD, XAUUSD.m, XAUUSD#...), d'ou le
   * classement par proximite plutot qu'une egalite stricte.
   */
  static pickGoldSymbol(
    symbols: CTraderLightSymbol[],
    preferred?: string
  ): CTraderLightSymbol | null {
    const normalize = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const enabled = symbols.filter((s) => s.enabled !== false);
    const pool = enabled.length > 0 ? enabled : symbols;

    if (preferred) {
      const want = normalize(preferred);
      const exact = pool.find((s) => normalize(s.symbolName ?? '') === want);
      if (exact) return exact;
    }

    const score = (s: CTraderLightSymbol): number => {
      const name = normalize(s.symbolName ?? '');
      if (name === 'XAUUSD') return 100;
      if (name === 'GOLD') return 90;
      if (name.startsWith('XAUUSD')) return 80 - Math.min(name.length - 6, 20);
      if (name.startsWith('GOLD')) return 60 - Math.min(name.length - 4, 20);
      if (name.includes('XAU') && name.includes('USD')) return 50;
      return -1;
    };

    let best: CTraderLightSymbol | null = null;
    let bestScore = 0;
    for (const s of pool) {
      const value = score(s);
      if (value > bestScore) {
        bestScore = value;
        best = s;
      }
    }
    return best;
  }

  /** Historique de bougies (le proxy plafonne le `count` cote serveur). */
  async getTrendbars(
    ctidTraderAccountId: number,
    symbolId: number,
    period: TrendbarPeriodName,
    count: number
  ): Promise<Candle[]> {
    const periodId = TrendbarPeriod[period];
    const minutesPerBar = PERIOD_MINUTES[period];
    const to = Date.now();
    const from = to - count * minutesPerBar * 60_000;

    const res = await this.request(
      PayloadType.GET_TRENDBARS_REQ,
      {
        ctidTraderAccountId,
        symbolId,
        period: periodId,
        fromTimestamp: from,
        toTimestamp: to,
        count,
      },
      PayloadType.GET_TRENDBARS_RES
    );

    const bars = (res.trendbar as Parameters<typeof decodeTrendbar>[0][] | undefined) ?? [];
    return bars.map(decodeTrendbar).sort((a, b) => a.t - b.t);
  }

  async subscribeSpots(ctidTraderAccountId: number, symbolId: number): Promise<void> {
    await this.request(
      PayloadType.SUBSCRIBE_SPOTS_REQ,
      { ctidTraderAccountId, symbolId: [symbolId], subscribeToSpotTimestamp: true },
      PayloadType.SUBSCRIBE_SPOTS_RES
    );
  }

  /**
   * Abonne la session aux bougies live. Les bougies closes arrivent ensuite
   * dans le champ `trendbar` des spot events.
   */
  async subscribeLiveTrendbar(
    ctidTraderAccountId: number,
    symbolId: number,
    period: TrendbarPeriodName
  ): Promise<void> {
    await this.request(
      PayloadType.SUBSCRIBE_LIVE_TRENDBAR_REQ,
      { ctidTraderAccountId, symbolId, period: TrendbarPeriod[period] },
      PayloadType.SUBSCRIBE_LIVE_TRENDBAR_RES
    );
  }

  close(): void {
    this.teardown('fermeture demandee');
    try {
      this.ws?.close();
    } catch {
      // socket deja morte, rien a faire
    }
  }

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  // --- interne -------------------------------------------------------------

  private send(message: CTraderMessage): void {
    this.ws?.send(JSON.stringify(message));
  }

  private request(
    payloadType: number,
    payload: Record<string, unknown>,
    expect: number
  ): Promise<Record<string, unknown>> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new CTraderError('NOT_CONNECTED', 'socket cTrader fermee'));
    }

    const clientMsgId = `m${++this.msgSeq}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(clientMsgId);
        reject(new CTraderError('TIMEOUT', `pas de reponse pour ${payloadType}`));
      }, this.timeout);

      this.pending.set(clientMsgId, { resolve, reject, expect, timer });
      this.send({ clientMsgId, payloadType, payload });
    });
  }

  private handleMessage(raw: string): void {
    let msg: CTraderMessage;
    try {
      msg = JSON.parse(raw) as CTraderMessage;
    } catch {
      return;
    }

    const payload = (msg.payload ?? {}) as Record<string, unknown>;

    if (msg.payloadType === PayloadType.SPOT_EVENT) {
      this.onSpot?.(payload as CTraderSpotPayload);
      return;
    }

    if (
      msg.payloadType === PayloadType.ACCOUNTS_TOKEN_INVALIDATED_EVENT ||
      msg.payloadType === PayloadType.ACCOUNT_DISCONNECT_EVENT ||
      msg.payloadType === PayloadType.CLIENT_DISCONNECT_EVENT
    ) {
      this.teardown('session invalidee par cTrader (token ou compte)');
      return;
    }

    const waiter = msg.clientMsgId ? this.pending.get(msg.clientMsgId) : undefined;
    if (!waiter) return;

    this.pending.delete(msg.clientMsgId!);
    clearTimeout(waiter.timer);

    if (msg.payloadType === PayloadType.ERROR_RES) {
      const err = payload as CTraderErrorPayload;
      waiter.reject(new CTraderError(err.errorCode ?? 'UNKNOWN_ERROR', err.description));
      return;
    }

    if (waiter.expect !== msg.payloadType) {
      waiter.reject(
        new CTraderError('UNEXPECTED_RESPONSE', `attendu ${waiter.expect}, recu ${msg.payloadType}`)
      );
      return;
    }

    waiter.resolve(payload);
  }

  private teardown(reason: string): void {
    if (this.closed) return;
    this.closed = true;

    if (this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
    for (const [, waiter] of this.pending) {
      clearTimeout(waiter.timer);
      waiter.reject(new CTraderError('DISCONNECTED', reason));
    }
    this.pending.clear();
    this.onClose?.(reason);
  }
}

export const PERIOD_MINUTES: Record<TrendbarPeriodName, number> = {
  M1: 1,
  M5: 5,
  M15: 15,
  M30: 30,
  H1: 60,
  H4: 240,
  D1: 1440,
};

export { num };
