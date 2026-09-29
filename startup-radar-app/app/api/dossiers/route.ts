import { listRoutes, newId, numOrNull, str } from "@/lib/crud";
import { getDossiers, saveDossiers } from "@/lib/store";
import type { Dossier } from "@/lib/types";

export const dynamic = "force-dynamic";

const DECISIONS = ["À creuser", "Investir", "Refuser"] as const;

export const { POST, DELETE } = listRoutes<Dossier>(getDossiers, saveDossiers, (b) => {
  const name = str(b.name, 120);
  if (!name) return "Donne le nom de la startup.";
  const checks: Record<string, boolean> = {};
  if (b.checks && typeof b.checks === "object") for (const [k, v] of Object.entries(b.checks)) checks[k.slice(0, 30)] = v === true;
  const decision = DECISIONS.find((d) => d === b.decision) ?? "À creuser";
  return {
    id: str(b.id, 80) || newId("d"),
    name,
    platform: str(b.platform, 60),
    amount: numOrNull(b.amount),
    checks,
    decision,
    notes: str(b.notes, 1000),
    created: str(b.created, 40) || new Date().toISOString(),
  };
});
