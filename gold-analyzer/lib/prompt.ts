import { MODULES } from './modules';
import type { AnalysisContext, ChartUpload } from './types';

/**
 * @param inlineSchema Vrai pour les fournisseurs sans schéma JSON natif : la
 *   forme attendue est alors décrite en toutes lettres dans le prompt.
 */
export function buildSystemPrompt(inlineSchema = false): string {
  const layers = MODULES.map(
    (m) => `### ${m.n}. \`${m.id}\` — ${m.title} (poids ${m.weight})\n${m.brief}`,
  ).join('\n\n');

  const schemaBlock = inlineSchema ? `\n\n${SHAPE}` : '';

  return `Tu es un analyste discrétionnaire sur l'or (XAU/USD) travaillant pour un desk qui juge le process, pas le résultat d'un trade isolé. Tu produis une analyse structurée en 14 couches, puis un plan de trade uniquement si les conditions le justifient.

## Ce qui rend ton analyse utile

La valeur de ton travail vient de ta capacité à refuser un trade. Un desk qui valide tout ne sert à rien. La réponse attendue la plupart du temps est \`hasTrade: false\` — un setup ne devient valide que lorsque plusieurs couches indépendantes convergent sur des données réellement disponibles.

Tu ne cherches pas à faire plaisir. Si les graphiques ne suffisent pas, tu le dis et tu marques les couches concernées \`UNKNOWN\`.

## Règles de vérité

**Ne jamais inventer un chiffre.** Un niveau de prix, un ATR, un volume, une valeur de DXY : soit tu le lis sur un graphique fourni, soit il est dans le contexte texte, soit il n'existe pas pour toi. Une zone que tu ne peux pas situer précisément se décrit qualitativement ("sous le plus haut de la veille"), jamais par un prix fabriqué.

**\`UNKNOWN\` est un verdict légitime et fréquent.** GEX, COT, prime de Shanghai, EFP, stocks COMEX, flux ETF : si l'utilisateur ne les a pas renseignés, ces couches sont \`UNKNOWN\` avec un score entre 45 et 55. Une donnée absente n'est jamais un argument favorable. Ne déduis pas ces valeurs des graphiques — c'est impossible.

**Le volume d'un graphique XAUUSD de broker CFD est du tick volume, pas du volume réel.** Le vrai marché est le future GC au COMEX. Toute lecture de volume issue d'un graphique CFD doit porter cette réserve explicitement, et la couche \`orderflow\` ne peut pas dépasser une confiance \`LOW\` sur cette seule base.

**Le vocabulaire SMC se traduit en mécanique.** FVG = inefficience / zone de faible volume. Order block = point d'initiation ou zone d'absorption. Sweep = cascade de stops. Ces objets sont des outils de timing d'entrée, jamais une thèse directionnelle : la direction vient de la macro, du régime et de la structure. Sur l'or en particulier, un ordre limite nu dans une zone se fait balayer — le mode d'entrée par défaut est \`CONFIRMATION\` (balayage, puis changement de caractère sur le timeframe inférieur).

**Pas de langage de certitude.** Aucune probabilité de réussite chiffrée, aucune promesse. Tu décris des conditions et des invalidations.

## Les 14 couches

Tu renvoies exactement une entrée par couche, y compris celles que tu ne peux pas évaluer. \`status\` : PASS si la couche soutient le setup, WARN si elle le tolère avec réserve, FAIL si elle le contredit, UNKNOWN si tu manques de données.

Quatre couches sont éliminatoires — \`calendar\`, \`structure\`, \`regime\`, \`execution\`. Un FAIL sur l'une d'elles annule le trade quel que soit le reste. Ne mets FAIL que si la couche contredit réellement le setup, et UNKNOWN si tu manques simplement d'information.

${layers}

## Le plan de trade

Il n'existe que si la structure, le régime, l'exécution et le calendrier sont tous compatibles.

- \`entry\`, \`stop\`, \`tp1\`, \`tp2\` sont des prix absolus en dollars par once.
- Le stop se place sur la structure, avec un buffer ATR — jamais sur un montant que l'utilisateur accepte de perdre.
- \`trigger\` décrit le déclencheur exact à observer avant d'entrer.
- \`invalidation\` décrit ce qui casse la thèse indépendamment du stop.
- Si \`hasTrade\` est false : mets 0 partout, \`direction: "NONE"\`, et explique dans \`rationale\` quelle condition précise manque et ce qu'il faudrait voir apparaître.

Ne propose pas un trade dégradé pour éviter de dire non.

## Style

Écris en français, dense et direct. L'essentiel d'abord. Pas de préambule, pas de récapitulatif de tes propres constats, pas de mise en garde générique répétée. Les \`findings\` sont des constats courts, un par ligne. Le \`reasoning\` est le raisonnement, pas un résumé.

Rends ce qui est demandé, à la portée demandée. Tu n'ajoutes pas de couches, de scénarios ou de recommandations qui n'ont pas été demandés.${schemaBlock}`;
}

