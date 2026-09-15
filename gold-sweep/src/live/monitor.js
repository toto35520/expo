/**
 * Moniteur live : execute la strategie sur le flux cTrader.
 *
 * Deux modes :
 *   - ALERTE (defaut)  : detecte et annonce les setups, ne touche a rien.
 *   - EXECUTION        : place en plus l'ordre limite avec SL/TP attaches.
 *
 * L'ordre est confie a cTrader avec son SL, son TP et son expiration : meme si
 * ce processus s'arrete, la protection reste en place cote broker. C'est un
 * choix deliberelement conservateur — aucune gestion critique ne depend de la
 * disponibilite de ce script.
 */

import { EventEmitter } from 'node:events';
import { buildConfig, resolveDistance, roundPrice } from '../core/config.js';
import { SweepStrategy, Phase } from '../core/strategy.js';
import { formatHm, utcMinuteOfDay } from '../core/time.js';
import { MarketFeed } from './feed.js';
import { ORDER_TYPE, TIF, TRADE_SIDE } from './ctrader/messages.js';

export class LiveMonitor extends EventEmitter {
  /**
   * @param {object} opts
   * @param {import('./ctrader/client.js').CTraderClient} opts.client
   * @param {object} opts.cfg config resolue
   * @param {object} opts.symbol symbole resolu ({symbolId, symbolName})
   * @param {boolean} [opts.execute] placer reellement les ordres
   * @param {number} [opts.equity] capital a utiliser (sinon solde du compte)
   * @param {import('../core/refdata.js').RefBundle|null} [opts.refs]
   * @param {import('../core/calendar.js').EconomicCalendar|null} [opts.calendar]
   * @param {(level:string,msg:string,extra?:any)=>void} [opts.log]
   */
  constructor(opts) {
    super();
    this.client = opts.client;
    this.cfg = opts.cfg;
    this.symbol = opts.symbol;
    this.execute = !!opts.execute;
    this.equityOverride = opts.equity ?? null;
    this.log = opts.log || (() => {});

    this.feed = new MarketFeed({
      client: this.client,
      symbolId: opts.symbol.symbolId,
      timeframeMin: 5,
      log: this.log,
    });
    this.strategy = new SweepStrategy(
      this.cfg,
      this.feed.series.atrProvider(),
      opts.refs || null,
      opts.calendar || null
    );

    this.equity = this.equityOverride;
    /** Ordres emis pendant cette session (trace locale). */
    this.emitted = [];
    this.clockTimer = null;
  }

  async start() {
    await this.feed.bootstrap(4);

    // Rejouer l'historique dans la strategie pour reconstituer l'etat du jour
    // (range de Londres, balayage deja survenu, PDH/PDL de la veille).
    const s = this.feed.series;
    for (let i = 0; i < s.length; i++) {
      // Les setups trouves pendant le rattrapage sont notes mais PAS executes :
      // ils appartiennent au passe.
      const found = this.strategy.onBar(s, i);
      for (const setup of found) {
        this.log('info', `setup historique (non execute) : ${setup.date} ${setup.dir} @ ${setup.entry}`);
      }
    }
    this.log('info', `etat du jour reconstitue : phase=${this.strategy.day?.phase ?? 'aucune'}`);

    if (this.equity == null) {
      try {
        const t = await this.client.getTrader();
        const raw = t.parsed?.trader?.balance;
        if (raw != null) {
          this.equity = Number(raw) / 100;
          this.log('info', `solde du compte : ${this.equity.toFixed(2)}`);
        }
      } catch (e) {
        this.log('warn', `solde indisponible (${e.message}) — repli sur risk.initialEquity`);
      }
      if (this.equity == null) this.equity = this.cfg.risk.initialEquity;
    }

    this.feed.on('bar', (e) => this._onBar(e));
    this.feed.on('tick', (t) => this.emit('tick', t));
    await this.feed.start();

    // Horloge : ferme la barre M5 meme sans tick (marche calme, flux coupe).
    this.clockTimer = setInterval(() => this.feed.tickClock(), 5000);
    this.clockTimer.unref?.();

    this.emit('started', { symbol: this.symbol, execute: this.execute });
    this.log('info', `moniteur demarre en mode ${this.execute ? 'EXECUTION' : 'ALERTE'}`);
  }

  stop() {
    if (this.clockTimer) clearInterval(this.clockTimer);
    this.feed.stop();
  }

  _onBar({ bar, index, series }) {
    this.emit('bar', { bar, index, plan: this.snapshot() });
    let setups;
    try {
      setups = this.strategy.onBar(series, index);
    } catch (e) {
      this.log('error', `erreur de strategie : ${e.message}`);
      this.emit('error', e);
      return;
    }
    for (const setup of setups) this._onSetup(setup);
  }

