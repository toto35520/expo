/**
 * Prereglages verifies sur 2021-05-19 -> 2026-09-07 (375 985 barres M5).
 *
 * Les chiffres cites sont ceux du backtest avec couts (spread 0.22 $, spread
 * news 0.45 $, slippage 0.06 $ sur stop) et politique intra-barre
 * 'conservative' (pire cas systematique).
 *
 * AUCUN de ces prereglages n'atteint la significativite statistique
 * (|t| > 2). Ils sont classes par STABILITE, pas par performance.
 */

export const PRESETS = {
  /**
   * Defaut. Echelle TP1/TP2/TP3 ancree sur la liquidite.
   * 22 trades, +7.4 R, PF 1.82, 50.0% de reussite, maxDD 3.0 R, t=1.26
   */
  stable: {},

  /**
   * Comportement historique : une cible unique fermant 100 % au niveau
   * oppose de Londres. Conserve comme point de comparaison — l'echelle de
   * cibles fait mieux sur toutes les metriques.
   * 22 trades, +6.9 R, PF 1.57, 45.5% de reussite, maxDD 4.1 R, t=0.94
   */
  cibleUnique: {
    target: { levels: { enabled: false } },
  },

  /**
   * Lecture LITTERALE de la strategie telle que decrite : entree au milieu du
   * FVG, TP au niveau oppose de Londres, SL juste au-dessus du piege.
   * 19 trades, +6.2 R, PF 1.91, 52.6% de reussite, maxDD 3.0 R, t=1.24
   */
  literal: {
    entry: { model: 'fvg', fvgLevel: 0.5 },
  },

  /**
   * Plus de signaux : repli sur l'Order Block quand il n'y a pas de FVG, et
   * jusqu'a 2 opportunites par jour (un second balayage, typiquement du cote
   * oppose, est guette apres le premier setup).
   * 50 trades, +14.3 R, PF 1.63, 42.0% de reussite, maxDD 7.4 R, t=1.44
   */
  frequent: {
    entry: { model: 'fvgOrOb', fvgLevel: 0.75, obLevel: 0.5 },
    filters: { maxTradesPerDay: 2 },
    sweep: { maxPerDay: 2, allowOppositeAfterFail: true },
  },

  /**
   * Entree par retracement de Fibonacci de la jambe MSS au lieu du FVG.
   * Meilleur taux de remplissage (56%) mais tres dependant du regime :
   * -3.0 R en 2022, +13.3 R en 2026.
   * 40 trades, +10.8 R, PF 1.62, 42.5% de reussite, maxDD 4.8 R, t=1.25
   */
  ote: {
    entry: { model: 'ote', oteLevel: 0.705 },
  },

  /**
   * Le plus selectif : toutes les confluences activees. Meilleur t-stat
   * mesure (1.17) et meilleur PF (2.02), mais seulement 3 trades par an —
   * l'echantillon est trop petit pour en tirer une conclusion.
   * 15 trades, +8.5 R, PF 3.00, 60.0% de reussite, maxDD 2.0 R, t=1.79 —
   * le meilleur t-stat mesure, mais 3 trades par an seulement
   */
  selective: {
    entry: { model: 'fvg', fvgLevel: 0.75 },
    filters: { premiumDiscount: 'mssLeg' },
  },

  /**
   * Conforme a la checklist complete : premium/discount, fenetre Silver
   * Bullet pour le remplissage, blackout des annonces destructrices,
   * inducement exige.
   *
   * ATTENTION — MESURE : empiler toutes les confluences ne laisse que
   * 5 trades en 5 ans et 4 mois (+0.6 R, PF 1.25). Le filtre est trop
   * restrictif pour etre exploitable : chaque condition retire des setups
   * valides, et leur intersection est quasiment vide. A garder comme
   * reference de la checklist, pas comme reglage de production.
   */
  checklist: {
    entry: { model: 'fvg', fvgLevel: 0.75 },
    filters: {
      premiumDiscount: 'mssLeg',
      silverBullet: 'fill',
      newsBlackout: 'all',
    },
    sweep: { requireInducement: true },
    refs: {
      dxy: { mode: 'require', onMissing: 'pass' },
      us10y: { mode: 'alignTrend', onMissing: 'pass' },
    },
  },

  /**
   * Audit uniquement : borne SUPERIEURE de performance (hypothese intra-barre
   * optimiste). Sert a mesurer l'incertitude d'execution, JAMAIS a decider.
   */
  auditOptimistic: {
    execution: { intrabar: 'optimistic' },
  },
};

/** @param {string} name */
export function getPreset(name) {
  if (!(name in PRESETS)) {
    throw new Error(
      `Prereglage inconnu : "${name}". Disponibles : ${Object.keys(PRESETS).join(', ')}`
    );
  }
  return PRESETS[name];
}
