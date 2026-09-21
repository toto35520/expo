import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { decodeTrendbar, RELATIVE_PRICE_SCALE } from '../src/lib/ctrader/protocol';
import { CandleSeries, resample } from '../src/lib/market/candles';
import { atr, bollinger, ema, rsi, sma } from '../src/lib/market/indicators';
import { analyzeStructure, fibZone, findSwings } from '../src/lib/market/structure';
import { buildLevels } from '../src/lib/market/levels';
import { analyze, DEFAULT_SETTINGS } from '../src/lib/engine/analyzer';
import { computeRisk, DEFAULT_RISK, OUNCES_PER_LOT } from '../src/lib/engine/risk';
import { buildTradeLevels } from '../src/lib/strategies/helpers';
import type { Candle, Quote } from '../src/lib/market/types';

const flat = (n: number, value: number): number[] => Array.from({ length: n }, () => value);

function candlesFrom(closes: number[], range = 1): Candle[] {
  return closes.map((c, i) => ({
    t: i * 60_000,
    o: i === 0 ? c : closes[i - 1],
    h: Math.max(c, i === 0 ? c : closes[i - 1]) + range / 2,
    l: Math.min(c, i === 0 ? c : closes[i - 1]) - range / 2,
    c,
    v: 10,
  }));
}

describe('indicateurs', () => {
  it('SMA sur serie constante vaut la constante', () => {
    const out = sma(flat(20, 2500), 5);
    assert.equal(out[3], null, 'pas de valeur avant la periode de chauffe');
    assert.equal(out[4], 2500);
    assert.equal(out[19], 2500);
  });

  it('EMA demarre sur la SMA de la periode puis converge', () => {
    const values = flat(50, 100);
    const out = ema(values, 10);
    assert.equal(out[8], null);
    assert.equal(out[9], 100, 'la graine est la SMA des 10 premieres valeurs');
    assert.equal(out[49], 100);

    // Une serie qui saute converge vers la nouvelle valeur sans l'atteindre d'un coup.
    const stepped = [...flat(20, 100), ...flat(20, 200)];
    const moving = ema(stepped, 10);
    const afterStep = moving[20]!;
    assert.ok(afterStep > 100 && afterStep < 200, `EMA intermediaire attendue, recu ${afterStep}`);
    assert.ok(moving[39]! > afterStep, "l'EMA continue de monter vers la nouvelle valeur");
  });

  it('RSI sature a 100 en hausse continue et a 0 en baisse continue', () => {
    const up = rsi(Array.from({ length: 40 }, (_, i) => 2000 + i * 3), 14);
    assert.equal(up[39], 100);

    const down = rsi(Array.from({ length: 40 }, (_, i) => 2000 - i * 3), 14);
    assert.equal(down[39], 0);
  });

  it('RSI reste entre 0 et 100 sur une serie bruitee', () => {
    const noisy = Array.from({ length: 200 }, (_, i) => 2500 + Math.sin(i / 3) * 12 + (i % 7) * 0.8);
    for (const value of rsi(noisy, 14)) {
      if (value === null) continue;
      assert.ok(value >= 0 && value <= 100, `RSI hors bornes : ${value}`);
    }
  });

  it('ATR vaut la hauteur de bougie quand elle est constante sans ecart', () => {
    const candles: Candle[] = Array.from({ length: 40 }, (_, i) => ({
      t: i * 60_000,
      o: 2500,
      h: 2502,
      l: 2498,
      c: 2500,
      v: 1,
    }));
    const out = atr(candles, 14);
    assert.equal(out[13], 4);
    assert.ok(Math.abs(out[39]! - 4) < 1e-9);
  });

  it('Bollinger : ecart-type nul sur serie plate, percentB coherent', () => {
    const out = bollinger(flat(40, 2500), 20, 2);
    const point = out[39]!;
    assert.equal(point.upper, 2500);
    assert.equal(point.lower, 2500);
    assert.equal(point.bandwidth, 0);

    const rising = bollinger(Array.from({ length: 60 }, (_, i) => 2500 + i), 20, 2);
    const last = rising[59]!;
    assert.ok(last.upper > last.middle && last.middle > last.lower);
    assert.ok(last.percentB > 0.5, 'un prix qui monte finit dans le haut des bandes');
  });
});

