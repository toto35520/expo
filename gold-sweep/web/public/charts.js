/**
 * Graphiques en SVG inline, sans bibliotheque.
 *
 * Palette : instance de reference validee (validate_palette.js, tous les
 * tests passent en mode clair ET sombre).
 *   - courbe de capital : une seule serie -> pas de legende, le titre nomme
 *     la serie ; bleu categoriel slot 1
 *   - entonnoir : rampe ORDINALE bleue (etapes ordonnees), jamais plus claire
 *     que l'etape 250 en clair / plus foncee que 600 en sombre, pour rester
 *     au-dessus de 2:1 sur la surface
 *   - resultat annuel : donnee de POLARITE -> paire divergente bleu/rouge avec
 *     zero neutre, pas un arc-en-ciel et pas vert/rouge (la paire bleu/rouge
 *     est plus sure pour les daltonismes : Delta E CVD 21.6 en clair)
 *
 * Toutes les valeurs chiffrees portent des jetons de texte, jamais la couleur
 * de la serie. Les grilles et les axes sont recessifs.
 */

const NS = 'http://www.w3.org/2000/svg';
const el = (name, attrs = {}) => {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
  return n;
};
const fmt = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '—');

/** Rampe ordinale bleue (etapes 250 -> 600) pour l'entonnoir. */
const ORDINAL = ['#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95'];

/** Infobulle partagee, positionnee en coordonnees page. */
function tooltip() {
  let node = document.getElementById('viz-tip');
  if (!node) {
    node = document.createElement('div');
    node.id = 'viz-tip';
    node.className = 'viz-tip';
    node.setAttribute('role', 'status');
    document.body.appendChild(node);
  }
  return {
    show(html, x, y) {
      node.innerHTML = html;
      node.style.display = 'block';
      const r = node.getBoundingClientRect();
      const left = Math.min(window.innerWidth - r.width - 8, Math.max(8, x - r.width / 2));
      const top = y - r.height - 12 < 8 ? y + 16 : y - r.height - 12;
      node.style.left = `${left}px`;
      node.style.top = `${top}px`;
    },
    hide() {
      node.style.display = 'none';
    },
  };
}

/**
 * Courbe des R cumules dans le temps.
 * @param {HTMLElement} host
 * @param {Array<{ts:number, r:number, cum:number, date:string, dir:string, exitReason:string}>} points
 */
