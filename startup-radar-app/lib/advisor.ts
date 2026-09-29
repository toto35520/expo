import Anthropic from "@anthropic-ai/sdk";
import { betaZodOutputFormat } from "@anthropic-ai/sdk/helpers/beta/zod";
import { z } from "zod";
import { summarize } from "./portfolio";
import { ACTION_TYPES, type ActionType, type AppState, type Argument, type Reco, type RecoAction, type SourceRef } from "./types";

export const MODEL = process.env.CLAUDE_MODEL || "claude-opus-5-5";
const FALLBACK_BETA = "server-side-fallback-2026-07-01";

// Les fonctions Vercel sont coupées à 300 s : chaque étape garde une marge.
const RESEARCH_BUDGET_MS = 200_000;
const DECISION_BUDGET_MS = 240_000;

const ArgumentSchema = z.object({
  point: z.string(),
  chiffre: z.string().nullable(),
  source: z.string().nullable(),
});

const RecoSchema = z.object({
  resume: z.string(),
  marche: z.string(),
  actions: z.array(
    z.object({
      type: z.string().describe("Un de : " + ACTION_TYPES.join(", ")),
      cible: z.string(),
      ticker: z.string().nullable(),
      montantEUR: z.number().nullable(),
      enBref: z.string(),
      these: z.string(),
      pour: z.array(ArgumentSchema),
      contre: z.array(ArgumentSchema),
      plan: z.string(),
      horizon: z.string(),
      confiance: z.string().describe("faible, moyenne ou forte"),
      sources: z.array(z.object({ titre: z.string(), url: z.string() })),
    }),
  ),
  alertes: z.array(z.string()),
  verifications: z.array(z.string()),
});

// Prompt système figé (mis en cache) : aucune donnée variable ici.
const SYSTEM = `Tu es l'analyste personnel d'un particulier français qui investit seul, depuis Trade Republic (compte-titres) pour les actions cotées et via des plateformes de crowdequity agréées AMF pour les startups non cotées. Il veut chaque jour savoir quoi acheter, quoi attendre et pourquoi, chiffres à l'appui.

Méthode, inspirée des clubs d'investissement comme Blast : croissance, marché, prix payé par rapport au revenu, solidité (investisseurs, trésorerie, gouvernance), proximité d'une sortie, accessibilité réelle pour lui.

Règles non négociables :
- Réponds en français simple, phrases courtes, sans jargon non expliqué.
- Appuie chaque recommandation sur des faits datés (cours, variation, levée, résultat, actualité) tirés des données fournies ou de tes recherches. Si une donnée manque, dis-le au lieu d'inventer.
- Chaque argument cite sa source : uniquement des liens réellement présents dans la veille ou les données fournies, jamais un lien inventé ou reconstruit.
- Donne toujours les arguments contre, pas seulement les arguments pour.
- Respecte son plafond : la part des startups et actions de croissance ne doit pas dépasser le pourcentage maximum de son patrimoine indiqué dans les réglages. Si le patrimoine n'est pas renseigné, rappelle-le dans les vérifications et reste prudent.
- Ne propose jamais d'investir plus que l'argent disponible indiqué. Étale les achats (plusieurs fois dans le temps) plutôt que tout d'un coup.
- Diversification : jamais plus de 25 % du budget startups sur une seule ligne.
- Introductions en bourse : attendre au moins 30 jours après la cotation avant d'acheter, sauf argument chiffré très fort.
- Il n'y a aucune obligation d'agir : « ATTENDRE » est une bonne réponse quand rien ne justifie un achat.
- Conflit d'intérêts : tu es Claude, développé par Anthropic. Pour Anthropic, ne donne jamais de recommandation d'achat, de vente ou de montant : uniquement des faits neutres (type SURVEILLER), en rappelant ce conflit.
- Termine par les vérifications qu'il doit faire lui-même avant d'agir (frais, disponibilité dans l'appli Trade Republic, document d'information).
- Ce n'est pas un conseil en investissement réglementé : ne promets jamais de gain.`;

