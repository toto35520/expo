"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { summarize, type Valued } from "@/lib/portfolio";
import type { AppState, Dossier, HistoryPoint, Position, Quote, RecoAction, RunLog, Score, Settings, WatchItem } from "@/lib/types";

/* ---------- formats ---------- */
const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur2 = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });
const signPct = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${nf.format(v)} %`);
const cls = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "pos" : "neg");
const toNum = (v: string) => {
  if (v.trim() === "") return null;
  const n = parseFloat(v.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
};
function ago(iso: string | null): string {
  if (!iso) return "jamais";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 2) return "à l'instant";
  if (m < 60) return `il y a ${m} min`;
  const h = Math.round(m / 60);
  if (h < 36) return `il y a ${h} h`;
  return `le ${new Date(iso).toLocaleDateString("fr-FR")}`;
}
function fmtBig(v: number | null | undefined, cur = "$") {
  if (v == null) return "—";
  if (v < 1) return `${nf.format(v * 1000)} M${cur}`;
  return `${nf.format(v)} Md${cur}`;
}
const STATUS: Record<string, string> = { acces: "Accessible maintenant", ipo: "IPO à surveiller", suivre: "À suivre" };
const CRIT: Array<[keyof Score, string]> = [
  ["croissance", "Croissance"],
  ["marche", "Marché"],
  ["valo", "Prix / valo"],
  ["solidite", "Solidité"],
  ["sortie", "Sortie proche"],
  ["acces", "Accès pour toi"],
];
const scoreTotal = (s?: Score | null) => (s ? CRIT.reduce((t, [k]) => t + (s[k] || 0), 0) : null);

async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  const j = (await r.json().catch(() => ({}))) as T & { error?: string };
  if (!r.ok) throw new Error(j.error || `Erreur ${r.status}`);
  return j;
}

/* ---------- petits graphiques ---------- */
function Spark({ data, w = 90, h = 26 }: { data: number[]; w?: number; h?: number }) {
  if (data.length < 2) return <span className="muted">—</span>;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const x = (i: number) => (i / (data.length - 1)) * (w - 4) + 2;
  const y = (v: number) => h - 3 - ((v - min) / (max - min || 1)) * (h - 6);
  const d = data.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const up = data[data.length - 1] >= data[0];
  const color = up ? "var(--go)" : "var(--bad)";
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" />
      <circle cx={x(data.length - 1)} cy={y(data[data.length - 1])} r="2.2" fill={color} />
    </svg>
  );
}

function HistoryChart({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2)
    return <p className="muted small">La courbe apparaîtra après quelques jours de mises à jour automatiques.</p>;
  const W = 640;
  const H = 180;
  const pad = { l: 56, r: 12, t: 10, b: 24 };
  const vals = points.flatMap((p) => [p.value, p.invested]);
  const min = Math.min(...vals) * 0.98;
  const max = Math.max(...vals) * 1.02;
  const x = (i: number) => pad.l + (i / (points.length - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - min) / (max - min || 1)) * (H - pad.t - pad.b);
  const line = (k: "value" | "invested") => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join("");
  const area = `${line("value")}L${x(points.length - 1)},${H - pad.b}L${x(0)},${H - pad.b}Z`;
  const ticks = [min, (min + max) / 2, max];
  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 420 }} role="img" aria-label="Évolution de la valeur du portefeuille">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--line)" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end">{eur.format(t)}</text>
          </g>
        ))}
        <path d={area} fill="var(--accent-soft)" />
        <path d={line("invested")} fill="none" stroke="var(--muted)" strokeDasharray="4 4" strokeWidth="1.2" />
        <path d={line("value")} fill="none" stroke="var(--accent)" strokeWidth="2" />
        <circle cx={x(points.length - 1)} cy={y(points[points.length - 1].value)} r="3.5" fill="var(--accent)" />
        <text x={pad.l} y={H - 6}>{points[0].date}</text>
        <text x={W - pad.r} y={H - 6} textAnchor="end">{points[points.length - 1].date}</text>
      </svg>
      <p className="small muted">Trait plein : valeur. Pointillés : montant investi.</p>
    </div>
  );
}

/* ---------- application ---------- */
type Tab = "jour" | "pf" | "radar" | "actus" | "dos" | "reglages";
const TABS: Array<[Tab, string]> = [
  ["jour", "Aujourd'hui"],
  ["pf", "Mon portefeuille"],
  ["radar", "Radar"],
  ["actus", "Actus & calendrier"],
  ["dos", "Mes dossiers"],
  ["reglages", "Réglages"],
];

export default function Dashboard({ passwordOn }: { passwordOn: boolean }) {
  const [state, setState] = useState<AppState | null>(null);
  const [tab, setTab] = useState<Tab>("jour");
  const [busy, setBusy] = useState<"" | "cours" | "ia">("");
  const [progress, setProgress] = useState("");
  const [msg, setMsg] = useState<{ text: string; err?: boolean } | null>(null);
  const autoTried = useRef(false);

  const load = useCallback(async () => {
    try {
      setState(await api<AppState>("/api/state"));
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : "Chargement impossible.", err: true });
    }
  }, []);

  const step = useCallback(
    (name: "cours" | "veille" | "decision", trigger: "manuel" | "ouverture") =>
      api<{ ok: boolean; message: string }>(`/api/refresh?step=${name}&trigger=${trigger}`, { method: "POST" }),
    [],
  );

  /** Cours seuls, ou analyse complète (cours → veille web → décision). */
  const refresh = useCallback(
    async (full: boolean, trigger: "manuel" | "ouverture" = "manuel") => {
      setBusy(full ? "ia" : "cours");
      setMsg(null);
      try {
        setProgress(full ? "Étape 1/3 · cours et actus…" : "Mise à jour des cours et des actus…");
        const c = await step("cours", trigger);
        await load();
        if (!full) {
          setMsg({ text: c.ok ? `À jour : ${c.message}.` : c.message, err: !c.ok });
          return;
        }
        setProgress("Étape 2/3 · veille web : l'IA lit les dernières nouvelles de tes lignes et de ton radar (1 à 3 min)…");
        const v = await step("veille", trigger);
        if (!v.ok && trigger === "manuel") setMsg({ text: `Veille web : ${v.message} L'analyse continue avec les données disponibles.`, err: true });
        setProgress("Étape 3/3 · rédaction des recommandations argumentées (1 à 2 min)…");
        const d = await step("decision", trigger);
        await load();
        setMsg(d.ok ? { text: `Analyse du jour prête : ${d.message}.` } : { text: `Analyse : ${d.message}`, err: true });
      } catch (e) {
        setMsg({ text: e instanceof Error ? e.message : "Mise à jour impossible.", err: true });
      } finally {
        setBusy("");
        setProgress("");
      }
    },
    [load, step],
  );

  useEffect(() => {
    try {
      const t = localStorage.getItem("radar.tab") as Tab | null;
      if (t && TABS.some(([k]) => k === t)) setTab(t);
    } catch {}
    load();
  }, [load]);

  // Rattrapage à l'ouverture : si la tâche du matin n'a pas tourné, l'app la lance elle-même.
  useEffect(() => {
    if (!state || busy || autoTried.current) return;
    autoTried.current = true;
    const snap = state.snapshot;
    const recoOld = snap.recoSeed || !snap.recoAt || Date.now() - new Date(snap.recoAt).getTime() > 26 * 3600e3;
    const coursOld = !snap.updatedAt || Date.now() - new Date(snap.updatedAt).getTime() > 6 * 3600e3;
    if (state.aiConfigured && recoOld) refresh(true, "ouverture");
    else if (coursOld) refresh(false, "ouverture");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const pf = useMemo(() => (state ? summarize(state.positions, state.snapshot.quotes) : null), [state]);

  function go(t: Tab) {
    setTab(t);
    try {
      localStorage.setItem("radar.tab", t);
    } catch {}
  }

  if (!state || !pf) {
    return (
      <main className="wrap">
        <h1>Radar Startups</h1>
        <p className="muted">{msg?.text ?? "Chargement de ton espace…"}</p>
      </main>
    );
  }

  const s = state.settings;
  const share = s.patrimoine ? (pf.value / s.patrimoine) * 100 : null;
  const fresh = state.snapshot.recoAt && !state.snapshot.recoSeed && Date.now() - new Date(state.snapshot.recoAt).getTime() < 26 * 3600e3;

  return (
    <main className="wrap">
      <header className="top">
        <div className="stack" style={{ gap: 4 }}>
          <h1>Radar Startups</h1>
          <span className={`status ${fresh ? "ok" : "late"}`}>
            <i />
            {fresh ? `Analyse du jour à jour (${ago(state.snapshot.recoAt)})` : state.snapshot.recoSeed ? "Analyse de départ, en attente de la première analyse automatique" : `Dernière analyse ${ago(state.snapshot.recoAt)}`}
            {" · cours "}{ago(state.snapshot.updatedAt)}
          </span>
        </div>
        <div className="row">
          <button className="btn ghost" disabled={!!busy} onClick={() => refresh(false)}>
            {busy === "cours" ? <span className="spin">↻</span> : "↻"} Cours
          </button>
          <button className="btn" disabled={!!busy || !state.aiConfigured} onClick={() => refresh(true)} title={state.aiConfigured ? "" : "Ajoute ANTHROPIC_API_KEY dans Vercel"}>
            {busy === "ia" ? "Analyse en cours…" : "Relancer l'analyse"}
          </button>
        </div>
      </header>

      {progress && <p className="warn progress" role="status"><span className="spin">↻</span> {progress}</p>}
      {msg && <p className={msg.err ? "warn err" : "warn"} role="status">{msg.text}</p>}
      {state.storage === "memoire" && (
        <p className="warn"><b>Base de données non connectée.</b> Tes données seront perdues au prochain redémarrage : ajoute Upstash Redis dans Vercel (voir le README).</p>
      )}

      <section className="kpis" aria-label="Résumé">
        <div className="kpi">
          <span className="lab">Valeur du portefeuille</span>
          <span className="val">{eur.format(pf.value)}</span>
          <span className="small muted">investi {eur.format(pf.invested)}</span>
        </div>
        <div className="kpi">
          <span className="lab">Plus ou moins-value</span>
          <span className={`val ${cls(pf.pnl)}`}>{pf.pnl >= 0 ? "+" : ""}{eur.format(pf.pnl)}</span>
          <span className={`small ${cls(pf.pnlPct)}`}>{signPct(pf.pnlPct)}</span>
        </div>
        <div className="kpi">
          <span className="lab">Aujourd'hui</span>
          <span className={`val ${cls(pf.day)}`}>{pf.day >= 0 ? "+" : ""}{eur.format(pf.day)}</span>
          <span className="small muted">sur les lignes cotées</span>
        </div>
        <div className="kpi">
          <span className="lab">Argent disponible</span>
          <span className="val">{s.cash != null ? eur.format(s.cash) : "—"}</span>
          <span className={`small ${share != null && share > s.maxStartupPct ? "neg" : "muted"}`}>
            {share != null ? `${nf.format(share)} % du patrimoine investi (max ${s.maxStartupPct} %)` : "renseigne ton patrimoine dans Réglages"}
          </span>
        </div>
      </section>

      <nav className="tabs" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => go(k)}>{l}</button>
        ))}
      </nav>

      {tab === "jour" && <Today state={state} valued={pf.valued} busy={busy} onRun={() => refresh(true)} />}
      {tab === "pf" && <Portfolio state={state} valued={pf.valued} reload={load} setMsg={setMsg} value={pf.value} />}
      {tab === "radar" && <Radar state={state} reload={load} setMsg={setMsg} />}
      {tab === "actus" && <News state={state} />}
      {tab === "dos" && <Dossiers state={state} reload={load} setMsg={setMsg} />}
      {tab === "reglages" && <SettingsTab state={state} reload={load} setMsg={setMsg} passwordOn={passwordOn} />}

      <p className="small muted" style={{ maxWidth: "80ch" }}>
        Ce n'est pas un conseil en investissement. Les analyses sont produites par une IA à partir de données publiques qui peuvent être incomplètes ou fausses. Tu peux perdre tout l'argent investi. Décide toujours toi-même.
      </p>
    </main>
  );
}

