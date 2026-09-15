/**
 * Interface du tableau de bord.
 *
 * Tout le calcul part dans un Web Worker : le CSV (24 Mo pour 5 ans de M5)
 * n'est jamais lu sur le fil principal, donc l'interface ne gele pas et le
 * fichier ne quitte pas la machine.
 */

import { equityCurve, funnel, yearBars } from './charts.js';

const $ = (id) => document.getElementById(id);
const fmt = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '—');
const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

// ─────────────────────────── theme ───────────────────────────
const THEME_KEY = 'gs-theme';
try {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) document.documentElement.dataset.theme = saved;
} catch {
  /* stockage indisponible : on garde la preference systeme */
}
$('theme').addEventListener('click', () => {
  const root = document.documentElement;
  const dark = root.dataset.theme
    ? root.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try {
    localStorage.setItem(THEME_KEY, root.dataset.theme);
  } catch {
    /* sans persistance, le basculement reste valable pour la session */
  }
  if (lastResult) render(lastResult); // les graphiques relisent les jetons CSS
});

// ─────────────────────────── worker ──────────────────────────
const worker = new Worker('./worker.js', { type: 'module' });
let seq = 0;
const inflight = new Map();

worker.addEventListener('message', (ev) => {
  const { id, ok, result, error, ready } = ev.data;
  if (ready) return;
  const p = inflight.get(id);
  if (!p) return;
  inflight.delete(id);
  if (ok) p.resolve(result);
  else p.reject(new Error(error));
});
worker.addEventListener('error', (e) => {
  status(`Erreur du worker : ${e.message}`, true);
});

const ask = (type, payload) =>
  new Promise((resolve, reject) => {
    const id = ++seq;
    inflight.set(id, { resolve, reject });
    worker.postMessage({ id, type, payload });
  });

function status(msg, isErr = false) {
  const n = $('status');
  n.textContent = msg;
  n.classList.toggle('err', isErr);
}

// ─────────────────── depot de fichiers ───────────────────────
/**
 * Branche une zone de depot sur un input fichier.
 * @param {HTMLElement} zone @param {HTMLInputElement} input
 * @param {(f:File)=>Promise<void>} onFile
 */
function wireDrop(zone, input, onFile) {
  const open = () => input.click();
  zone.addEventListener('click', open);
  zone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      open();
    }
  });
  ['dragenter', 'dragover'].forEach((t) =>
    zone.addEventListener(t, (e) => {
      e.preventDefault();
      zone.classList.add('over');
    })
  );
  ['dragleave', 'drop'].forEach((t) =>
    zone.addEventListener(t, (e) => {
      e.preventDefault();
      zone.classList.remove('over');
    })
  );
  zone.addEventListener('drop', (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f) onFile(f);
  });
  input.addEventListener('change', () => {
    if (input.files?.[0]) onFile(input.files[0]);
  });
}

let loaded = false;

wireDrop($('drop'), $('file'), async (file) => {
  status(`Lecture de ${file.name} (${(file.size / 1048576).toFixed(1)} Mo)…`);
  $('run').disabled = true;
  try {
    const r = await ask('load', { file });
    loaded = true;
    $('drop').classList.add('loaded');
    $('drop-title').textContent = `${r.name} — ${r.describe.bars.toLocaleString('fr-FR')} barres M${r.describe.timeframeMin}`;
    $('drop-hint').innerHTML =
      `${r.describe.from.slice(0, 10)} &rarr; ${r.describe.to.slice(0, 10)} &middot; ` +
      `prix ${r.describe.priceMin.toFixed(0)}–${r.describe.priceMax.toFixed(0)} &middot; ` +
      `analyse en ${r.parseMs} ms` +
      (r.describe.skipped.skippedBadRows
        ? ` &middot; <b>${r.describe.skipped.skippedBadRows} lignes incoherentes rejetees</b>`
        : '');
    $('run').disabled = false;
    status('Pret. Lancez le backtest.');
  } catch (e) {
    loaded = false;
    $('drop').classList.remove('loaded');
    status(`CSV refuse : ${e.message}`, true);
  }
});

