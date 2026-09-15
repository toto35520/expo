/**
 * Rendu HTML du rapport de backtest — module PUR (aucun acces disque).
 *
 * Separe de report.js pour que le tableau de bord web puisse produire
 * exactement le meme rapport cote navigateur.
 */

const n = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '-');

/** Courbe SVG a partir d'une serie de valeurs. */
function sparkline(values, w = 900, h = 220, color = '#2f9e6f') {
  if (!values.length) return '<p>Aucune donnee</p>';
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / Math.max(1, values.length - 1)) * (w - 60) + 50;
    const y = h - 25 - ((v - min) / span) * (h - 50);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const zeroY = h - 25 - ((0 - min) / span) * (h - 50);
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto">
  <line x1="50" y1="${zeroY.toFixed(1)}" x2="${w - 10}" y2="${zeroY.toFixed(1)}" stroke="var(--grid)" stroke-dasharray="4 4"/>
  <polyline fill="none" stroke="${color}" stroke-width="2" points="${pts.join(' ')}"/>
  <text x="6" y="20" fill="var(--muted)" font-size="12">${max.toFixed(1)} R</text>
  <text x="6" y="${(h - 8).toFixed(0)}" fill="var(--muted)" font-size="12">${min.toFixed(1)} R</text>
</svg>`;
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

/**
 * Construit la page HTML autonome et renvoie la chaine.
 * @returns {string}
 */
export function renderHtml({ res, m, cfg, title = 'Backtest XAUUSD — NY Open Liquidity Sweep' }) {
  const se = m.rStdev / Math.sqrt(m.trades || 1);
  const tStat = se > 0 ? m.expectancyR / se : NaN;
  const kpi = (label, value, sub = '', tone = '') =>
    `<div class="kpi ${tone}"><div class="kv">${esc(value)}</div><div class="kl">${esc(label)}</div>${sub ? `<div class="ks">${esc(sub)}</div>` : ''}</div>`;

  const yearRows = Object.keys(m.byYear).sort().map((y) => {
    const v = m.byYear[y];
    return `<tr><td>${y}</td><td>${v.n}</td><td>${n((v.wins / v.n) * 100, 1)}%</td><td class="${v.r >= 0 ? 'pos' : 'neg'}">${n(v.r, 1)}</td><td>${n(v.r / v.n, 3)}</td></tr>`;
  }).join('');

  const exitRows = Object.entries(m.byExit).sort((a, b) => b[1].n - a[1].n).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td>${v.n}</td><td class="${v.r >= 0 ? 'pos' : 'neg'}">${n(v.r, 1)}</td><td>${n(v.r / v.n, 3)}</td></tr>`
  ).join('');

  const f = res.funnel;
  const funnelRows = [
    ['Jours observes', f.daysSeen],
    ['Jours armes (range de Londres valide)', f.daysArmed],
    ['Jours avec balayage', f.daysSwept],
    ['Jours avec cassure de structure', f.daysMssBreak],
    ['Setups emis', f.setupsEmitted],
    ['Ordres remplis', res.orderStats.filled],
  ].map(([k, v], i, a) => {
    const prev = i > 0 ? a[i - 1][1] : v;
    const p = prev ? (v / prev) * 100 : 100;
    return `<tr><td>${esc(k)}</td><td>${v}</td><td>${n(p, 0)}%</td><td><div class="bar" style="width:${Math.max(1, (v / Math.max(1, a[0][1])) * 100).toFixed(1)}%"></div></td></tr>`;
  }).join('');

  const rejRows = Object.entries(f.rejected).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join('');

  const tradeRows = res.trades.map((t) =>
    `<tr><td>${t.date}</td><td>${t.entryTime.slice(11, 16)}</td><td>${t.dir === 'sell' ? 'Vente' : 'Achat'}</td>` +
    `<td>${n(t.entry)}</td><td>${n(t.sl)}</td><td>${n(t.tp)}</td><td>${n(t.exit)}</td>` +
    `<td>${esc(t.exitReason)}</td><td>${n(t.lots)}</td><td class="${t.r >= 0 ? 'pos' : 'neg'}">${n(t.r, 2)}</td><td class="${t.pnl >= 0 ? 'pos' : 'neg'}">${n(t.pnl)}</td></tr>`
  ).join('');

  const html = `<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest Gold Sweep</title>
<style>
:root{--bg:#fbfbf9;--fg:#1c1c1a;--muted:#6b6b66;--card:#ffffff;--line:#e4e3de;--grid:#cfceC8;--pos:#2f9e6f;--neg:#c4523f;--accent:#8a6d3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#131311;--fg:#eceae4;--muted:#9a9890;--card:#1c1c19;--line:#2e2e29;--grid:#3a3a34;--pos:#4cc48c;--neg:#e4785f;--accent:#c9a66b}}
:root[data-theme="dark"]{--bg:#131311;--fg:#eceae4;--muted:#9a9890;--card:#1c1c19;--line:#2e2e29;--grid:#3a3a34;--pos:#4cc48c;--neg:#e4785f;--accent:#c9a66b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:32px 16px 72px}
h1{font-size:1.6rem;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:1.05rem;margin:36px 0 12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
.sub{color:var(--muted);margin:0 0 28px;font-size:.9rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kv{font-size:1.5rem;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kl{color:var(--muted);font-size:.78rem;margin-top:3px}
.ks{color:var(--muted);font-size:.72rem;margin-top:5px;opacity:.8}
.kpi.pos .kv{color:var(--pos)}.kpi.neg .kv{color:var(--neg)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:.86rem}
th,td{text-align:right;padding:7px 9px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600;font-size:.74rem;text-transform:uppercase;letter-spacing:.04em}
tbody tr:last-child td{border-bottom:none}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.bar{height:9px;background:var(--accent);border-radius:3px;opacity:.75}
.scroll{max-height:480px;overflow:auto}
.warn{background:color-mix(in srgb,var(--neg) 9%,var(--card));border-left:3px solid var(--neg);padding:14px 16px;border-radius:0 8px 8px 0;margin:16px 0}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;margin:0;font-size:.85rem}
dt{color:var(--muted)}dd{margin:0;font-variant-numeric:tabular-nums}
@media(max-width:560px){.kv{font-size:1.25rem}dl{grid-template-columns:1fr}}
</style>
</head>
<body><div class="wrap">
<h1>${esc(title)}</h1>
<p class="sub">${esc(cfg.instrument.symbol)} &middot; ${esc(cfg.sessions.dateFrom || 'debut')} &rarr; ${esc(cfg.sessions.dateTo || 'fin')} &middot; genere le ${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC</p>

<div class="kpis">
${kpi('Trades', String(m.trades), `${n(m.tradesPerYear, 1)} / an`)}
${kpi('Taux de reussite', n(m.winRate, 1) + ' %', `${m.wins} G / ${m.losses} P`)}
${kpi('Total', n(m.totalR, 1) + ' R', `esperance ${n(m.expectancyR, 3)} R`, m.totalR >= 0 ? 'pos' : 'neg')}
${kpi('Profit factor', n(m.profitFactor, 2), `payoff ${n(m.payoffRatio, 2)}`, m.profitFactor >= 1 ? 'pos' : 'neg')}
${kpi('Drawdown max', n(m.maxDdR, 1) + ' R', n(m.maxDdPct, 1) + ' % du capital', 'neg')}
${kpi('t de Student', n(tStat, 2), Math.abs(tStat) > 2 ? 'significatif a 5 %' : 'NON significatif', Math.abs(tStat) > 2 ? 'pos' : '')}
${kpi('Resultat net', n(m.netPnl, 0) + ' $', `${n(m.returnPct, 1)} % &middot; TCAM ${n(m.cagrPct, 1)} %`, m.netPnl >= 0 ? 'pos' : 'neg')}
${kpi('Remplissage', n(m.fillRate, 0) + ' %', `${res.orderStats.filled} / ${res.orderStats.placed} ordres`)}
</div>

${Math.abs(tStat) <= 2 ? `<div class="warn"><strong>Lecture statistique.</strong> Avec ${m.trades} trades et un ecart-type de ${n(m.rStdev, 2)} R, l'erreur-type de l'esperance vaut ${n(se, 3)} R. Le t de Student de ${n(tStat, 2)} ne permet pas d'exclure que ce resultat soit du hasard (seuil usuel |t| &gt; 2). Ce backtest ne demontre pas un avantage statistique.</div>` : ''}

