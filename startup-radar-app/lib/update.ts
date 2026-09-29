import { describeError, runAdvisor } from "./advisor";
import { getFx, getQuote, resolveIsin } from "./market";
import { getNews } from "./news";
import { summarize } from "./portfolio";
import { getState, pushHistory, savePositions, saveSnapshot } from "./store";
import type { Quote } from "./types";

/**
 * Mise à jour complète : cours, actus, historique du portefeuille,
 * puis recommandations IA si `withAI` est vrai.
 */
export async function runUpdate({ withAI }: { withAI: boolean }) {
  const state = await getState();
  const snapshot = { ...state.snapshot };
  const log: string[] = [];

  // Retrouve le ticker des lignes importées qui n'ont qu'un ISIN.
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

  // Cours
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

  // Actus
  try {
    const names = [...state.watchlist.map((w) => w.name), ...state.positions.map((p) => p.name)];
    const news = await getNews(names);
    if (news.length) snapshot.news = news;
  } catch (e) {
    log.push(`Actus non mises à jour : ${e instanceof Error ? e.message : "erreur"}`);
  }

  snapshot.updatedAt = new Date().toISOString();
  await saveSnapshot(snapshot);

  // Historique de la valeur du portefeuille
  const pf = summarize(state.positions, snapshot.quotes);
  if (state.positions.length) {
    await pushHistory({ date: snapshot.updatedAt.slice(0, 10), value: Math.round(pf.value * 100) / 100, invested: Math.round(pf.invested * 100) / 100 });
  }

  // Recommandations IA
  if (withAI) {
    try {
      const { reco, model } = await runAdvisor({ ...state, snapshot });
      snapshot.reco = reco;
      snapshot.recoAt = new Date().toISOString();
      snapshot.recoError = null;
      snapshot.recoModel = model;
    } catch (e) {
      snapshot.recoError = describeError(e);
      log.push(snapshot.recoError);
    }
    await saveSnapshot(snapshot);
  }

  return { ok: true, symbols: symbols.length, quoteErrors, news: snapshot.news.length, reco: Boolean(snapshot.reco), log };
}
