import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/auth";
import { getSnapshot, incrDaily } from "@/lib/store";
import { runDecisionStep, runMarket, runResearchStep, type Trigger } from "@/lib/update";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/**
 * Mise à jour à la demande, une étape par appel pour rester sous la limite de
 * Vercel : ?step=cours | veille | decision. &trigger=ouverture pour le
 * rattrapage automatique à l'ouverture de l'app.
 */
export async function POST(req: Request) {
  const denied = await requireAuth();
  if (denied) return denied;
  const u = new URL(req.url);
  const step = u.searchParams.get("step") ?? "cours";
  const trigger: Trigger = u.searchParams.get("trigger") === "ouverture" ? "ouverture" : "manuel";

  if (step === "cours") return NextResponse.json(await runMarket(trigger));

  if (step === "veille") {
    if (trigger === "ouverture") {
      // Rattrapage : seulement si la dernière veille date de plus de 20 h.
      const r = (await getSnapshot()).research;
      if (r && Date.now() - new Date(r.at).getTime() < 20 * 3600e3) return NextResponse.json({ ok: true, message: "Veille déjà à jour." });
      if ((await incrDaily("catchup-veille")) > 1) return NextResponse.json({ ok: false, message: "Rattrapage déjà tenté aujourd'hui." });
    } else {
      const max = Number(process.env.MAX_MANUAL_AI_RUNS ?? 3);
      if ((await incrDaily("manual-ai")) > max) {
        return NextResponse.json({ ok: false, message: `Tu as déjà lancé ${max} analyses aujourd'hui. La prochaine arrive automatiquement demain matin.` }, { status: 429 });
      }
    }
    return NextResponse.json(await runResearchStep(trigger));
  }

  if (step === "decision") {
    if (trigger === "ouverture" && (await incrDaily("catchup-decision")) > 1) {
      return NextResponse.json({ ok: false, message: "Rattrapage déjà tenté aujourd'hui." });
    }
    if (trigger === "manuel" && (await incrDaily("manual-decision")) > Number(process.env.MAX_MANUAL_AI_RUNS ?? 3) + 1) {
      return NextResponse.json({ ok: false, message: "Limite d'analyses atteinte pour aujourd'hui." }, { status: 429 });
    }
    return NextResponse.json(await runDecisionStep(trigger));
  }

  return NextResponse.json({ error: "Étape inconnue." }, { status: 400 });
}