<h2>Courbe des R cumules</h2>
<div class="card">${sparkline(m.cumR, 900, 240, m.totalR >= 0 ? 'var(--pos)' : 'var(--neg)')}</div>

<h2>Entonnoir de selection</h2>
<div class="card"><table><thead><tr><th>Etape</th><th>Nombre</th><th>Conversion</th><th></th></tr></thead><tbody>${funnelRows}</tbody></table></div>

<h2>Performance par annee</h2>
<div class="card"><table><thead><tr><th>Annee</th><th>Trades</th><th>Reussite</th><th>Total R</th><th>Esperance</th></tr></thead><tbody>${yearRows}</tbody></table></div>

<h2>Motifs de sortie</h2>
<div class="card"><table><thead><tr><th>Motif</th><th>Trades</th><th>Total R</th><th>R moyen</th></tr></thead><tbody>${exitRows}</tbody></table></div>

<h2>Motifs de rejet</h2>
<div class="card scroll"><table><thead><tr><th>Motif</th><th>Occurrences</th></tr></thead><tbody>${rejRows}</tbody></table></div>

<h2>Parametrage actif</h2>
<div class="card"><dl>
<dt>Range de Londres</dt><dd>${esc(cfg.sessions.londonStart)}&ndash;${esc(cfg.sessions.londonEnd)} GMT (ancre ${esc(cfg.sessions.londonAnchor)})</dd>
<dt>Fenetre de balayage</dt><dd>${esc(cfg.sessions.sweepStart)}&ndash;${esc(cfg.sessions.sweepEnd)} GMT</dd>
<dt>Signal pas avant</dt><dd>${esc(cfg.sessions.signalNotBefore)} GMT</dd>
<dt>Modele d'entree</dt><dd>${esc(cfg.entry.model)} &middot; niveau ${esc(cfg.entry.model === 'fvg' ? cfg.entry.fvgLevel : cfg.entry.model === 'ote' ? cfg.entry.oteLevel : cfg.entry.obLevel)} &middot; expire ${cfg.entry.expiryBars} barres</dd>
<dt>Stop</dt><dd>${esc(cfg.stop.anchor)} + ${cfg.stop.buffer} ${esc(cfg.stop.bufferMode)} &middot; borne ${cfg.stop.minDistance}&ndash;${cfg.stop.maxDistance} ${esc(cfg.stop.distanceMode)}</dd>
<dt>Objectif</dt><dd>${esc(cfg.target.anchor)} &middot; R:R min ${cfg.target.minRR}</dd>
<dt>Penetration du balayage</dt><dd>${cfg.sweep.minPenetration}&ndash;${cfg.sweep.maxPenetration} ${esc(cfg.sweep.penetrationMode)} &middot; cote ${esc(cfg.sweep.side)}</dd>
<dt>Filtres</dt><dd>premium=${esc(cfg.filters.premiumDiscount)} &middot; silverBullet=${esc(cfg.filters.silverBullet)} &middot; news=${esc(cfg.filters.newsBlackout)}</dd>
<dt>Gestion</dt><dd>BE=${esc(cfg.manage.breakEvenAtRR ?? 'off')} &middot; partiel=${esc(cfg.manage.partial.enabled ? cfg.manage.partial.anchor : 'off')} &middot; trail=${esc(cfg.manage.trail)}</dd>
<dt>Couts</dt><dd>spread ${cfg.costs.spreadUsd} $ (news ${cfg.costs.spreadUsdNews} $) &middot; slippage ${cfg.costs.slippageUsdOnStop} $ &middot; commission ${cfg.costs.commissionPerLotPerSide} $/lot/cote</dd>
<dt>Hypothese intra-barre</dt><dd>${esc(cfg.execution.intrabar)}</dd>
<dt>Risque</dt><dd>${esc(cfg.risk.model)} ${cfg.risk.pctPerTrade} % &middot; capital initial ${cfg.risk.initialEquity} $</dd>
</dl></div>

<h2>Trades (${m.trades})</h2>
<div class="card scroll"><table><thead><tr><th>Date</th><th>Heure</th><th>Sens</th><th>Entree</th><th>SL</th><th>TP</th><th>Sortie</th><th>Motif</th><th>Lots</th><th>R</th><th>$</th></tr></thead><tbody>${tradeRows}</tbody></table></div>
</div></body></html>`;
  return html;
}
