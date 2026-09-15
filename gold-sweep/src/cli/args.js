/**
 * Analyseur d'arguments de ligne de commande, sans dependance.
 * Gere --cle=valeur, --cle valeur, --drapeau, -x, et les chemins pointes
 * pour surcharger n'importe quel parametre de config (--set stop.buffer=0.4).
 */

import { readFileSync } from 'node:fs';
import { deepMerge, setPath } from '../core/config.js';
import { getPreset } from '../core/presets.js';

/** @param {string[]} argv */
export function parseArgs(argv) {
  const out = { _: [], flags: {}, sets: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--') {
      out._.push(...argv.slice(i + 1));
      break;
    }
    if (a.startsWith('--')) {
      const body = a.slice(2);
      const eq = body.indexOf('=');
      let key;
      let val;
      if (eq >= 0) {
        key = body.slice(0, eq);
        val = body.slice(eq + 1);
      } else {
        key = body;
        const next = argv[i + 1];
        if (next !== undefined && !next.startsWith('--')) {
          val = next;
          i++;
        } else {
          val = true;
        }
      }
      if (key === 'set') out.sets.push(String(val));
      else out.flags[key] = val;
    } else if (a.startsWith('-') && a.length > 1) {
      out.flags[a.slice(1)] = argv[i + 1] && !argv[i + 1].startsWith('-') ? argv[++i] : true;
    } else {
      out._.push(a);
    }
  }
  return out;
}

/** Convertit une chaine en valeur JS typee (nombre, booleen, null, JSON). */
export function coerce(v) {
  if (typeof v !== 'string') return v;
  const t = v.trim();
  if (t === 'true') return true;
  if (t === 'false') return false;
  if (t === 'null') return null;
  if (t === '') return '';
  if (/^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(t)) return Number(t);
  if (t.startsWith('[') || t.startsWith('{')) {
    try {
      return JSON.parse(t);
    } catch {
      return t;
    }
  }
  return t;
}

/**
 * Construit un override de config a partir des arguments :
 *   --preset frequent
 *   --config mon-reglage.json
 *   --set stop.buffer=0.4 --set filters.premiumDiscount=mssLeg
 *   --from 2024-01-01 --to 2025-12-31
 */
export function buildOverride(args) {
  let ov = {};
  if (args.flags.preset) ov = deepMerge(ov, getPreset(String(args.flags.preset)));
  if (args.flags.config) {
    const raw = readFileSync(String(args.flags.config), 'utf8');
    ov = deepMerge(ov, JSON.parse(raw));
  }
  if (args.flags.from) ov = deepMerge(ov, { sessions: { dateFrom: String(args.flags.from) } });
  if (args.flags.to) ov = deepMerge(ov, { sessions: { dateTo: String(args.flags.to) } });
  if (args.flags.equity) ov = deepMerge(ov, { risk: { initialEquity: Number(args.flags.equity) } });
  if (args.flags.risk) ov = deepMerge(ov, { risk: { pctPerTrade: Number(args.flags.risk) } });
  if (args.flags.spread) ov = deepMerge(ov, { costs: { spreadUsd: Number(args.flags.spread) } });
  if (args.flags.symbol) ov = deepMerge(ov, { instrument: { symbol: String(args.flags.symbol) } });

  for (const s of args.sets) {
    const eq = s.indexOf('=');
    if (eq < 0) throw new Error(`--set attend cle=valeur, recu : ${s}`);
    setPath(ov, s.slice(0, eq).trim(), coerce(s.slice(eq + 1)));
  }
  return ov;
}

/** Lit une variable d'environnement obligatoire. */
export function requireEnv(name, hint) {
  const v = process.env[name];
  if (!v) {
    throw new Error(
      `Variable d'environnement manquante : ${name}` + (hint ? `\n  ${hint}` : '')
    );
  }
  return v;
}

/** Journal horodate simple. */
export function makeLogger(level = 'info') {
  const order = { debug: 0, info: 1, warn: 2, error: 3 };
  const min = order[level] ?? 1;
  const tag = { debug: 'DEBUG', info: 'INFO ', warn: 'WARN ', error: 'ERREUR' };
  return (lvl, msg, extra) => {
    if ((order[lvl] ?? 1) < min) return;
    const t = new Date().toISOString().slice(11, 23);
    const line = `[${t}] ${tag[lvl] || lvl} ${msg}`;
    if (lvl === 'error') console.error(line);
    else console.log(line);
    if (extra !== undefined) console.log('        ' + JSON.stringify(extra));
  };
}