/** Series de reference et calendrier (optionnels). */
const refWires = [
  ['opt-dxy', 'file-dxy', 'dxy-state', 'loadRef', { name: 'DXY' }],
  ['opt-ty', 'file-ty', 'ty-state', 'loadRef', { name: 'US10Y' }],
  ['opt-cal', 'file-cal', 'cal-state', 'loadCalendar', {}],
];
for (const [zoneId, inputId, stateId, type, extra] of refWires) {
  wireDrop($(zoneId), $(inputId), async (file) => {
    try {
      const r = await ask(type, { file, ...extra });
      $(zoneId).classList.add('loaded');
      $(stateId).textContent = r.dates
        ? `${r.dates} dates chargees`
        : `${r.bars.toLocaleString('fr-FR')} barres · ${r.from} → ${r.to}`;
      status(
        type === 'loadCalendar'
          ? 'Calendrier charge. Activez filters.newsBlackout = calendar ou all.'
          : `${extra.name} charge. Activez refs.${extra.name === 'DXY' ? 'dxy.mode' : 'us10y.mode'} dans la surcharge JSON.`
      );
    } catch (e) {
      $(zoneId).classList.remove('loaded');
      $(stateId).textContent = 'refuse';
      status(`Fichier refuse : ${e.message}`, true);
    }
  });
}

// ──────────────────────── configuration ──────────────────────
/** Construit la surcharge depuis les champs + le JSON libre. */
function buildOverride() {
  const o = {};
  const set = (path, v) => {
    const k = path.split('.');
    let cur = o;
    for (const key of k.slice(0, -1)) cur = cur[key] = cur[key] || {};
    cur[k[k.length - 1]] = v;
  };

  for (const node of document.querySelectorAll('[data-path]')) {
    const raw = node.value.trim();
    if (raw === '') continue;
    const path = node.dataset.path;
    if (node.tagName === 'SELECT') set(path, raw);
    else if (node.type === 'number') {
      const n = Number(raw);
      if (!Number.isFinite(n)) throw new Error(`Valeur numerique invalide pour ${path} : « ${raw} »`);
      set(path, n);
    } else set(path, raw);
  }

  const txt = $('json').value.trim();
  $('json-err').textContent = '';
  if (txt) {
    let extra;
    try {
      extra = JSON.parse(txt);
    } catch (e) {
      $('json-err').textContent = `JSON invalide : ${e.message}`;
      throw new Error('La surcharge JSON libre est invalide.');
    }
    const merge = (a, b) => {
      for (const [k, v] of Object.entries(b)) {
        a[k] = v && typeof v === 'object' && !Array.isArray(v) ? merge(a[k] || {}, v) : v;
      }
      return a;
    };
    merge(o, extra);
  }
  return o;
}

let lastResult = null;

$('reset').addEventListener('click', () => {
  for (const n of document.querySelectorAll('[data-path]')) n.value = '';
  $('json').value = '';
  $('json-err').textContent = '';
  $('preset').value = 'stable';
  status(loaded ? 'Parametres reinitialises.' : 'Chargez un CSV pour commencer.');
});

$('run').addEventListener('click', async () => {
  if (!loaded) return;
  $('run').disabled = true;
  status('Calcul en cours…');
  try {
    const override = buildOverride();
    // Le prereglage est applique cote worker via buildConfig ; on l'injecte
    // ici comme base, la surcharge des champs gagne.
    const presetName = $('preset').value;
    const payload = { override: { __preset: presetName, ...override } };
    const r = await ask('run', payload);
    lastResult = r;
    render(r);
    status(
      `${r.metrics.trades} trade${r.metrics.trades > 1 ? 's' : ''} · ` +
        `${fmt(r.metrics.totalR, 1)} R · calcule en ${r.runMs} ms`
    );
  } catch (e) {
    status(e.message, true);
  } finally {
    $('run').disabled = false;
  }
});

// ──────────────────────────── rendu ──────────────────────────
function kpi(label, value, sub = '', tone = '') {
  return (
    `<div class="kpi ${tone}"><div class="kpi-v">${esc(value)}</div>` +
    `<div class="kpi-l">${esc(label)}</div>` +
    (sub ? `<div class="kpi-s">${sub}</div>` : '') +
    `</div>`
  );
}