function buildContext(state: AppState): string {
  const { settings, snapshot, watchlist, events, dossiers } = state;
  const pf = summarize(state.positions, snapshot.quotes);
  const today = new Date().toISOString().slice(0, 10);
  const in90 = new Date(Date.now() + 90 * 864e5).toISOString().slice(0, 10);
  const total = (s?: { [k: string]: number } | null) => (s ? Object.values(s).reduce((a, b) => a + b, 0) : null);
  const data = {
    date: today,
    reglages: {
      patrimoineTotalEUR: settings.patrimoine,
      argentDisponibleEUR: settings.cash,
      partMaxStartupsPct: settings.maxStartupPct,
      profilRisque: settings.risque,
      horizon: settings.horizon,
      notes: settings.notes || null,
    },
    portefeuille: {
      valeurEUR: Math.round(pf.value),
      investiEUR: Math.round(pf.invested),
      plusMoinsValuePct: pf.pnlPct != null ? Number(pf.pnlPct.toFixed(1)) : null,
      partDuPatrimoinePct: settings.patrimoine ? Number(((pf.value / settings.patrimoine) * 100).toFixed(1)) : null,
      lignes: pf.valued.map((p) => ({
        nom: p.name,
        ticker: p.ticker ?? null,
        type: p.kind,
        quantite: p.quantity ?? null,
        investiEUR: Math.round(p.invested),
        valeurEUR: Math.round(p.value),
        plusMoinsValuePct: p.pnlPct != null ? Number(p.pnlPct.toFixed(1)) : null,
        variation1jPct: p.quote?.change1d != null ? Number(p.quote.change1d.toFixed(2)) : null,
        variation1moisPct: p.quote?.change1m != null ? Number(p.quote.change1m.toFixed(1)) : null,
        notes: p.notes || null,
      })),
    },
    radar: watchlist.map((w) => {
      const q = w.ticker ? snapshot.quotes[w.ticker] : undefined;
      return {
        nom: w.name,
        secteur: w.sector,
        statut: w.status,
        ticker: w.ticker ?? null,
        cours: q ? `${q.price} ${q.currency}` : null,
        variation1jPct: q?.change1d != null ? Number(q.change1d.toFixed(2)) : null,
        variation1moisPct: q?.change1m != null ? Number(q.change1m.toFixed(1)) : null,
        valorisationMd: w.val ?? null,
        revenuRecurrentMd: w.arr ?? null,
        noteSur30: w.noScore ? null : total(w.score as unknown as Record<string, number> | null),
        chiffres: w.growth || null,
        verdictPrecedent: w.verdict || null,
        prochainEvenement: w.next || null,
      };
    }),
    evenementsAVenir: events.filter((e) => e.date >= today && e.date <= in90),
    actusCitantTesStartups: snapshot.news
      .filter((n) => n.matches.length)
      .slice(0, 15)
      .map((n) => ({ date: n.date.slice(0, 10), titre: n.title, lien: n.link, cite: n.matches })),
    dernieresActus: snapshot.news.slice(0, 15).map((n) => ({ date: n.date.slice(0, 10), titre: n.title, source: n.source })),
    dossiersCrowdequityEnCours: dossiers
      .filter((d) => d.decision === "À creuser")
      .map((d) => ({ nom: d.name, plateforme: d.platform, verifie: Object.values(d.checks).filter(Boolean).length + "/8" })),
  };
  return JSON.stringify(data, null, 1);
}

function textOf(content: Anthropic.Beta.BetaContentBlock[]): string {
  return content
    .filter((b): b is Anthropic.Beta.BetaTextBlock => b.type === "text")
    .map((b) => b.text)
    .join("\n")
    .trim();
}

function sourcesOf(content: Anthropic.Beta.BetaContentBlock[]): SourceRef[] {
  const out: SourceRef[] = [];
  for (const b of content) {
    if (b.type === "web_search_tool_result" && Array.isArray(b.content)) {
      for (const r of b.content) if (r.type === "web_search_result") out.push({ titre: r.title, url: r.url });
    }
  }
  return out;
}

function client() {
  if (!process.env.ANTHROPIC_API_KEY) throw new Error("ANTHROPIC_API_KEY n'est pas configurée dans Vercel.");
  return new Anthropic({ maxRetries: 1 });
}

