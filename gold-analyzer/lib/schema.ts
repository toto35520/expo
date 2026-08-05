import { MODULES } from './modules';

/**
 * Schéma JSON pour `output_config.format`.
 *
 * Contraintes de l'API structured outputs :
 *  - `additionalProperties: false` obligatoire sur chaque objet
 *  - toutes les propriétés doivent figurer dans `required`
 *  - pas de contraintes numériques (minimum/maximum) ni de longueur de chaîne
 *  → les bornes sont donc décrites en toutes lettres dans `description`.
 */
export const ANALYSIS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['dataQuality', 'modules', 'tradePlan', 'synthesis'],
  properties: {
    dataQuality: {
      type: 'object',
      additionalProperties: false,
      required: ['completeness', 'notes', 'missing'],
      properties: {
        completeness: {
          type: 'integer',
          description:
            "Entier de 0 à 100. Part des données nécessaires réellement disponibles. Des graphiques seuls, sans aucune donnée macro/flux/options, ne dépassent pas 40.",
        },
        notes: {
          type: 'string',
          description: 'Ce que l’absence de données empêche de conclure.',
        },
        missing: {
          type: 'array',
          items: { type: 'string' },
          description: 'Données manquantes, nommées précisément.',
        },
      },
    },
    modules: {
      type: 'array',
      description:
        'Exactement une entrée par module, dans l’ordre des identifiants fournis. Aucun module ne peut être omis.',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['id', 'status', 'score', 'confidence', 'findings', 'dataGaps', 'reasoning'],
        properties: {
          id: {
            type: 'string',
            enum: MODULES.map((m) => m.id),
          },
          status: {
            type: 'string',
            enum: ['PASS', 'WARN', 'FAIL', 'UNKNOWN'],
            description:
              'PASS = la couche soutient le setup. WARN = elle le tolère avec réserve. FAIL = elle le contredit. UNKNOWN = données insuffisantes pour se prononcer.',
          },
          score: {
            type: 'integer',
            description:
              'Entier de 0 à 100. 50 = neutre. UNKNOWN reste entre 45 et 55 : une donnée absente n’est jamais un point favorable.',
          },
          confidence: {
            type: 'string',
            enum: ['HIGH', 'MEDIUM', 'LOW', 'NONE'],
            description: 'Fiabilité de ce verdict compte tenu des données réellement disponibles.',
          },
          findings: {
            type: 'array',
            items: { type: 'string' },
            description:
              'Constats concrets, un par ligne. Chiffres et niveaux uniquement s’ils sont lisibles sur les graphiques ou fournis en contexte.',
          },
          dataGaps: {
            type: 'array',
            items: { type: 'string' },
            description: 'Ce qui manque pour trancher cette couche.',
          },
          reasoning: {
            type: 'string',
            description: 'Deux à quatre phrases. Le raisonnement, pas un résumé des constats.',
          },
        },
      },
    },
    tradePlan: {
      type: 'object',
      additionalProperties: false,
      required: [
        'hasTrade',
        'direction',
        'setupName',
        'timeframe',
        'entryType',
        'entry',
        'stop',
        'tp1',
        'tp2',
        'trigger',
        'invalidation',
        'rationale',
        'riskNotes',
      ],
      properties: {
        hasTrade: {
          type: 'boolean',
          description:
            'false dès qu’aucun setup ne réunit les conditions. C’est la réponse attendue la plupart du temps.',
        },
        direction: { type: 'string', enum: ['LONG', 'SHORT', 'NONE'] },
        setupName: {
          type: 'string',
          description: 'Nom court du setup, ou chaîne vide si aucun trade.',
        },
        timeframe: { type: 'string', description: 'Timeframe d’exécution (ex. M15 sur biais H4).' },
        entryType: {
          type: 'string',
          enum: ['MARKET', 'LIMIT', 'STOP', 'CONFIRMATION', 'NONE'],
          description:
            'CONFIRMATION = attendre balayage puis changement de caractère avant d’entrer. C’est le mode par défaut sur l’or.',
        },
        entry: { type: 'number', description: 'Prix d’entrée. 0 si aucun trade.' },
        stop: { type: 'number', description: 'Stop structurel + buffer ATR. 0 si aucun trade.' },
        tp1: { type: 'number', description: 'Premier objectif. 0 si aucun trade.' },
        tp2: { type: 'number', description: 'Second objectif. 0 si aucun trade.' },
        trigger: {
          type: 'string',
          description: 'Le déclencheur exact à observer avant d’entrer. Vide si aucun trade.',
        },
        invalidation: {
          type: 'string',
          description: 'Ce qui invalide la thèse, indépendamment du stop.',
        },
        rationale: {
          type: 'string',
          description:
            'Pourquoi ce trade, en reliant les couches qui le portent. Si hasTrade est false : pourquoi il n’y a pas de trade.',
        },
        riskNotes: {
          type: 'array',
          items: { type: 'string' },
          description: 'Risques spécifiques : news, spread, gap, corrélation, liquidité de session.',
        },
      },
    },
    synthesis: {
      type: 'object',
      additionalProperties: false,
      required: [
        'regime',
        'dominantDriver',
        'bias',
        'summary',
        'reactionCheck',
        'whatWouldChangeMyMind',
      ],
      properties: {
        regime: {
          type: 'string',
          description: 'Régime identifié : tendance/range, vol en expansion/contraction.',
        },
        dominantDriver: {
          type: 'string',
          description:
            'Quel driver gouverne l’or en ce moment : taux réels, dollar, banques centrales, géopolitique, flux techniques.',
        },
        bias: { type: 'string', description: 'Biais directionnel HTF en une phrase.' },
        summary: {
          type: 'string',
          description: 'Trois à cinq phrases. L’essentiel d’abord.',
        },
        reactionCheck: {
          type: 'string',
          description:
            'Lecture de la réaction du prix aux dernières données : conforme, ou divergente (donc épuisement) ?',
        },
        whatWouldChangeMyMind: {
          type: 'string',
          description: 'Le fait précis qui retournerait cette lecture.',
        },
      },
    },
  },
} as const;