describe('protocole cTrader', () => {
  it('reconstruit une bougie depuis les deltas et l echelle 1/100000', () => {
    // low = 3000.00 $ ; open +1.50 ; high +4.25 ; close +3.00
    const bar = decodeTrendbar({
      volume: 42,
      low: 3000 * RELATIVE_PRICE_SCALE,
      deltaOpen: 1.5 * RELATIVE_PRICE_SCALE,
      deltaHigh: 4.25 * RELATIVE_PRICE_SCALE,
      deltaClose: 3 * RELATIVE_PRICE_SCALE,
      utcTimestampInMinutes: 29_000_000,
    });

    assert.equal(bar.l, 3000);
    assert.equal(bar.o, 3001.5);
    assert.equal(bar.h, 3004.25);
    assert.equal(bar.c, 3003);
    assert.equal(bar.v, 42);
    assert.equal(bar.t, 29_000_000 * 60_000);
    assert.ok(bar.h >= Math.max(bar.o, bar.c) && bar.l <= Math.min(bar.o, bar.c));
  });

  it('accepte les entiers transmis en chaine par le proxy JSON', () => {
    const bar = decodeTrendbar({
      volume: '7',
      low: String(2500 * RELATIVE_PRICE_SCALE),
      deltaOpen: '0',
      deltaHigh: String(2 * RELATIVE_PRICE_SCALE),
      deltaClose: String(1 * RELATIVE_PRICE_SCALE),
      utcTimestampInMinutes: 100,
    });
    assert.equal(bar.l, 2500);
    assert.equal(bar.h, 2502);
    assert.equal(bar.c, 2501);
  });
});

describe('agregation des bougies', () => {
  it('range les ticks dans le bon intervalle et met a jour OHLC', () => {
    const series = new CandleSeries();
    const base = 1_700_000_000_000 - (1_700_000_000_000 % 900_000);

    series.pushTick(2500, base + 1_000);
    series.pushTick(2510, base + 2_000);
    series.pushTick(2495, base + 3_000);
    series.pushTick(2505, base + 4_000);

    const m15 = series.get('M15');
    assert.equal(m15.length, 1, 'les 4 ticks tiennent dans la meme bougie M15');
    assert.equal(m15[0].o, 2500);
    assert.equal(m15[0].h, 2510);
    assert.equal(m15[0].l, 2495);
    assert.equal(m15[0].c, 2505);

    // Un tick dans l'intervalle suivant ouvre une nouvelle bougie sur la cloture precedente.
    series.pushTick(2506, base + 900_000 + 1_000);
    const after = series.get('M15');
    assert.equal(after.length, 2);
    assert.equal(after[1].o, 2505);
    assert.equal(after[1].c, 2506);
  });

  it('ignore les ticks arrives en retard', () => {
    const series = new CandleSeries();
    const base = 1_700_000_000_000 - (1_700_000_000_000 % 900_000);
    series.pushTick(2500, base + 900_000);
    const before = series.get('M15').length;
    series.pushTick(9999, base);
    assert.equal(series.get('M15').length, before);
    assert.ok(series.get('M15').every((c) => c.h < 9999));
  });

  it('le reechantillonnage conserve les extremes', () => {
    const candles = candlesFrom([10, 12, 9, 14, 11, 13], 2).map((c, i) => ({ ...c, t: i * 60_000 }));
    const h1 = resample(candles, 3 * 60_000);
    assert.equal(h1.length, 2);
    assert.equal(h1[0].o, candles[0].o);
    assert.equal(h1[0].h, Math.max(...candles.slice(0, 3).map((c) => c.h)));
    assert.equal(h1[0].l, Math.min(...candles.slice(0, 3).map((c) => c.l)));
    assert.equal(h1[0].c, candles[2].c);
  });
});