  async _onSetup(setup) {
    const sizing = this.sizeFor(setup);
    const checklist = this.checklist(setup);
    const signal = { ...setup, sizing, checklist, spreadLive: this.feed.spread };
    this.emitted.push(signal);
    this.emit('signal', signal);

    if (!this.execute) {
      this.log('info', `SETUP DETECTE (mode alerte, aucun ordre place)`);
      return;
    }
    if (!sizing.lots) {
      this.log('warn', `setup ignore : volume calcule nul (${sizing.reason || 'risque trop faible'})`);
      return;
    }
    try {
      const res = await this.placeOrder(setup, sizing);
      this.log('info', `ordre transmis : ${JSON.stringify(res.summary)}`);
      this.emit('orderPlaced', { setup, sizing, res });
    } catch (e) {
      this.log('error', `echec du placement : ${e.message}`);
      this.emit('orderFailed', { setup, sizing, error: e });
    }
  }

  /** Dimensionnement de la position pour un setup. */
  sizeFor(setup) {
    const cfg = this.cfg;
    const inst = cfg.instrument;
    const slDist = Math.abs(setup.sl - setup.entry);
    if (!(slDist > 0)) return { lots: 0, reason: 'distance de stop nulle' };

    const equity = this.equity ?? cfg.risk.initialEquity;
    let riskCash;
    let lots;
    if (cfg.risk.model === 'fixedLots') {
      lots = cfg.risk.lots;
      riskCash = slDist * lots * inst.contractSize;
    } else {
      riskCash =
        cfg.risk.model === 'fixedCash' ? cfg.risk.cashPerTrade : equity * (cfg.risk.pctPerTrade / 100);
      lots = riskCash / (slDist * inst.contractSize);
    }
    const stepped = Math.floor(lots / inst.lotStep + 1e-9) * inst.lotStep;
    const snapped = Math.min(inst.maxLots, Math.round(stepped / inst.lotStep) * inst.lotStep);
    const finalLots = snapped < inst.minLots ? 0 : Number(snapped.toFixed(4));

    return {
      lots: finalLots,
      apiVolume: Math.round(finalLots * inst.apiVolumePerLot),
      riskCash: slDist * finalLots * inst.contractSize,
      riskPctOfEquity: equity ? (slDist * finalLots * inst.contractSize / equity) * 100 : NaN,
      slDistUsd: slDist,
      slDistPips: slDist / inst.pipSize,
      rewardCash: Math.abs(setup.tp - setup.entry) * finalLots * inst.contractSize,
      equity,
      reason: finalLots ? null : `volume < minLots (${inst.minLots}) — capital ou risque insuffisant`,
    };
  }

  /**
   * Checklist de validation avant entree — les 5 cases a cocher.
   * Chaque ligne est calculee depuis les donnees du setup, pas declarative.
   */
  checklist(setup) {
    const cfg = this.cfg;
    const mod = utcMinuteOfDay(setup.signalTs);
    const sbStart = cfg.resolved.silverBulletStart;
    const sbEnd = cfg.resolved.silverBulletEnd;
    const newsT = cfg.resolved.newsTime;
    const thr = cfg.filters.premiumThreshold;
    const isSell = setup.dir === 'sell';

    const penAtr = setup.atrAtSignal > 0 ? setup.sweepPenetrationUsd / setup.atrAtSignal : NaN;
    const fib = Number.isFinite(setup.fibLeg) ? setup.fibLeg : setup.fibLondon;
    const premiumOk = Number.isFinite(fib) ? (isSell ? fib >= thr : fib <= 1 - thr) : null;

    return [
      {
        label: 'Haut/Bas de Londres balaye par une meche agressive',
        ok: Number.isFinite(penAtr) && penAtr >= cfg.sweep.minPenetration,
        detail: `penetration ${setup.sweepPenetrationUsd.toFixed(2)} $ = ${penAtr.toFixed(2)} ATR ` +
          `(seuil ${cfg.sweep.minPenetration} ATR, plafond ${cfg.sweep.maxPenetration})`,
      },
      {
        label: 'Cassure de structure (MSS) avec bougie de deplacement',
        ok: setup.displacementBody > 0,
        detail: `corps de jambe ${setup.displacementBody.toFixed(2)} $ = ` +
          `${(setup.displacementBody / setup.atrAtSignal).toFixed(2)} ATR sur ${setup.displacementLen} barre(s), ` +
          `structure cassee a ${setup.structureLevel.toFixed(2)} (${setup.structureSrc})`,
      },
      {
        label: `Entree en zone ${isSell ? 'Premium' : 'Discount'} (> ${(thr * 100).toFixed(0)}% de la structure)`,
        ok: premiumOk,
        detail: Number.isFinite(fib)
          ? `position dans la jambe de retournement : ${(fib * 100).toFixed(0)}%` +
            (Number.isFinite(setup.fibLondon) ? ` | dans le range de Londres : ${(setup.fibLondon * 100).toFixed(0)}%` : '')
          : 'non evalue (filters.premiumDiscount desactive)',
      },
      {
        label: 'DXY confirme (correlation inverse respectee)',
        ok: setup.dxy ? (setup.dxy.available ? setup.dxy.swept : null) : null,
        detail: setup.dxy
          ? setup.dxy.available
            ? `DXY a balaye son ${setup.dxy.mirrorSide === 'low' ? 'Bas' : 'Haut'} de Londres de ` +
              `${setup.dxy.penetration.toFixed(3)}${setup.dxy.reversal ? ' avec rejet' : ''}`
            : 'serie DXY absente ou non couverte a cet horodatage'
          : 'non evalue (refs.dxy.mode = off)',
      },
      {
        label: `Horaire dans la fenetre ${formatHm(newsT)}-${formatHm(sbEnd)} GMT`,
        ok: mod >= newsT && mod <= sbEnd,
        detail: `signal a ${formatHm(mod)} GMT | Silver Bullet ${formatHm(sbStart)}-${formatHm(sbEnd)}` +
          (mod >= sbStart && mod <= sbEnd ? ' (dans la fenetre)' : ' (hors fenetre Silver Bullet)'),
      },
    ];
  }