type SetMsg = (m: { text: string; err?: boolean } | null) => void;

/* ---------- Aujourd'hui ---------- */
const DAYS = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const host = (u: string) => {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
};

function Linkified({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s)\]]+)/g);
  return (
    <>
      {parts.map((p, i) =>
        /^https?:\/\//.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noopener noreferrer">{host(p)}</a>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function Today({ state, valued, busy, onRun }: { state: AppState; valued: Valued[]; busy: string; onRun: () => void }) {
  const { reco, recoAt, recoError, recoModel, recoSeed, quotes, research, runs } = state.snapshot;
  const movers = Object.values(quotes)
    .filter((q) => q.change1d != null)
    .sort((a, b) => Math.abs(b.change1d ?? 0) - Math.abs(a.change1d ?? 0));
  const nameOf = (q: Quote) =>
    valued.find((p) => p.ticker === q.symbol)?.name ?? state.watchlist.find((w) => w.ticker === q.symbol)?.name ?? q.name ?? q.symbol;
  const buys = reco?.actions.filter((a) => (a.type === "ACHETER" || a.type === "RENFORCER") && a.montantEUR) ?? [];
  const total = buys.reduce((t, a) => t + (a.montantEUR ?? 0), 0);
  const nSources = new Set(reco?.actions.flatMap((a) => a.sources.map((x) => x.url)) ?? []).size;

  return (
    <section className="stack">
      {recoError && !busy && <p className="warn err">La dernière analyse automatique a échoué : {recoError}</p>}

      {reco && (
        <div className="brief">
          <div className="row spread">
            <span className="eyebrow">{DAYS.format(recoAt ? new Date(recoAt) : new Date())} · ton brief</span>
            <span className="small muted">{recoSeed ? "Analyse de départ, faite à la main le 29/09" : `${recoModel} · ${recoAt ? new Date(recoAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : ""}`}</span>
          </div>
          <p className="lead">{reco.resume}</p>
          <p className="small"><b>Marché :</b> {reco.marche}</p>
          <div className="row">
            {buys.length > 0 && <span className="chip strong">{buys.length} achat{buys.length > 1 ? "s" : ""} proposé{buys.length > 1 ? "s" : ""} · {eur.format(total)}</span>}
            <span className="chip">{reco.actions.length} décisions argumentées</span>
            <span className="chip">{nSources} sources vérifiées</span>
            {reco.alertes.length > 0 && <span className="chip warnchip">{reco.alertes.length} alerte{reco.alertes.length > 1 ? "s" : ""}</span>}
          </div>
          {recoSeed && (
            <p className="small muted">
              {state.aiConfigured
                ? "L'analyse automatique remplacera celle-ci dès la première mise à jour du matin, ou tout de suite si tu cliques sur « Relancer l'analyse »."
                : "Pour une analyse automatique chaque matin, ajoute ANTHROPIC_API_KEY dans Vercel."}
            </p>
          )}
        </div>
      )}

      {reco?.actions.map((a, i) => <ActionCard key={i} a={a} rank={i + 1} quote={a.ticker ? quotes[a.ticker] : undefined} />)}

      {reco && (
        <div className="grid2">
          <div className="panel">
            <h3>Alertes et dates à retenir</h3>
            {reco.alertes.length ? <ul className="small list">{reco.alertes.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="small muted">Rien de particulier.</p>}
          </div>
          <div className="panel">
            <h3>À vérifier toi-même avant d'agir</h3>
            <ul className="small list">{reco.verifications.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </div>
        </div>
      )}

      {research && (
        <details className="panel">
          <summary><h3 style={{ display: "inline" }}>La veille complète du jour</h3> <span className="small muted">· {research.sources.length} sources lues {ago(research.at)}</span></summary>
          <div className="note"><Linkified text={research.note} /></div>
          {research.sources.length > 0 && (
            <ul className="small list">
              {research.sources.map((x) => <li key={x.url}><a href={x.url} target="_blank" rel="noopener noreferrer">{x.titre || host(x.url)}</a> <span className="muted">{host(x.url)}</span></li>)}
            </ul>
          )}
        </details>
      )}

      <div className="panel">
        <h3>Ce qui a bougé depuis hier</h3>
        {movers.length ? (
          <div className="tablebox" style={{ border: 0 }}>
            <table style={{ minWidth: 520 }}>
              <thead><tr><th>Titre</th><th className="n">Cours</th><th className="n">1 jour</th><th className="n">1 mois</th><th>3 mois</th></tr></thead>
              <tbody>
                {movers.map((q) => (
                  <tr key={q.symbol}>
                    <td><span className="nm">{nameOf(q)}</span> <span className="small muted mono">{q.symbol}</span></td>
                    <td className="n">{nf2.format(q.price)} {q.currency === "GBp" ? "p" : q.currency}</td>
                    <td className={`n ${cls(q.change1d)}`}>{signPct(q.change1d)}</td>
                    <td className={`n ${cls(q.change1m)}`}>{signPct(q.change1m)}</td>
                    <td><Spark data={q.closes} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="small muted">Les cours apparaîtront après la première mise à jour.</p>
        )}
      </div>

      <Health state={state} runs={runs ?? []} busy={busy} onRun={onRun} />
    </section>
  );
}

const CONF = { faible: 1, moyenne: 2, forte: 3 } as const;

function ActionCard({ a, rank, quote }: { a: RecoAction; rank: number; quote?: Quote }) {
  return (
    <article className={`card action ${a.type}`}>
      <div className="row spread">
        <div className="row">
          <span className="rank mono">{rank}</span>
          <span className={`pill ${a.type}`}>{a.type}</span>
          <h3 style={{ fontSize: "1.15rem" }}>{a.cible}</h3>
          {a.ticker && <span className="small muted mono">{a.ticker}</span>}
        </div>
        {a.montantEUR != null && <span className="amount">{eur.format(a.montantEUR)}</span>}
      </div>
      {quote && (
        <div className="row small">
          <span className="mono">{nf2.format(quote.price)} {quote.currency === "GBp" ? "p" : quote.currency}</span>
          <span className={`mono ${cls(quote.change1d)}`}>{signPct(quote.change1d)} sur 1 jour</span>
          <span className={`mono ${cls(quote.change1m)}`}>{signPct(quote.change1m)} sur 1 mois</span>
          <Spark data={quote.closes} w={120} h={28} />
        </div>
      )}
      <p className="enbref">{a.enBref}</p>
      <p>{a.these}</p>
      <div className="grid2">
        <div className="stack" style={{ gap: 6 }}>
          <span className="lab pos">Pourquoi</span>
          <ul className="args">
            {a.pour.map((x, i) => (
              <li key={i} className="yes">
                {x.point}
                {x.chiffre && <> : <b>{x.chiffre}</b></>}
                {x.source && <> <a className="src" href={x.source} target="_blank" rel="noopener noreferrer">{host(x.source)}</a></>}
              </li>
            ))}
          </ul>
        </div>
        <div className="stack" style={{ gap: 6 }}>
          <span className="lab neg">Ce qui peut mal tourner</span>
          <ul className="args">
            {a.contre.map((x, i) => (
              <li key={i} className="no">
                {x.point}
                {x.chiffre && <> : <b>{x.chiffre}</b></>}
                {x.source && <> <a className="src" href={x.source} target="_blank" rel="noopener noreferrer">{host(x.source)}</a></>}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="plan"><span className="lab">Plan</span><p>{a.plan}</p></div>
      <div className="row spread small">
        <span className="row">
          <span className="muted">Horizon : <b>{a.horizon}</b></span>
          <span className="conf" aria-label={`Confiance ${a.confiance}`}>
            Confiance
            {[1, 2, 3].map((n) => <i key={n} className={n <= CONF[a.confiance] ? "on" : ""} />)}
            {a.confiance}
          </span>
        </span>
        <span className="row">{a.sources.map((x) => <a key={x.url} className="src" href={x.url} target="_blank" rel="noopener noreferrer" title={x.titre}>{host(x.url)}</a>)}</span>
      </div>
    </article>
  );
}

const STEP_LABEL = { cours: "Cours et actus", veille: "Veille web", decision: "Recommandations" } as const;
const TRIGGER_LABEL = { auto: "automatique", manuel: "à la main", ouverture: "rattrapage à l'ouverture" } as const;

function Health({ state, runs, busy, onRun }: { state: AppState; runs: RunLog[]; busy: string; onRun: () => void }) {
  const last = (st: RunLog["step"]) => runs.find((r) => r.step === st);
  const lastAuto = runs.find((r) => r.trigger === "auto");
  const problems: string[] = [];
  if (!state.aiConfigured) problems.push("ANTHROPIC_API_KEY manquante : pas d'analyse IA.");
  if (state.storage === "memoire") problems.push("Base Upstash non connectée : rien n'est sauvegardé entre deux mises à jour.");
  if (!lastAuto) problems.push("Aucune mise à jour automatique reçue de Vercel pour l'instant. Vérifie Settings → Cron Jobs dans ton projet Vercel (les tâches tournent entre 5 h et 7 h, heure de Paris).");
  return (
    <details className="panel" open={problems.length > 0}>
      <summary><h3 style={{ display: "inline" }}>Mises à jour automatiques</h3> <span className={`small ${problems.length ? "neg" : "pos"}`}>· {problems.length ? `${problems.length} point${problems.length > 1 ? "s" : ""} à régler` : "tout fonctionne"}</span></summary>
      {problems.length > 0 && <ul className="small list neg">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <div className="tablebox" style={{ border: 0 }}>
        <table style={{ minWidth: 480 }}>
          <thead><tr><th>Étape</th><th>Dernier passage</th><th>Résultat</th></tr></thead>
          <tbody>
            {(["cours", "veille", "decision"] as const).map((st) => {
              const r = last(st);
              return (
                <tr key={st}>
                  <td className="nm">{STEP_LABEL[st]}</td>
                  <td className="small">{r ? `${new Date(r.at).toLocaleString("fr-FR")} · ${TRIGGER_LABEL[r.trigger]} · ${r.seconds} s` : "jamais"}</td>
                  <td className={`small ${r ? (r.ok ? "pos" : "neg") : "muted"}`}>{r ? r.message : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted">Chaque matin : cours vers 5 h, veille web vers 6 h, recommandations vers 7 h (heure de Paris), cours à nouveau vers 18 h. Si une tâche n'a pas tourné, l'app la rattrape quand tu l'ouvres.</p>
      {state.aiConfigured && <div><button className="btn ghost" disabled={!!busy} onClick={onRun}>Lancer l'analyse complète maintenant</button></div>}
    </details>
  );
}

/* ---------- Portefeuille ---------- */
const EMPTY_POS = { id: "", name: "", kind: "cote", ticker: "", isin: "", quantity: "", invested: "", manualValue: "", platform: "Trade Republic", date: "", notes: "" };
type PosForm = typeof EMPTY_POS;
const COLORS = ["var(--accent)", "var(--go)", "var(--watch)", "var(--follow)", "var(--bad)"];

function Portfolio({ state, valued, reload, setMsg, value }: { state: AppState; valued: Valued[]; reload: () => Promise<void>; setMsg: SetMsg; value: number }) {
  const [f, setF] = useState<PosForm>(EMPTY_POS);
  const [saving, setSaving] = useState(false);
  const [armed, setArmed] = useState("");
  const s = state.settings;
  const share = s.patrimoine ? (value / s.patrimoine) * 100 : null;
  const upd = (k: keyof PosForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api("/api/positions", {
        method: "POST",
        body: JSON.stringify({ ...f, quantity: toNum(f.quantity), invested: toNum(f.invested), manualValue: toNum(f.manualValue), source: valued.find((p) => p.id === f.id)?.source }),
      });
      setF(EMPTY_POS);
      await reload();
      setMsg({ text: "Ligne enregistrée. Clique sur « Actualiser les cours » pour son cours en direct." });
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : "Enregistrement impossible.", err: true });
    } finally {
      setSaving(false);
    }
  }
  function edit(p: Position) {
    setF({
      id: p.id, name: p.name, kind: p.kind, ticker: p.ticker ?? "", isin: p.isin ?? "", quantity: p.quantity?.toString() ?? "",
      invested: p.invested.toString(), manualValue: p.manualValue?.toString() ?? "", platform: p.platform ?? "", date: p.date ?? "", notes: p.notes ?? "",
    });
    window.scrollTo({ top: document.getElementById("posform")?.offsetTop ?? 0, behavior: "smooth" });
  }
  async function del(id: string) {
    if (armed !== id) return setArmed(id);
    await api(`/api/positions?id=${encodeURIComponent(id)}`, { method: "DELETE" });
    setArmed("");
    reload();
  }
  async function importCsv(file: File) {
    setMsg({ text: "Import en cours…" });
    try {
      const r = await fetch("/api/import", { method: "POST", body: await file.text() });
      const j = (await r.json()) as { error?: string; positions?: number; used?: number; skipped?: number; warnings?: string[] };
      if (!r.ok) throw new Error(j.error);
      await reload();
      setMsg({ text: `Import terminé : ${j.positions} lignes à partir de ${j.used} transactions (${j.skipped} ignorées).${j.warnings?.length ? " " + j.warnings.join(" ") : ""} Lance « Actualiser les cours » pour retrouver les tickers.` });
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : "Import impossible.", err: true });
    }
  }

  return (
    <section className="stack">
      <div className="grid2">
        <div className="panel">
          <h3>Part de ton patrimoine investie ici</h3>
          <div className="gauge">
            <div className="track">
              <div className={`fill ${share != null && share > s.maxStartupPct ? "over" : ""}`} style={{ width: `${Math.min(100, ((share ?? 0) / (s.maxStartupPct * 2.5)) * 100)}%` }} />
              <div className="limit" style={{ left: "40%" }} />
            </div>
          </div>
          <p className="small muted">
            {share != null ? `${nf.format(share)} % investi, limite fixée à ${s.maxStartupPct} % (le trait noir).` : "Renseigne ton patrimoine total dans Réglages pour activer la jauge."}
          </p>
          {valued.length > 0 && (
            <>
              <div className="alloc" role="img" aria-label="Répartition par ligne">
                {valued.map((p, i) => <span key={p.id} title={`${p.name} : ${eur.format(p.value)}`} style={{ width: `${(p.value / (value || 1)) * 100}%`, background: COLORS[i % COLORS.length] }} />)}
              </div>
              <div className="row small muted">
                {valued.map((p, i) => <span key={p.id}><b style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: COLORS[i % COLORS.length], marginRight: 6 }} />{p.name} {nf.format((p.value / (value || 1)) * 100)} %</span>)}
              </div>
            </>
          )}
        </div>
        <div className="panel">
          <h3>Évolution</h3>
          <HistoryChart points={state.history} />
        </div>
      </div>

      <div className="tablebox">
        <table>
          <thead><tr><th>Ligne</th><th className="n">Quantité</th><th className="n">Cours</th><th className="n">1 jour</th><th className="n">Investi</th><th className="n">Valeur</th><th className="n">+/-</th><th>3 mois</th><th></th></tr></thead>
          <tbody>
            {valued.length === 0 && <tr><td colSpan={9} className="empty">Aucune ligne. Importe ton relevé Trade Republic ou ajoute une ligne ci-dessous.</td></tr>}
            {valued.map((p) => (
              <tr key={p.id}>
                <td>
                  <div className="nm">{p.name}</div>
                  <div className="small muted">{[p.ticker || (p.kind === "cote" ? "ticker manquant" : "non coté"), p.platform].filter(Boolean).join(" · ")}</div>
                </td>
                <td className="n">{p.quantity != null ? nf2.format(p.quantity) : "—"}</td>
                <td className="n">{p.quote ? eur2.format(p.quote.priceEUR) : "—"}</td>
                <td className={`n ${cls(p.quote?.change1d)}`}>{signPct(p.quote?.change1d)}</td>
                <td className="n">{eur.format(p.invested)}</td>
                <td className="n">{eur.format(p.value)}</td>
                <td className={`n ${cls(p.pnl)}`}>{signPct(p.pnlPct)}</td>
                <td>{p.quote ? <Spark data={p.quote.closes} /> : null}</td>
                <td>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <button className="link" onClick={() => edit(p)}>Modifier</button>
                    <button className="link" onClick={() => del(p.id)}>{armed === p.id ? "Confirmer" : "Supprimer"}</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid2">
        <form className="panel" id="posform" onSubmit={save}>
          <h3>{f.id ? `Modifier ${f.name}` : "Ajouter une ligne"}</h3>
          <div className="form">
            <label>Nom<input value={f.name} onChange={upd("name")} required placeholder="SpaceX" /></label>
            <label>Type
              <select value={f.kind} onChange={upd("kind")}><option value="cote">Action cotée</option><option value="non-cote">Startup non cotée</option></select>
            </label>
            <label>Plateforme<input value={f.platform} onChange={upd("platform")} /></label>
            {f.kind === "cote" ? (
              <>
                <label>Ticker Yahoo<input value={f.ticker} onChange={upd("ticker")} placeholder="SPCX, CBRS, SMT.L" /></label>
                <label>Quantité (fractions OK)<input value={f.quantity} onChange={upd("quantity")} inputMode="decimal" placeholder="2,35" /></label>
                <label>ISIN (optionnel)<input value={f.isin} onChange={upd("isin")} /></label>
              </>
            ) : (
              <label>Valeur estimée (€)<input value={f.manualValue} onChange={upd("manualValue")} inputMode="decimal" placeholder="laisser vide = montant investi" /></label>
            )}
            <label>Montant investi (€)<input value={f.invested} onChange={upd("invested")} inputMode="decimal" required placeholder="350" /></label>
            <label>Date<input type="date" value={f.date} onChange={upd("date")} /></label>
            <label className="wide">Notes<input value={f.notes} onChange={upd("notes")} placeholder="Raison de l'achat, réduction d'impôt…" /></label>
          </div>
          <div className="actions">
            {f.id && <button type="button" className="btn ghost" onClick={() => setF(EMPTY_POS)}>Annuler</button>}
            <button className="btn" disabled={saving}>{saving ? "Enregistrement…" : "Enregistrer"}</button>
          </div>
        </form>
        <div className="panel">
          <h3>Importer depuis Trade Republic</h3>
          <p className="small">Trade Republic n'a pas d'API officielle : l'app ne peut pas se connecter à ton compte. Tu exportes tes transactions en CSV, puis tu les déposes ici.</p>
          <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>
            <li>Sur app.traderepublic.com (ordinateur) : Profil → Relevés / Transactions → exporter en CSV. L'emplacement peut changer selon les versions.</li>
            <li>Dépose le fichier ci-dessous. L'app additionne achats et ventes par titre.</li>
            <li>Clique « Actualiser les cours » : les tickers sont retrouvés à partir des ISIN.</li>
          </ol>
          <label className="stack small muted" htmlFor="csv">
            Fichier CSV
            <input id="csv" type="file" accept=".csv,text/csv" onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} />
          </label>
          <p className="small muted">Un nouvel import remplace les lignes importées précédemment. Tes lignes ajoutées à la main restent.</p>
        </div>
      </div>
    </section>
  );
}

/* ---------- Radar ---------- */
function Radar({ state, reload, setMsg }: { state: AppState; reload: () => Promise<void>; setMsg: SetMsg }) {
  const [filter, setFilter] = useState<"all" | "acces" | "ipo" | "suivre">("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [edit, setEdit] = useState<WatchItem | null>(null);
  const quotes = state.snapshot.quotes;
  const rows = state.watchlist
    .filter((w) => filter === "all" || w.status === filter)
    .filter((w) => !q || [w.name, w.sector, w.country].join(" ").toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (scoreTotal(b.score) ?? -1) - (scoreTotal(a.score) ?? -1));

  async function del(id: string) {
    await api(`/api/watchlist?id=${encodeURIComponent(id)}`, { method: "DELETE" });
    setOpen(null);
    reload();
  }

  return (
    <section className="stack">
      {edit && <WatchForm item={edit} onDone={async (saved) => { setEdit(null); if (saved) { await reload(); setMsg({ text: "Fiche enregistrée." }); } }} setMsg={setMsg} />}
      <div className="row spread">
        <div className="row">
          {(["all", "acces", "ipo", "suivre"] as const).map((k) => (
            <button key={k} className={`btn ${filter === k ? "" : "ghost"}`} onClick={() => setFilter(k)}>{k === "all" ? "Toutes" : STATUS[k]}</button>
          ))}
        </div>
        <div className="row">
          <input style={{ width: 200 }} type="search" placeholder="Chercher…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Chercher" />
          <button className="btn" onClick={() => setEdit({ id: "", name: "", sector: "", country: "", status: "suivre", cur: "$" })}>+ Ajouter</button>
        </div>
      </div>
      <div className="tablebox">
        <table>
          <thead><tr><th>Startup</th><th className="n">Note /30</th><th>Statut</th><th>Dernière levée</th><th className="n">Valorisation</th><th className="n">Cours / 1 mois</th></tr></thead>
          <tbody>
            {rows.map((w) => {
              const t = scoreTotal(w.score);
              const qt = w.ticker ? quotes[w.ticker] : undefined;
              return [
                <tr key={w.id} className="click" onClick={() => setOpen(open === w.id ? null : w.id)}>
                  <td><div className="nm">{w.name}</div><div className="small muted">{[w.sector, w.country].filter(Boolean).join(" · ")}</div></td>
                  <td className="n">{t == null ? <span className="muted small">{w.noScore ? "non notée" : "—"}</span> : <span className="score">{t}<span className="mini"><i style={{ width: `${(t / 30) * 100}%` }} /></span></span>}</td>
                  <td><span className={`pill ${w.status}`}>{STATUS[w.status]}</span>{w.next && <div className="small muted">{w.next}</div>}</td>
                  <td>{w.round || "—"}<div className="small muted">{w.date}</div></td>
                  <td className="n">{fmtBig(w.val, w.cur)}</td>
                  <td className="n">{qt ? <>{nf2.format(qt.price)} {qt.currency === "GBp" ? "p" : qt.currency}<div className={`small ${cls(qt.change1m)}`}>{signPct(qt.change1m)}</div></> : "—"}</td>
                </tr>,
                open === w.id && (
                  <tr key={w.id + "-d"} className="detail">
                    <td colSpan={6}>
                      <div className="stack">
                        {(w.verdict || t != null) && (
                          <p><b>Verdict :</b> {w.verdict || "—"} {w.profil && <span className="pill suivre">{w.profil}</span>}</p>
                        )}
                        {w.score && (
                          <div className="row small">{CRIT.map(([k, l]) => <span key={k} className="muted">{l} <b className="mono">{w.score?.[k]}/5</b></span>)}</div>
                        )}
                        <div className="grid2">
                          <div className="stack"><span className="lab">Pourquoi la suivre</span><p>{w.why || "—"}</p>{w.growth && <p className="small muted"><b>Chiffres :</b> {w.growth}</p>}</div>
                          <div className="stack"><span className="lab">Risques</span><p>{w.risks || "—"}</p><span className="lab">Comment y investir</span><p>{w.how || "—"}</p></div>
                        </div>
                        <div className="row spread small">
                          <span className="muted">{w.src ? <>Source : <a href={w.src} target="_blank" rel="noopener noreferrer">{w.srcl || w.src}</a></> : "Pas de source"}{w.updated ? ` · mis à jour ${w.updated}` : ""}</span>
                          <span className="row"><button className="btn ghost" onClick={() => setEdit(w)}>Modifier</button><button className="btn danger" onClick={() => del(w.id)}>Retirer</button></span>
                        </div>
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted">Note sur 30 : croissance, marché, prix, solidité, sortie proche, accès pour toi (chacun de 1 à 5). Clique sur une ligne pour la fiche complète.</p>
    </section>
  );
}

function WatchForm({ item, onDone, setMsg }: { item: WatchItem; onDone: (saved: boolean) => void; setMsg: SetMsg }) {
  const [w, setW] = useState<WatchItem>(item);
  const [sc, setSc] = useState<Record<string, string>>(Object.fromEntries(CRIT.map(([k]) => [k, item.score?.[k]?.toString() ?? ""])));
  const txt = (k: keyof WatchItem) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setW({ ...w, [k]: e.target.value });
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      const score = CRIT.every(([k]) => toNum(sc[k] ?? "") != null) ? Object.fromEntries(CRIT.map(([k]) => [k, toNum(sc[k])])) : null;
      await api("/api/watchlist", { method: "POST", body: JSON.stringify({ ...w, val: typeof w.val === "string" ? toNum(w.val) : w.val, arr: typeof w.arr === "string" ? toNum(w.arr) : w.arr, score }) });
      onDone(true);
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : "Enregistrement impossible.", err: true });
    }
  }
  return (
    <form className="panel" onSubmit={save}>
      <h3>{item.id ? `Modifier ${item.name}` : "Ajouter une startup"}</h3>
      <div className="form">
        <label>Nom<input value={w.name} onChange={txt("name")} required /></label>
        <label>Secteur<input value={w.sector} onChange={txt("sector")} /></label>
        <label>Pays<input value={w.country} onChange={txt("country")} /></label>
        <label>Statut<select value={w.status} onChange={txt("status")}><option value="acces">Accessible maintenant</option><option value="ipo">IPO à surveiller</option><option value="suivre">À suivre</option></select></label>
        <label>Ticker Yahoo (si cotée)<input value={w.ticker ?? ""} onChange={txt("ticker")} /></label>
        <label>Dernière levée<input value={w.round ?? ""} onChange={txt("round")} /></label>
        <label>Date (AAAA-MM)<input value={w.date ?? ""} onChange={txt("date")} /></label>
        <label>Valorisation (Md)<input value={w.val?.toString() ?? ""} onChange={txt("val")} inputMode="decimal" /></label>
        <label>Revenu récurrent (Md)<input value={w.arr?.toString() ?? ""} onChange={txt("arr")} inputMode="decimal" /></label>
        <label className="wide">Chiffres clés<input value={w.growth ?? ""} onChange={txt("growth")} /></label>
        <label className="wide">Pourquoi la suivre<textarea value={w.why ?? ""} onChange={txt("why")} /></label>
        <label className="wide">Risques<textarea value={w.risks ?? ""} onChange={txt("risks")} /></label>
        <label className="wide">Comment y investir<textarea value={w.how ?? ""} onChange={txt("how")} /></label>
        {CRIT.map(([k, l]) => (
          <label key={k}>{l} (1-5)<input type="number" min={1} max={5} value={sc[k] ?? ""} onChange={(e) => setSc({ ...sc, [k]: e.target.value })} /></label>
        ))}
        <label className="wide">Verdict<input value={w.verdict ?? ""} onChange={txt("verdict")} /></label>
        <label>Source (lien)<input type="url" value={w.src ?? ""} onChange={txt("src")} /></label>
        <label>Nom de la source<input value={w.srcl ?? ""} onChange={txt("srcl")} /></label>
        <label>Prochain événement<input value={w.next ?? ""} onChange={txt("next")} /></label>
      </div>
      <div className="actions"><button type="button" className="btn ghost" onClick={() => onDone(false)}>Annuler</button><button className="btn">Enregistrer</button></div>
    </form>
  );
}

/* ---------- Actus ---------- */
function News({ state }: { state: AppState }) {
  const [only, setOnly] = useState(false);
  const today = new Date().toISOString().slice(0, 10);
  const news = state.snapshot.news.filter((n) => !only || n.matches.length);
  const events = [...state.events].sort((a, b) => b.date.localeCompare(a.date));
  return (
    <section className="grid2" style={{ alignItems: "start" }}>
      <div className="panel">
        <div className="row spread">
          <h3>Dernières actus</h3>
          <label className="row small muted"><input type="checkbox" style={{ width: "auto" }} checked={only} onChange={(e) => setOnly(e.target.checked)} /> seulement mes startups</label>
        </div>
        <div className="news">
          {news.length === 0 && <p className="small muted">Aucune actu pour l'instant. Clique sur « Actualiser les cours ».</p>}
          {news.slice(0, 50).map((n) => (
            <a key={n.link} className="item" href={n.link} target="_blank" rel="noopener noreferrer">
              <span className="small muted mono">{n.date.slice(0, 10)}<br />{n.source}</span>
              <span>{n.title}{n.matches.length > 0 && <> <span className="pill acces">{n.matches.join(", ")}</span></>}</span>
            </a>
          ))}
        </div>
      </div>
      <div className="panel">
        <h3>Calendrier</h3>
        <div className="news">
          {events.map((e) => (
            <div key={e.id} className="item" style={{ display: "grid", gridTemplateColumns: "96px minmax(0,1fr)", gap: 12, padding: "10px 4px", borderBottom: "1px solid var(--line)" }}>
              <span className={`small mono ${e.date > today ? "" : "muted"}`} style={e.date > today ? { color: "var(--accent)", fontWeight: 600 } : {}}>{e.date}{e.date > today ? " · à venir" : ""}</span>
              <span className="small"><span className={`pill ${e.type === "IPO" ? "ipo" : e.type === "Levée" ? "acces" : "suivre"}`}>{e.type}</span> <b>{e.who}</b> · {e.what}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- Dossiers ---------- */
const CHECKS: Array<[string, string, string]> = [
  ["ca", "Chiffre d'affaires connu", "Le chiffre d'affaires actuel est donné dans le dossier"],
  ["croissance", "Croissance forte", "Il progresse d'au moins 50 % sur 12 mois"],
  ["tresorerie", "Trésorerie suffisante", "Avec cette levée, l'entreprise tient au moins 18 mois"],
  ["valo", "Prix raisonnable", "Valorisation inférieure à 20 fois le chiffre d'affaires"],
  ["equipe", "Équipe solide", "Fondateurs à temps plein, avec une expérience ou un succès passé"],
  ["fonds", "Investisseur pro présent", "Un fonds ou des business angels reconnus investissent aussi"],
  ["droits", "Mes droits sont clairs", "Pacte lu : type d'actions, qui est payé en premier en cas de vente"],
  ["fiscal", "Éligible IR-PME / JEI", "Réduction d'impôt de 18 % (30 % si JEI) confirmée"],
];

function Dossiers({ state, reload, setMsg }: { state: AppState; reload: () => Promise<void>; setMsg: SetMsg }) {
  const blank = { name: "", platform: "", amount: "", decision: "À creuser" as Dossier["decision"], notes: "", checks: {} as Record<string, boolean> };
  const [f, setF] = useState(blank);
  const [armed, setArmed] = useState("");
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/api/dossiers", { method: "POST", body: JSON.stringify({ ...f, amount: toNum(f.amount) }) });
      setF(blank);
      await reload();
      setMsg({ text: "Dossier enregistré." });
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : "Enregistrement impossible.", err: true });
    }
  }
  async function del(id: string) {
    if (armed !== id) return setArmed(id);
    await api(`/api/dossiers?id=${encodeURIComponent(id)}`, { method: "DELETE" });
    reload();
  }
  const list = [...state.dossiers].sort((a, b) => b.created.localeCompare(a.created));
  return (
    <section className="stack">
      <form className="panel" onSubmit={save}>
        <h3>Analyser un dossier de crowdequity</h3>
        <p className="small muted">Coche seulement ce que tu as vérifié. En dessous de 6 sur 8, passe ton tour.</p>
        <div className="form">
          <label>Startup<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></label>
          <label>Plateforme<input value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value })} placeholder="WiSEED, Tudigo…" /></label>
          <label>Montant envisagé (€)<input value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} inputMode="decimal" /></label>
          <fieldset className="wide checks">
            {CHECKS.map(([k, l, d]) => (
              <label key={k}><input type="checkbox" checked={!!f.checks[k]} onChange={(e) => setF({ ...f, checks: { ...f.checks, [k]: e.target.checked } })} /><span><b>{l}</b><br /><span className="small muted">{d}</span></span></label>
            ))}
          </fieldset>
          <label>Décision<select value={f.decision} onChange={(e) => setF({ ...f, decision: e.target.value as Dossier["decision"] })}><option>À creuser</option><option>Investir</option><option>Refuser</option></select></label>
          <label className="wide">Notes<input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
        </div>
        <div className="actions"><span className="small muted">{Object.values(f.checks).filter(Boolean).length}/8 vérifié</span><button className="btn">Enregistrer</button></div>
      </form>
      <div className="tablebox">
        <table>
          <thead><tr><th>Startup</th><th>Plateforme</th><th className="n">Vérifié</th><th className="n">Montant</th><th>Décision</th><th>Ce qui manque</th><th></th></tr></thead>
          <tbody>
            {list.length === 0 && <tr><td colSpan={7} className="empty">Aucun dossier analysé.</td></tr>}
            {list.map((d) => {
              const ok = CHECKS.filter(([k]) => d.checks[k]).length;
              return (
                <tr key={d.id}>
                  <td className="nm">{d.name}{d.notes && <div className="small muted">{d.notes}</div>}</td>
                  <td>{d.platform}</td>
                  <td className={`n ${ok >= 6 ? "pos" : "neg"}`}>{ok}/8</td>
                  <td className="n">{d.amount != null ? eur.format(d.amount) : "—"}</td>
                  <td><span className={`pill ${d.decision === "Investir" ? "acces" : d.decision === "Refuser" ? "suivre" : "ipo"}`}>{d.decision}</span>{d.decision === "Investir" && ok < 6 && <div className="small neg">moins de 6/8 : risqué</div>}</td>
                  <td className="small muted">{CHECKS.filter(([k]) => !d.checks[k]).map(([, l]) => l).join(", ") || "rien"}</td>
                  <td><button className="link" onClick={() => del(d.id)}>{armed === d.id ? "Confirmer" : "Supprimer"}</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ---------- Réglages ---------- */
function SettingsTab({ state, reload, setMsg, passwordOn }: { state: AppState; reload: () => Promise<void>; setMsg: SetMsg; passwordOn: boolean }) {
  const s = state.settings;
  const [f, setF] = useState({
    patrimoine: s.patrimoine?.toString() ?? "",
    cash: s.cash?.toString() ?? "",
    maxStartupPct: s.maxStartupPct.toString(),
    risque: s.risque,
    horizon: s.horizon,
    notes: s.notes,
  });
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify({ ...f, patrimoine: toNum(f.patrimoine), cash: toNum(f.cash), maxStartupPct: toNum(f.maxStartupPct) }) });
      await reload();
      setMsg({ text: "Réglages enregistrés. Ils seront pris en compte dans la prochaine analyse." });
    } catch (err) {
      setMsg({ text: err instanceof Error ? err.message : "Enregistrement impossible.", err: true });
    }
  }
  async function logout() {
    await fetch("/api/auth", { method: "DELETE" });
    location.reload();
  }
  return (
    <section className="grid2" style={{ alignItems: "start" }}>
      <form className="panel" onSubmit={save}>
        <h3>Ta situation</h3>
        <p className="small muted">L'analyse du jour s'appuie sur ces chiffres pour doser ses recommandations.</p>
        <div className="form" style={{ gridTemplateColumns: "repeat(2, minmax(0,1fr))" }}>
          <label>Patrimoine financier total (€)<input value={f.patrimoine} onChange={(e) => setF({ ...f, patrimoine: e.target.value })} inputMode="decimal" placeholder="épargne + placements" /></label>
          <label>Argent disponible à investir (€)<input value={f.cash} onChange={(e) => setF({ ...f, cash: e.target.value })} inputMode="decimal" /></label>
          <label>Part max en startups et croissance (%)<input value={f.maxStartupPct} onChange={(e) => setF({ ...f, maxStartupPct: e.target.value })} inputMode="decimal" /></label>
          <label>Profil de risque<select value={f.risque} onChange={(e) => setF({ ...f, risque: e.target.value as Settings["risque"] })}><option value="prudent">Prudent</option><option value="equilibre">Équilibré</option><option value="dynamique">Dynamique</option></select></label>
          <label>Horizon<input value={f.horizon} onChange={(e) => setF({ ...f, horizon: e.target.value })} /></label>
          <label className="wide">Préférences (secteurs, choses à éviter…)<textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="J'investis seul, pas de club payant. Pas de crypto." /></label>
        </div>
        <div className="actions"><button className="btn">Enregistrer</button></div>
      </form>
      <div className="stack">
        <div className="panel">
          <h3>État de l'app</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            <li>Base de données : {state.storage === "redis" ? "connectée (Upstash Redis)" : "non connectée, données temporaires"}</li>
            <li>Recommandations IA : {state.aiConfigured ? "activées" : "désactivées (ANTHROPIC_API_KEY manquante)"}</li>
            <li>Mot de passe : {passwordOn ? "activé" : "désactivé : ajoute APP_PASSWORD dans Vercel"}</li>
            <li>Mise à jour automatique : chaque jour vers 7 h (heure de Paris en été)</li>
          </ul>
        </div>
        <div className="panel">
          <h3>Pourquoi pas de connexion directe à Trade Republic ?</h3>
          <p className="small">Trade Republic ne propose pas d'API publique. Les outils non officiels demandent ton numéro et ton code PIN, plus une validation sur ton téléphone à chaque connexion : les stocker sur un serveur mettrait tout ton compte en danger. L'export CSV est plus sûr.</p>
        </div>
        {passwordOn && <div><button className="btn danger" onClick={logout}>Se déconnecter</button></div>}
      </div>
    </section>
  );
}