describe('structure de marche', () => {
  it('identifie une tendance haussiere en creux et sommets ascendants', () => {
    const closes: number[] = [];
    let price = 2400;
    for (let wave = 0; wave < 8; wave++) {
      for (let i = 0; i < 6; i++) closes.push((price += 4));
      for (let i = 0; i < 3; i++) closes.push((price -= 3));
    }
    const read = analyzeStructure(candlesFrom(closes), 2);
    assert.equal(read.bias, 'HAUSSIER');
    assert.ok(read.highs.length >= 2 && read.lows.length >= 2);
    assert.ok(read.lastHigh !== null && read.lastLow !== null);
  });

  it('identifie une tendance baissiere', () => {
    const closes: number[] = [];
    let price = 2600;
    for (let wave = 0; wave < 8; wave++) {
      for (let i = 0; i < 6; i++) closes.push((price -= 4));
      for (let i = 0; i < 3; i++) closes.push((price += 3));
    }
    assert.equal(analyzeStructure(candlesFrom(closes), 2).bias, 'BAISSIER');
  });

  it('detecte un swing sur des sommets egaux (double sommet)', () => {
    // Plateau volontaire : deux bougies partagent exactement le meme plus haut.
    const candles: Candle[] = [
      { t: 0, o: 10, h: 11, l: 9, c: 10, v: 1 },
      { t: 1, o: 11, h: 12, l: 10, c: 11, v: 1 },
      { t: 2, o: 12, h: 15, l: 11, c: 14, v: 1 },
      { t: 3, o: 14, h: 15, l: 13, c: 14, v: 1 },
      { t: 4, o: 13, h: 14, l: 12, c: 13, v: 1 },
      { t: 5, o: 12, h: 13, l: 11, c: 12, v: 1 },
      { t: 6, o: 11, h: 12, l: 10, c: 11, v: 1 },
    ];

    const swings = findSwings(candles, 2);
    const highs = swings.filter((s) => s.kind === 'HIGH');
    assert.equal(highs.length, 1, 'un plateau ne doit produire qu un seul swing');
    assert.equal(highs[0].price, 15);
    assert.equal(highs[0].index, 2, 'le premier sommet du plateau fait foi');
  });

  it('la zone de Fibonacci couvre bien 38,2 - 61,8 % de la jambe', () => {
    const leg = {
      from: { index: 0, t: 0, price: 2400, kind: 'LOW' as const },
      to: { index: 10, t: 10, price: 2500, kind: 'HIGH' as const },
      direction: 'UP' as const,
      amplitude: 100,
    };
    const zone = fibZone(leg);
    assert.ok(Math.abs(zone.level382 - 2461.8) < 0.01);
    assert.ok(Math.abs(zone.level500 - 2450) < 0.01);
    assert.ok(Math.abs(zone.level618 - 2438.2) < 0.01);
    assert.ok(zone.inZone(2450), 'le milieu de jambe est dans la zone');
    assert.ok(!zone.inZone(2495), 'un retracement superficiel est hors zone');
    assert.ok(!zone.inZone(2405), 'un retracement profond est hors zone');
  });
});

describe('gestion du risque', () => {
  it('impose un stop minimal en ATR et calcule des objectifs en R', () => {
    const levels = buildTradeLevels({
      direction: 'BUY',
      entry: 2500,
      structuralStop: 2499.9, // volontairement trop proche
      atr: 4,
      minStopAtr: 0.8,
      cushion: 0,
    })!;

    const risque = levels.entry - levels.stopLoss;
    assert.ok(Math.abs(risque - 3.2) < 1e-9, `plancher de stop attendu 3,2 $, recu ${risque}`);
    assert.ok(Math.abs(levels.takeProfits[0] - (2500 + risque)) < 1e-9, 'TP1 a 1 R');
    assert.ok(levels.takeProfits[2] > levels.takeProfits[0]);
  });

  it('place le stop du bon cote pour une vente', () => {
    const levels = buildTradeLevels({
      direction: 'SELL',
      entry: 2500,
      structuralStop: 2506,
      atr: 4,
    })!;
    assert.ok(levels.stopLoss > levels.entry, 'stop au-dessus pour une vente');
    assert.ok(levels.takeProfits.every((tp) => tp < levels.entry), 'objectifs en dessous');
  });

  it('dimensionne la position sur le risque accepte, pas sur le capital', () => {
    const plan = computeRisk(
      'BUY',
      { entry: 2500, stopLoss: 2495, takeProfits: [2505, 2510, 2515] },
      { balance: 10_000, riskPercent: 1, currency: 'USD' }
    )!;

    assert.equal(plan.riskAmount, 100);
    assert.equal(plan.stopDistance, 5);
    // 100 $ de risque / (5 $ x 100 onces) = 0,20 lot
    assert.ok(Math.abs(plan.lots - 0.2) < 1e-9, `0,20 lot attendu, recu ${plan.lots}`);
    assert.ok(Math.abs(plan.potentialLoss - 100) < 1e-6, 'la perte au stop egale le risque accepte');
    assert.equal(plan.valuePerDollarMove, 0.2 * OUNCES_PER_LOT);
    assert.ok(Math.abs(plan.rewardRisk[0] - 1) < 1e-9);
    assert.ok(Math.abs(plan.rewardRisk[2] - 3) < 1e-9);
  });

  it('refuse un plan sans distance de stop', () => {
    assert.equal(
      computeRisk('BUY', { entry: 2500, stopLoss: 2500, takeProfits: [2510] }, DEFAULT_RISK),
      null
    );
  });
});