  /** Transmet l'ordre limite avec SL, TP et expiration attaches. */
  async placeOrder(setup, sizing) {
    const cfg = this.cfg;
    const nowMod = utcMinuteOfDay(Date.now());
    // Expiration : la plus proche entre l'expiration en barres et l'heure limite.
    const barsMs = cfg.entry.expiryBars > 0 ? cfg.entry.expiryBars * 5 * 60_000 : 4 * 3_600_000;
    const minutesToLimit = Math.max(1, setup.expiryMinute - nowMod);
    const expirationTimestamp = Date.now() + Math.min(barsMs, minutesToLimit * 60_000);

    const payload = {
      symbolId: this.symbol.symbolId,
      orderType: cfg.entry.model === 'market' ? ORDER_TYPE.MARKET : ORDER_TYPE.LIMIT,
      tradeSide: setup.dir === 'sell' ? TRADE_SIDE.SELL : TRADE_SIDE.BUY,
      volume: sizing.apiVolume,
      stopLoss: roundPrice(cfg, setup.sl),
      takeProfit: roundPrice(cfg, setup.tp),
      label: 'gold-sweep',
      comment: `NYsweep ${setup.side} rr=${setup.rr.toFixed(2)}`,
      clientOrderId: `gs-${setup.date}-${setup.dir}-${setup.signalIdx}`,
    };
    if (payload.orderType === ORDER_TYPE.LIMIT) {
      payload.limitPrice = roundPrice(cfg, setup.entry);
      payload.timeInForce = TIF.GOOD_TILL_DATE;
      payload.expirationTimestamp = Math.floor(expirationTimestamp);
    } else {
      payload.timeInForce = TIF.IMMEDIATE_OR_CANCEL;
    }

    const res = await this.client.newOrder(payload);
    return {
      res,
      summary: {
        side: setup.dir,
        lots: sizing.lots,
        volume: sizing.apiVolume,
        limit: payload.limitPrice,
        sl: payload.stopLoss,
        tp: payload.takeProfit,
        expire: payload.expirationTimestamp ? new Date(payload.expirationTimestamp).toISOString() : null,
      },
    };
  }

  /** Etat courant du plan journalier, pour affichage. */
  snapshot() {
    const d = this.strategy.day;
    const s = this.feed.series;
    const i = s.length - 1;
    const atrArr = s.atr(this.cfg.filters.atrPeriod);
    const out = {
      symbol: this.symbol.symbolName,
      bars: s.length,
      lastBarTs: i >= 0 ? s.time[i] : null,
      bid: this.feed.bid,
      ask: this.feed.ask,
      spread: this.feed.spread,
      atr: i >= 0 ? atrArr[i] : NaN,
      equity: this.equity,
      mode: this.execute ? 'EXECUTION' : 'ALERTE',
      signalsToday: this.emitted.length,
      funnel: this.strategy.funnel,
    };
    if (!d) return { ...out, phase: 'aucune donnee' };
    return {
      ...out,
      date: d.date,
      phase: d.phase,
      londonHigh: Number.isFinite(d.londonHigh) ? d.londonHigh : null,
      londonLow: Number.isFinite(d.londonLow) ? d.londonLow : null,
      londonRange: d.londonRange ?? null,
      londonBars: d.londonBars,
      sweep: d.sweep
        ? {
            side: d.sweep.side,
            dir: d.sweep.dir,
            level: d.sweep.level,
            extreme: d.sweep.extremePrice,
            penetrationUsd: Math.abs(d.sweep.extremePrice - d.sweep.level),
            at: new Date(d.sweep.crossTs).toISOString(),
          }
        : null,
      lastRejection: d.lastRejection,
      setupsToday: d.setups.length,
    };
  }
}
