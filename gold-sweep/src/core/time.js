/**
 * Gestion du temps & des sessions.
 *
 * Tout est manipule en millisecondes epoch UTC. Les fenetres horaires de la
 * strategie sont exprimees en "minutes depuis minuit GMT" (0..1439).
 *
 * Point critique souvent oublie : la strategie est decrite en GMT fixe
 * ("NY ouvre a 13h00 GMT"), ce qui n'est vrai qu'en heure d'ete americaine.
 * En heure d'hiver (EST, UTC-5) l'ouverture NY glisse a 14h00 GMT et le
 * London High/Low 07:00-12:00 GMT glisse a 08:00-13:00 GMT.
 * On implemente donc les deux referentiels et on les compare au backtest.
 *
 * Les regles DST sont codees en dur (deterministes depuis 2007) pour ne
 * dependre ni d'ICU ni d'une timezone database.
 */

export const MS_MIN = 60_000;
export const MS_HOUR = 3_600_000;
export const MS_DAY = 86_400_000;

/** @param {number} y @param {number} m 0-11 @param {number} d */
function utcDate(y, m, d, h = 0, mi = 0) {
  return Date.UTC(y, m, d, h, mi, 0, 0);
}

/**
 * Jour du mois du n-ieme `dow` d'un mois (n=1 -> premier).
 * @param {number} year @param {number} month 0-11 @param {number} dow 0=dim
 * @param {number} n
 */
function nthDowOfMonth(year, month, dow, n) {
  const firstDow = new Date(Date.UTC(year, month, 1)).getUTCDay();
  return 1 + ((dow - firstDow + 7) % 7) + (n - 1) * 7;
}

/** Dernier `dow` du mois. */
function lastDowOfMonth(year, month, dow) {
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const lastDow = new Date(Date.UTC(year, month, daysInMonth)).getUTCDay();
  return daysInMonth - ((lastDow - dow + 7) % 7);
}

/**
 * Heure d'ete des Etats-Unis (America/New_York).
 * Debut : 2e dimanche de mars a 02:00 locale (= 07:00 UTC, EST=UTC-5).
 * Fin   : 1er dimanche de novembre a 02:00 locale (= 06:00 UTC, EDT=UTC-4).
 * @param {number} ts epoch ms
 * @returns {boolean} true si EDT (UTC-4)
 */
export function isUsDst(ts) {
  const y = new Date(ts).getUTCFullYear();
  const start = utcDate(y, 2, nthDowOfMonth(y, 2, 0, 2), 7, 0);
  const end = utcDate(y, 10, nthDowOfMonth(y, 10, 0, 1), 6, 0);
  return ts >= start && ts < end;
}

/**
 * Heure d'ete du Royaume-Uni (Europe/London).
 * Debut : dernier dimanche de mars a 01:00 UTC.
 * Fin   : dernier dimanche d'octobre a 01:00 UTC.
 * @param {number} ts epoch ms
 * @returns {boolean} true si BST (UTC+1)
 */
export function isUkDst(ts) {
  const y = new Date(ts).getUTCFullYear();
  const start = utcDate(y, 2, lastDowOfMonth(y, 2, 0), 1, 0);
  const end = utcDate(y, 9, lastDowOfMonth(y, 9, 0), 1, 0);
  return ts >= start && ts < end;
}

/**
 * Decalage a appliquer aux fenetres NY exprimees en GMT-ete.
 * @param {number} ts @param {'gmt'|'local'} anchor
 * @returns {number} minutes a ajouter
 */
export function nyShiftMinutes(ts, anchor) {
  if (anchor !== 'local') return 0;
  return isUsDst(ts) ? 0 : 60;
}

/**
 * Decalage a appliquer aux fenetres Londres exprimees en GMT-ete.
 * @param {number} ts @param {'gmt'|'local'} anchor
 * @returns {number} minutes a ajouter
 */
export function londonShiftMinutes(ts, anchor) {
  if (anchor !== 'local') return 0;
  return isUkDst(ts) ? 0 : 60;
}

/** Minutes depuis minuit UTC. @param {number} ts */
export function utcMinuteOfDay(ts) {
  return Math.floor(((ts % MS_DAY) + MS_DAY) % MS_DAY / MS_MIN);
}

/** Index de jour UTC (nombre de jours depuis epoch). @param {number} ts */
export function utcDayIndex(ts) {
  return Math.floor(ts / MS_DAY);
}

/** 0=dimanche .. 6=samedi. @param {number} ts */
export function utcDayOfWeek(ts) {
  return new Date(ts).getUTCDay();
}

/** "YYYY-MM-DD" @param {number} ts */
export function isoDate(ts) {
  return new Date(ts).toISOString().slice(0, 10);
}

/** "YYYY-MM-DD HH:MM" @param {number} ts */
export function isoMinute(ts) {
  return new Date(ts).toISOString().slice(0, 16).replace('T', ' ');
}

/**
 * Parse "HH:MM" -> minutes depuis minuit. Accepte aussi un nombre.
 * @param {string|number} v
 */
export function parseHm(v) {
  if (typeof v === 'number') return v;
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(v).trim());
  if (!m) throw new Error(`Heure invalide (attendu "HH:MM") : ${v}`);
  const h = Number(m[1]);
  const mi = Number(m[2]);
  if (h > 23 || mi > 59) throw new Error(`Heure hors bornes : ${v}`);
  return h * 60 + mi;
}

/** minutes -> "HH:MM" @param {number} min */
export function formatHm(min) {
  const m = ((min % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}