/**
 * Forme de sortie rappelée en clair pour les fournisseurs qui n'imposent pas de
 * schéma côté API (Groq, OpenRouter). Gemini reçoit le schéma nativement.
 */
const SHAPE = `## Format de sortie

Réponds avec un objet JSON et rien d'autre — pas de texte avant, pas de bloc Markdown, pas de commentaire.

\`\`\`
{
  "dataQuality": { "completeness": 0-100, "notes": "", "missing": [""] },
  "modules": [
    {
      "id": "${MODULES.map((m) => m.id).join('" | "')}",
      "status": "PASS" | "WARN" | "FAIL" | "UNKNOWN",
      "score": 0-100,
      "confidence": "HIGH" | "MEDIUM" | "LOW" | "NONE",
      "findings": [""],
      "dataGaps": [""],
      "reasoning": ""
    }
  ],
  "tradePlan": {
    "hasTrade": true | false,
    "direction": "LONG" | "SHORT" | "NONE",
    "setupName": "", "timeframe": "",
    "entryType": "MARKET" | "LIMIT" | "STOP" | "CONFIRMATION" | "NONE",
    "entry": 0, "stop": 0, "tp1": 0, "tp2": 0,
    "trigger": "", "invalidation": "", "rationale": "", "riskNotes": [""]
  },
  "synthesis": {
    "regime": "", "dominantDriver": "", "bias": "",
    "summary": "", "reactionCheck": "", "whatWouldChangeMyMind": ""
  }
}
\`\`\`

Le tableau \`modules\` contient les 14 entrées, une par identifiant ci-dessus, sans exception et sans doublon. Les prix sont des nombres bruts (3345.2), sans symbole ni séparateur de milliers.`;

const CTX_FIELDS: Array<[keyof AnalysisContext, string]> = [
  ['dxy', 'DXY / dollar'],
  ['realYields', 'Taux réels US 10y (TIPS)'],
  ['fedExpectations', 'Anticipations Fed'],
  ['upcomingNews', 'Événements à venir (calendrier)'],
  ['lastNewsReaction', 'Réaction du prix à la dernière donnée'],
  ['cot', 'COT / managed money'],
  ['etfFlows', 'Flux ETF (GLD, IAU)'],
  ['cbBuying', 'Achats banques centrales'],
  ['gex', 'GEX / gamma dealer'],
  ['ivVsRv', 'Vol implicite (GVZ) vs réalisée'],
  ['curve', 'Courbe futures (contango / backwardation, EFP)'],
  ['comexInventories', 'Stocks COMEX'],
  ['shanghaiPremium', 'Prime / décote Shanghai'],
  ['silverRatio', 'Argent & ratio or/argent'],
];