describe('niveaux de reference', () => {
  it('separe correctement obstacles et appuis autour du prix', () => {
    const day = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000);
    const intraday: Candle[] = [];
    // Veille
    for (let i = 0; i < 60; i++) {
      const t = day - 86_400_000 + i * 900_000;
      intraday.push({ t, o: 2480, h: 2490, l: 2470, c: 2485, v: 5 });
    }
    // Jour en cours
    for (let i = 0; i < 40; i++) {
      intraday.push({ t: day + i * 900_000, o: 2500, h: 2515, l: 2495, c: 2505, v: 5 });
    }

    const map = buildLevels(intraday, intraday, 2505);
    assert.ok(map.above.every((l) => l.price > 2505));
    assert.ok(map.below.every((l) => l.price <= 2505));
    assert.ok(map.above.length > 0 && map.below.length > 0);
    assert.equal(map.dayHigh, 2515);
    assert.equal(map.dayLow, 2495);
    assert.equal(map.prevDayHigh, 2490);
    assert.equal(map.prevDayLow, 2470);
    // Les obstacles sont tries du plus proche au plus lointain.
    for (let i = 1; i < map.above.length; i++) {
      assert.ok(map.above[i].price >= map.above[i - 1].price);
    }
  });
});

describe('analyse complete', () => {
  function seededSeries(direction: 'UP' | 'DOWN'): CandleSeries {
    const series = new CandleSeries();
    const start = Date.now() - 400 * 900_000;
    let price = 2500;
    const bars: Candle[] = [];
    for (let i = 0; i < 400; i++) {
      const drift = direction === 'UP' ? 1.2 : -1.2;
      const wobble = Math.sin(i / 5) * 2.5;
      const open = price;
      price += drift + wobble * 0.3;
      bars.push({
        t: start + i * 900_000,
        o: open,
        h: Math.max(open, price) + 1.4,
        l: Math.min(open, price) - 1.4,
        c: price,
        v: 100,
      });
    }
    for (const tf of ['M1', 'M5', 'M15', 'H1', 'H4'] as const) {
      series.seed(tf, bars);
    }
    return series;
  }

  const quote = (mid: number): Quote => ({
    bid: mid - 0.15,
    ask: mid + 0.15,
    mid,
    spread: 0.3,
    ts: Date.now(),
  });

  it('produit un biais haussier sur une serie haussiere', () => {
    const series = seededSeries('UP');
    const price = series.get('M15').at(-1)!.c;
    const read = analyze(series, quote(price), DEFAULT_SETTINGS);

    assert.ok(read.globalScore > 20, `score global attendu positif, recu ${read.globalScore}`);
    assert.equal(read.globalBias, 'HAUSSIER');
    assert.ok(read.alignment > 50);
    assert.equal(read.strategies.length, 5, 'les 5 strategies sont evaluees');
  });

  it('produit un biais baissier sur une serie baissiere', () => {
    const series = seededSeries('DOWN');
    const price = series.get('M15').at(-1)!.c;
    const read = analyze(series, quote(price), DEFAULT_SETTINGS);

    assert.ok(read.globalScore < -20, `score global attendu negatif, recu ${read.globalScore}`);
    assert.equal(read.globalBias, 'BAISSIER');
  });

  it('bloque la diffusion quand le spread depasse la limite', () => {
    const series = seededSeries('UP');
    const price = series.get('M15').at(-1)!.c;
    const wide: Quote = { bid: price - 2, ask: price + 2, mid: price, spread: 4, ts: Date.now() };

    const read = analyze(series, wide, DEFAULT_SETTINGS);
    assert.equal(read.candidates.length, 0, 'aucun signal diffuse avec un spread excessif');
    assert.ok(read.blockers.some((b) => b.includes('Spread')));
  });

  it('bloque la diffusion quand la volatilite est trop faible', () => {
    const series = seededSeries('UP');
    const price = series.get('M15').at(-1)!.c;
    const read = analyze(series, quote(price), { ...DEFAULT_SETTINGS, minAtr: 999 });
    assert.equal(read.candidates.length, 0);
    assert.ok(read.blockers.some((b) => b.includes('Volatilite')));
  });

  it("chaque setup arme porte un plan de trade coherent", () => {
    const series = seededSeries('UP');
    const price = series.get('M15').at(-1)!.c;
    const read = analyze(series, quote(price), DEFAULT_SETTINGS);

    for (const strategy of read.strategies) {
      if (!strategy.levels || !strategy.direction) continue;
      const { entry, stopLoss, takeProfits } = strategy.levels;
      if (strategy.direction === 'BUY') {
        assert.ok(stopLoss < entry, `${strategy.id} : stop sous l'entree pour un achat`);
        assert.ok(takeProfits.every((tp) => tp > entry), `${strategy.id} : objectifs au-dessus`);
      } else {
        assert.ok(stopLoss > entry, `${strategy.id} : stop au-dessus pour une vente`);
        assert.ok(takeProfits.every((tp) => tp < entry), `${strategy.id} : objectifs en dessous`);
      }
      assert.ok(strategy.score >= 0 && strategy.score <= 100);
      assert.ok(strategy.readiness >= 0 && strategy.readiness <= 1);
    }
  });
});