/** Étape 1 : veille web du jour sur ses lignes et son radar (moins de 200 s). */
export async function runResearch(state: AppState): Promise<{ note: string; sources: SourceRef[] }> {
  const c = client();
  const context = buildContext(state);
  const signal = AbortSignal.timeout(RESEARCH_BUDGET_MS);
  const messages: Anthropic.Beta.BetaMessageParam[] = [
    {
      role: "user",
      content: `Voici ses données du jour (JSON) :\n${context}\n\nFais la veille du jour avant toute recommandation. Cherche sur le web les nouvelles des 7 derniers jours pour : ses lignes en portefeuille, les sociétés cotées de son radar, les introductions en bourse prévues, et les 2 ou 3 startups du radar les mieux notées. Ensuite rédige une note de veille en français : un paragraphe par société, avec les chiffres datés (cours, variation, levée, chiffre d'affaires, analystes) et le lien de la source après chaque fait.`,
    },
  ];
  const sources: SourceRef[] = [];
  let note = "";
  for (let i = 0; i < 4; i++) {
    const msg = await c.beta.messages
      .stream(
        {
          model: MODEL,
          max_tokens: 16000,
          betas: [FALLBACK_BETA],
          fallbacks: "default",
          system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
          thinking: { type: "adaptive" },
          output_config: { effort: "medium" },
          tools: [{ type: "web_search_20260209", name: "web_search", max_uses: 6 }],
          messages,
        },
        { signal },
      )
      .finalMessage();
    sources.push(...sourcesOf(msg.content));
    note += "\n" + textOf(msg.content);
    if (msg.stop_reason === "refusal") throw new Error("La veille du jour a été refusée par le modèle.");
    if (msg.stop_reason !== "pause_turn") break;
    messages.push({ role: "assistant", content: msg.content });
  }
  const seen = new Set<string>();
  return { note: note.trim(), sources: sources.filter((s) => !seen.has(s.url) && seen.add(s.url)) };
}

const plain = (x: string) => x.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().trim();

function normalizeType(t: string): ActionType {
  const p = plain(t);
  return ACTION_TYPES.find((a) => plain(a) === p) ?? ACTION_TYPES.find((a) => p.startsWith(plain(a).slice(0, 5))) ?? "SURVEILLER";
}

function normalizeConf(c: string): RecoAction["confiance"] {
  const p = plain(c);
  return p.startsWith("FORT") ? "forte" : p.startsWith("FAIBL") ? "faible" : "moyenne";
}

/** Étape 2 : transforme la veille en recommandations argumentées (moins de 240 s). */
export async function runDecision(state: AppState): Promise<Reco> {
  const c = client();
  const context = buildContext(state);
  const r = state.snapshot.research;
  const fresh = r && Date.now() - new Date(r.at).getTime() < 20 * 3600e3;
  const note = fresh ? r.note : "(Pas de veille web récente : appuie-toi seulement sur les données fournies et dis-le.)";
  const sources = fresh ? r.sources : [];
  const res = await c.beta.messages.parse(
    {
      model: MODEL,
      max_tokens: 16000,
      betas: [FALLBACK_BETA],
      fallbacks: "default",
      system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
      output_config: { effort: "medium", format: betaZodOutputFormat(RecoSchema) },
      messages: [
        {
          role: "user",
          content: `Données du jour (JSON) :\n${context}\n\nNote de veille du jour :\n${note}\n\nSources disponibles (les seules que tu peux citer, avec les liens des actus et fiches ci-dessus) :\n${sources
            .slice(0, 60)
            .map((s) => `- ${s.titre} : ${s.url}`)
            .join("\n")}\n\nDonne tes recommandations du jour, en français simple :\n- resume : 2 ou 3 phrases, ce qu'il doit retenir aujourd'hui.\n- marche : l'ambiance du marché tech et startups, avec 1 ou 2 chiffres datés.\n- actions : 3 à 5 actions, la plus importante d'abord. Pour chacune : type, cible, ticker Yahoo si cotée, montantEUR si achat (sinon null), enBref (la décision en une phrase), these (le raisonnement en 3 à 6 phrases), pour (3 à 5 arguments : point, chiffre daté, lien source), contre (2 à 4 risques, même format), plan (quand et comment acheter : en combien de fois, à quel niveau de prix, quel événement attendre), horizon, confiance, sources (titre et lien de chaque source utilisée).\n- alertes : ce qui a bougé fortement ou arrive bientôt (IPO, fin de blocage, résultats), avec la date.\n- verifications : ce qu'il doit vérifier lui-même avant d'agir.`,
        },
      ],
    },
    { signal: AbortSignal.timeout(DECISION_BUDGET_MS) },
  );
  if (res.stop_reason === "refusal") throw new Error("Le modèle a refusé de produire les recommandations.");
  const raw = res.parsed_output;
  if (!raw) throw new Error("Réponse du modèle illisible, nouvel essai à la prochaine mise à jour.");
  const reco: Reco = {
    ...raw,
    actions: raw.actions.map((a) => ({ ...a, type: normalizeType(a.type), confiance: normalizeConf(a.confiance) })),
  };
  return enforce(reco, state, sources);
}