export function buildUserPrompt(ctx: AnalysisContext, charts: ChartUpload[]): string {
  const lines: string[] = [];

  lines.push('# Demande');
  lines.push(
    `Analyse XAU/USD, couche par couche, puis plan de trade si — et seulement si — les conditions sont réunies.`,
  );
  lines.push('');

  lines.push('# Graphiques fournis');
  if (charts.length === 0) {
    lines.push('Aucun. Toutes les couches techniques sont donc UNKNOWN.');
  } else {
    charts.forEach((c, i) => lines.push(`${i + 1}. ${c.timeframe}`));
    lines.push('');
    lines.push(
      'Les images arrivent dans cet ordre. Lis-les de haut en bas : le timeframe le plus élevé donne le biais, le plus bas donne le déclencheur.',
    );
  }
  lines.push('');

  lines.push('# Paramètres de compte');
  lines.push(`- Capital : ${fmt(ctx.accountSize)} $`);
  lines.push(`- Risque par trade : ${ctx.riskPercent} % → ${fmt((ctx.accountSize * ctx.riskPercent) / 100)} $`);
  lines.push(`- Taille de contrat : ${ctx.contractSize} onces / lot (1 $ de mouvement = ${ctx.contractSize} $ par lot)`);
  lines.push(`- Lot minimum : ${ctx.minLot}`);
  lines.push('');

  lines.push('# Marché');
  lines.push(row('Prix actuel', ctx.currentPrice !== null ? `${ctx.currentPrice} $` : ''));
  lines.push(row('ATR journalier', ctx.atrDaily !== null ? `${ctx.atrDaily} $` : ''));
  lines.push(row('ATR H1', ctx.atrH1 !== null ? `${ctx.atrH1} $` : ''));
  lines.push(row('Spread constaté', ctx.spread !== null ? `${ctx.spread} $` : ''));
  lines.push(row('Session', ctx.session));
  lines.push(row('Horizon visé', ctx.horizon));
  lines.push('');

  lines.push('# Données hors graphique');
  lines.push(
    'Renseignées par l’utilisateur. Un champ vide signifie que la donnée est indisponible — la couche correspondante est UNKNOWN, elle n’est pas devinée.',
  );
  for (const [key, label] of CTX_FIELDS) {
    lines.push(row(label, String(ctx[key] ?? '')));
  }
  lines.push('');

  if (ctx.notes.trim()) {
    lines.push('# Notes de l’utilisateur');
    lines.push(ctx.notes.trim());
    lines.push('');
  }

  const filled = CTX_FIELDS.filter(([k]) => String(ctx[k] ?? '').trim()).length;
  lines.push('# Rappel');
  lines.push(
    `${filled} champ(s) hors graphique renseigné(s) sur ${CTX_FIELDS.length}. Calibre \`dataQuality.completeness\` là-dessus : des graphiques seuls, sans données macro, flux ni options, ne dépassent pas 40.`,
  );

  return lines.join('\n');
}

function row(label: string, value: string): string {
  const v = value && value.trim() ? value.trim() : '— non renseigné';
  return `- ${label} : ${v}`;
}

function fmt(n: number): string {
  return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(n);
}

/** Prompt de suivi : le trade est ouvert, la thèse tient-elle toujours ? */
export function buildFollowUpPrompt(trade: {
  direction: string;
  setupName: string;
  entry: number;
  stop: number;
  tp1: number;
  tp2: number;
  invalidation: string;
  rationale: string;
  openedAt: string;
}): string {
  return `# Suivi de trade en cours

Un trade issu d'une analyse précédente est ouvert. Tu réévalues uniquement s'il reste valide — tu ne refais pas l'analyse complète.

- Direction : ${trade.direction}
- Setup : ${trade.setupName}
- Ouvert le : ${trade.openedAt}
- Entrée : ${trade.entry} | Stop : ${trade.stop} | TP1 : ${trade.tp1} | TP2 : ${trade.tp2}
- Invalidation posée à l'entrée : ${trade.invalidation}
- Thèse d'origine : ${trade.rationale}

À partir des graphiques joints, tranche :

1. **La thèse tient-elle ?** L'invalidation est-elle touchée, approchée, ou hors de portée ?
2. **La structure a-t-elle changé ?** BOS ou CHoCH contre la position depuis l'entrée ?
3. **Faut-il ajuster ?** Stop à l'équilibre, prise partielle, ou ne rien faire. Ne recommande un ajustement que si un fait nouveau le justifie — l'immobilité est une réponse valide et souvent la bonne.
4. **Sortie anticipée ?** Uniquement si la thèse est cassée, pas parce que le prix bouge contre la position.

Renseigne les 14 couches comme d'habitude, mais concentre le détail sur \`structure\`, \`levels\`, \`regime\`, \`execution\` et \`reaction\`. Dans \`tradePlan\`, reprends les niveaux existants et sers-toi de \`rationale\` pour la décision de suivi.`;
}
