import { NextResponse } from "next/server";
import { cronDenied } from "@/lib/cron";
import { incrDaily } from "@/lib/store";
import { runDecisionStep } from "@/lib/update";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/** Tâche planifiée du matin (voir vercel.json). */
export async function GET(req: Request) {
  const denied = cronDenied(req);
  if (denied) return denied;
  if ((await incrDaily("auto-decision")) > 2) return NextResponse.json({ ok: false, message: "Déjà faite aujourd'hui." });
  return NextResponse.json(await runDecisionStep("auto"));
}
