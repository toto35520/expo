/**
 * Moteur de backtest barre par barre.
 *
 * Modele de prix : le CSV est traite comme la serie MID. On en derive
 *   ask = mid + spread/2   et   bid = mid - spread/2
 * ce qui penalise correctement les trois evenements :
 *   - remplissage de la limite  -> plus difficile
 *   - declenchement du stop     -> plus facile
 *   - atteinte du take profit   -> plus difficile
 * C'est le modele honnete ; ne jamais evaluer les niveaux sur le mid brut.
 *
 * Ordre intra-barre : une barre M5 ne dit pas dans quel ordre le haut et le
 * bas ont ete touches. Trois politiques (`execution.intrabar`) :
 *   'conservative' -> toujours le pire cas (defaut, le seul honnete)
 *   'ohlcPath'     -> chemin reconstruit O->H->L->C / O->L->H->C
 *   'optimistic'   -> meilleur cas (sert uniquement a borner l'incertitude)
 */

import { resolveDistance } from '../core/config.js';
import { SweepStrategy } from '../core/strategy.js';
import { MS_MIN, isoDate, utcDayIndex, utcMinuteOfDay } from '../core/time.js';

/**
 * Determine lequel des niveaux fournis est touche en premier dans la barre.
 * @param {{open:number,high:number,low:number,close:number}} bar
 * @param {Array<{key:string, price:number, dir:1|-1}>} levels
 *        dir=+1 : touche si le prix MONTE jusqu'a price ; dir=-1 : s'il DESCEND
 * @param {'conservative'|'ohlcPath'|'optimistic'} policy
 * @param {Array<string>} priority ordre du pire au meilleur (pour conservative)
 * @returns {string|null} clef du niveau touche en premier
 */
export function firstTouch(bar, levels, policy, priority) {
  const touched = levels.filter((l) =>
    l.dir === 1 ? bar.high >= l.price : bar.low <= l.price
  );
  if (!touched.length) return null;
  if (touched.length === 1) return touched[0].key;

  if (policy === 'conservative') {
    for (const key of priority) if (touched.some((t) => t.key === key)) return key;
    return touched[0].key;
  }
  if (policy === 'optimistic') {
    for (const key of [...priority].reverse()) if (touched.some((t) => t.key === key)) return key;
    return touched[0].key;
  }

  // ohlcPath : on reconstruit un chemin plausible et on prend le 1er croisement.
  const bullish = bar.close >= bar.open;
  const path = bullish
    ? [bar.open, bar.high, bar.low, bar.close]
    : [bar.open, bar.low, bar.high, bar.close];

  for (let seg = 0; seg < path.length - 1; seg++) {
    const a = path[seg];
    const b = path[seg + 1];
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    let best = null;
    let bestDist = Infinity;
    for (const l of touched) {
      if (l.price >= lo && l.price <= hi) {
        const dist = Math.abs(l.price - a);
        if (dist < bestDist) {
          bestDist = dist;
          best = l.key;
        }
      }
    }
    if (best) return best;
  }
  // Niveau touche par un extreme non couvert par le chemin : pire cas.
  for (const key of priority) if (touched.some((t) => t.key === key)) return key;
  return touched[0].key;
}

/** Arrondit un volume au pas de lot. */
function roundLots(cfg, lots) {
  const { lotStep, minLots, maxLots } = cfg.instrument;
  const r = Math.floor(lots / lotStep + 1e-9) * lotStep;
  const snapped = Math.round(r / lotStep) * lotStep;
  return Math.min(maxLots, Math.max(0, snapped < minLots ? 0 : snapped));
}

/**
 * Lance un backtest complet.
 *
 * @param {import('../core/csv.js').Series} s
 * @param {object} cfg config resolue
 * @param {(p:number)=>Float64Array} atrProvider
 * @param {{collectTrades?: boolean, collectEquity?: boolean}} [opts]
 * @param {import('../core/refdata.js').RefBundle|null} [refs] series correlees
 * @param {import('../core/calendar.js').EconomicCalendar|null} [calendar]
 */
