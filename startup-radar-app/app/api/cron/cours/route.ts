import { NextResponse } from "next/server";
import { cronDenied } from "@/lib/cron";
import { runMarket } from "@/lib/update";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/** Tâche planifiée : cours et actus (voir vercel.json). */
export async function GET(req: Request) {
  const denied = cronDenied(req);
  if (denied) return denied;
  return NextResponse.json(await runMarket("auto"));
}
