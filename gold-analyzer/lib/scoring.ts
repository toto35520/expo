import { MODULES, MODULE_BY_ID, TOTAL_WEIGHT, type ModuleId } from './modules';
import type {
  AnalysisContext,
  Confidence,
  GateResult,
  Grade,
  ModuleResult,
  RawAnalysis,
  Sizing,
} from './types';

const CONFIDENCE_VALUE: Record<Confidence, number> = {
  HIGH: 100,
  MEDIUM: 70,
  LOW: 35,
  NONE: 0,
};

/**
 * Score pondéré sur les 14 couches.
 *
 * Un module UNKNOWN est ramené à 50 quel que soit le score renvoyé : une donnée
 * absente ne peut pas devenir un argument favorable. C'est le mécanisme qui
 * empêche l'outil de produire un score élevé sur un dossier vide.
 */
export function computeScore(modules: ModuleResult[]): number {
  let weighted = 0;
  let weight = 0;

  for (const def of MODULES) {
    const m = modules.find((x) => x.id === def.id);
    if (!m) {
      // Module absent de la réponse : traité comme inconnu, donc neutre.
      weighted += 50 * def.weight;
      weight += def.weight;
      continue;
    }
    const score = m.status === 'UNKNOWN' ? 50 : clamp(m.score, 0, 100);
    weighted += score * def.weight;
    weight += def.weight;
  }

  return weight > 0 ? Math.round(weighted / weight) : 0;
}

/**
 * Confiance globale : moyenne pondérée des confiances déclarées.
 * Séparée du score — « à quel point le setup est bon » et « à quel point on le
 * sait » sont deux questions différentes, et les confondre est malhonnête.
 */
export function computeConfidence(modules: ModuleResult[]): number {
  let weighted = 0;
  let weight = 0;
  for (const def of MODULES) {
    const m = modules.find((x) => x.id === def.id);
    const c = m ? CONFIDENCE_VALUE[m.confidence] : 0;
    weighted += c * def.weight;
    weight += def.weight;
  }
  return weight > 0 ? Math.round(weighted / weight) : 0;
}

const MIN_RR = 1.5;
const MIN_STOP_ATR = 0.35;
const MAX_STOP_ATR = 3;
const MIN_CONFIDENCE = 40;
const MIN_COMPLETENESS = 35;

/**
 * Gates éliminatoires. Un seul FAIL suffit à annuler le trade, quel que soit
 * le score. C'est volontaire : la plupart des configurations doivent être
 * refusées, sinon l'outil n'a aucune valeur.
 */