export function runBacktest(s, cfg, atrProvider, opts = {}, refs = null, calendar = null) {
  const collectTrades = opts.collectTrades !== false;
  const collectEquity = opts.collectEquity !== false;

  const strat = new SweepStrategy(cfg, atrProvider, refs, calendar);
  const atrArr = atrProvider(cfg.filters.atrPeriod);

  const inst = cfg.instrument;
  const ex = cfg.execution;
  const halfSpread = cfg.costs.spreadUsd / 2;
  const halfSpreadNews = cfg.costs.spreadUsdNews / 2;

  let equity = cfg.risk.initialEquity;
  let peak = equity;
  let maxDd = 0;
  let maxDdPct = 0;

  /** @type {object|null} ordre limite en attente */
  let order = null;
  /** @type {object|null} position ouverte */
  let pos = null;

  const trades = [];
  const equityCurve = [];
  const orderStats = {
    placed: 0,
    filled: 0,
    expiredTime: 0,
    expiredBars: 0,
    cancelledSl: 0,
    cancelledTp: 0,
    cancelledEod: 0,
    expiredWindow: 0,
    rejectedRisk: 0,
    rejectedCircuit: 0,
  };

  // Etat journalier : compteurs de coupe-circuit.
  let curDay = -1;
  let tradesToday = 0;
  let rToday = 0;
  let consecLosses = 0;

  /** Demi-spread applicable a cette barre (elargi en fenetre news). */
  const spreadAt = (ts) => {
    const mod = utcMinuteOfDay(ts);
    const inNews = Math.abs(mod - cfg.resolved.newsTime) <= cfg.sessions.newsWindowMinutes;
    return inNews ? halfSpreadNews : halfSpread;
  };

  /**
   * Ouvre une position a partir d'un ordre/setup rempli, puis verifie
   * immediatement une eventuelle sortie dans la meme barre.
   * Si `lots` n'est pas fourni, le dimensionnement est calcule ici
   * (cas de l'ordre au marche).
   */
  const openPosition = (o, i, ts, hs, bar, lots = null, riskCash = null) => {
    const slDist = Math.abs(o.sl - o.entry);
    if (!(slDist > 0)) {
      orderStats.rejectedRisk++;
      return;
    }
    if (lots === null) {
      const riskBase = cfg.risk.compounding ? equity : cfg.risk.initialEquity;
      if (cfg.risk.model === 'fixedLots') {
        lots = roundLots(cfg, cfg.risk.lots);
        riskCash = slDist * lots * inst.contractSize;
      } else {
        riskCash =
          cfg.risk.model === 'fixedCash' ? cfg.risk.cashPerTrade : riskBase * (cfg.risk.pctPerTrade / 100);
        lots = roundLots(cfg, riskCash / (slDist * inst.contractSize));
        riskCash = slDist * lots * inst.contractSize;
      }
    }
    if (lots <= 0 || !(riskCash > 0) || equity <= 0) {
      orderStats.rejectedRisk++;
      return;
    }

    orderStats.filled++;
    const off = resolveDistance(cfg, cfg.manage.breakEvenOffsetMode, cfg.manage.breakEvenOffset, {
      atr: o.atrAtSignal,
      price: o.entry,
      range: o.londonRange,
    });
    pos = {
      ...o,
      entryPrice: o.entry,
      entryIdx: i,
      entryTs: ts,
      lots,
      lotsOrig: lots,
      closedLots: 0,
      riskCash,
      slDist,
      slOrig: o.sl,
      tpOrig: o.tp,
      realized: 0,
      mae: 0,
      mfe: 0,
      partialsTaken: 0,
      movedToBe: false,
      partialPending:
        cfg.manage.partial.enabled &&
        (cfg.manage.partial.anchor !== 'internalLiquidity' || !!o.internalLiquidity),
      partialLevel:
        cfg.manage.partial.anchor === 'internalLiquidity'
          ? o.internalLiquidity
            ? o.internalLiquidity.level
            : NaN
          : o.dir === 'sell'
            ? o.entry - cfg.manage.partial.atRR * slDist
            : o.entry + cfg.manage.partial.atRR * slDist,
      bePending: cfg.manage.breakEvenAtRR !== null,
      beTrigger:
        cfg.manage.breakEvenAtRR !== null
          ? o.dir === 'sell'
            ? o.entry - cfg.manage.breakEvenAtRR * slDist
            : o.entry + cfg.manage.breakEvenAtRR * slDist
          : NaN,
      beOffset: Number.isFinite(off) ? off : 0,
    };

    // Le remplissage et la sortie peuvent tomber dans la meme barre M5.
    if (ex.allowSameBarExit) {
      const isS = pos.dir === 'sell';
      const slMid = isS ? pos.sl - hs : pos.sl + hs;
      const tpMid = isS ? pos.tp + hs : pos.tp - hs;
      const hit = firstTouch(
        bar,
        [
          { key: 'sl', price: slMid, dir: isS ? 1 : -1 },
          { key: 'tp', price: tpMid, dir: isS ? -1 : 1 },
        ],
        ex.intrabar,
        ['sl', 'tp']
      );
      if (hit === 'sl') {
        const slip = cfg.costs.slippageUsdOnStop;
        closePosition(isS ? pos.sl + slip : pos.sl - slip, ts, i, 'sl');
      } else if (hit === 'tp') {
        closePosition(pos.tp, ts, i, 'tp');
      }
    }
  };

  /** Cloture la position et comptabilise le resultat. */
  const closePosition = (exitPrice, ts, idx, reason, lotsToClose = null) => {
    const lots = lotsToClose === null ? pos.lots : Math.min(lotsToClose, pos.lots);
    const units = lots * inst.contractSize;
    const gross = pos.dir === 'sell' ? (pos.entryPrice - exitPrice) * units : (exitPrice - pos.entryPrice) * units;
    const commission = cfg.costs.commissionPerLotPerSide * lots;
    const net = gross - commission;

    equity += net;
    pos.realized += net;
    pos.lots -= lots;
    pos.closedLots += lots;

    if (equity > peak) peak = equity;
    const dd = peak - equity;
    if (dd > maxDd) {
      maxDd = dd;
      maxDdPct = (dd / peak) * 100;
    }

    if (pos.lots <= 1e-9) {
      const rMultiple = pos.realized / pos.riskCash;
      rToday += rMultiple;
      if (pos.realized > 0) consecLosses = 0;
      else consecLosses++;

      if (collectTrades) {
        trades.push({
          date: pos.date,
          dir: pos.dir,
          side: pos.side,
          entryTs: pos.entryTs,
          entryTime: new Date(pos.entryTs).toISOString(),
          exitTs: ts,
          exitTime: new Date(ts).toISOString(),
          holdBars: idx - pos.entryIdx,
          entry: pos.entryPrice,
          sl: pos.slOrig,
          tp: pos.tpOrig,
          exit: exitPrice,
          exitReason: reason,
          lots: pos.lotsOrig,
          riskCash: pos.riskCash,
          pnl: pos.realized,
          r: rMultiple,
          rrPlanned: pos.rr,
          maeUsd: pos.mae,
          mfeUsd: pos.mfe,
          maeR: pos.mae / pos.slDist,
          mfeR: pos.mfe / pos.slDist,
          equityAfter: equity,
          slDistUsd: pos.slDist,
          atrAtSignal: pos.atrAtSignal,
          londonRange: pos.londonRange,
          sweepPenetrationUsd: pos.sweepPenetrationUsd,
          zoneKind: pos.zoneKind,
          partialsTaken: pos.partialsTaken,
          movedToBe: pos.movedToBe,
        });
      }
      tradesToday++;
      pos = null;
    }
  };

  for (let i = 0; i < s.length; i++) {
    const ts = s.time[i];
    const bar = { open: s.open[i], high: s.high[i], low: s.low[i], close: s.close[i] };
    const mod = utcMinuteOfDay(ts);
    const hs = spreadAt(ts);
    const atrNow = atrArr[i];

    // ── Rotation de journee : remise a zero des compteurs ─────────────
    const dIdx = utcDayIndex(ts);
    if (dIdx !== curDay) {
      curDay = dIdx;
      tradesToday = 0;
      rToday = 0;
    }

    // ── 1. Gestion de la position ouverte (avant tout nouveau signal) ──
    if (pos) {
      // Suivi MAE / MFE en USD favorable / defavorable.
      const adverse = pos.dir === 'sell' ? bar.high - pos.entryPrice : pos.entryPrice - bar.low;
      const favour = pos.dir === 'sell' ? pos.entryPrice - bar.low : bar.high - pos.entryPrice;
      if (adverse > pos.mae) pos.mae = adverse;
      if (favour > pos.mfe) pos.mfe = favour;

      // Cloture forcee de fin de journee (priorite sur tout le reste).
      if (mod >= pos.forceCloseMinute) {
        const exit = pos.dir === 'sell' ? bar.close + hs : bar.close - hs;
        closePosition(exit, ts, i, 'forceClose');
      }
    }

    if (pos) {
      // Sortie sur duree maximale de detention.
      if (cfg.manage.maxHoldBars > 0 && i - pos.entryIdx >= cfg.manage.maxHoldBars) {
        const exit = pos.dir === 'sell' ? bar.close + hs : bar.close - hs;
        closePosition(exit, ts, i, 'timeStop');
      }
    }

    if (pos) {
      const isSell = pos.dir === 'sell';
      // Niveaux exprimes en MID pour comparaison aux OHLC de la serie.
      // Short : on sort a l'ASK -> le SL se declenche 'hs' plus tot.
      const slMid = isSell ? pos.sl - hs : pos.sl + hs;
      const tpMid = isSell ? pos.tp + hs : pos.tp - hs;

      const levels = [
        { key: 'sl', price: slMid, dir: isSell ? 1 : -1 },
        { key: 'tp', price: tpMid, dir: isSell ? -1 : 1 },
      ];
      if (pos.partialPending) {
        const pMid = isSell ? pos.partialLevel + hs : pos.partialLevel - hs;
        levels.push({ key: 'partial', price: pMid, dir: isSell ? -1 : 1 });
      }
      if (pos.bePending) {
        const bMid = isSell ? pos.beTrigger + hs : pos.beTrigger - hs;
        levels.push({ key: 'be', price: bMid, dir: isSell ? -1 : 1 });
      }

      // Boucle : plusieurs evenements peuvent se produire dans la meme barre
      // (partiel puis TP par exemple). On les traite dans l'ordre du chemin.
      let guard = 0;
      while (pos && guard++ < 6) {
        const hit = firstTouch(bar, levels, ex.intrabar, ['sl', 'be', 'partial', 'tp']);
        if (!hit) break;

        if (hit === 'sl') {
          const slip = cfg.costs.slippageUsdOnStop;
          const exit = isSell ? pos.sl + slip : pos.sl - slip;
          closePosition(exit, ts, i, pos.movedToBe ? 'breakEven' : 'sl');
          break;
        }
        if (hit === 'tp') {
          closePosition(pos.tp, ts, i, 'tp');
          break;
        }
        if (hit === 'partial') {
          const lots = roundLots(cfg, pos.lotsOrig * cfg.manage.partial.closePct);
          pos.partialPending = false;
          pos.partialsTaken++;
          const li = levels.findIndex((l) => l.key === 'partial');
          if (li >= 0) levels.splice(li, 1);
          if (lots > 0 && lots < pos.lots) closePosition(pos.partialLevel, ts, i, 'partial', lots);
          continue;
        }
        if (hit === 'be') {
          const off = resolveDistance(cfg, cfg.manage.breakEvenOffsetMode, cfg.manage.breakEvenOffset, {
            atr: pos.atrAtSignal,
            price: pos.entryPrice,
            range: pos.londonRange,
          });
          const o = Number.isFinite(off) ? off : 0;
          pos.sl = isSell ? pos.entryPrice - o : pos.entryPrice + o;
          pos.bePending = false;
          pos.movedToBe = true;
          const bi = levels.findIndex((l) => l.key === 'be');
          if (bi >= 0) levels.splice(bi, 1);
          const si = levels.findIndex((l) => l.key === 'sl');
          if (si >= 0) levels[si].price = isSell ? pos.sl - hs : pos.sl + hs;
          continue;
        }
        break;
      }
    }

    // Trailing stop (applique a la cloture de barre, apres les sorties).
    if (pos && cfg.manage.trail === 'atr' && Number.isFinite(atrNow)) {
      const d = cfg.manage.trailAtrMult * atrNow;
      const cand = pos.dir === 'sell' ? bar.close + d : bar.close - d;
      if (pos.dir === 'sell' ? cand < pos.sl : cand > pos.sl) pos.sl = cand;
    }

    // ── 2. Cycle de vie de l'ordre limite en attente ───────────────────
    if (order) {
      const isSell = order.dir === 'sell';
      let killed = null;

      if (mod >= order.forceCloseMinute) killed = 'cancelledEod';
      else if (mod >= order.expiryMinute) killed = 'expiredTime';
      else if (i >= order.expiryIdx) killed = 'expiredBars';
      else if (mod > order.fillUntilMinute) killed = 'expiredWindow';

      if (!killed && cfg.entry.cancelIfSlTouched) {
        const slMid = isSell ? order.sl - hs : order.sl + hs;
        if (isSell ? bar.high >= slMid : bar.low <= slMid) killed = 'cancelledSl';
      }
      if (!killed && cfg.entry.cancelIfTpTouched) {
        const tpMid = isSell ? order.tp + hs : order.tp - hs;
        if (isSell ? bar.low <= tpMid : bar.high >= tpMid) killed = 'cancelledTp';
      }

      // Remplissage. Une limite de vente s'execute au BID : il faut que le mid
      // depasse la limite de hs pour que le bid l'atteigne.
      // La fenetre Silver Bullet, si active, borne l'heure de remplissage.
      const fillMid = isSell ? order.entry + hs : order.entry - hs;
      const inFillWindow = mod >= order.fillFromMinute && mod <= order.fillUntilMinute;
      const canFill = inFillWindow && (isSell ? bar.high >= fillMid : bar.low <= fillMid);

      if (killed && canFill) {
        // Ambigu dans la meme barre : politique intra-barre.
        const which = firstTouch(
          bar,
          [
            { key: 'fill', price: fillMid, dir: isSell ? 1 : -1 },
            { key: 'kill', price: isSell ? order.sl - hs : order.sl + hs, dir: isSell ? 1 : -1 },
          ],
          ex.intrabar,
          ['kill', 'fill']
        );
        if (which === 'fill') killed = null;
      }

      if (killed) {
        orderStats[killed]++;
        order = null;
      } else if (canFill && !pos) {
        // Coupe-circuits evalues au moment du remplissage.
        const blockTrades = tradesToday >= cfg.filters.maxTradesPerDay;
        const blockLosses =
          cfg.filters.maxConsecutiveLosses > 0 && consecLosses >= cfg.filters.maxConsecutiveLosses;
        const blockDaily = cfg.filters.dailyLossLimitR > 0 && rToday <= -cfg.filters.dailyLossLimitR;

        if (blockTrades || blockLosses || blockDaily) {
          orderStats.rejectedCircuit++;
          order = null;
        } else {
          const slDist = Math.abs(order.sl - order.entry);
          const riskBase = cfg.risk.compounding ? equity : cfg.risk.initialEquity;
          let riskCash;
          let lots;
          if (cfg.risk.model === 'fixedLots') {
            lots = roundLots(cfg, cfg.risk.lots);
            riskCash = slDist * lots * inst.contractSize;
          } else {
            riskCash =
              cfg.risk.model === 'fixedCash' ? cfg.risk.cashPerTrade : riskBase * (cfg.risk.pctPerTrade / 100);
            lots = roundLots(cfg, riskCash / (slDist * inst.contractSize));
            riskCash = slDist * lots * inst.contractSize;
          }

          if (lots <= 0 || riskCash <= 0 || equity <= 0) {
            orderStats.rejectedRisk++;
            order = null;
          } else {
            const o = order;
            order = null;
            openPosition(o, i, ts, hs, bar, lots, riskCash);
          }
        }
      }
    }

    // ── 3. Nouveaux signaux (a la cloture de la barre i) ────────────────
    const emitted = strat.onBar(s, i);
    for (const setup of emitted) {
      if (pos || order) break; // une seule position/ordre a la fois
      if (tradesToday >= cfg.filters.maxTradesPerDay) {
        orderStats.rejectedCircuit++;
        break;
      }
      orderStats.placed++;
      if (cfg.entry.model === 'market') {
        // Ordre au marche : execute immediatement a la cloture de la barre de
        // signal, en payant le demi-spread ET le slippage (execution agressive).
        const slip = cfg.costs.slippageUsdOnStop;
        const px = setup.dir === 'sell' ? bar.close - hs - slip : bar.close + hs + slip;
        openPosition({ ...setup, entry: px }, i, ts, hs, bar);
      } else {
        order = { ...setup };
      }
    }

    if (collectEquity && (i % 12 === 0 || i === s.length - 1)) {
      equityCurve.push({ ts, equity });
    }
  }

  // Position encore ouverte en fin d'historique : cloture au dernier prix.
  if (pos) {
    const last = s.length - 1;
    const hs = spreadAt(s.time[last]);
    const exit = pos.dir === 'sell' ? s.close[last] + hs : s.close[last] - hs;
    closePosition(exit, s.time[last], last, 'endOfData');
  }

  return {
    trades,
    equityCurve,
    funnel: strat.funnel,
    orderStats,
    finalEquity: equity,
    maxDd,
    maxDdPct,
    cfg,
  };
}
