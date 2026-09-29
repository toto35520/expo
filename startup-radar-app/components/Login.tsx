"use client";

import { useState } from "react";

export default function Login() {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    const r = await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
    if (r.ok) location.reload();
    else {
      setErr(((await r.json().catch(() => ({}))) as { error?: string }).error || "Connexion impossible.");
      setBusy(false);
    }
  }
  return (
    <main className="login">
      <form className="panel" onSubmit={submit}>
        <h1>Radar Startups</h1>
        <p className="muted small">Ton espace privé. Entre le mot de passe défini dans Vercel (APP_PASSWORD).</p>
        <label className="stack small muted" htmlFor="pw">
          Mot de passe
          <input id="pw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required />
        </label>
        {err && <p className="err small">{err}</p>}
        <button className="btn" disabled={busy} type="submit">{busy ? "Connexion…" : "Entrer"}</button>
      </form>
    </main>
  );
}
