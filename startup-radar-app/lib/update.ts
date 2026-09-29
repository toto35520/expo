import { describeError, MODEL, runDecision, runResearch } from "./advisor";
import { getFx, getQuote, resolveIsin } from "./market";
import { getNews } from "./news";
import { summarize } from "./portfolio";
import { getSnapshot, getState, pushHistory, savePositions, saveSnapshot } from "./store";
import type { Quote, RunLog, Snapshot } from "./types";

export type Step = RunLog["step"];
export type Trigger = RunLog["trigger"];

async function logRun(step: Step, trigger: Trigger, ok: boolean, message: string, t0: number) {
  const snap = await getSnapshot();
  const run: RunLog = { at: new Date().toISOString(), step, trigger, ok, message, seconds: Math.round((Date.now() - t0) / 1000) };
  snap.runs = [run, ...(snap.runs ?? [])].slice(0, 40);
  await saveSnapshot(snap);
}

/** Étape « cours » : cours, taux de change, actus, historique. Quelques secondes. */
export async function runMarket(trigger: Trigger) {
  const t0 = Date.now();
  const state = await getState();
  const snapshot: Snapshot = { ...state.snapshot };
  const log: string[] = [];

  let changed = false;
  for (const p of state.positions) {
    if (p.kind === "cote" && !p.ticker && p.isin) {
      const t = await resolveIsin(p.isin);
      if (t) {
        p.ticker = t;
        changed = true;
        log.push(`Ticker trouvé pour ${p.name} : ${t}`);
      }
    }
  }
  if (changed) await savePositions(state.positions);

  const symbols = [
    ...new Set(
      [...state.positions.filter((p) => p.kind === "cote").map((p) => p.ticker), ...state.watchlist.map((w) => w.ticker)].filter(
        (s): s is string => Boolean(s),
      ),
    ),
  ];
  const quoteErrors: string[] = [];
  try {
    const fx = await getFx();
    snapshot.fx = fx;
    const results = await Promise.allSettled(symbols.map((s) => getQuote(s, fx)));
    const quotes: Record<string, Quote> = {};
    results.forEach((r, i) => {
      if (r.status === "fulfilled") quotes[symbols[i]] = r.value;
      else {
        quoteErrors.push(symbols[i]);
        if (snapshot.quotes[symbols[i]]) quotes[symbols[i]] = snapshot.quotes[symbols[i]];
      }
    });
    snapshot.quotes = quotes;
  } catch (e) {
    quoteErrors.push("change");
    log.push(`Cours non mis à jour : ${e instanceof Error ? e.message : "erreur"}`);
  }
  snapshot.quoteErrors = quoteErrors;

  try {
    const news = await getNews([...state.watchlist.map((w) => w.name), ...state.positions.map((p) => p.name)]);
    if (news.length) snapshot.news = news;
    else log.push("Aucune actu reçue des flux.");
  } catch (e) {
    log.push(`Actus non mises à jour : ${e instanceof Error ? e.message : "erreur"}`);
  }

  snapshot.updatedAt = new Date().toISOString();
  await saveSnapshot({ ...(await getSnapshot()), quotes: snapshot.quotes, fx: snapshot.fx, quoteErrors, news: snapshot.news, updatedAt: snapshot.updatedAt });

  const pf = summarize(state.positions, snapshot.quotes);
  if (state.positions.length) {
    await pushHistory({ date: snapshot.updatedAt.slice(0, 10), value: Math.round(pf.value * 100) / 100, invested: Math.round(pf.invested * 100) / 100 });
  }
  const ok = quoteErrors.length < symbols.length || symbols.length === 0;
  const msg = `${symbols.length - quoteErrors.length}/${symbols.length} cours, ${snapshot.news.length} actus` + (log.length ? ` · ${log.join(" · ")}` : "");
  await logRun("cours", trigger, ok, msg, t0);
  return { ok, quoteErrors, message: msg };
}

/** Étape « veille » : recherche web du jour avec Claude. Moins de 200 s. */
export async function runResearchStep(trigger: Trigger) {
  const t0 = Date.now();
  const state = await getState();
  try {
    const { note, sources } = await runResearch(state);
    const snap = await getSnapshot();
    snap.research = { note, sources, at: new Date().toISOString() };
    await saveSnapshot(snap);
    const msg = `${sources.length} sources consultées`;
    await logRun("veille", trigger, true, msg, t0);
    return { ok: true, message: msg };
  } catch (e) {
    const msg = describeError(e);
    await logRun("veille", trigger, false, msg, t0);
    return { ok: false, message: msg };
  }
}

/** Étape « décision » : recommandations argumentées. Moins de 240 s. */
export async function runDecisionStep(trigger: Trigger) {
  const t0 = Date.now();
  const state = await getState();
  try {
    const reco = await runDecision(state);
    const snap = await getSnapshot();
    Object.assign(snap, { reco, recoAt: new Date().toISOString(), recoError: null, recoModel: MODEL, recoSeed: false });
    await saveSnapshot(snap);
    const msg = `${reco.actions.length} recommandations`;
    await logRun("decision", trigger, true, msg, t0);
    return { ok: true, message: msg };
  } catch (e) {
    const msg = describeError(e);
    const snap = await getSnapshot();
    snap.recoError = msg;
    await saveSnapshot(snap);
    await logRun("decision", trigger, false, msg, t0);
    return { ok: false, message: msg };
  }
}
