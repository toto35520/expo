/**
 * Les 14 couches d'analyse. L'ordre est celui dans lequel elles sont présentées.
 *
 * `weight`  : poids dans le score pondéré (somme = 100)
 * `gate`    : si true, un statut FAIL sur ce module rend le trade éliminatoire
 *             quel que soit le score des autres modules.
 */

export type ModuleId =
  | 'macro'
  | 'calendar'
  | 'structure'
  | 'levels'
  | 'orderflow'
  | 'priceaction'
  | 'options'
  | 'physical'
  | 'flows'
  | 'correlations'
  | 'regime'
  | 'seasonality'
  | 'reaction'
  | 'execution';

export interface ModuleDef {
  id: ModuleId;
  n: number;
  title: string;
  weight: number;
  gate: boolean;
  /** Ce que la couche doit établir — repris tel quel dans le prompt système. */
  brief: string;
}

export const MODULES: ModuleDef[] = [
  {
    id: 'macro',
    n: 1,
    title: 'Macro & taux réels',
    weight: 12,
    gate: false,
    brief:
      "Taux réels US (10y TIPS), DXY, anticipations Fed (dot plot, futures Fed funds), CPI/PPI/PCE et emploi lus à travers leur effet sur la trajectoire des taux. Identifier quel régime macro domine actuellement : taux réels, dollar, achats de banques centrales, ou prime de risque géopolitique. La corrélation or/taux réels se casse par périodes — dire laquelle gouverne le prix maintenant plutôt que réciter un modèle figé.",
  },
  {
    id: 'calendar',
    n: 2,
    title: 'Calendrier économique & risque événementiel',
    weight: 6,
    gate: true,
    brief:
      "Événements à fort impact dans la fenêtre du trade (FOMC, CPI, NFP, PPI, PCE, discours Fed, fixings de Londres 10h30 et 15h00 UK). FAIL si un événement à fort impact tombe pendant la durée de vie prévue du trade sans que ce soit la thèse elle-même. Le rollover broker (00h) élargit le spread.",
  },
  {
    id: 'structure',
    n: 3,
    title: 'Structure de marché multi-timeframe',
    weight: 14,
    gate: true,
    brief:
      "Top-down strict : Weekly/Daily donnent le biais, H4 la structure, H1/M30 le setup, M5 le déclencheur. HH/HL vs LH/LL, BOS, CHoCH. FAIL si les timeframes se contredisent (setup contre le biais HTF sans CHoCH confirmé sur le HTF), ou si les graphiques fournis ne permettent pas d'établir la structure.",
  },
  {
    id: 'levels',
    n: 4,
    title: 'Niveaux clés & pools de liquidité',
    weight: 10,
    gate: false,
    brief:
      "Plus haut/bas de la veille (PDH/PDL), de la semaine (PWH/PWL), du mois. Chiffres ronds — l'or respecte fortement les paliers de 10, 50 et 100 $. Égalités de hauts/bas, pools de stops, ouverture hebdomadaire. Ne jamais inventer un niveau : ne citer que des prix effectivement lisibles sur les graphiques fournis.",
  },
  {
    id: 'orderflow',
    n: 5,
    title: 'Order flow & volume réel',
    weight: 8,
    gate: false,
    brief:
      "Le volume affiché sur un graphique XAUUSD de broker CFD est du TICK VOLUME, pas du volume réel — le vrai marché est le future GC au COMEX. Le dire explicitement si l'utilisateur n'a fourni que des graphiques CFD. Chercher : absorption (prix qui plafonne sur volume élevé), initiative (mouvement sur faible volume), POC / VAH / VAL, nœuds de haut et faible volume. Statut UNKNOWN si aucune donnée de volume réel n'est disponible.",
  },
  {
    id: 'priceaction',
    n: 6,
    title: 'Price action & mécanique (FVG, OB, sweeps)',
    weight: 8,
    gate: false,
    brief:
      "Traduire le vocabulaire SMC en mécanique de marché : FVG = zone de faible volume / inefficience ; order block = point d'initiation ou zone d'absorption ; liquidity sweep = cascade de stops ; breaker = polarité support/résistance. Ces zones sont des outils de TIMING D'ENTRÉE, jamais une thèse directionnelle. Sur l'or, ne jamais valider un ordre limite nu dans une zone : exiger balayage → CHoCH sur timeframe inférieur → entrée. Signaler si une zone n'est adossée à aucun volume ni aucun niveau structurel.",
  },
  {
    id: 'options',
    n: 7,
    title: 'Options & positionnement dealer',
    weight: 5,
    gate: false,
    brief:
      "GEX sur GLD / options GC : dealers long gamma → marché compressé, range, fade des extrêmes ; short gamma → mouvements amplifiés, breakouts qui vont loin. GVZ (vol implicite) vs volatilité réalisée. Risk reversal 25-delta pour le sentiment institutionnel. Expirations d'options (fin de mois précédant le mois de livraison) : aimantation vers les gros strikes. UNKNOWN si non renseigné.",
  },
  {
    id: 'physical',
    n: 8,
    title: 'Marché physique & courbe des futures',
    weight: 4,
    gate: false,
    brief:
      "Contango / backwardation, spread EFP (dislocation Londres/COMEX), stocks COMEX registered vs eligible, taux de lease de l'or / GOFO, prime ou décote du Shanghai Gold Exchange (demande physique chinoise réelle), flux des douanes suisses. Une décote de Shanghai = la Chine n'achète plus, information invisible sur le graphique. UNKNOWN si non renseigné.",
  },
  {
    id: 'flows',
    n: 9,
    title: 'Flux & positionnement',
    weight: 5,
    gate: false,
    brief:
      "COT (managed money net) — les extrêmes sont un signal contrariant, pas un signal d'entrée. Encours ETF (GLD, IAU). Niveaux de bascule des CTA. Fonds vol-targeting qui réduisent mécaniquement quand la vol monte. Rebalancements de fin de mois/trimestre. Roll des indices matières premières (5e au 9e jour ouvré). Achats de banques centrales. UNKNOWN si non renseigné.",
  },
  {
    id: 'correlations',
    n: 10,
    title: 'Corrélations intermarchés',
    weight: 6,
    gate: false,
    brief:
      "DXY (inverse, sauf régime de crise), argent et ratio or/argent, taux réels/TIPS, VIX/S&P pour l'appétit au risque, Bitcoin comme concurrent du trade de débasement, cuivre pour le cycle industriel. Point clé : si l'or ET le dollar montent ensemble, ce n'est pas une anomalie — c'est un signal de stress systémique ou de dé-dollarisation, et ça change la lecture. Utiliser des corrélations glissantes, pas supposées.",
  },
  {
    id: 'regime',
    n: 11,
    title: 'Détection de régime',
    weight: 8,
    gate: true,
    brief:
      "Volatilité en expansion ou en contraction (ATR sur ATR, bandes de Bollinger). Tendance ou range (ADX, indice de choppiness). En range → mean reversion, on fade les extrêmes. En expansion → breakout, on suit. FAIL si le setup proposé est du mean reversion en régime d'expansion, ou du breakout en plein range compressé : appliquer la mauvaise stratégie au mauvais régime est la première cause de séries de pertes.",
  },
  {
    id: 'seasonality',
    n: 12,
    title: 'Saisonnalité & timing de session',
    weight: 3,
    gate: false,
    brief:
      "Saisonnalité de l'or (janvier et août-septembre historiquement porteurs, mars et juin-juillet plus faibles ; restockage nouvel an chinois, saison des mariages indiens). Session : range asiatique → manipulation/balayage à l'open de Londres (08h-10h UK) → vrai mouvement ; plus grosse volatilité à l'open NY et sur les données (13h30-15h00 UK). La saisonnalité est un départage, jamais une thèse.",
  },
  {
    id: 'reaction',
    n: 13,
    title: 'Réaction au news (plus important que le news)',
    weight: 4,
    gate: false,
    brief:
      "Ce qui compte n'est pas la donnée, c'est comment le prix y répond. News haussière + l'or monte = normal, peu d'information. News haussière + l'or BAISSE = épuisement fort, souvent un sommet : tous ceux qui devaient acheter ont acheté. News baissière + l'or refuse de baisser = acheteur structurel dessous. Cette lecture prime sur n'importe quelle prévision.",
  },
  {
    id: 'execution',
    n: 14,
    title: 'Exécution, dimensionnement & risque',
    weight: 7,
    gate: true,
    brief:
      "ATR obligatoire sur l'or : avec des ranges journaliers de 30 à 60 $, un stop en pips fixes n'a aucun sens. Stop placé sur la structure + buffer ATR, jamais sur ce que l'utilisateur est prêt à perdre. Spread qui explose au rollover et sur les news. Risque de gap du week-end (l'or gappe le dimanche sur news géopolitique). Swap overnight souvent négatif dans les deux sens. FAIL si aucun stop structurel n'est identifiable, si le stop est absurde par rapport à l'ATR, ou si le trade impose de tenir à travers une news à fort impact.",
  },
];

export const MODULE_BY_ID = Object.fromEntries(
  MODULES.map((m) => [m.id, m]),
) as Record<ModuleId, ModuleDef>;

export const TOTAL_WEIGHT = MODULES.reduce((s, m) => s + m.weight, 0);
