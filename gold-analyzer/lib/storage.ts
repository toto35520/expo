import type { Analysis, JournalTrade } from './types';

const TRADES_KEY = 'gold-analyzer:trades:v1';
const ANALYSES_KEY = 'gold-analyzer:analyses:v1';
const CONTEXT_KEY = 'gold-analyzer:context:v1';
const MAX_ANALYSES = 30;

function read<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): boolean {
  if (typeof window === 'undefined') return false;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

// --- Trades ---------------------------------------------------------------

export function getTrades(): JournalTrade[] {
  return read<JournalTrade[]>(TRADES_KEY, []).sort((a, b) =>
    b.createdAt.localeCompare(a.createdAt),
  );
}

export function saveTrade(trade: JournalTrade): void {
  const all = read<JournalTrade[]>(TRADES_KEY, []);
  const i = all.findIndex((t) => t.id === trade.id);
  if (i >= 0) all[i] = trade;
  else all.push(trade);
  write(TRADES_KEY, all);
}

export function deleteTrade(id: string): void {
  write(
    TRADES_KEY,
    read<JournalTrade[]>(TRADES_KEY, []).filter((t) => t.id !== id),
  );
}

export function tradeFromAnalysis(a: Analysis): JournalTrade {
  return {
    id: `tr_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    analysisId: a.id,
    createdAt: new Date().toISOString(),
    closedAt: null,
    status: 'PENDING',
    direction: a.tradePlan.direction,
    setupName: a.tradePlan.setupName || 'Sans nom',
    session: a.context.session,
    grade: a.grade,
    score: a.score,
    entry: a.tradePlan.entry,
    stop: a.tradePlan.stop,
    tp1: a.tradePlan.tp1,
    tp2: a.tradePlan.tp2,
    lots: a.sizing?.lots ?? 0,
    riskUSD: a.sizing?.riskActual ?? 0,
    exit: null,
    mae: null,
    mfe: null,
    executionGrade: null,
    notes: '',
    snapshot: a,
  };
}

// --- Analyses (historique consultable) ------------------------------------

export function getAnalyses(): Analysis[] {
  return read<Analysis[]>(ANALYSES_KEY, []);
}

export function saveAnalysis(a: Analysis): void {
  const all = read<Analysis[]>(ANALYSES_KEY, []);
  all.unshift(a);
  // Les snapshots contiennent beaucoup de texte : on borne l'historique pour
  // ne pas saturer le quota localStorage (~5 Mo).
  let kept = all.slice(0, MAX_ANALYSES);
  while (kept.length > 1 && !write(ANALYSES_KEY, kept)) {
    kept = kept.slice(0, kept.length - 1);
  }
}

export function getAnalysis(id: string): Analysis | null {
  return getAnalyses().find((a) => a.id === id) ?? null;
}

// --- Contexte (pré-rempli d'une session à l'autre) ------------------------

export function getSavedContext<T>(fallback: T): T {
  return read<T>(CONTEXT_KEY, fallback);
}

export function saveContext(ctx: unknown): void {
  write(CONTEXT_KEY, ctx);
}

export function exportAll(): string {
  return JSON.stringify(
    {
      version: 1,
      exportedAt: new Date().toISOString(),
      trades: getTrades(),
      analyses: getAnalyses(),
    },
    null,
    2,
  );
}

export function importAll(payload: string): { trades: number; analyses: number } {
  const data = JSON.parse(payload) as { trades?: JournalTrade[]; analyses?: Analysis[] };
  if (data.trades) write(TRADES_KEY, data.trades);
  if (data.analyses) write(ANALYSES_KEY, data.analyses.slice(0, MAX_ANALYSES));
  return { trades: data.trades?.length ?? 0, analyses: data.analyses?.length ?? 0 };
}
