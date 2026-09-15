/**
 * Flux de marche live : agregation de barres M5 et serie extensible.
 *
 * Choix d'architecture important : la strategie consomme exactement la meme
 * structure `Series` (tableaux indexes) en live qu'au backtest. Aucun code de
 * strategie n'est duplique — c'est ce qui garantit que le comportement valide
 * sur 5 ans d'historique est litteralement celui qui tourne sur le compte.
 *
 * Les barres sont construites sur le BID, comme l'historique cTrader et comme
 * le CSV fourni. Le spread reel bid/ask est suivi separement et utilise par le
 * moniteur : en live on connait le vrai spread, on n'a donc pas besoin de la
 * valeur modelisee du backtest.
 */

import { EventEmitter } from 'node:events';
import { PERIOD, toPrice, trendbarToBar } from './ctrader/messages.js';

const MS_MIN = 60_000;

/**
 * Serie OHLCV extensible, compatible avec l'interface `Series` du backtest.
 * Maintient aussi les ATR de Wilder de maniere incrementale.
 */
export class LiveSeries {
  /** @param {number} [capacity] */
  constructor(capacity = 4096) {
    this.cap = capacity;
    this.time = new Float64Array(capacity);
    this.open = new Float64Array(capacity);
    this.high = new Float64Array(capacity);
    this.low = new Float64Array(capacity);
    this.close = new Float64Array(capacity);
    this.volume = new Float64Array(capacity);
    this.length = 0;
    this.timeframeMs = 5 * MS_MIN;
    this.stats = { skippedBadRows: 0, skippedOutOfRange: 0 };
    /** @type {Map<number, {arr: Float64Array, sum: number}>} */
    this._atr = new Map();
  }

  _grow() {
    const cap = this.cap * 2;
    for (const k of ['time', 'open', 'high', 'low', 'close', 'volume']) {
      const next = new Float64Array(cap);
      next.set(this[k]);
      this[k] = next;
    }
    for (const st of this._atr.values()) {
      const next = new Float64Array(cap).fill(NaN);
      next.set(st.arr);
      st.arr = next;
    }
    this.cap = cap;
  }

  /**
   * Ajoute une barre CLOSE. Rejette les barres non chronologiques.
   * @param {{time:number, open:number, high:number, low:number, close:number, volume?:number}} b
   * @returns {boolean} true si ajoutee
   */
  push(b) {
    if (this.length && b.time <= this.time[this.length - 1]) return false;
    if (!(b.open > 0 && b.high > 0 && b.low > 0 && b.close > 0)) return false;
    if (this.length >= this.cap) this._grow();
    const i = this.length;
    this.time[i] = b.time;
    this.open[i] = b.open;
    this.high[i] = b.high;
    this.low[i] = b.low;
    this.close[i] = b.close;
    this.volume[i] = b.volume || 0;
    this.length = i + 1;
    for (const [period, st] of this._atr) this._stepAtr(period, st, i);
    return true;
  }

  /** Remplace la derniere barre (correction par une trendbar autoritaire). */
  replaceLast(b) {
    if (!this.length) return false;
    const i = this.length - 1;
    if (this.time[i] !== b.time) return false;
    this.open[i] = b.open;
    this.high[i] = b.high;
    this.low[i] = b.low;
    this.close[i] = b.close;
    this.volume[i] = b.volume || this.volume[i];
    // Les ATR dependent de cette barre : on les recalcule a cet index.
    for (const [period, st] of this._atr) {
      st.arr[i] = NaN;
      this._stepAtr(period, st, i, true);
    }
    return true;
  }

  _stepAtr(period, st, i, recompute = false) {
    if (i === 0) {
      st.arr[0] = NaN;
      return;
    }
    const prevClose = this.close[i - 1];
    const tr = Math.max(
      this.high[i] - this.low[i],
      Math.abs(this.high[i] - prevClose),
      Math.abs(this.low[i] - prevClose)
    );
    if (i < period) {
      if (!recompute) st.sum += tr;
      st.arr[i] = NaN;
    } else if (i === period) {
      if (!recompute) st.sum += tr;
      st.arr[i] = st.sum / period;
    } else {
      const prev = st.arr[i - 1];
      st.arr[i] = Number.isFinite(prev) ? (prev * (period - 1) + tr) / period : NaN;
    }
  }

  /**
   * ATR de Wilder, calcule incrementalement. Interface identique a celle
   * attendue par la strategie.
   * @param {number} period
   * @returns {Float64Array}
   */
  atr(period) {
    let st = this._atr.get(period);
    if (!st) {
      st = { arr: new Float64Array(this.cap).fill(NaN), sum: 0 };
      this._atr.set(period, st);
      // Rattrapage sur l'historique deja charge.
      for (let i = 1; i < this.length; i++) this._stepAtr(period, st, i);
    }
    return st.arr;
  }

  /** Fournisseur d'ATR a passer a SweepStrategy. */
  atrProvider() {
    return (period) => this.atr(period);
  }
}

/**
 * Agrege les cotations en barres M5 et emet les barres CLOSES.
 *
 * Deux sources se completent :
 *  - les ticks de cotation (toujours disponibles) : agregation locale ;
 *  - les trendbars live envoyees dans le SpotEvent (quand le broker les
 *    fournit) : elles corrigent la barre en cours, faisant autorite.
 */
