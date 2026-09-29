import { listRoutes, newId, numOrNull, str } from "@/lib/crud";
import { getPositions, savePositions } from "@/lib/store";
import type { Position } from "@/lib/types";

export const dynamic = "force-dynamic";

export const { POST, DELETE } = listRoutes<Position>(getPositions, savePositions, (b) => {
  const name = str(b.name, 120);
  const invested = numOrNull(b.invested);
  if (!name) return "Donne un nom à la ligne.";
  if (invested == null || invested < 0) return "Indique le montant investi en euros.";
  const kind = b.kind === "non-cote" ? "non-cote" : "cote";
  return {
    id: str(b.id, 80) || newId("p"),
    name,
    kind,
    ticker: str(b.ticker, 20).toUpperCase() || null,
    isin: str(b.isin, 12).toUpperCase() || null,
    quantity: numOrNull(b.quantity),
    invested,
    manualValue: numOrNull(b.manualValue),
    platform: str(b.platform, 60),
    date: str(b.date, 20),
    notes: str(b.notes, 500),
    source: b.source === "import-tr" ? "import-tr" : "manuel",
  };
});
