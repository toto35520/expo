/**
 * Acces disque — SEUL module du moteur a dependre de Node.
 *
 * Tout le reste (config, strategie, indicateurs, backtest, metriques) ne
 * manipule que des chaines et des tableaux typés, et tourne donc aussi bien
 * dans Node que dans un navigateur. C'est ce qui permet au tableau de bord
 * web d'executer exactement le meme moteur, cote client, sans upload du CSV.
 */

import { readFileSync } from 'node:fs';
import { EconomicCalendar } from './calendar.js';
import { parseCsv } from './csv.js';
import { RefSeries } from './refdata.js';

/**
 * @param {string} path
 * @param {{from?: string, to?: string}} [opts]
 * @returns {import('./csv.js').Series}
 */
export function loadCsv(path, opts = {}) {
  return parseCsv(readFileSync(path, 'utf8'), opts);
}

/** @param {string} path */
export function loadCalendar(path) {
  return EconomicCalendar.fromText(readFileSync(path, 'utf8'));
}

/** @param {string} name @param {string} path */
export function loadRefSeries(name, path) {
  return RefSeries.fromText(name, readFileSync(path, 'utf8'));
}
