import { Redis } from "@upstash/redis";
import { SEED_EVENTS, SEED_WATCHLIST } from "./seed";
import {
  DEFAULT_SETTINGS,
  EMPTY_SNAPSHOT,
  type AppState,
  type Dossier,
  type EventItem,
  type HistoryPoint,
  type Position,
  type Settings,
  type Snapshot,
  type WatchItem,
} from "./types";

const url = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const token = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;

const redis = url && token ? new Redis({ url, token }) : null;

// Sans base configurée (développement local), les données vivent en mémoire
// et disparaissent au redémarrage.
const memory = new Map<string, unknown>();

export const storageKind: AppState["storage"] = redis ? "redis" : "memoire";

const P = "radar:";
export const KEYS = {
  positions: P + "positions",
  watchlist: P + "watchlist",
  dossiers: P + "dossiers",
  events: P + "events",
  settings: P + "settings",
  snapshot: P + "snapshot",
  history: P + "history",
} as const;

async function get<T>(key: string): Promise<T | null> {
  if (redis) return (await redis.get<T>(key)) ?? null;
  return (memory.get(key) as T | undefined) ?? null;
}

async function set<T>(key: string, value: T): Promise<void> {
  if (redis) await redis.set(key, value);
  else memory.set(key, value);
}

export async function incrDaily(name: string): Promise<number> {
  const key = `${P}count:${name}:${new Date().toISOString().slice(0, 10)}`;
  if (redis) {
    const n = await redis.incr(key);
    if (n === 1) await redis.expire(key, 60 * 60 * 48);
    return n;
  }
  const n = ((memory.get(key) as number | undefined) ?? 0) + 1;
  memory.set(key, n);
  return n;
}

export async function getPositions(): Promise<Position[]> {
  return (await get<Position[]>(KEYS.positions)) ?? [];
}
export const savePositions = (v: Position[]) => set(KEYS.positions, v);

export async function getWatchlist(): Promise<WatchItem[]> {
  const w = await get<WatchItem[]>(KEYS.watchlist);
  if (w) return w;
  await set(KEYS.watchlist, SEED_WATCHLIST);
  return SEED_WATCHLIST;
}
export const saveWatchlist = (v: WatchItem[]) => set(KEYS.watchlist, v);

export async function getDossiers(): Promise<Dossier[]> {
  return (await get<Dossier[]>(KEYS.dossiers)) ?? [];
}
export const saveDossiers = (v: Dossier[]) => set(KEYS.dossiers, v);

export async function getEvents(): Promise<EventItem[]> {
  const e = await get<EventItem[]>(KEYS.events);
  if (e) return e;
  await set(KEYS.events, SEED_EVENTS);
  return SEED_EVENTS;
}
export const saveEvents = (v: EventItem[]) => set(KEYS.events, v);

export async function getSettings(): Promise<Settings> {
  return { ...DEFAULT_SETTINGS, ...((await get<Settings>(KEYS.settings)) ?? {}) };
}
export const saveSettings = (v: Settings) => set(KEYS.settings, v);

export async function getSnapshot(): Promise<Snapshot> {
  return { ...EMPTY_SNAPSHOT, ...((await get<Snapshot>(KEYS.snapshot)) ?? {}) };
}
export const saveSnapshot = (v: Snapshot) => set(KEYS.snapshot, v);

export async function getHistory(): Promise<HistoryPoint[]> {
  return (await get<HistoryPoint[]>(KEYS.history)) ?? [];
}

/** Ajoute ou remplace le point du jour, garde environ 2 ans d'historique. */
export async function pushHistory(p: HistoryPoint): Promise<void> {
  const h = (await getHistory()).filter((x) => x.date !== p.date);
  h.push(p);
  h.sort((a, b) => a.date.localeCompare(b.date));
  await set(KEYS.history, h.slice(-730));
}

export async function getState(): Promise<AppState> {
  const [positions, watchlist, dossiers, events, settings, snapshot, history] = await Promise.all([
    getPositions(),
    getWatchlist(),
    getDossiers(),
    getEvents(),
    getSettings(),
    getSnapshot(),
    getHistory(),
  ]);
  return {
    positions,
    watchlist,
    dossiers,
    events,
    settings,
    snapshot,
    history,
    storage: storageKind,
    aiConfigured: Boolean(process.env.ANTHROPIC_API_KEY),
  };
}
