import { MODULES, type ModuleId } from './modules';
import {
  computeConfidence,
  computeGates,
  computeGrade,
  computeScore,
  orderModules,
} from './scoring';
import { computeSizing } from './sizing';
import type {
  Analysis,
  AnalysisContext,
  Confidence,
  Direction,
  ModuleResult,
  RawAnalysis,
  Status,
  TradePlan,
} from './types';

const STATUSES: Status[] = ['PASS', 'WARN', 'FAIL', 'UNKNOWN'];
const CONFIDENCES: Confidence[] = ['HIGH', 'MEDIUM', 'LOW', 'NONE'];
const DIRECTIONS: Direction[] = ['LONG', 'SHORT', 'NONE'];
const ENTRY_TYPES = ['MARKET', 'LIMIT', 'STOP', 'CONFIRMATION', 'NONE'] as const;

/**
 * Assemble le résultat final.
 *
 * Le modèle juge chaque couche ; le score, les conditions éliminatoires et le
 * verdict sont calculés ici. Un modèle ne peut donc pas s'attribuer une bonne
 * note, et le comportement est identique quel que soit le fournisseur.
 */
export function assembleAnalysis(input: unknown, context: AnalysisContext): Analysis {
  const raw = normalize(input);
  const modules = orderModules(raw.modules);
  const normalized: RawAnalysis = { ...raw, modules };

  const sizing = computeSizing(raw.tradePlan, context);
  const gates = computeGates(normalized, sizing, context);
  const score = computeScore(modules);
  const confidenceScore = computeConfidence(modules);
  const grade = computeGrade(score, gates, confidenceScore, raw.dataQuality.completeness);

  return {
    ...normalized,
    score,
    confidenceScore,
    gates,
    grade,
    sizing,
    createdAt: new Date().toISOString(),
    id: `an_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    context,
  };
}

/**
 * Remet la réponse du modèle en forme.
 *
 * Les modèles gratuits omettent des champs, renvoient des nombres en chaînes ou
 * inventent des identifiants de couche. Plutôt que d'échouer, on répare ce qui
 * est réparable et on marque UNKNOWN ce qui manque — une couche absente ne doit
 * jamais devenir un point favorable.
 */
export function normalize(input: unknown): RawAnalysis {
  const o = obj(input);

  const dq = obj(o.dataQuality);
  const dataQuality = {
    completeness: clampInt(num(dq.completeness), 0, 100, 0),
    notes: str(dq.notes),
    missing: strArray(dq.missing),
  };

  const seen = new Set<ModuleId>();
  const modules: ModuleResult[] = [];
  for (const m of arr(o.modules)) {
    const mo = obj(m);
    const id = String(mo.id ?? '') as ModuleId;
    if (!MODULES.some((d) => d.id === id) || seen.has(id)) continue;
    seen.add(id);
    const status = pick(mo.status, STATUSES, 'UNKNOWN');
    modules.push({
      id,
      status,
      score: status === 'UNKNOWN' ? 50 : clampInt(num(mo.score), 0, 100, 50),
      confidence: pick(mo.confidence, CONFIDENCES, status === 'UNKNOWN' ? 'NONE' : 'LOW'),
      findings: strArray(mo.findings),
      dataGaps: strArray(mo.dataGaps),
      reasoning: str(mo.reasoning),
    });
  }

  const tp = obj(o.tradePlan);
  const direction = pick(tp.direction, DIRECTIONS, 'NONE');
  const entry = num(tp.entry) ?? 0;
  const stop = num(tp.stop) ?? 0;

  // Un plan sans niveaux exploitables n'est pas un plan, quoi qu'annonce le modèle.
  const hasTrade = Boolean(tp.hasTrade) && direction !== 'NONE' && entry > 0 && stop > 0;

  const tradePlan: TradePlan = {
    hasTrade,
    direction: hasTrade ? direction : 'NONE',
    setupName: str(tp.setupName),
    timeframe: str(tp.timeframe),
    entryType: pick(tp.entryType, ENTRY_TYPES, hasTrade ? 'CONFIRMATION' : 'NONE'),
    entry: hasTrade ? entry : 0,
    stop: hasTrade ? stop : 0,
    tp1: hasTrade ? (num(tp.tp1) ?? 0) : 0,
    tp2: hasTrade ? (num(tp.tp2) ?? 0) : 0,
    trigger: str(tp.trigger),
    invalidation: str(tp.invalidation),
    rationale:
      str(tp.rationale) ||
      (hasTrade ? '' : 'Le modèle n’a pas motivé l’absence de trade.'),
    riskNotes: strArray(tp.riskNotes),
  };

  const sy = obj(o.synthesis);
  return {
    dataQuality,
    modules,
    tradePlan,
    synthesis: {
      regime: str(sy.regime),
      dominantDriver: str(sy.dominantDriver),
      bias: str(sy.bias),
      summary: str(sy.summary),
      reactionCheck: str(sy.reactionCheck),
      whatWouldChangeMyMind: str(sy.whatWouldChangeMyMind),
    },
  };
}

// --- Coercition défensive --------------------------------------------------

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function str(v: unknown): string {
  if (typeof v === 'string') return v.trim();
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return '';
}

function strArray(v: unknown): string[] {
  if (typeof v === 'string') return v.trim() ? [v.trim()] : [];
  return arr(v).map(str).filter(Boolean);
}

/** Accepte 3345, "3345", "3 345,20" et "$3,345.20". */
function num(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v !== 'string') return null;
  const cleaned = v.replace(/[^\d.,-]/g, '');
  if (!cleaned) return null;
  // Si les deux séparateurs sont présents, le dernier est le décimal.
  const lastComma = cleaned.lastIndexOf(',');
  const lastDot = cleaned.lastIndexOf('.');
  let normalized: string;
  if (lastComma >= 0 && lastDot >= 0) {
    normalized =
      lastComma > lastDot
        ? cleaned.replace(/\./g, '').replace(',', '.')
        : cleaned.replace(/,/g, '');
  } else if (lastComma >= 0) {
    // Une seule virgule : décimale si elle n'isole pas un groupe de 3 chiffres.
    normalized =
      cleaned.length - lastComma === 4 ? cleaned.replace(',', '') : cleaned.replace(',', '.');
  } else {
    normalized = cleaned;
  }
  const n = parseFloat(normalized);
  return Number.isFinite(n) ? n : null;
}

function clampInt(v: number | null, lo: number, hi: number, fallback: number): number {
  if (v === null) return fallback;
  return Math.max(lo, Math.min(hi, Math.round(v)));
}

function pick<T extends string>(v: unknown, allowed: readonly T[], fallback: T): T {
  const s = String(v ?? '').trim().toUpperCase();
  return (allowed as readonly string[]).includes(s) ? (s as T) : fallback;
}