/** Garde-fous : liens vérifiés, conflit d'intérêts, budget. */
function enforce(reco: Reco, state: AppState, research: SourceRef[]): Reco {
  const known = new Map<string, string>();
  for (const s of research) known.set(s.url, s.titre);
  for (const n of state.snapshot.news) known.set(n.link, n.title);
  for (const w of state.watchlist) if (w.src) known.set(w.src, w.srcl || w.name);
  const norm = (u: string) => u.replace(/[#?].*$/, "").replace(/\/$/, "");
  const knownNorm = new Map([...known].map(([u, t]) => [norm(u), { u, t }]));
  const check = (u: string | null) => (u && knownNorm.has(norm(u)) ? knownNorm.get(norm(u))!.u : null);
  const fixArgs = (list: Argument[]) => list.map((x) => ({ ...x, source: check(x.source) }));

  const alertes = [...reco.alertes];
  const actions = reco.actions.map((a) => {
    const sources = a.sources.filter((s) => check(s.url)).map((s) => ({ titre: s.titre || knownNorm.get(norm(s.url))!.t, url: check(s.url)! }));
    let out: RecoAction = { ...a, pour: fixArgs(a.pour), contre: fixArgs(a.contre), sources };
    if (/anthropic/i.test(a.cible) && a.type !== "SURVEILLER" && a.type !== "ATTENDRE") {
      out = {
        ...out,
        type: "SURVEILLER",
        montantEUR: null,
        enBref: "À suivre sans recommandation : l'IA de cette app est développée par Anthropic (conflit d'intérêts).",
      };
    }
    return out;
  });
  const buys = actions
    .filter((a) => (a.type === "ACHETER" || a.type === "RENFORCER") && a.montantEUR)
    .reduce((s, a) => s + (a.montantEUR ?? 0), 0);
  const cash = state.settings.cash;
  if (cash != null && buys > cash) {
    alertes.unshift(`Les achats proposés (${Math.round(buys)} €) dépassent ton argent disponible (${Math.round(cash)} €) : réduis-les ou étale-les.`);
  }
  return { ...reco, actions, alertes };
}

export function describeError(e: unknown): string {
  if (e instanceof Anthropic.AuthenticationError) return "Clé API Anthropic invalide : vérifie ANTHROPIC_API_KEY dans Vercel.";
  if (e instanceof Anthropic.RateLimitError) return "Limite de l'API Anthropic atteinte, nouvel essai à la prochaine mise à jour.";
  if (e instanceof Anthropic.APIUserAbortError) return "Étape trop longue, arrêtée avant la limite de Vercel. Nouvel essai à la prochaine mise à jour.";
  if (e instanceof Anthropic.BadRequestError) return `Requête refusée par l'API Anthropic : ${e.message}`;
  if (e instanceof Anthropic.APIError) return `Erreur de l'API Anthropic (${e.status ?? "réseau"}) : ${e.message}`;
  if (e instanceof Error && e.name === "TimeoutError") return "Étape trop longue, arrêtée avant la limite de Vercel.";
  return e instanceof Error ? e.message : "Erreur inconnue";
}
