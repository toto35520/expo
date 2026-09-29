import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const COOKIE = "radar_session";

function secret(): string {
  return process.env.SESSION_SECRET || process.env.APP_PASSWORD || "dev-only-secret";
}

export function sessionToken(): string {
  return createHmac("sha256", secret()).update("radar-ok:" + (process.env.APP_PASSWORD ?? "")).digest("hex");
}

function safeEqual(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export function passwordMatches(input: string): boolean {
  const pw = process.env.APP_PASSWORD;
  if (!pw) return true;
  return safeEqual(input, pw);
}

/** Vrai si le visiteur est connecté (ou si aucun mot de passe n'est défini). */
export async function isAuthed(): Promise<boolean> {
  if (!process.env.APP_PASSWORD) return true;
  const c = (await cookies()).get(COOKIE)?.value;
  return Boolean(c && safeEqual(c, sessionToken()));
}

export async function requireAuth(): Promise<NextResponse | null> {
  if (await isAuthed()) return null;
  return NextResponse.json({ error: "Connecte-toi d'abord." }, { status: 401 });
}

export const passwordConfigured = () => Boolean(process.env.APP_PASSWORD);