export function equityCurve(host, points) {
  host.innerHTML = '';
  if (points.length < 2) {
    host.innerHTML = '<p class="empty">Au moins deux trades sont necessaires pour tracer une courbe.</p>';
    return;
  }
  const W = 880;
  const H = 300;
  const M = { t: 16, r: 16, b: 34, l: 52 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;

  const xs = points.map((p) => p.ts);
  const ys = points.map((p) => p.cum);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const yMin = Math.min(0, ...ys);
  const yMax = Math.max(0, ...ys);
  const yPad = (yMax - yMin) * 0.08 || 1;
  const lo = yMin - yPad;
  const hi = yMax + yPad;

  const sx = (t) => M.l + ((t - x0) / (x1 - x0 || 1)) * iw;
  const sy = (v) => M.t + ih - ((v - lo) / (hi - lo || 1)) * ih;

  const svg = el('svg', {
    viewBox: `0 0 ${W} ${H}`,
    role: 'img',
    'aria-label': `Courbe des R cumules : ${fmt(ys[ys.length - 1], 1)} R au terme de ${points.length} trades`,
  });
  svg.style.width = '100%';
  svg.style.height = 'auto';

  // Grille recessive : 5 lignes horizontales + etiquettes.
  const ticks = 5;
  for (let i = 0; i <= ticks; i++) {
    const v = lo + ((hi - lo) * i) / ticks;
    const y = sy(v);
    svg.appendChild(el('line', { x1: M.l, y1: y, x2: W - M.r, y2: y, class: 'viz-grid' }));
    const lab = el('text', { x: M.l - 8, y: y + 4, class: 'viz-axis', 'text-anchor': 'end' });
    lab.textContent = fmt(v, 1);
    svg.appendChild(lab);
  }
  // Ligne du zero, plus marquee que la grille.
  const zy = sy(0);
  svg.appendChild(el('line', { x1: M.l, y1: zy, x2: W - M.r, y2: zy, class: 'viz-zero' }));

  // Etiquettes d'annees, posees aux FRONTIERES d'annee (1er janvier) et non
  // au premier trade de l'annee : les trades se regroupent dans le temps, et
  // les etiquettes se chevauchaient (« 20245 »). Un espacement minimum est
  // impose, les etiquettes trop proches sont abandonnees plutot qu'empilees.
  const MIN_GAP = 46;
  const yA = new Date(x0).getUTCFullYear();
  const yB = new Date(x1).getUTCFullYear();
  const candidates = [];
  for (let y = yA; y <= yB; y++) {
    const ts = Date.UTC(y, 0, 1);
    if (ts >= x0 && ts <= x1) candidates.push({ year: y, ts });
  }
  // Periode courte sans 1er janvier : on borne par les extremes.
  if (candidates.length < 2) {
    candidates.length = 0;
    candidates.push({ year: yA, ts: x0 }, { year: yB, ts: x1 });
  }
  let lastX = -Infinity;
  for (const c of candidates) {
    const x = sx(c.ts);
    if (x - lastX < MIN_GAP || x > W - M.r - 12) continue;
    lastX = x;
    svg.appendChild(el('line', { x1: x, y1: M.t + ih, x2: x, y2: M.t + ih + 4, class: 'viz-grid' }));
    const lab = el('text', { x, y: H - 10, class: 'viz-axis', 'text-anchor': 'middle' });
    lab.textContent = String(c.year);
    svg.appendChild(lab);
  }

  // Trace en escalier : le capital ne bouge qu'a la cloture d'un trade.
  let d = `M ${sx(points[0].ts)} ${sy(0)}`;
  for (const p of points) d += ` L ${sx(p.ts)} ${sy(p.cum - p.r)} L ${sx(p.ts)} ${sy(p.cum)}`;
  svg.appendChild(el('path', { d, class: 'viz-line' }));

  // Couche de survol : curseur + infobulle.
  const tip = tooltip();
  const cross = el('line', { class: 'viz-cross', y1: M.t, y2: M.t + ih, style: 'display:none' });
  const dot = el('circle', { r: 5, class: 'viz-dot', style: 'display:none' });
  svg.appendChild(cross);
  svg.appendChild(dot);

  const hit = el('rect', { x: M.l, y: M.t, width: iw, height: ih, fill: 'transparent', style: 'cursor:crosshair' });
  svg.appendChild(hit);

  const nearest = (px) => {
    let best = 0;
    let bd = Infinity;
    points.forEach((p, i) => {
      const dd = Math.abs(sx(p.ts) - px);
      if (dd < bd) {
        bd = dd;
        best = i;
      }
    });
    return best;
  };

  const move = (ev) => {
    const box = svg.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * W;
    const p = points[nearest(px)];
    const cx = sx(p.ts);
    const cy = sy(p.cum);
    cross.setAttribute('x1', cx);
    cross.setAttribute('x2', cx);
    cross.style.display = '';
    dot.setAttribute('cx', cx);
    dot.setAttribute('cy', cy);
    dot.style.display = '';
    tip.show(
      `<strong>${p.date}</strong><br>` +
        `${p.dir === 'sell' ? 'Vente' : 'Achat'} &middot; sortie ${p.exitReason}<br>` +
        `resultat <b>${fmt(p.r, 2)} R</b><br>cumul <b>${fmt(p.cum, 1)} R</b>`,
      (cx / W) * box.width + box.left,
      (cy / H) * box.height + box.top
    );
  };
  hit.addEventListener('mousemove', move);
  hit.addEventListener('touchmove', (e) => {
    if (e.touches[0]) move(e.touches[0]);
  });
  const leave = () => {
    cross.style.display = 'none';
    dot.style.display = 'none';
    tip.hide();
  };
  hit.addEventListener('mouseleave', leave);
  hit.addEventListener('touchend', leave);

  host.appendChild(svg);
}

/**
 * Entonnoir de selection : barres horizontales, rampe ordinale.
 * @param {HTMLElement} host
 * @param {Array<{label:string, value:number, note?:string}>} stages
 */
export function funnel(host, stages) {
  host.innerHTML = '';
  const max = Math.max(1, ...stages.map((s) => s.value));
  const tip = tooltip();
  const wrap = document.createElement('div');
  wrap.className = 'funnel';

  stages.forEach((s, i) => {
    const prev = i > 0 ? stages[i - 1].value : s.value;
    const conv = prev ? (s.value / prev) * 100 : 100;
    const row = document.createElement('div');
    row.className = 'funnel-row';
    row.tabIndex = 0;
    row.innerHTML =
      `<span class="funnel-label">${s.label}</span>` +
      `<span class="funnel-track"><span class="funnel-bar" style="width:${Math.max(0.4, (s.value / max) * 100)}%;background:${ORDINAL[Math.min(i, ORDINAL.length - 1)]}"></span></span>` +
      `<span class="funnel-value">${s.value}</span>` +
      `<span class="funnel-conv">${i === 0 ? '' : fmt(conv, 0) + '&nbsp;%'}</span>`;

    const show = (ev) => {
      const r = row.getBoundingClientRect();
      tip.show(
        `<strong>${s.label}</strong><br>${s.value}` +
          (i > 0 ? `<br>conversion depuis l'etape precedente : <b>${fmt(conv, 0)} %</b>` : '') +
          (s.note ? `<br><span class="tip-note">${s.note}</span>` : ''),
        ev.clientX || r.left + r.width / 2,
        r.top + r.height / 2
      );
    };
    row.addEventListener('mousemove', show);
    row.addEventListener('focus', show);
    row.addEventListener('mouseleave', tip.hide);
    row.addEventListener('blur', tip.hide);
    wrap.appendChild(row);
  });
  host.appendChild(wrap);
}

/**
 * Resultat par annee : barres verticales, paire divergente (polarite).
 * @param {HTMLElement} host
 * @param {Array<{year:string, r:number, trades:number, winRate:number}>} rows
 */
export function yearBars(host, rows) {
  host.innerHTML = '';
  if (!rows.length) {
    host.innerHTML = '<p class="empty">Aucun trade a ventiler.</p>';
    return;
  }
  const W = 880;
  const H = 240;
  const M = { t: 26, r: 16, b: 46, l: 52 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;
  const vals = rows.map((r) => r.r);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const pad = (hi - lo) * 0.14 || 1;
  const y0 = lo - pad;
  const y1 = hi + pad;
  const sy = (v) => M.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;

  const gap = 2; // ecart de surface entre barres adjacentes
  const slot = iw / rows.length;
  const bw = Math.max(8, Math.min(72, slot - 14)) - gap;

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Resultat en R par annee' });
  svg.style.width = '100%';
  svg.style.height = 'auto';

  for (let i = 0; i <= 4; i++) {
    const v = y0 + ((y1 - y0) * i) / 4;
    const y = sy(v);
    svg.appendChild(el('line', { x1: M.l, y1: y, x2: W - M.r, y2: y, class: 'viz-grid' }));
    const lab = el('text', { x: M.l - 8, y: y + 4, class: 'viz-axis', 'text-anchor': 'end' });
    lab.textContent = fmt(v, 1);
    svg.appendChild(lab);
  }
  const zy = sy(0);
  svg.appendChild(el('line', { x1: M.l, y1: zy, x2: W - M.r, y2: zy, class: 'viz-zero' }));

  const tip = tooltip();
  rows.forEach((r, i) => {
    const cx = M.l + slot * i + slot / 2;
    const top = r.r >= 0 ? sy(r.r) : zy;
    const h = Math.max(2, Math.abs(sy(r.r) - zy));
    // Extremite arrondie de 4px cote donnee, ancree a la ligne du zero.
    const rad = Math.min(4, h / 2);
    const bar = el('rect', {
      x: cx - bw / 2,
      y: top,
      width: bw,
      height: h,
      rx: rad,
      class: r.r >= 0 ? 'viz-bar-pos' : 'viz-bar-neg',
      tabindex: '0',
      role: 'graphics-symbol',
      'aria-label': `${r.year} : ${fmt(r.r, 1)} R sur ${r.trades} trade${r.trades > 1 ? 's' : ''}`,
    });
    svg.appendChild(bar);

    // Etiquette directe : peu de barres, donc toutes etiquetees.
    const vl = el('text', {
      x: cx,
      y: r.r >= 0 ? top - 7 : top + h + 15,
      class: 'viz-value',
      'text-anchor': 'middle',
    });
    vl.textContent = fmt(r.r, 1);
    svg.appendChild(vl);

    const xl = el('text', { x: cx, y: H - 24, class: 'viz-axis', 'text-anchor': 'middle' });
    xl.textContent = r.year;
    svg.appendChild(xl);
    const nl = el('text', { x: cx, y: H - 9, class: 'viz-axis-sub', 'text-anchor': 'middle' });
    nl.textContent = `${r.trades} tr.`;
    svg.appendChild(nl);

    const show = (ev) => {
      const box = svg.getBoundingClientRect();
      tip.show(
        `<strong>${r.year}</strong><br>resultat <b>${fmt(r.r, 1)} R</b><br>` +
          `${r.trades} trade${r.trades > 1 ? 's' : ''} &middot; reussite ${fmt(r.winRate, 0)} %` +
          (r.trades < 3 ? '<br><span class="tip-note">echantillon trop petit pour conclure</span>' : ''),
        ev.clientX || (cx / W) * box.width + box.left,
        (top / H) * box.height + box.top
      );
    };
    bar.addEventListener('mousemove', show);
    bar.addEventListener('focus', show);
    bar.addEventListener('mouseleave', tip.hide);
    bar.addEventListener('blur', tip.hide);
  });

  host.appendChild(svg);
}
