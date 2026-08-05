import type { ModuleId } from './modules';

export type Status = 'PASS' | 'WARN' | 'FAIL' | 'UNKNOWN';
export type Confidence = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';
export type Direction = 'LONG' | 'SHORT' | 'NONE';

export interface ModuleResult {
  id: ModuleId;
  status: Status;
  /** 0-100. 50 = neutre. UNKNOWN doit rester proche de 50, jamais élevé. */
  score: number;
  confidence: Confidence;
  findings: string[];
  dataGaps: string[];
  reasoning: string;
}

export interface TradePlan {
  hasTrade: boolean;
  direction: Direction;
  setupName: string;
  timeframe: string;
  entryType: 'MARKET' | 'LIMIT' | 'STOP' | 'CONFIRMATION' | 'NONE';
  entry: number;
  stop: number;
  tp1: number;
  tp2: number;
  trigger: string;
  invalidation: string;
  rationale: string;
  riskNotes: string[];
}

export interface Synthesis {
  regime: string;
  dominantDriver: string;
  bias: string;
  summary: string;
  reactionCheck: string;
  whatWouldChangeMyMind: string;
}

export interface DataQuality {
  completeness: number;
  notes: string;
  missing: string[];
}

/** Ce que le modèle renvoie (structured output). */
export interface RawAnalysis {
  dataQuality: DataQuality;
  modules: ModuleResult[];
  tradePlan: TradePlan;
  synthesis: Synthesis;
}

export interface GateResult {
  id: string;
  label: string;
  passed: boolean;
  reason: string;
}

export type Grade = 'A+' | 'A' | 'B' | 'C' | 'NO TRADE';

export interface Sizing {
  lots: number;
  stopDistance: number;
  riskRequested: number;
  riskActual: number;
  valuePerDollarPerLot: number;
  rr1: number;
  rr2: number;
  belowMinLot: boolean;
}

/** Résultat final : sortie modèle + calculs déterministes côté app. */
export interface Analysis extends RawAnalysis {
  score: number;
  confidenceScore: number;
  gates: GateResult[];
  grade: Grade;
  sizing: Sizing | null;
  createdAt: string;
  id: string;
  context: AnalysisContext;
}

export interface AnalysisContext {
  // Compte
  accountSize: number;
  riskPercent: number;
  contractSize: number;
  minLot: number;
  // Marché
  currentPrice: number | null;
  atrDaily: number | null;
  atrH1: number | null;
  spread: number | null;
  session: string;
  horizon: string;
  // Données que le graphique ne peut pas donner
  dxy: string;
  realYields: string;
  fedExpectations: string;
  upcomingNews: string;
  cot: string;
  etfFlows: string;
  gex: string;
  ivVsRv: string;
  curve: string;
  shanghaiPremium: string;
  comexInventories: string;
  silverRatio: string;
  cbBuying: string;
  lastNewsReaction: string;
  notes: string;
}

export interface ChartUpload {
  id: string;
  timeframe: string;
  dataUrl: string;
  mediaType: string;
  bytes: number;
}

// ---------------------------------------------------------------------------
// Journal
// ---------------------------------------------------------------------------

export type TradeStatus = 'PENDING' | 'ACTIVE' | 'CLOSED' | 'CANCELLED';

export interface JournalTrade {
  id: string;
  analysisId: string;
  createdAt: string;
  closedAt: string | null;
  status: TradeStatus;
  direction: Direction;
  setupName: string;
  session: string;
  grade: Grade;
  score: number;
  entry: number;
  stop: number;
  tp1: number;
  tp2: number;
  lots: number;
  riskUSD: number;
  /** Prix de sortie effectif. */
  exit: number | null;
  /** Excursion maximale défavorable / favorable, en prix. */
  mae: number | null;
  mfe: number | null;
  /** Note d'exécution 1-5, indépendante du P&L. */
  executionGrade: number | null;
  notes: string;
  snapshot: Analysis | null;
}