export function computeGates(
  raw: RawAnalysis,
  sizing: Sizing | null,
  ctx: AnalysisContext,
): GateResult[] {
  const gates: GateResult[] = [];
  const mod = (id: ModuleId) => raw.modules.find((m) => m.id === id);

  // 1. Couches éliminatoires déclarées FAIL par l'analyse
  for (const def of MODULES.filter((m) => m.gate)) {
    const m = mod(def.id);
    const failed = m?.status === 'FAIL';
    gates.push({
      id: `module:${def.id}`,
      label: def.title,
      passed: !failed,
      reason: failed
        ? m!.reasoning || 'Cette couche contredit le setup.'
        : m
          ? `Statut ${m.status}.`
          : 'Couche non évaluée — traitée comme non bloquante.',
    });
  }

  // 2. Un trade doit exister pour que les gates suivantes aient un sens
  if (!raw.tradePlan.hasTrade) {
    gates.push({
      id: 'trade:exists',
      label: 'Setup identifié',
      passed: false,
      reason: 'Aucun setup ne réunit les conditions requises.',
    });
    return gates;
  }

  gates.push({
    id: 'trade:exists',
    label: 'Setup identifié',
    passed: true,
    reason: raw.tradePlan.setupName || 'Setup présent.',
  });

  // 3. Cohérence des niveaux : stop du bon côté, TP du bon côté
  const { direction, entry, stop, tp1 } = raw.tradePlan;
  const levelsOk =
    direction === 'LONG'
      ? stop < entry && tp1 > entry
      : direction === 'SHORT'
        ? stop > entry && tp1 < entry
        : false;
  gates.push({
    id: 'levels:coherent',
    label: 'Cohérence entrée / stop / objectif',
    passed: levelsOk,
    reason: levelsOk
      ? `${direction} — entrée ${entry}, stop ${stop}, TP1 ${tp1}.`
      : 'Les niveaux sont incohérents avec la direction annoncée.',
  });

  // 4. Ratio risque/rendement
  const rr = sizing?.rr1 ?? 0;
  gates.push({
    id: 'risk:rr',
    label: `Ratio R:R ≥ ${MIN_RR}`,
    passed: rr >= MIN_RR,
    reason: rr > 0 ? `R:R au TP1 = ${rr}.` : 'R:R incalculable.',
  });

  // 5. Stop dimensionné par l'ATR, pas arbitraire
  if (ctx.atrDaily && sizing) {
    const ratio = sizing.stopDistance / ctx.atrDaily;
    const ok = ratio >= MIN_STOP_ATR && ratio <= MAX_STOP_ATR;
    gates.push({
      id: 'risk:atr',
      label: 'Stop cohérent avec l’ATR',
      passed: ok,
      reason: `Stop = ${sizing.stopDistance} $ soit ${ratio.toFixed(2)} × ATR journalier (${ctx.atrDaily} $). Fenêtre acceptée : ${MIN_STOP_ATR}–${MAX_STOP_ATR} × ATR.`,
    });
  } else {
    gates.push({
      id: 'risk:atr',
      label: 'Stop cohérent avec l’ATR',
      passed: false,
      reason:
        'ATR journalier non renseigné. Sur l’or, un stop non calibré à l’ATR n’est pas validable.',
    });
  }

  // 6. Taille de position réalisable au risque demandé
  if (sizing) {
    gates.push({
      id: 'risk:size',
      label: 'Position dimensionnable au risque demandé',
      passed: !sizing.belowMinLot,
      reason: sizing.belowMinLot
        ? `Le risque de ${sizing.riskRequested} $ impose une taille sous le lot minimum (${ctx.minLot}). Un lot minimum ferait risquer ${round(ctx.minLot * sizing.stopDistance * sizing.valuePerDollarPerLot)} $.`
        : `${sizing.lots} lot(s) → risque réel ${sizing.riskActual} $.`,
    });
  } else {
    gates.push({
      id: 'risk:size',
      label: 'Position dimensionnable au risque demandé',
      passed: false,
      reason: 'Dimensionnement impossible.',
    });
  }

  // 7. Confiance minimale : un setup parfait sur des données absentes reste refusé
  const confidence = computeConfidence(raw.modules);
  gates.push({
    id: 'data:confidence',
    label: `Confiance ≥ ${MIN_CONFIDENCE}`,
    passed: confidence >= MIN_CONFIDENCE,
    reason: `Confiance globale ${confidence}/100. En dessous de ${MIN_CONFIDENCE}, le verdict repose sur trop d’inconnues.`,
  });

  gates.push({
    id: 'data:completeness',
    label: `Complétude des données ≥ ${MIN_COMPLETENESS}`,
    passed: raw.dataQuality.completeness >= MIN_COMPLETENESS,
    reason: `Complétude ${raw.dataQuality.completeness}/100.`,
  });

  return gates;
}

export function computeGrade(
  score: number,
  gates: GateResult[],
  confidence: number,
  completeness: number,
): Grade {
  if (gates.some((g) => !g.passed)) return 'NO TRADE';
  if (score >= 85 && confidence >= 70 && completeness >= 70) return 'A+';
  if (score >= 75 && confidence >= 60) return 'A';
  if (score >= 65) return 'B';
  if (score >= 55) return 'C';
  return 'NO TRADE';
}

export function gradeMeaning(grade: Grade): string {
  switch (grade) {
    case 'A+':
      return 'Toutes les couches convergent sur des données solides. Rare — c’est ce qu’on attend d’un setup A+.';
    case 'A':
      return 'Setup valide. Taille pleine autorisée dans les limites du plan de risque.';
    case 'B':
      return 'Setup acceptable mais avec réserves. Taille réduite de moitié, ou passer son tour.';
    case 'C':
      return 'Observation seulement. Pas d’engagement de capital.';
    case 'NO TRADE':
      return 'Au moins une condition éliminatoire n’est pas remplie. Aucun trade, quel que soit le score.';
  }
}

/** Modules ordonnés comme la définition, avec les manquants matérialisés. */
export function orderModules(modules: ModuleResult[]): ModuleResult[] {
  return MODULES.map(
    (def) =>
      modules.find((m) => m.id === def.id) ?? {
        id: def.id,
        status: 'UNKNOWN' as const,
        score: 50,
        confidence: 'NONE' as const,
        findings: [],
        dataGaps: ['Couche non retournée par l’analyse.'],
        reasoning: 'Non évaluée.',
      },
  );
}

export function moduleTitle(id: ModuleId): string {
  return MODULE_BY_ID[id]?.title ?? id;
}

export function moduleWeight(id: ModuleId): number {
  return MODULE_BY_ID[id]?.weight ?? 0;
}

export { TOTAL_WEIGHT };

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}

function round(n: number) {
  return Math.round(n * 100) / 100;
}
