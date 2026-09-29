import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/auth";
import { numOrNull, str } from "@/lib/crud";
import { getSettings, saveSettings } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const denied = await requireAuth();
  if (denied) return denied;
  const b = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const cur = await getSettings();
  const pct = numOrNull(b.maxStartupPct);
  const next = {
    patrimoine: "patrimoine" in b ? numOrNull(b.patrimoine) : cur.patrimoine,
    cash: "cash" in b ? numOrNull(b.cash) : cur.cash,
    maxStartupPct: pct != null ? Math.max(1, Math.min(50, pct)) : cur.maxStartupPct,
    risque: b.risque === "prudent" || b.risque === "equilibre" || b.risque === "dynamique" ? b.risque : cur.risque,
    horizon: "horizon" in b ? str(b.horizon, 60) : cur.horizon,
    notes: "notes" in b ? str(b.notes, 1000) : cur.notes,
  };
  await saveSettings(next);
  return NextResponse.json({ ok: true, settings: next });
}
