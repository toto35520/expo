import { listRoutes, newId, numOrNull, str } from "@/lib/crud";
import { getWatchlist, saveWatchlist } from "@/lib/store";
import type { Score, WatchItem } from "@/lib/types";

export const dynamic = "force-dynamic";

const CRIT: Array<keyof Score> = ["croissance", "marche", "valo", "solidite", "sortie", "acces"];

export const { POST, DELETE } = listRoutes<WatchItem>(getWatchlist, saveWatchlist, (b) => {
  const name = str(b.name, 120);
  if (!name) return "Donne un nom à la startup.";
  let score: Score | null = null;
  if (b.score && typeof b.score === "object") {
    const s = b.score as Record<string, unknown>;
    const vals = CRIT.map((k) => numOrNull(s[k]));
    if (vals.every((v) => v != null)) {
      score = Object.fromEntries(CRIT.map((k, i) => [k, Math.max(1, Math.min(5, Math.round(vals[i] as number)))])) as unknown as Score;
    }
  }
  const status = b.status === "acces" || b.status === "ipo" ? b.status : "suivre";
  return {
    id: str(b.id, 80) || newId("w"),
    name,
    sector: str(b.sector, 80),
    country: str(b.country, 40),
    status,
    ticker: str(b.ticker, 20).toUpperCase() || null,
    round: str(b.round, 120),
    date: str(b.date, 10),
    val: numOrNull(b.val),
    cur: b.cur === "€" ? "€" : "$",
    arr: numOrNull(b.arr),
    growth: str(b.growth),
    why: str(b.why),
    risks: str(b.risks),
    how: str(b.how),
    src: /^https?:\/\//.test(str(b.src)) ? str(b.src) : "",
    srcl: str(b.srcl, 120),
    next: str(b.next, 120),
    score,
    noScore: b.noScore === true,
    profil: str(b.profil, 60),
    verdict: str(b.verdict, 500),
    updated: new Date().toISOString().slice(0, 10),
  };
});
