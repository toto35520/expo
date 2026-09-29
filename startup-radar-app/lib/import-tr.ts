import type { Position } from "./types";

/**
 * Lit un export CSV de transactions (Trade Republic ou autre courtier) et en
 * déduit les lignes détenues : quantité nette et montant investi par titre.
 * Les colonnes sont reconnues par leur nom (français, anglais ou allemand).
 */

const H = {
  date: ["date", "datum", "booking date", "transaction date", "date d'exécution", "execution date"],
  type: ["type", "typ", "transaction type", "opération", "operation", "art", "category", "catégorie"],
  name: ["name", "nom", "titre", "instrument", "security", "wertpapier", "description", "libellé", "asset"],
  isin: ["isin"],
  quantity: ["quantity", "quantité", "shares", "anzahl", "stück", "nombre", "qty", "parts"],
  amount: ["amount", "montant", "total", "betrag", "value", "valeur", "net amount", "montant net"],
  price: ["price", "prix", "kurs", "cours", "unit price"],
};

function splitLine(line: string, sep: string): string[] {
  const out: string[] = [];
  let cur = "";
  let q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (q && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else q = !q;
    } else if (ch === sep && !q) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

function num(s: string | undefined): number | null {
  if (!s) return null;
  let t = s.replace(/[€$£\s ]/g, "");
  if (/,\d{1,6}$/.test(t) && t.includes(".")) t = t.replace(/\./g, "").replace(",", ".");
  else t = t.replace(",", ".");
  const n = parseFloat(t);
  return Number.isFinite(n) ? n : null;
}

function findCol(headers: string[], keys: string[]): number {
  const h = headers.map((x) => x.toLowerCase().replace(/^﻿/, "").trim());
  for (const k of keys) {
    const i = h.findIndex((x) => x === k);
    if (i >= 0) return i;
  }
  for (const k of keys) {
    const i = h.findIndex((x) => x.includes(k));
    if (i >= 0) return i;
  }
  return -1;
}

export interface ImportResult {
  positions: Position[];
  rows: number;
  used: number;
  skipped: number;
  warnings: string[];
}

export function parseTransactionsCsv(text: string): ImportResult {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) throw new Error("Le fichier est vide ou n'a qu'une ligne.");
  const sep = [";", ",", "\t"].map((s) => ({ s, n: lines[0].split(s).length })).sort((a, b) => b.n - a.n)[0].s;
  const headers = splitLine(lines[0], sep);
  const col = Object.fromEntries(Object.entries(H).map(([k, keys]) => [k, findCol(headers, keys)])) as Record<keyof typeof H, number>;
  const warnings: string[] = [];
  if (col.isin < 0 && col.name < 0) throw new Error("Aucune colonne « ISIN » ni « Nom » trouvée. Colonnes lues : " + headers.join(", "));
  if (col.quantity < 0) warnings.push("Pas de colonne quantité : les cours en direct ne pourront pas être calculés, seule la somme investie est reprise.");
  if (col.amount < 0 && col.price < 0) throw new Error("Aucune colonne montant ou prix trouvée. Colonnes lues : " + headers.join(", "));

  const agg = new Map<string, Position>();
  let used = 0;
  let skipped = 0;
  for (const line of lines.slice(1)) {
    const c = splitLine(line, sep);
    const type = (col.type >= 0 ? c[col.type] : "").toLowerCase();
    const isin = col.isin >= 0 ? c[col.isin]?.toUpperCase() : "";
    const name = (col.name >= 0 ? c[col.name] : "") || isin;
    if (!isin && !name) {
      skipped++;
      continue;
    }
    // On ne garde que les achats, ventes et plans d'investissement.
    const isSell = /sell|vente|verkauf|cession/.test(type);
    const isBuy = /buy|achat|kauf|savings|sparplan|plan|invest|souscription/.test(type) || (!type && col.type < 0);
    if (!isSell && !isBuy) {
      skipped++;
      continue;
    }
    let qty = Math.abs(num(col.quantity >= 0 ? c[col.quantity] : undefined) ?? 0);
    let amount = Math.abs(num(col.amount >= 0 ? c[col.amount] : undefined) ?? 0);
    const price = num(col.price >= 0 ? c[col.price] : undefined);
    if (!amount && price && qty) amount = price * qty;
    if (!qty && price && amount) qty = amount / price;
    const key = isin || name.toLowerCase();
    const p =
      agg.get(key) ??
      ({
        id: "tr-" + key.replace(/[^a-z0-9]+/gi, "-").toLowerCase(),
        name,
        kind: "cote",
        isin: isin || null,
        ticker: null,
        quantity: 0,
        invested: 0,
        platform: "Trade Republic",
        source: "import-tr",
      } as Position);
    if (isSell) {
      // La vente réduit la quantité et le coût au prorata.
      const q0 = p.quantity ?? 0;
      const ratio = q0 > 0 ? Math.min(1, qty / q0) : 1;
      p.invested = p.invested * (1 - ratio);
      p.quantity = Math.max(0, q0 - qty);
    } else {
      p.quantity = (p.quantity ?? 0) + qty;
      p.invested += amount;
      const d = col.date >= 0 ? c[col.date] : "";
      if (d && (!p.date || d < p.date)) p.date = d;
    }
    agg.set(key, p);
    used++;
  }
  const positions = [...agg.values()]
    .filter((p) => (p.quantity ?? 0) > 1e-9 || p.invested > 0.5)
    .map((p) => ({ ...p, invested: Math.round(p.invested * 100) / 100, quantity: p.quantity ? Math.round(p.quantity * 1e6) / 1e6 : null }));
  return { positions, rows: lines.length - 1, used, skipped, warnings };
}