function table(headers, rows, align = []) {
  if (!rows.length) return '<p class="empty">Aucune donnee.</p>';
  const th = headers.map((h) => `<th>${esc(h)}</th>`).join('');
  const tr = rows
    .map((r) => '<tr>' + r.map((c, i) => `<td class="${align[i] || ''}">${c}</td>`).join('') + '</tr>')
    .join('');
  return `<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
}

function render(r) {
  const m = r.metrics;
  const cfg = r.config;
  $('results').classList.remove('hidden');

  const se = m.rStdev / Math.sqrt(Math.max(1, m.trades));
  const t = se > 0 ? m.expectancyR / se : NaN;
  const signif = Math.abs(t) > 2;

  $('kpis').innerHTML = [
    kpi('Trades', String(m.trades), `${fmt(m.tradesPerYear, 1)} par an`),
    kpi('Taux de reussite', `${fmt(m.winRate, 1)} %`, `${m.wins} gains / ${m.losses} pertes`),
    kpi('Total', `${fmt(m.totalR, 1)} R`, `esperance ${fmt(m.expectancyR, 3)} R`, m.totalR >= 0 ? 'pos' : 'neg'),
    kpi('Profit factor', fmt(m.profitFactor, 2), `payoff ${fmt(m.payoffRatio, 2)}`, m.profitFactor >= 1 ? 'pos' : 'neg'),
    kpi('Drawdown max', `${fmt(m.maxDdR, 1)} R`, `${fmt(m.maxDdPct, 1)} % du capital`, 'neg'),
    kpi('t de Student', fmt(t, 2), signif ? 'significatif a 5 %' : 'NON significatif', signif ? 'pos' : ''),
    kpi('Resultat net', `${fmt(m.netPnl, 0)} $`, `${fmt(m.returnPct, 1)} % · TCAM ${fmt(m.cagrPct, 1)} %`, m.netPnl >= 0 ? 'pos' : 'neg'),
    kpi('Remplissage', `${fmt(m.fillRate, 0)} %`, `${r.orderStats.filled} / ${r.orderStats.placed} ordres`),
  ].join('');

  $('stat-note').innerHTML = m.trades
    ? `<h3>Lecture statistique</h3><p class="sub" style="margin:0">` +
      `Avec <b>${m.trades} trades</b> et un ecart-type de <b>${fmt(m.rStdev, 2)} R</b>, ` +
      `l'erreur-type de l'esperance vaut <b>${fmt(se, 3)} R</b>. Le t de Student de ` +
      `<b>${fmt(t, 2)}</b> ${signif
        ? 'depasse le seuil usuel de 2 : le resultat se distingue du hasard.'
        : `reste sous le seuil usuel de 2 : <b>ce resultat ne se distingue pas du hasard</b>. ` +
          `Il faudrait environ ${Math.ceil((2 * m.rStdev / Math.max(1e-9, Math.abs(m.expectancyR))) ** 2)} trades ` +
          `au meme rythme pour conclure.`}</p>`
    : '<p class="empty">Aucun trade : desserrez les filtres ou elargissez la periode.</p>';

  // ── courbe de capital ──
  let cum = 0;
  const pts = r.trades.map((tr) => {
    cum += tr.r;
    return { ts: tr.exitTs, r: tr.r, cum, date: tr.date, dir: tr.dir, exitReason: tr.exitReason };
  });
  equityCurve($('chart-equity'), pts);
  $('equity-table').innerHTML = table(
    ['Date', 'Sens', 'R', 'Cumul R', 'Sortie'],
    pts.map((p) => [
      p.date,
      p.dir === 'sell' ? 'Vente' : 'Achat',
      `<span class="${p.r >= 0 ? 'pos' : 'neg'}">${fmt(p.r, 2)}</span>`,
      fmt(p.cum, 1),
      esc(p.exitReason),
    ])
  );

  // ── par annee ──
  const years = Object.keys(m.byYear)
    .sort()
    .map((y) => ({
      year: y,
      r: m.byYear[y].r,
      trades: m.byYear[y].n,
      winRate: (m.byYear[y].wins / m.byYear[y].n) * 100,
    }));
  yearBars($('chart-years'), years);
  $('years-table').innerHTML = table(
    ['Annee', 'Trades', 'Reussite', 'Total R', 'Esperance'],
    years.map((y) => [
      y.year,
      y.trades,
      `${fmt(y.winRate, 1)} %`,
      `<span class="${y.r >= 0 ? 'pos' : 'neg'}">${fmt(y.r, 1)}</span>`,
      fmt(y.r / y.trades, 3),
    ])
  );

  // ── entonnoir ──
  const f = r.funnel;
  funnel($('chart-funnel'), [
    { label: 'Jours observes', value: f.daysSeen },
    { label: 'Jours armes', value: f.daysArmed, note: 'range de Londres complet et dans les bornes' },
    { label: 'Jours balayes', value: f.daysSwept, note: `haut ${f.daysSweptHigh} · bas ${f.daysSweptLow}` },
    { label: 'Cassure de structure', value: f.daysMssBreak, note: 'MSS confirme dans la fenetre' },
    { label: 'Setups emis', value: f.setupsEmitted, note: `vente ${f.setupsSell} · achat ${f.setupsBuy}` },
    { label: 'Ordres remplis', value: r.orderStats.filled, note: 'la limite a ete touchee' },
  ]);
  $('rejections').innerHTML = table(
    ['Motif', 'Occurrences'],
    Object.entries(f.rejected)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => [`<code>${esc(k)}</code>`, v])
  );

  // ── sorties / ordres ──
  $('exits').innerHTML = table(
    ['Motif', 'Trades', 'Total R', 'R moyen'],
    Object.entries(m.byExit)
      .sort((a, b) => b[1].n - a[1].n)
      .map(([k, v]) => [
        esc(k),
        v.n,
        `<span class="${v.r >= 0 ? 'pos' : 'neg'}">${fmt(v.r, 1)}</span>`,
        fmt(v.r / v.n, 3),
      ])
  );
  $('orders').innerHTML = table(
    ['Etat', 'Nombre'],
    Object.entries(r.orderStats)
      .filter(([, v]) => v > 0)
      .map(([k, v]) => [esc(k), v])
  );

  // ── trades ──
  $('trades').innerHTML = table(
    ['Date', 'Heure', 'Sens', 'Entree', 'SL', 'TP', 'Sortie', 'Motif', 'Lots', 'R', '$'],
    r.trades.map((tr) => [
      tr.date,
      tr.entryTime.slice(11, 16),
      tr.dir === 'sell' ? 'Vente' : 'Achat',
      fmt(tr.entry),
      fmt(tr.sl),
      fmt(tr.tp),
      fmt(tr.exit),
      esc(tr.exitReason),
      fmt(tr.lots),
      `<span class="${tr.r >= 0 ? 'pos' : 'neg'}">${fmt(tr.r, 2)}</span>`,
      `<span class="${tr.pnl >= 0 ? 'pos' : 'neg'}">${fmt(tr.pnl)}</span>`,
    ])
  );
}

// ──────────────────────────── export ─────────────────────────
function download(name, text, mime = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  $('export-status').textContent = `${name} telecharge.`;
}

$('export-html').addEventListener('click', async () => {
  if (!lastResult) return;
  try {
    const { html } = await ask('exportHtml', {});
    download('gold-sweep-rapport.html', html, 'text/html');
  } catch (e) {
    $('export-status').textContent = e.message;
  }
});
$('export-json').addEventListener('click', () => {
  if (!lastResult) return;
  download('gold-sweep-resultat.json', JSON.stringify(lastResult, null, 2));
});
$('export-cfg').addEventListener('click', () => {
  if (!lastResult) return;
  const { resolved, ...clean } = lastResult.config;
  download('gold-sweep-config.json', JSON.stringify(clean, null, 2));
});

// ───────────────── preuves de validation ────────────────────
fetch('./validation.json')
  .then((r) => (r.ok ? r.json() : {}))
  .then((docs) => {
    const map = {
      'doc-01': '01-sensibilite.txt',
      'doc-02': '02-robustesse.txt',
      'doc-03': '03-candidats.txt',
      'doc-04': '04-grille-surajustement.txt',
    };
    for (const [id, file] of Object.entries(map)) {
      $(id).textContent = docs[file] || 'Preuve non incluse dans cette construction.';
    }
  })
  .catch(() => {
    for (const id of ['doc-01', 'doc-02', 'doc-03', 'doc-04']) {
      $(id).textContent = 'Preuves indisponibles.';
    }
  });
