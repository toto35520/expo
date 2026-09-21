/**
 * Sessions de marche (heures UTC).
 *
 * L'or vit surtout sur Londres et New York : l'ouverture de Londres casse
 * souvent le range asiatique, et le fixing/ouverture US amene le gros du
 * volume. Le moteur s'en sert pour pondérer les signaux et pour construire
 * les ranges d'ouverture.
 */

export type SessionName = 'ASIE' | 'LONDRES' | 'NEW_YORK' | 'LONDRES_NY' | 'HORS_SESSION';

export interface SessionWindow {
  name: SessionName;
  label: string;
  startMin: number;
  endMin: number;
}

/** Fenetres en minutes depuis 00:00 UTC. */
export const SESSIONS: SessionWindow[] = [
  { name: 'ASIE', label: 'Asie (Tokyo)', startMin: 0, endMin: 7 * 60 },
  { name: 'LONDRES', label: 'Londres', startMin: 7 * 60, endMin: 13 * 60 + 30 },
  { name: 'LONDRES_NY', label: 'Recouvrement Londres / New York', startMin: 13 * 60 + 30, endMin: 16 * 60 },
  { name: 'NEW_YORK', label: 'New York', startMin: 16 * 60, endMin: 21 * 60 },
];

export const LONDON_OPEN_MIN = 7 * 60;
export const NY_OPEN_MIN = 13 * 60 + 30;

export function minutesOfDayUtc(ts: number): number {
  const d = new Date(ts);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}

export function currentSession(ts: number): SessionWindow {
  const m = minutesOfDayUtc(ts);
  const day = new Date(ts).getUTCDay();
  if (day === 6 || (day === 0 && m < 22 * 60)) {
    return { name: 'HORS_SESSION', label: 'Marche ferme (week-end)', startMin: 0, endMin: 1440 };
  }
  const found = SESSIONS.find((s) => m >= s.startMin && m < s.endMin);
  return found ?? { name: 'HORS_SESSION', label: 'Hors session (liquidite faible)', startMin: 0, endMin: 1440 };
}

/** Poids de qualite du contexte : on evite de sur-trader les heures creuses. */
export function sessionQuality(name: SessionName): number {
  switch (name) {
    case 'LONDRES_NY':
      return 1;
    case 'LONDRES':
      return 0.9;
    case 'NEW_YORK':
      return 0.85;
    case 'ASIE':
      return 0.5;
    default:
      return 0.25;
  }
}

export function startOfUtcDay(ts: number): number {
  return Math.floor(ts / 86_400_000) * 86_400_000;
}

/** Timestamp d'ouverture d'une session pour le jour de `ts`. */
export function sessionOpenTs(ts: number, openMinute: number): number {
  return startOfUtcDay(ts) + openMinute * 60_000;
}

export function formatUtcTime(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${hh}:${mm} UTC`;
}