export class MarketFeed extends EventEmitter {
  /**
   * @param {object} opts
   * @param {import('./ctrader/client.js').CTraderClient} opts.client
   * @param {number} opts.symbolId
   * @param {number} [opts.timeframeMin]
   * @param {(level:string,msg:string,extra?:any)=>void} [opts.log]
   */
  constructor({ client, symbolId, timeframeMin = 5, log = () => {} }) {
    super();
    this.client = client;
    this.symbolId = Number(symbolId);
    this.timeframeMin = timeframeMin;
    this.bucketMs = timeframeMin * MS_MIN;
    this.log = log;

    this.series = new LiveSeries();
    /** Barre en construction. */
    this.current = null;
    /** Dernier bid/ask connus. */
    this.bid = NaN;
    this.ask = NaN;
    this.lastTickTs = 0;

    this._onSpot = this._onSpot.bind(this);
  }

  get spread() {
    return Number.isFinite(this.bid) && Number.isFinite(this.ask) ? this.ask - this.bid : NaN;
  }

  /** Periode cTrader correspondant au timeframe. */
  get period() {
    const map = { 1: PERIOD.M1, 5: PERIOD.M5, 15: PERIOD.M15, 30: PERIOD.M30, 60: PERIOD.H1 };
    const p = map[this.timeframeMin];
    if (!p) throw new Error(`timeframe non supporte : ${this.timeframeMin} min`);
    return p;
  }

  /**
   * Charge l'historique necessaire : assez de barres pour l'ATR, la session de
   * Londres du jour et le High/Low de la veille.
   * @param {number} [days]
   */
  async bootstrap(days = 4) {
    const now = Date.now();
    const bars = await this.client.getTrendbars(
      this.symbolId,
      this.period,
      now - days * 86_400_000,
      now
    );
    let added = 0;
    for (const b of bars) {
      // La derniere barre peut etre encore en cours : on la garde a part.
      if (b.time + this.bucketMs > now) {
        this.current = { ...b };
        continue;
      }
      if (this.series.push(b)) added++;
    }
    this.log('info', `historique charge : ${added} barres M${this.timeframeMin}` +
      (this.series.length ? ` (${new Date(this.series.time[0]).toISOString()} -> ${new Date(this.series.time[this.series.length-1]).toISOString()})` : ''));
    this.emit('bootstrap', { bars: added });
    return added;
  }

  /** Branche le flux temps reel. */
  async start() {
    this.client.on('spot', this._onSpot);
    await this.client.subscribeSpots([this.symbolId]);
    try {
      await this.client.subscribeTrendbars(this.symbolId, this.period);
    } catch (e) {
      // Pas bloquant : l'agregation locale suffit.
      this.log('warn', `abonnement aux barres live refuse (${e.message}) — agregation locale seule`);
    }
  }

  stop() {
    this.client.off('spot', this._onSpot);
  }

  _onSpot(ev) {
    if (Number(ev.symbolId) !== this.symbolId) return;
    const ts = ev.timestamp ? Number(ev.timestamp) : Date.now();
    if (ev.bid != null) this.bid = toPrice(ev.bid);
    if (ev.ask != null) this.ask = toPrice(ev.ask);
    this.lastTickTs = ts;
    this.emit('tick', { ts, bid: this.bid, ask: this.ask, spread: this.spread });

    // Trendbars autoritaires fournies par le broker.
    if (ev.trendbar && ev.trendbar.length) {
      for (const tb of ev.trendbar) {
        if (tb.period != null && Number(tb.period) !== this.period) continue;
        const bar = trendbarToBar(tb);
        this._absorbAuthoritative(bar, ts);
      }
      return;
    }

    if (!Number.isFinite(this.bid)) return;
    this._absorbTick(ts, this.bid, 1);
  }

  /** Integre une barre faisant autorite (peut cloturer la precedente). */
  _absorbAuthoritative(bar, nowTs) {
    const bucket = Math.floor(bar.time / this.bucketMs) * this.bucketMs;
    if (this.current && this.current.time < bucket) this._closeCurrent();
    if (!this.current || this.current.time !== bucket) {
      this.current = { ...bar, time: bucket };
    } else {
      // Fusion : le broker fait autorite sur l'amplitude.
      this.current.high = Math.max(this.current.high, bar.high);
      this.current.low = Math.min(this.current.low, bar.low);
      this.current.close = bar.close;
      this.current.volume = bar.volume;
    }
    // Cloture par le temps si le bucket est depasse.
    if (nowTs >= bucket + this.bucketMs) this._closeCurrent();
  }

  /** Integre un tick dans la barre en cours. */
  _absorbTick(ts, price, vol) {
    const bucket = Math.floor(ts / this.bucketMs) * this.bucketMs;
    if (this.current && this.current.time !== bucket) {
      if (bucket > this.current.time) this._closeCurrent();
      else return; // tick en retard sur une barre deja cloturee
    }
    if (!this.current) {
      this.current = { time: bucket, open: price, high: price, low: price, close: price, volume: vol };
      return;
    }
    if (price > this.current.high) this.current.high = price;
    if (price < this.current.low) this.current.low = price;
    this.current.close = price;
    this.current.volume += vol;
  }

  /** Ferme la barre en cours et l'ajoute a la serie. */
  _closeCurrent() {
    if (!this.current) return;
    const bar = this.current;
    this.current = null;
    if (this.series.push(bar)) {
      this.emit('bar', { bar, index: this.series.length - 1, series: this.series });
    }
  }

  /**
   * A appeler periodiquement : cloture la barre en cours si son intervalle est
   * ecoule, meme en l'absence de tick (marche calme ou flux interrompu).
   */
  tickClock(nowTs = Date.now()) {
    if (this.current && nowTs >= this.current.time + this.bucketMs) this._closeCurrent();
  }
}
