import { NextResponse } from "next/server";

/**
 * Vercel appelle les tâches planifiées avec « Authorization: Bearer CRON_SECRET »
 * si la variable existe. Sans elle, on accepte l'agent « vercel-cron » pour que
 * la mise à jour du matin ne soit jamais bloquée par un oubli de configuration.
 */
export function cronDenied(req: Request): NextResponse | null {
  const secret = process.env.CRON_SECRET;
  const auth = req.headers.get("authorization");
  if (secret) {
    if (auth === `Bearer ${secret}`) return null;
  } else if ((req.headers.get("user-agent") ?? "").startsWith("vercel-cron")) {
    return null;
  }
  return NextResponse.json({ error: "Accès refusé." }, { status: 401 });
}
