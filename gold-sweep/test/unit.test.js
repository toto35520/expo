/**
 * Suite de tests. Executer : node --test test/
 *
 * Le test central est `pas de regard vers le futur` : il verifie qu'un
 * backtest sur un historique TRONQUE produit exactement les memes trades que
 * le prefixe du backtest complet. C'est la seule preuve qui compte : si la
 * strategie utilisait une information future, tronquer changerait le passe.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildConfig, deepMerge, resolveDistance, roundPrice } from '../src/core/config.js';
import { loadCsv } from '../src/core/load.js';
import { atr, findFvgs, findOrderBlock, findSwings, orderBlockZone, zoneLevel } from '../src/core/indicators.js';
import { isNfpDay, newsSpike } from '../src/core/calendar.js';
import { RefSeries } from '../src/core/refdata.js';
import { isUkDst, isUsDst, parseHm, formatHm, utcMinuteOfDay } from '../src/core/time.js';
import { firstTouch, runBacktest } from '../src/backtest/engine.js';
import { computeMetrics } from '../src/backtest/metrics.js';
import { PRESETS } from '../src/core/presets.js';
import { decode, decodeUnknown, encode } from '../src/live/protobuf.js';
import * as M from '../src/live/ctrader/messages.js';
import { CTraderClient } from '../src/live/ctrader/client.js';
import { LiveSeries, MarketFeed } from '../src/live/feed.js';
import { LiveMonitor } from '../src/live/monitor.js';

const CSV = process.env.GS_TEST_CSV ||
  '/root/.claude/uploads/bb7ccdc0-6c49-51b9-8293-298d39e0053f/e54ba8ca-xauusd-m5-2021-05-19-2026-09-07.csv';

let SERIES = null;
function series() {
  if (!SERIES) SERIES = loadCsv(CSV);
  return SERIES;
}
function provider(s) {
  const cache = new Map();
  return (p) => {
    if (!cache.has(p)) cache.set(p, atr(s, p));
    return cache.get(p);
  };
}

// ──────────────────────────── TEMPS / DST ────────────────────────────

test('heure d ete US : bascules exactes', () => {
  assert.equal(isUsDst(Date.parse('2025-03-09T06:59:00Z')), false);
  assert.equal(isUsDst(Date.parse('2025-03-09T07:00:00Z')), true);
  assert.equal(isUsDst(Date.parse('2025-11-02T05:59:00Z')), true);
  assert.equal(isUsDst(Date.parse('2025-11-02T06:00:00Z')), false);
  assert.equal(isUsDst(Date.parse('2024-03-10T07:00:00Z')), true);
  assert.equal(isUsDst(Date.parse('2026-03-08T07:00:00Z')), true);
});

test('heure d ete UK : bascules exactes', () => {
  assert.equal(isUkDst(Date.parse('2025-03-30T00:59:00Z')), false);
  assert.equal(isUkDst(Date.parse('2025-03-30T01:00:00Z')), true);
  assert.equal(isUkDst(Date.parse('2025-10-26T00:59:00Z')), true);
  assert.equal(isUkDst(Date.parse('2025-10-26T01:00:00Z')), false);
});

test('conversion des heures', () => {
  assert.equal(parseHm('13:35'), 815);
  assert.equal(parseHm('00:00'), 0);
  assert.equal(parseHm('23:59'), 1439);
  assert.equal(formatHm(815), '13:35');
  assert.equal(utcMinuteOfDay(Date.parse('2025-06-02T14:30:00Z')), 870);
  assert.throws(() => parseHm('25:00'), /hors bornes/);
  assert.throws(() => parseHm('bogus'), /invalide/);
});

// ───────────────────────────── CONFIG ────────────────────────────────

test('config : validation des incoherences', () => {
  assert.throws(() => buildConfig({ sessions: { sweepStart: '15:00' } }), /doit etre >=/);
  assert.throws(() => buildConfig({ entry: { model: 'bogus' } }), /entry.model invalide/);
  assert.throws(() => buildConfig({ stop: { distanceMode: 'furlongs' } }), /stop.distanceMode invalide/);
  assert.throws(() => buildConfig({ filters: { premiumThreshold: 2 } }), /premiumThreshold/);
  assert.throws(() => buildConfig({ target: { minRR: 30, maxRR: 5 } }), /minRR doit etre </);
});

test('config : distances normalisees', () => {
  const cfg = buildConfig();
  assert.equal(resolveDistance(cfg, 'pips', 30, {}), 3);
  assert.equal(resolveDistance(cfg, 'usd', 2.5, {}), 2.5);
  assert.equal(resolveDistance(cfg, 'atr', 0.5, { atr: 4 }), 2);
  assert.equal(resolveDistance(cfg, 'pctPrice', 0.1, { price: 4000 }), 4);
  assert.equal(resolveDistance(cfg, 'rangePct', 50, { range: 30 }), 15);
  assert.equal(resolveDistance(cfg, 'atr', null, { atr: 4 }), null);
  assert.ok(Number.isNaN(resolveDistance(cfg, 'atr', 1, { atr: NaN })));
  // C'est le point qui rend la strategie stable dans le temps : une meme
  // valeur ATR donne des distances differentes selon le regime.
  assert.ok(resolveDistance(cfg, 'atr', 0.3, { atr: 5.29 }) > resolveDistance(cfg, 'atr', 0.3, { atr: 0.96 }));
});

test('deepMerge : null desactive, undefined preserve', () => {
  // `null` est une valeur signifiante dans cette config (= filtre desactive).
  // Un null fourni en surcharge doit ecraser la base, sinon "--set x=null"
  // serait silencieusement ignore. Regression : c'etait le cas.
  assert.equal(buildConfig({ filters: { londonRangeMin: null } }).filters.londonRangeMin, null);
  assert.equal(buildConfig().filters.londonRangeMin, 3.0, 'clef absente -> defaut conserve');
  assert.equal(buildConfig({ manage: { breakEvenAtRR: null } }).manage.breakEvenAtRR, null);
  assert.equal(buildConfig({ manage: { breakEvenAtRR: 1.5 } }).manage.breakEvenAtRR, 1.5);
  assert.equal(deepMerge({ a: 1, b: 2 }, { b: undefined }).b, 2, 'undefined ne touche a rien');
  assert.equal(deepMerge({ a: 1 }, { a: null }).a, null);
  // Cas concret : basculer une fenetre in-sample en out-of-sample.
  const oos = deepMerge(
    { sessions: { dateFrom: null, dateTo: '2024-12-31' } },
    { sessions: { dateFrom: '2025-01-01', dateTo: null } }
  );
  assert.deepEqual(oos.sessions, { dateFrom: '2025-01-01', dateTo: null });
  assert.doesNotThrow(() => buildConfig(null));
});

test('bornes de dates : la periode est bien restreinte', () => {
  const s = series();
  const prov = provider(s);
  const tout = runBacktest(s, buildConfig(), prov, { collectEquity: false });
  const apres = runBacktest(s, buildConfig({ sessions: { dateFrom: '2025-01-01' } }), prov, { collectEquity: false });
  assert.ok(apres.trades.length > 0, 'des trades sur la fenetre restreinte');
  assert.ok(apres.trades.length < tout.trades.length);
  for (const t of apres.trades) assert.ok(t.date >= '2025-01-01', `trade hors fenetre : ${t.date}`);
  const avant = runBacktest(s, buildConfig({ sessions: { dateTo: '2024-12-31' } }), prov, { collectEquity: false });
  for (const t of avant.trades) assert.ok(t.date <= '2024-12-31', `trade hors fenetre : ${t.date}`);
  assert.equal(avant.trades.length + apres.trades.length, tout.trades.length, 'partition exacte');
});

test('config : arrondi de prix', () => {
  const cfg = buildConfig();
  assert.equal(roundPrice(cfg, 4405.4949), 4405.49);
  assert.equal(roundPrice(cfg, 4405.495), 4405.5);
});

// ──────────────────────────── INDICATEURS ────────────────────────────

test('ATR de Wilder : amorcage et recurrence', () => {
  const s = {
    time: Float64Array.from([0, 1, 2, 3, 4, 5].map((i) => i * 300000)),
    open: Float64Array.from([10, 10, 10, 10, 10, 10]),
    high: Float64Array.from([11, 12, 13, 12, 11, 12]),
    low: Float64Array.from([9, 10, 11, 10, 9, 10]),
    close: Float64Array.from([10, 11, 12, 11, 10, 11]),
    volume: new Float64Array(6),
    length: 6,
  };
  const a = atr(s, 3);
  assert.ok(Number.isNaN(a[0]) && Number.isNaN(a[1]) && Number.isNaN(a[2]));
  assert.ok(Number.isFinite(a[3]), 'ATR disponible a l index = period');
  // Recurrence de Wilder verifiee a la main sur la barre suivante.
  const tr4 = Math.max(s.high[4] - s.low[4], Math.abs(s.high[4] - s.close[3]), Math.abs(s.low[4] - s.close[3]));
  assert.ok(Math.abs(a[4] - (a[3] * 2 + tr4) / 3) < 1e-12);
});

test('swings fractals : latence de confirmation', () => {
  const s = series();
  const { lows, highs } = findSwings(s, 100, 300, 2);
  assert.ok(lows.length > 0 && highs.length > 0);
  for (const l of [...lows, ...highs]) {
    assert.equal(l.confirmedAt, l.i + 2, 'un fractal n est confirme que lookback barres plus tard');
  }
  // Un swing bas doit etre strictement inferieur a ses voisins.
  for (const l of lows.slice(0, 20)) {
    assert.ok(s.low[l.i] < s.low[l.i - 1] && s.low[l.i] < s.low[l.i + 1]);
    assert.ok(s.low[l.i] < s.low[l.i - 2] && s.low[l.i] < s.low[l.i + 2]);
  }
});

test('Fair Value Gap : geometrie baissiere et haussiere', () => {
  const mk = (h, l) => ({
    time: Float64Array.from(h.map((_, i) => i * 300000)),
    open: Float64Array.from(h), high: Float64Array.from(h),
    low: Float64Array.from(l), close: Float64Array.from(l),
    volume: new Float64Array(h.length), length: h.length,
  });
  // Baissier : low[0]=20 > high[2]=12 -> trou [12,20]
  const bear = findFvgs(mk([25, 18, 12], [20, 14, 8]), 2, 2, 'bearish');
  assert.equal(bear.length, 1);
  assert.deepEqual({ lower: bear[0].lower, upper: bear[0].upper, proximal: bear[0].proximal, distal: bear[0].distal },
    { lower: 12, upper: 20, proximal: 12, distal: 20 });
  // Haussier : high[0]=12 < low[2]=20 -> trou [12,20], proximal = bord haut
  const bull = findFvgs(mk([12, 18, 25], [8, 14, 20]), 2, 2, 'bullish');
  assert.equal(bull.length, 1);
  assert.deepEqual({ lower: bull[0].lower, upper: bull[0].upper, proximal: bull[0].proximal, distal: bull[0].distal },
    { lower: 12, upper: 20, proximal: 20, distal: 12 });
  // Pas de trou quand les barres se chevauchent.
  assert.equal(findFvgs(mk([25, 22, 24], [20, 18, 21]), 2, 2, 'bearish').length, 0);
});

test('Order Block : derniere bougie opposee et zones', () => {
  const s = {
    time: Float64Array.from([0, 1, 2, 3].map((i) => i * 300000)),
    open: Float64Array.from([10, 12, 15, 14]),
    close: Float64Array.from([12, 15, 13, 11]),  // idx0,1 haussieres ; 2,3 baissieres
    high: Float64Array.from([13, 16, 16, 15]),
    low: Float64Array.from([9, 11, 12, 10]),
    volume: new Float64Array(4), length: 4,
  };
  const ob = findOrderBlock(s, 2, 6, 'sell');
  assert.equal(ob.i, 1, 'derniere bougie HAUSSIERE avant la jambe vendeuse');
  const body = orderBlockZone(ob, 'body', 'sell');
  assert.deepEqual({ lower: body.lower, upper: body.upper }, { lower: 12, upper: 15 });
  assert.equal(body.proximal, 12, 'en vente le prix remonte : il touche le bas en premier');
  assert.equal(zoneLevel(body, 0), 12);
  assert.equal(zoneLevel(body, 1), 15);
  assert.equal(zoneLevel(body, 0.5), 13.5);
  const full = orderBlockZone(ob, 'full', 'sell');
  assert.deepEqual({ lower: full.lower, upper: full.upper }, { lower: 11, upper: 16 });
});

// ───────────────────────────── CALENDRIER ────────────────────────────

test('NFP : premier vendredi du mois', () => {
  assert.ok(isNfpDay(Date.parse('2025-01-03T12:00:00Z')));
  assert.ok(isNfpDay(Date.parse('2025-08-01T12:00:00Z')));
  assert.ok(!isNfpDay(Date.parse('2025-01-10T12:00:00Z')), '2e vendredi');
  assert.ok(!isNfpDay(Date.parse('2025-01-02T12:00:00Z')), 'jeudi');
});

test('detecteur de choc de news : mesure et causalite', () => {
  const s = series();
  const A = atr(s, 14);
  // Recherche du premier jour couvrant 13:30 et verification du ratio.
  const MS_DAY = 86_400_000;
  const dayStart = 0;
  const r = newsSpike(s, dayStart, 500, 810, A, 3);
  if (r.idx >= 0) {
    assert.equal(utcMinuteOfDay(s.time[r.idx]), 810, 'la barre trouvee est bien celle de 13:30');
    // L'ATR utilise doit etre celui d'AVANT la barre de news.
    assert.equal(r.atr, A[r.idx - 1]);
  }
  // Barre absente -> pas de choc, pas d exception.
  const none = newsSpike(s, 0, 3, 810, A, 3);
  assert.equal(none.spike, false);
});

// ─────────────────────── ORDRE INTRA-BARRE ───────────────────────────

test('firstTouch : les trois politiques', () => {
  const levels = [{ key: 'sl', price: 104, dir: 1 }, { key: 'tp', price: 96, dir: -1 }];
  const prio = ['sl', 'tp'];
  const bear = { open: 100, high: 105, low: 95, close: 96 };
  const bull = { open: 100, high: 105, low: 95, close: 104 };
  assert.equal(firstTouch(bear, levels, 'conservative', prio), 'sl', 'pire cas quel que soit le sens');
  assert.equal(firstTouch(bull, levels, 'conservative', prio), 'sl');
  assert.equal(firstTouch(bear, levels, 'optimistic', prio), 'tp');
  assert.equal(firstTouch(bear, levels, 'ohlcPath', prio), 'tp', 'barre baissiere : O->L en premier');
  assert.equal(firstTouch(bull, levels, 'ohlcPath', prio), 'sl', 'barre haussiere : O->H en premier');
  // Un seul niveau touche -> pas d ambiguite.
  assert.equal(firstTouch({ open: 100, high: 105, low: 99, close: 104 }, levels, 'conservative', prio), 'sl');
  assert.equal(firstTouch({ open: 100, high: 101, low: 95, close: 96 }, levels, 'conservative', prio), 'tp');
  // Aucun niveau touche.
  assert.equal(firstTouch({ open: 100, high: 101, low: 99, close: 100 }, levels, 'conservative', prio), null);
});

// ══════════════════ LE TEST CENTRAL : PAS DE LOOK-AHEAD ══════════════

test('pas de regard vers le futur : tronquer l historique ne change pas le passe', () => {
  const s = series();
  const cut = 200_000; // ~2023-09
  const full = runBacktest(s, buildConfig(), provider(s), { collectEquity: false });

  // Meme serie tronquee a `cut` barres.
  const trunc = {
    time: s.time.subarray(0, cut), open: s.open.subarray(0, cut),
    high: s.high.subarray(0, cut), low: s.low.subarray(0, cut),
    close: s.close.subarray(0, cut), volume: s.volume.subarray(0, cut),
    length: cut, timeframeMs: s.timeframeMs, stats: s.stats,
  };
  const partial = runBacktest(trunc, buildConfig(), provider(trunc), { collectEquity: false });

  const cutTs = s.time[cut - 1];
  // On compare les trades entierement contenus dans la fenetre tronquee.
  // Le dernier trade du run tronque peut etre cloture artificiellement par la
  // fin des donnees : on l'exclut.
  const fullIn = full.trades.filter((t) => t.exitTs < cutTs && t.exitReason !== 'endOfData');
  const partIn = partial.trades.filter((t) => t.exitTs < cutTs && t.exitReason !== 'endOfData');

  assert.ok(fullIn.length > 3, `echantillon suffisant (${fullIn.length} trades)`);
  assert.equal(partIn.length, fullIn.length, 'meme nombre de trades avant la troncature');
  for (let i = 0; i < fullIn.length; i++) {
    const a = fullIn[i];
    const b = partIn[i];
    assert.equal(b.entryTs, a.entryTs, `trade ${i} : meme horodatage d entree`);
    assert.equal(b.entry, a.entry, `trade ${i} : meme prix d entree`);
    assert.equal(b.sl, a.sl, `trade ${i} : meme stop`);
    assert.equal(b.tp, a.tp, `trade ${i} : meme objectif`);
    assert.equal(b.exitReason, a.exitReason, `trade ${i} : meme motif de sortie`);
    assert.ok(Math.abs(b.r - a.r) < 1e-9, `trade ${i} : meme resultat en R`);
  }
});

test('backtest deterministe a la re-execution', () => {
  const s = series();
  const a = runBacktest(s, buildConfig(), provider(s), { collectEquity: false });
  const b = runBacktest(s, buildConfig(), provider(s), { collectEquity: false });
  assert.equal(a.trades.length, b.trades.length);
  assert.equal(a.finalEquity, b.finalEquity);
  assert.deepEqual(a.funnel.rejected, b.funnel.rejected);
});

test('prereglages : chiffres documentes reproduits', () => {
  const s = series();
  const prov = provider(s);
  const attendu = {
    stable: { trades: 22, totalR: 6.9 },
    literal: { trades: 19, totalR: 4.3 },
    frequent: { trades: 50, totalR: 16.6 },
    ote: { trades: 40, totalR: 11.2 },
    selective: { trades: 15, totalR: 7.4 },
  };
  for (const [name, exp] of Object.entries(attendu)) {
    const cfg = buildConfig(PRESETS[name]);
    const m = computeMetrics(runBacktest(s, cfg, prov, { collectEquity: false }), cfg);
    assert.equal(m.trades, exp.trades, `${name} : nombre de trades`);
    assert.ok(Math.abs(m.totalR - exp.totalR) < 0.05, `${name} : totalR ${m.totalR.toFixed(2)} attendu ~${exp.totalR}`);
  }
});

test('les couts degradent bien le resultat', () => {
  const s = series();
  const prov = provider(s);
  const sans = computeMetrics(runBacktest(s, buildConfig({ costs: { spreadUsd: 0, spreadUsdNews: 0, slippageUsdOnStop: 0 } }), prov, { collectEquity: false }), buildConfig());
  const avec = computeMetrics(runBacktest(s, buildConfig({ costs: { spreadUsd: 1.0, spreadUsdNews: 2.0, slippageUsdOnStop: 0.5, commissionPerLotPerSide: 5 } }), prov, { collectEquity: false }), buildConfig());
  assert.ok(avec.totalR < sans.totalR, 'des couts plus lourds doivent reduire le resultat');
});

test('metriques : coherence interne', () => {
  const s = series();
  const cfg = buildConfig();
  const res = runBacktest(s, cfg, provider(s));
  const m = computeMetrics(res, cfg);
  assert.equal(m.wins + m.losses + m.scratches, m.trades);
  assert.ok(Math.abs(m.totalR - res.trades.reduce((a, t) => a + t.r, 0)) < 1e-9);
  assert.ok(Math.abs(m.netPnl - (res.finalEquity - cfg.risk.initialEquity)) < 1e-6);
  assert.ok(m.maxDdR >= 0);
  assert.ok(m.fillRate >= 0 && m.fillRate <= 100);
  for (const t of res.trades) {
    assert.ok(t.lots > 0, 'volume strictement positif');
    assert.ok(t.riskCash > 0, 'risque strictement positif');
    // Le risque doit correspondre au % configure (aux arrondis de lot pres).
    assert.ok(t.riskCash / t.equityAfter < 0.05, 'risque par trade raisonnable');
  }
});

// ──────────────────────────── PROTOBUF ──────────────────────────────

test('protobuf : aller-retour de tous les types de fil', () => {
  const Inner = { 1: { name: 'x', type: 'int32' }, 2: { name: 's', type: 'string' } };
  const S = {
    1: { name: 'a', type: 'uint32' }, 2: { name: 'b', type: 'string' },
    3: { name: 'c', type: 'bytes' }, 4: { name: 'd', type: 'bool' },
    5: { name: 'e', type: 'int64' }, 6: { name: 'f', type: 'message', message: Inner },
    7: { name: 'g', type: 'uint64', repeated: true }, 8: { name: 'h', type: 'double' },
    9: { name: 'i', type: 'sint64' },
  };
  const obj = { a: 2100, b: 'accentue éà€', c: Buffer.from([0, 1, 255]), d: true, e: -123456789,
    f: { x: 42, s: 'imbrique' }, g: [0, 1, 127, 128, 555783000], h: -3.14159, i: -77 };
  const back = decode(S, encode(S, obj));
  assert.equal(back.a, obj.a);
  assert.equal(back.b, obj.b);
  assert.deepEqual([...back.c], [...obj.c]);
  assert.equal(back.d, true);
  assert.equal(back.e, obj.e);
  assert.deepEqual(back.f, obj.f);
  assert.deepEqual(back.g, obj.g);
  assert.equal(back.h, obj.h);
  assert.equal(back.i, obj.i);
});

test('protobuf : varints aux frontieres d octet', () => {
  const S = { 1: { name: 'v', type: 'uint64' } };
  for (const v of [0, 1, 127, 128, 16383, 16384, 2097151, 2097152, 268435455, 268435456, Number.MAX_SAFE_INTEGER]) {
    assert.equal(decode(S, encode(S, { v })).v, v, `varint ${v}`);
  }
});

test('protobuf : champ inconnu ignore, champs suivants preserves', () => {
  const Emis = { 1: { name: 'a', type: 'uint32' }, 9: { name: 'inconnu', type: 'string' }, 2: { name: 'b', type: 'string' } };
  const Recu = { 1: { name: 'a', type: 'uint32' }, 2: { name: 'b', type: 'string' } };
  const r = decode(Recu, encode(Emis, { a: 7, inconnu: 'xx', b: 'ok' }));
  assert.equal(r.a, 7);
  assert.equal(r.b, 'ok');
});

test('protobuf : desaccord de type de fil -> champ ignore, pas corrompu', () => {
  // Le serveur envoie un varint la ou notre schema attend une chaine.
  const Serveur = { 7: { name: 'truc', type: 'uint64' }, 8: { name: 'nom', type: 'string' } };
  const Notre = { 7: { name: 'description', type: 'string' }, 8: { name: 'nom', type: 'string' } };
  const r = decode(Notre, encode(Serveur, { truc: 123456, nom: 'XAUUSD' }));
  assert.equal(r.description, undefined, 'champ non lu');
  assert.ok(Array.isArray(r.__wireMismatch) && r.__wireMismatch.length === 1, 'desaccord signale');
  assert.equal(r.nom, 'XAUUSD', 'le reste du message reste lisible');
});

test('protobuf : decodeUnknown expose la structure reelle', () => {
  const Inner = { 1: { name: 'id', type: 'int64' }, 2: { name: 'nom', type: 'string' } };
  const Outer = { 2: { name: 'acct', type: 'int64' }, 3: { name: 'sym', type: 'message', message: Inner, repeated: true } };
  const rows = decodeUnknown(encode(Outer, { acct: 123, sym: [{ id: 41, nom: 'XAUUSD' }] }), 1);
  assert.equal(rows[0].field, 2);
  assert.equal(rows[0].value, 123);
  assert.equal(rows[1].field, 3);
  assert.equal(rows[1].asMessage[1].value, 'XAUUSD');
});

// ──────────────────────── MESSAGES CTRADER ──────────────────────────

test('trendbar cTrader : reconstruction exacte des OHLC', () => {
  // Valeurs issues de la derniere ligne reelle du CSV fourni.
  const bar = M.trendbarToBar({
    volume: 1355, period: 5, low: 440279000,
    deltaOpen: 89000, deltaHigh: 224000, deltaClose: 111000,
    utcTimestampInMinutes: Math.floor(Date.parse('2026-09-07T13:25:00Z') / 60000),
  });
  assert.equal(new Date(bar.time).toISOString(), '2026-09-07T13:25:00.000Z');
  assert.equal(bar.open, 4403.68);
  assert.equal(bar.high, 4405.03);
  assert.equal(bar.low, 4402.79);
  assert.equal(bar.close, 4403.9);
  assert.equal(bar.volume, 1355);
  assert.ok(bar.high >= bar.open && bar.high >= bar.close && bar.low <= bar.open && bar.low <= bar.close);
});

test('ordre limite : prix transmis en double, sans perte', () => {
  const payload = { payloadType: 2106, ctidTraderAccountId: 12345678, symbolId: 41,
    orderType: M.ORDER_TYPE.LIMIT, tradeSide: M.TRADE_SIDE.SELL, volume: 1400,
    limitPrice: 4405.49, stopLoss: 4412.31, takeProfit: 4380.07,
    timeInForce: M.TIF.GOOD_TILL_DATE, expirationTimestamp: Date.parse('2026-09-07T16:00:00Z') };
  const b = decode(M.ProtoOANewOrderReq, encode(M.ProtoOANewOrderReq, payload));
  assert.equal(b.limitPrice, 4405.49);
  assert.equal(b.stopLoss, 4412.31);
  assert.equal(b.takeProfit, 4380.07);
  assert.equal(b.tradeSide, M.TRADE_SIDE.SELL);
  assert.equal(b.volume, 1400);
  assert.equal(b.expirationTimestamp, payload.expirationTimestamp);
});

test('conversion de prix 1/100000', () => {
  assert.equal(M.toPrice(440368000), 4403.68);
  assert.equal(M.toPrice(100000), 1);
});

// ─────────────────────── TRAMAGE RESEAU ─────────────────────────────

test('trames TCP : reassemblage quelle que soit la fragmentation', () => {
  const frame = (pt, schema, obj) => {
    const e = encode(M.ProtoMessage, { payloadType: pt, payload: encode(schema, { ...obj, payloadType: pt }) });
    const h = Buffer.allocUnsafe(4);
    h.writeUInt32BE(e.length, 0);
    return Buffer.concat([h, e]);
  };
  const all = Buffer.concat([
    frame(M.PT.HEARTBEAT_EVENT, M.ProtoHeartbeatEvent, {}),
    frame(M.PT.SPOT_EVENT, M.ProtoOASpotEvent, { ctidTraderAccountId: 1, symbolId: 41, bid: 440368000, ask: 440390000 }),
    frame(M.PT.ACCOUNT_AUTH_RES, M.ProtoOAAccountAuthRes, { ctidTraderAccountId: 1 }),
  ]);
  const mk = () => {
    const c = new CTraderClient({ env: 'demo', clientId: 'a', clientSecret: 'b', accessToken: 'c', accountId: 1 });
    const got = [];
    c.on('message', (m) => got.push(m.type));
    return { c, got };
  };
  // Un octet a la fois : le pire cas.
  {
    const { c, got } = mk();
    for (const b of all) c._onData(Buffer.from([b]));
    assert.deepEqual(got, [51, 2131, 2103]);
  }
  // Bloc unique.
  {
    const { c, got } = mk();
    c._onData(all);
    assert.deepEqual(got, [51, 2131, 2103]);
  }
  // Coupures arbitraires, dont au milieu de l en-tete de longueur.
  {
    const { c, got } = mk();
    c._onData(all.subarray(0, 2));
    c._onData(all.subarray(2, 9));
    c._onData(all.subarray(9));
    assert.deepEqual(got, [51, 2131, 2103]);
  }
});

test('trames : longueur aberrante rejetee sans plantage', () => {
  const c = new CTraderClient({ env: 'demo', clientId: 'a', clientSecret: 'b', accessToken: 'c', accountId: 1 });
  const bad = Buffer.alloc(8);
  bad.writeUInt32BE(0xffffffff, 0);
  assert.doesNotThrow(() => c._onData(bad));
  assert.equal(c.buffer.length, 0, 'tampon reinitialise');
});

test('client : env invalide refuse', () => {
  assert.throws(() => new CTraderClient({ env: 'production', clientId: 'a', clientSecret: 'b', accessToken: 'c' }), /env invalide/);
});

// ─────────────────────── SERIE LIVE / FLUX ──────────────────────────

test('ATR incremental identique a l ATR batch', () => {
  const s = series();
  const N = 20_000;
  const ls = new LiveSeries(64);
  ls.atr(14);
  for (let i = 0; i < N; i++) {
    ls.push({ time: s.time[i], open: s.open[i], high: s.high[i], low: s.low[i], close: s.close[i], volume: s.volume[i] });
  }
  const batch = atr({ ...s, length: N }, 14);
  const live = ls.atr(14);
  for (let i = 0; i < N; i++) {
    assert.equal(Number.isFinite(live[i]), Number.isFinite(batch[i]), `NaN coherent a ${i}`);
    if (Number.isFinite(batch[i])) assert.ok(Math.abs(live[i] - batch[i]) < 1e-9, `ATR identique a ${i}`);
  }
});

test('LiveSeries : rejette les barres invalides', () => {
  const ls = new LiveSeries(8);
  assert.ok(ls.push({ time: 1000, open: 1, high: 2, low: 0.5, close: 1.5 }));
  assert.equal(ls.push({ time: 1000, open: 1, high: 2, low: 0.5, close: 1.5 }), false, 'meme horodatage');
  assert.equal(ls.push({ time: 500, open: 1, high: 2, low: 0.5, close: 1.5 }), false, 'horodatage anterieur');
  assert.equal(ls.push({ time: 2000, open: 0, high: 2, low: 0.5, close: 1.5 }), false, 'prix nul');
  assert.equal(ls.length, 1);
});

test('LiveSeries : croissance de capacite sans perte', () => {
  const ls = new LiveSeries(4);
  for (let i = 0; i < 100; i++) ls.push({ time: i * 300000 + 300000, open: 10 + i, high: 11 + i, low: 9 + i, close: 10.5 + i });
  assert.equal(ls.length, 100);
  assert.equal(ls.open[0], 10);
  assert.equal(ls.open[99], 109);
  assert.ok(ls.cap >= 100);
});

test('agregation M5 depuis les ticks', () => {
  const fake = { on() {}, off() {}, async subscribeSpots() {}, async subscribeTrendbars() {}, async getTrendbars() { return []; } };
  const feed = new MarketFeed({ client: fake, symbolId: 41, timeframeMin: 5 });
  const closed = [];
  feed.on('bar', (e) => closed.push(e.bar));
  const t0 = Date.parse('2026-09-07T13:00:00Z');
  feed._absorbTick(t0 + 10_000, 4400.0, 1);
  feed._absorbTick(t0 + 60_000, 4402.5, 1);
  feed._absorbTick(t0 + 120_000, 4399.0, 1);
  feed._absorbTick(t0 + 290_000, 4401.0, 1);
  assert.equal(closed.length, 0, 'rien de cloture avant la fin du bucket');
  feed._absorbTick(t0 + 310_000, 4405.0, 1);
  assert.equal(closed.length, 1);
  assert.deepEqual(
    { t: closed[0].time, o: closed[0].open, h: closed[0].high, l: closed[0].low, c: closed[0].close },
    { t: t0, o: 4400, h: 4402.5, l: 4399, c: 4401 }
  );
  // L horloge ferme la barre en cours meme sans tick.
  feed.tickClock(t0 + 700_000);
  assert.equal(closed.length, 2);
  // Un tick en retard sur une barre deja fermee est ignore.
  feed._absorbTick(t0 + 60_000, 9999, 1);
  assert.ok(!closed.some((b) => b.high === 9999));
});

// ─────────────────── REFERENCES CORRELEES ───────────────────────────

test('RefSeries : recherche binaire et couverture', () => {
  const base = Date.parse('2025-06-02T00:00:00Z');
  const times = [0, 1, 2, 3, 4, 5].map((k) => base + k * 300_000);
  const mk = (t) => ({
    time: Float64Array.from(t), open: Float64Array.from(t.map(() => 100)),
    high: Float64Array.from(t.map(() => 101)), low: Float64Array.from(t.map(() => 99)),
    close: Float64Array.from(t.map(() => 100)), volume: new Float64Array(t.length),
    length: t.length, timeframeMs: 300_000, stats: {},
  });
  const r = new RefSeries('T', mk(times));
  assert.equal(r.idxAt(times[2]), 2);
  assert.equal(r.idxAt(times[2] + 60_000), 2, 'derniere barre <= ts');
  assert.equal(r.idxAt(base - 1), -1);
  assert.equal(r.idxAt(base + 99 * 300_000), 5);
  assert.equal(r.covers(times[2] + 60_000), true);
  assert.equal(r.covers(base + 99 * 300_000), false, 'trou de donnees detecte');
  assert.equal(r.priceAt(times[3]), 100);
  assert.ok(Number.isNaN(r.priceAt(base - 1)));
});

// ───────────────────── DIMENSIONNEMENT LIVE ─────────────────────────

test('dimensionnement : risque respecte et arrondi au pas de lot', () => {
  const cfg = buildConfig({ risk: { initialEquity: 10_000, pctPerTrade: 1.0 } });
  const fake = { on() {}, off() {}, async subscribeSpots() {}, async subscribeTrendbars() {}, async getTrendbars() { return []; }, async getTrader() { return { parsed: {} }; } };
  const m = new LiveMonitor({ client: fake, cfg, symbol: { symbolId: 41, symbolName: 'XAUUSD' } });
  m.equity = 10_000;
  const setup = { entry: 4405.5, sl: 4412.3, tp: 4380 };
  const sz = m.sizeFor(setup);
  // 1% de 10 000 = 100 $ ; distance 6.80 $ ; 100 oz/lot -> 0.147 -> 0.14
  assert.equal(sz.lots, 0.14);
  assert.equal(sz.apiVolume, 1400);
  assert.ok(sz.riskCash <= 100.000001, 'jamais plus que le risque autorise');
  assert.ok(sz.riskPctOfEquity <= 1.0000001);
  // Capital trop petit -> volume nul et motif explicite, pas d ordre.
  m.equity = 10;
  const tiny = m.sizeFor(setup);
  assert.equal(tiny.lots, 0);
  assert.match(tiny.reason, /minLots/);
  // Distance de stop nulle -> refus.
  assert.equal(m.sizeFor({ entry: 100, sl: 100, tp: 90 }).lots, 0);
});

test('checklist : 5 cases, evaluees depuis les donnees', () => {
  const cfg = buildConfig({ filters: { premiumDiscount: 'mssLeg' } });
  const fake = { on() {}, off() {}, async subscribeSpots() {}, async subscribeTrendbars() {}, async getTrendbars() { return []; } };
  const m = new LiveMonitor({ client: fake, cfg, symbol: { symbolId: 41, symbolName: 'XAUUSD' } });
  m.equity = 10_000;
  const setup = {
    date: '2026-09-07', dir: 'sell', side: 'high', signalTs: Date.parse('2026-09-07T14:10:00Z'),
    signalIdx: 100, entry: 4405.5, sl: 4412.3, tp: 4380, rr: 3.72,
    sweepPenetrationUsd: 8.4, atrAtSignal: 5.3, displacementBody: 7.1, displacementLen: 2,
    structureLevel: 4398.2, structureSrc: 'fractal', fibLeg: 0.68, fibLondon: 0.81,
    dxy: null, expiryMinute: 960,
  };
  const c = m.checklist(setup);
  assert.equal(c.length, 5);
  assert.equal(c[0].ok, true, 'balayage suffisant');
  assert.equal(c[1].ok, true, 'deplacement present');
  assert.equal(c[2].ok, true, 'entree en premium (68% > 50%)');
  assert.equal(c[3].ok, null, 'DXY non evalue sans serie');
  assert.equal(c[4].ok, true, 'signal a 14:10, dans la fenetre');
  // Entree en discount pour une vente -> case non validee.
  const bad = m.checklist({ ...setup, fibLeg: 0.30, fibLondon: 0.30 });
  assert.equal(bad[2].ok, false);
  // Signal trop tot -> case horaire non validee.
  const early = m.checklist({ ...setup, signalTs: Date.parse('2026-09-07T12:10:00Z') });
  assert.equal(early[4].ok, false);
});
