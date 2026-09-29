import { fetchWithTimeout } from "./market";
import type { NewsItem } from "./types";

// Flux RSS publics : levées de fonds US et France, actualité startups.
export const FEEDS: Array<{ name: string; url: string }> = [
  { name: "Crunchbase News", url: "https://news.crunchbase.com/feed/" },
  { name: "Maddyness", url: "https://www.maddyness.com/feed/" },
  { name: "FrenchWeb", url: "https://www.frenchweb.fr/feed" },
  { name: "TechCrunch Startups", url: "https://techcrunch.com/category/startups/feed/" },
];

function decode(s: string): string {
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;|&rsquo;|&#8217;/g, "’")
    .replace(/&#8211;|&ndash;/g, "–")
    .replace(/&#8230;|&hellip;/g, "…")
    .replace(/&nbsp;|&#160;/g, " ")
    .trim();
}

function tag(xml: string, name: string): string {
  const m = xml.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`, "i"));
  return m ? decode(m[1]) : "";
}

async function readFeed(feed: { name: string; url: string }): Promise<NewsItem[]> {
  const r = await fetchWithTimeout(feed.url, 8000);
  if (!r.ok) return [];
  const xml = await r.text();
  const items = xml.match(/<item[\s>][\s\S]*?<\/item>/gi) ?? [];
  return items.slice(0, 25).map((it) => {
    const d = new Date(tag(it, "pubDate") || tag(it, "dc:date"));
    return {
      title: tag(it, "title"),
      link: tag(it, "link"),
      date: Number.isNaN(d.getTime()) ? new Date().toISOString() : d.toISOString(),
      source: feed.name,
      matches: [],
    };
  });
}

/** Récupère les dernières actus et marque celles qui citent tes startups. */
export async function getNews(names: string[]): Promise<NewsItem[]> {
  const results = await Promise.allSettled(FEEDS.map(readFeed));
  const all = results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
  const keys = names
    .map((n) => ({ name: n, key: n.replace(/\(.*?\)/g, "").trim().toLowerCase() }))
    .filter((k) => k.key.length >= 3);
  const seen = new Set<string>();
  const out: NewsItem[] = [];
  for (const n of all) {
    if (!n.title || !n.link || seen.has(n.link)) continue;
    seen.add(n.link);
    const t = n.title.toLowerCase();
    n.matches = keys.filter((k) => new RegExp(`(^|[^a-z])${k.key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z]|$)`).test(t)).map((k) => k.name);
    out.push(n);
  }
  out.sort((a, b) => b.date.localeCompare(a.date));
  return out.slice(0, 80);
}
