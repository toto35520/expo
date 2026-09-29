export type PositionKind = "cote" | "non-cote";

export interface Position {
  id: string;
  name: string;
  kind: PositionKind;
  /** Symbole Yahoo Finance, ex. SPCX, CBRS, SMT.L */
  ticker?: string | null;
  isin?: string | null;
  quantity?: number | null;
  /** Montant total investi en euros */
  invested: number;
  /** Valeur estimée en euros pour les lignes non cotées */
  manualValue?: number | null;
  platform?: string;
  date?: string;
  notes?: string;
  source?: "manuel" | "import-tr";
}

export type WatchStatus = "acces" | "ipo" | "suivre";

export interface Score {
  croissance: number;
  marche: number;
  valo: number;
  solidite: number;
  sortie: number;
  acces: number;
}

export interface WatchItem {
  id: string;
  name: string;
  sector: string;
  country: string;
  status: WatchStatus;
  ticker?: string | null;
  round?: string;
  date?: string;
  /** Valorisation en milliards */
  val?: number | null;
  cur?: "$" | "€";
  /** Revenu annuel récurrent en milliards */
  arr?: number | null;
  growth?: string;
  why?: string;
  risks?: string;
  how?: string;
  src?: string;
  srcl?: string;
  next?: string;
  score?: Score | null;
  noScore?: boolean;
  profil?: string;
  verdict?: string;
  updated?: string;
}

export interface Dossier {
  id: string;
  name: string;
  platform?: string;
  amount?: number | null;
  checks: Record<string, boolean>;
  decision: "À creuser" | "Investir" | "Refuser";
  notes?: string;
  created: string;
}

export interface EventItem {
  id: string;
  date: string;
  type: string;
  who: string;
  what: string;
}

export interface Settings {
  /** Patrimoine financier total en euros */
  patrimoine: number | null;
  /** Argent disponible à investir en euros */
  cash: number | null;
  /** Part maximale du patrimoine en startups, en % */
  maxStartupPct: number;
  risque: "prudent" | "equilibre" | "dynamique";
  horizon: string;
  notes: string;
}

export interface Quote {
  symbol: string;
  name?: string;
  price: number;
  currency: string;
  priceEUR: number;
  change1d: number | null;
  change1m: number | null;
  closes: number[];
  at: string;
  source: "yahoo" | "stooq";
}

export interface NewsItem {
  title: string;
  link: string;
  date: string;
  source: string;
  /** Noms de ta liste ou de ton portefeuille cités dans le titre */
  matches: string[];
}

export const ACTION_TYPES = ["ACHETER", "RENFORCER", "ATTENDRE", "ALLÉGER", "VENDRE", "SURVEILLER"] as const;
export type ActionType = (typeof ACTION_TYPES)[number];

export interface SourceRef {
  titre: string;
  url: string;
}

export interface Argument {
  /** L'argument, en une phrase */
  point: string;
  /** Le chiffre qui le prouve, avec sa date */
  chiffre: string | null;
  /** Lien vérifié (présent dans la veille du jour ou tes fiches), sinon null */
  source: string | null;
}

export interface RecoAction {
  type: ActionType;
  cible: string;
  ticker: string | null;
  montantEUR: number | null;
  /** La recommandation en une phrase */
  enBref: string;
  /** Le raisonnement complet, 3 à 6 phrases */
  these: string;
  pour: Argument[];
  contre: Argument[];
  /** Comment et quand acheter (en plusieurs fois, niveau de prix…) */
  plan: string;
  horizon: string;
  confiance: "faible" | "moyenne" | "forte";
  sources: SourceRef[];
}

export interface Reco {
  resume: string;
  marche: string;
  actions: RecoAction[];
  alertes: string[];
  verifications: string[];
}

export interface RunLog {
  at: string;
  step: "cours" | "veille" | "decision";
  trigger: "auto" | "manuel" | "ouverture";
  ok: boolean;
  message: string;
  seconds: number;
}

export interface Snapshot {
  updatedAt: string | null;
  fx: { USD: number; GBP: number } | null;
  quotes: Record<string, Quote>;
  quoteErrors: string[];
  news: NewsItem[];
  reco: Reco | null;
  recoAt: string | null;
  recoError: string | null;
  recoModel: string | null;
  /** Vrai tant que l'analyse affichée est celle de départ, écrite à la main */
  recoSeed?: boolean;
  research: { note: string; sources: SourceRef[]; at: string } | null;
  runs: RunLog[];
}

export interface HistoryPoint {
  date: string;
  value: number;
  invested: number;
}

export interface AppState {
  positions: Position[];
  watchlist: WatchItem[];
  dossiers: Dossier[];
  events: EventItem[];
  settings: Settings;
  snapshot: Snapshot;
  history: HistoryPoint[];
  storage: "redis" | "memoire";
  aiConfigured: boolean;
  health: { cronSecret: boolean; password: boolean };
}

export const DEFAULT_SETTINGS: Settings = {
  patrimoine: null,
  cash: 5000,
  maxStartupPct: 10,
  risque: "dynamique",
  horizon: "5 à 10 ans",
  notes: "",
};

export const EMPTY_SNAPSHOT: Snapshot = {
  updatedAt: null,
  fx: null,
  quotes: {},
  quoteErrors: [],
  news: [],
  reco: null,
  recoAt: null,
  recoError: null,
  recoModel: null,
  research: null,
  runs: [],
};
