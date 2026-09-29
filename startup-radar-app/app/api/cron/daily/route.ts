import { NextResponse } from "next/server";
import { runUpdate } from "@/lib/update";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/** Appelée chaque matin par Vercel (voir vercel.json). */
export async function GET(req: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) {
    return NextResponse.json({ error: "Accès refusé." }, { status: 401 });
  }
  return NextResponse.json(await runUpdate({ withAI: true }));
}
