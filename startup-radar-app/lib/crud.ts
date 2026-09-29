import { NextResponse } from "next/server";
import { requireAuth } from "./auth";

/** Routes génériques : POST ajoute ou remplace (par id), DELETE ?id= supprime. */
export function listRoutes<T extends { id: string }>(
  load: () => Promise<T[]>,
  save: (v: T[]) => Promise<void>,
  clean: (raw: Record<string, unknown>) => T | string,
) {
  async function POST(req: Request) {
    const denied = await requireAuth();
    if (denied) return denied;
    const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body) return NextResponse.json({ error: "Données illisibles." }, { status: 400 });
    const item = clean(body);
    if (typeof item === "string") return NextResponse.json({ error: item }, { status: 400 });
    const list = await load();
    const i = list.findIndex((x) => x.id === item.id);
    if (i >= 0) list[i] = item;
    else list.push(item);
    await save(list);
    return NextResponse.json({ ok: true, item });
  }
  async function DELETE(req: Request) {
    const denied = await requireAuth();
    if (denied) return denied;
    const id = new URL(req.url).searchParams.get("id");
    if (!id) return NextResponse.json({ error: "Identifiant manquant." }, { status: 400 });
    await save((await load()).filter((x) => x.id !== id));
    return NextResponse.json({ ok: true });
  }
  return { POST, DELETE };
}

export const str = (v: unknown, max = 2000) => (typeof v === "string" ? v.trim().slice(0, max) : "");
export const numOrNull = (v: unknown) => {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v).replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
};
export const newId = (prefix: string) => prefix + "-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
