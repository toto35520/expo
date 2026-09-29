import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/auth";
import { parseTransactionsCsv } from "@/lib/import-tr";
import { getPositions, savePositions } from "@/lib/store";

export const dynamic = "force-dynamic";

/** Remplace les lignes déjà importées de Trade Republic par celles du nouveau fichier. */
export async function POST(req: Request) {
  const denied = await requireAuth();
  if (denied) return denied;
  const text = await req.text();
  if (text.length > 5_000_000) return NextResponse.json({ error: "Fichier trop gros (5 Mo maximum)." }, { status: 400 });
  try {
    const result = parseTransactionsCsv(text);
    const existing = await getPositions();
    const keepTickers = new Map(existing.filter((p) => p.source === "import-tr" && p.ticker).map((p) => [p.id, p.ticker]));
    const imported = result.positions.map((p) => ({ ...p, ticker: keepTickers.get(p.id) ?? p.ticker }));
    await savePositions([...existing.filter((p) => p.source !== "import-tr"), ...imported]);
    return NextResponse.json({ ok: true, ...result, positions: imported.length });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : "Import impossible." }, { status: 400 });
  }
}
