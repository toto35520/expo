import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/auth";
import { incrDaily } from "@/lib/store";
import { runUpdate } from "@/lib/update";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/** Mise à jour à la demande. ?ai=1 relance aussi l'analyse IA (limitée par jour). */
export async function POST(req: Request) {
  const denied = await requireAuth();
  if (denied) return denied;
  let withAI = new URL(req.url).searchParams.get("ai") === "1";
  if (withAI) {
    const max = Number(process.env.MAX_MANUAL_AI_RUNS ?? 3);
    const n = await incrDaily("manual-ai");
    if (n > max) {
      return NextResponse.json({ error: `Tu as déjà lancé ${max} analyses IA aujourd'hui. La prochaine arrive automatiquement demain matin.` }, { status: 429 });
    }
  }
  return NextResponse.json(await runUpdate({ withAI }));
}
