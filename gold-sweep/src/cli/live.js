#!/usr/bin/env node
/**
 * gs-live — connexion cTrader Open API en temps reel.
 *
 * Sous-commandes
 *   accounts                       comptes accessibles avec le jeton
 *   symbols  [--filter XAU]        symboles disponibles
 *   discover --symbol XAUUSD       champs BRUTS renvoyes par le broker
 *                                  (a utiliser pour verifier apiVolumePerLot)
 *   history  --symbol XAUUSD       telecharge des barres, exporte en CSV
 *   plan     --symbol XAUUSD       etat du plan du jour, puis quitte
 *   watch    --symbol XAUUSD       surveillance continue (alerte par defaut)
 *
 * Identifiants — variables d'environnement :
 *   CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_ACCESS_TOKEN
 *   CTRADER_REFRESH_TOKEN (optionnel), CTRADER_ACCOUNT_ID (optionnel)
 *   CTRADER_ENV = demo | live   (defaut : demo)
 *
 * Aucun ordre n'est place sans --execute. Le mode par defaut est l'alerte.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { buildConfig } from '../core/config.js';
import { loadCalendar, loadRefSeries } from '../core/load.js';
import { RefBundle } from '../core/refdata.js';
import { formatHm, utcMinuteOfDay } from '../core/time.js';
import { CTraderClient } from '../live/ctrader/client.js';
import { PERIOD } from '../live/ctrader/messages.js';
import { LiveMonitor } from '../live/monitor.js';
import { buildOverride, makeLogger, parseArgs, requireEnv } from './args.js';

const USAGE = `
gs-live — strategie NY Open Liquidity Sweep en temps reel (cTrader Open API)

  gs-live accounts
  gs-live symbols  [--filter XAU]
  gs-live discover --symbol XAUUSD
  gs-live history  --symbol XAUUSD [--days 30] [--period M5] [--out data/x.csv]
  gs-live plan     --symbol XAUUSD
  gs-live watch    --symbol XAUUSD [--execute] [--preset stable]

  --env demo|live       surcharge CTRADER_ENV
  --symbol <nom>        symbole (tolerant aux suffixes de broker)
  --account <id>        ctidTraderAccountId
  --execute             PLACE REELLEMENT LES ORDRES (sinon : alerte seule)
  --equity <n>          capital de dimensionnement (sinon : solde du compte)
  --risk <pct>          risque par trade en %
  --preset / --set      configuration de la strategie (memes options qu'au backtest)
  --dxy <f.csv>         serie DXY pour la confluence
  --us10y <f.csv>       serie US10Y pour le filtre macro
  --calendar <f.csv>    calendrier economique
  --days / --period     pour 'history'
  --log debug|info|warn|error
  --help

Identifiants via l'environnement :
  CTRADER_CLIENT_ID  CTRADER_CLIENT_SECRET  CTRADER_ACCESS_TOKEN
  CTRADER_REFRESH_TOKEN  CTRADER_ACCOUNT_ID  CTRADER_ENV
`;

function connectOpts(args, log) {
  return {
    env: String(args.flags.env || process.env.CTRADER_ENV || 'demo'),
    clientId: requireEnv('CTRADER_CLIENT_ID', 'Identifiant application, depuis https://openapi.ctrader.com'),
    clientSecret: requireEnv('CTRADER_CLIENT_SECRET'),
    accessToken: requireEnv('CTRADER_ACCESS_TOKEN', 'Jeton OAuth2 obtenu pour votre compte cTrader'),
    refreshToken: process.env.CTRADER_REFRESH_TOKEN || null,
    accountId: args.flags.account || process.env.CTRADER_ACCOUNT_ID || null,
    log,
  };
}

const num = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '-');

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  if (args.flags.help || !cmd) {
    console.log(USAGE);
    return;
  }
  const log = makeLogger(String(args.flags.log || 'info'));
  const client = new CTraderClient(connectOpts(args, log));
  let monitor = null;

  const shutdown = async () => {
    if (monitor) monitor.stop();
    await client.close();
  };
  process.on('SIGINT', async () => {
    console.log('\ninterruption demandee — fermeture');
    await shutdown();
    process.exit(0);
  });

  await client.connect();

  try {
    // ── accounts ───────────────────────────────────────────────────
    if (cmd === 'accounts') {
      const list = await client.listAccounts();
      console.log(`\n  ${list.length} compte(s) accessible(s) :\n`);
      console.log('    ctidTraderAccountId     type    login');
      for (const a of list) {
        console.log(
          `    ${String(a.ctidTraderAccountId).padEnd(22)} ${(a.isLive ? 'LIVE' : 'DEMO').padEnd(7)} ${a.traderLogin ?? '-'}`
        );
      }
      console.log('');
      return;
    }

    // ── symbols ────────────────────────────────────────────────────
    if (cmd === 'symbols') {
      const list = await client.loadSymbols();
      const filt = args.flags.filter ? String(args.flags.filter).toUpperCase() : null;
      const shown = list
        .filter((s) => !filt || s.symbolName.toUpperCase().includes(filt))
        .sort((a, b) => a.symbolName.localeCompare(b.symbolName));
      console.log(`\n  ${shown.length} symbole(s)${filt ? ` contenant "${filt}"` : ''} :\n`);
      console.log('    id       nom              actif  description');
      for (const s of shown) {
        console.log(
          `    ${String(s.symbolId).padEnd(8)} ${s.symbolName.padEnd(16)} ${(s.enabled ? 'oui' : 'non').padEnd(6)} ${s.description || ''}`
        );
      }
      console.log('');
      return;
    }

    // ── discover ───────────────────────────────────────────────────
    if (cmd === 'discover') {
      await client.loadSymbols();
      const sym = client.resolveSymbol(String(args.flags.symbol || 'XAUUSD'));
      console.log(`\n  SYMBOLE RESOLU  ${sym.symbolName}  (id ${sym.symbolId})\n`);
      const det = await client.symbolDetails(sym.symbolId);
      console.log('  Champs interpretes par ce client :');
      console.log('   ', JSON.stringify(det.parsed.symbol?.[0] ?? {}, null, 2).replace(/\n/g, '\n    '));
      if (det.parsed.symbol?.[0]?.__wireMismatch) {
        console.log('\n  DESACCORDS DE SCHEMA (champs ignores par securite) :');
        console.log('   ', JSON.stringify(det.parsed.symbol[0].__wireMismatch));
      }
      console.log('\n  Champs BRUTS reellement envoyes par le broker :');
      console.log('  (utilisez-les pour verifier instrument.apiVolumePerLot, lotSize, minVolume, stepVolume)\n');
      console.log('    champ  type            valeur');
      const dump = (rows, indent = '    ') => {
        for (const r of rows) {
          const v = typeof r.value === 'string' && r.value.length > 60 ? r.value.slice(0, 60) + '...' : r.value;
          console.log(`${indent}${String(r.field).padStart(5)}  ${String(r.hint || '').padEnd(15)} ${v}`);
          if (r.asMessage) dump(r.asMessage, indent + '      ');
        }
      };
      dump(det.raw);
      const tr = await client.getTrader();
      console.log('\n  COMPTE (champs bruts) :\n');
      dump(tr.raw);
      console.log('');
      return;
    }

    // ── history ────────────────────────────────────────────────────
    if (cmd === 'history') {
      await client.loadSymbols();
      const sym = client.resolveSymbol(String(args.flags.symbol || 'XAUUSD'));
      const periodName = String(args.flags.period || 'M5').toUpperCase();
      const period = PERIOD[periodName];
      if (!period) throw new Error(`periode inconnue : ${periodName} (M1 M5 M15 M30 H1 H4 D1 ...)`);
      const days = Number(args.flags.days || 30);

      // L'API borne le nombre de barres par requete : on decoupe en tranches.
      const now = Date.now();
      const sliceDays = periodName === 'M1' ? 2 : periodName === 'M5' ? 10 : 60;
      const all = [];
      for (let start = now - days * 86_400_000; start < now; start += sliceDays * 86_400_000) {
        const end = Math.min(now, start + sliceDays * 86_400_000);
        const bars = await client.getTrendbars(sym.symbolId, period, start, end);
        log('info', `${new Date(start).toISOString().slice(0, 10)} -> ${new Date(end).toISOString().slice(0, 10)} : ${bars.length} barres`);
        all.push(...bars);
      }
      // Deduplication + tri.
      const byTime = new Map();
      for (const b of all) byTime.set(b.time, b);
      const bars = [...byTime.values()].sort((a, b) => a.time - b.time);
      console.log(`\n  ${bars.length} barres ${periodName} pour ${sym.symbolName}`);
      if (bars.length) {
        console.log(`  ${new Date(bars[0].time).toISOString()} -> ${new Date(bars[bars.length - 1].time).toISOString()}`);
      }
      if (args.flags.out) {
        const lines = ['time,open,high,low,close,volume'];
        for (const b of bars) {
          lines.push(
            `${new Date(b.time).toISOString()},${b.open},${b.high},${b.low},${b.close},${b.volume}`
          );
        }
        mkdirSync(dirname(String(args.flags.out)), { recursive: true });
        writeFileSync(String(args.flags.out), lines.join('\n') + '\n');
        console.log(`  CSV ecrit : ${args.flags.out}`);
        console.log('  Ce fichier est directement exploitable par gs-backtest (--csv, --dxy, --us10y).');
      } else {
        console.log('  (ajoutez --out <fichier.csv> pour exporter)');
      }
      console.log('');
      return;
    }

    // ── plan / watch ───────────────────────────────────────────────
    if (cmd !== 'plan' && cmd !== 'watch') {
      console.error(USAGE);
      console.error(`Sous-commande inconnue : ${cmd}`);
      process.exitCode = 2;
      return;
    }

    const cfg = buildConfig(buildOverride(args));
    await client.loadSymbols();
    const sym = client.resolveSymbol(String(args.flags.symbol || cfg.instrument.symbol));
    log('info', `symbole resolu : ${sym.symbolName} (id ${sym.symbolId})`);

    let refs = null;
    if (args.flags.dxy || args.flags.us10y) {
      refs = new RefBundle({
        dxy: args.flags.dxy ? loadRefSeries('DXY', String(args.flags.dxy)) : null,
        us10y: args.flags.us10y ? loadRefSeries('US10Y', String(args.flags.us10y)) : null,
      });
      log('info', `references : ${JSON.stringify(refs.describe())}`);
    }
    const calendar = args.flags.calendar ? loadCalendar(String(args.flags.calendar)) : null;

    const execute = !!args.flags.execute;
    if (execute) {
      console.log('\n  *** MODE EXECUTION : DES ORDRES REELS SERONT PLACES ***');
      console.log(`  *** environnement : ${client.env.toUpperCase()}  compte : ${client.accountId} ***`);
      console.log(`  *** verifiez instrument.apiVolumePerLot (${cfg.instrument.apiVolumePerLot}) avec "gs-live discover" ***\n`);
    }

    monitor = new LiveMonitor({
      client,
      cfg,
      symbol: sym,
      execute,
      equity: args.flags.equity ? Number(args.flags.equity) : null,
      refs,
      calendar,
      log,
    });

    monitor.on('signal', (sig) => {
      const line = '─'.repeat(72);
      console.log(`\n${line}`);
      console.log(`  SETUP ${sig.dir === 'sell' ? 'VENTE' : 'ACHAT'}  ${sig.date}  ${new Date(sig.signalTs).toISOString().slice(11, 16)} GMT`);
      console.log(line);
      console.log(`  balayage du ${sig.side === 'high' ? 'HAUT' : 'BAS'} de Londres a ${num(sig.sweepLevel)}`);
      console.log(`    range de Londres : ${num(sig.londonLow)} - ${num(sig.londonHigh)}  (${num(sig.londonRange)} $)`);
      console.log(`    extreme du piege : ${num(sig.sweepExtreme)}  penetration ${num(sig.sweepPenetrationUsd)} $ = ${num(sig.sweepPenetrationUsd / sig.atrAtSignal)} ATR`);
      console.log(`    structure cassee : ${num(sig.structureLevel)} (${sig.structureSrc})`);
      if (sig.fvg) console.log(`    FVG : ${num(sig.fvg.lower)} - ${num(sig.fvg.upper)}  (${num(sig.fvg.size)} $)`);
      console.log('');
      console.log(`  ORDRE  ${sig.zoneKind === 'market' ? 'AU MARCHE' : 'LIMITE'}`);
      console.log(`    entree  ${num(sig.entry)}`);
      console.log(`    stop    ${num(sig.sl)}   (${num(sig.slDistUsd)} $ = ${num(sig.slDistPips, 0)} pips)`);
      console.log(`    cible   ${num(sig.tp)}   R:R ${num(sig.rr)}`);
      console.log(`    volume  ${sig.sizing.lots} lots (API ${sig.sizing.apiVolume})  risque ${num(sig.sizing.riskCash)} $ = ${num(sig.sizing.riskPctOfEquity)} % du capital`);
      console.log(`    gain si cible atteinte : ${num(sig.sizing.rewardCash)} $`);
      if (Number.isFinite(sig.spreadLive)) console.log(`    spread live : ${num(sig.spreadLive, 3)} $`);
      console.log('');
      console.log('  CHECKLIST');
      for (const c of sig.checklist) {
        console.log(`    ${c.ok === true ? '[x]' : c.ok === false ? '[ ]' : '[?]'} ${c.label}`);
        console.log(`        ${c.detail}`);
      }
      const ko = sig.checklist.filter((c) => c.ok === false).length;
      const unknown = sig.checklist.filter((c) => c.ok === null).length;
      console.log('');
      console.log(`  ${sig.checklist.length - ko - unknown}/${sig.checklist.length} cases validees` +
        (ko ? `, ${ko} NON validee(s)` : '') + (unknown ? `, ${unknown} non evaluable(s)` : ''));
      console.log(`${line}\n`);
    });

    monitor.on('orderPlaced', ({ res }) => console.log(`  >>> ORDRE PLACE : ${JSON.stringify(res.summary)}\n`));
    monitor.on('orderFailed', ({ error }) => console.error(`  >>> ECHEC : ${error.message}\n`));

    await monitor.start();

    const showPlan = () => {
      const p = monitor.snapshot();
      const mod = utcMinuteOfDay(Date.now());
      console.log(`\n  ── PLAN DU JOUR ${p.date || '-'} — ${formatHm(mod)} GMT ─────────────────`);
      console.log(`     phase              ${p.phase}`);
      console.log(`     barres chargees    ${p.bars}`);
      console.log(`     bid / ask          ${num(p.bid)} / ${num(p.ask)}   spread ${num(p.spread, 3)} $`);
      console.log(`     ATR(${cfg.filters.atrPeriod}) M5        ${num(p.atr)} $`);
      console.log(`     Londres            ${p.londonLow != null ? `${num(p.londonLow)} - ${num(p.londonHigh)}  (${num(p.londonRange)} $, ${p.londonBars} barres)` : 'pas encore figee'}`);
      if (p.sweep) {
        console.log(`     balayage           ${p.sweep.side === 'high' ? 'HAUT' : 'BAS'} a ${num(p.sweep.level)} le ${p.sweep.at.slice(11, 16)} GMT`);
        console.log(`                        extreme ${num(p.sweep.extreme)}  penetration ${num(p.sweep.penetrationUsd)} $`);
      } else {
        console.log('     balayage           aucun');
      }
      if (p.lastRejection) console.log(`     dernier rejet      ${p.lastRejection.reason}`);
      console.log(`     setups du jour     ${p.setupsToday ?? 0}`);
      console.log(`     capital / mode     ${num(p.equity)} $ / ${p.mode}`);
      console.log('  ─────────────────────────────────────────────────────────────\n');
    };

    showPlan();
    if (cmd === 'plan') {
      await shutdown();
      return;
    }

    monitor.on('bar', ({ bar }) => {
      log('debug', `barre M5 close ${new Date(bar.time).toISOString().slice(11, 16)} O${num(bar.open)} H${num(bar.high)} L${num(bar.low)} C${num(bar.close)}`);
    });
    // Rappel periodique de l'etat du plan.
    const planTimer = setInterval(showPlan, Number(args.flags['plan-every'] || 900) * 1000);
    planTimer.unref?.();
    client.on('reconnected', () => log('info', 'reconnecte — abonnements rejoues'));
    client.on('tokenInvalidated', async () => {
      try {
        await client.refreshAccessToken();
        await client.authenticate();
      } catch (e) {
        log('error', `rafraichissement impossible : ${e.message}`);
      }
    });

    console.log('  surveillance active — Ctrl+C pour arreter\n');
    await new Promise(() => {}); // boucle jusqu'a SIGINT
  } catch (e) {
    await shutdown();
    throw e;
  }
}

main().catch((e) => {
  console.error(`\nErreur : ${e.message}\n`);
  if (process.env.GS_DEBUG) console.error(e.stack);
  process.exitCode = 1;
});
