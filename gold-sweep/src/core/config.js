/**
 * Jeu de parametres complet de la strategie "NY Open Liquidity Sweep" sur XAUUSD.
 *
 * Chaque champ est documente avec : ce qu'il fait, la valeur par defaut issue
 * de la description de la strategie, et la plage utile pour l'optimisation.
 * Aucune valeur n'est codee en dur ailleurs dans le moteur.
 */

import { parseHm, formatHm } from './time.js';

export const DEFAULTS = {
  // ─────────────────────────── INSTRUMENT ───────────────────────────
  instrument: {
    /** Nom du symbole cote broker. */
    symbol: 'XAUUSD',
    /** Taille d'1 pip en USD de cotation. Or 2/3 decimales : 1 pip = 0.10 $. */
    pipSize: 0.1,
    /** Onces par lot standard. */
    contractSize: 100,
    /** Decimales de cotation (arrondi des niveaux d'ordre). */
    digits: 2,
    /** Volume minimum / pas / maximum en lots. */
    minLots: 0.01,
    lotStep: 0.01,
    maxLots: 100,
    /**
     * Volume brut cTrader correspondant a 1 lot. Chez la plupart des brokers
     * le volume est exprime en centiemes d'unite de base : XAUUSD, 1 lot =
     * 100 onces -> 10000.
     *
     * A CONFIRMER sur votre compte avec `gs-live discover --symbol XAUUSD`
     * avant toute execution reelle : c'est ce nombre qui determine la taille
     * de vos positions.
     */
    apiVolumePerLot: 10_000,
  },

  // ───────────────────────────── COUTS ──────────────────────────────
  costs: {
    /** Spread moyen en USD (bid/ask). L'or : 0.15-0.35 typique, 0.6+ sur news. */
    spreadUsd: 0.22,
    /** Spread additionnel applique dans la fenetre news (elargissement). */
    spreadUsdNews: 0.45,
    /** Commission par lot et par cote (aller = 1 cote, retour = 1 cote). */
    commissionPerLotPerSide: 0,
    /** Slippage sur execution au marche / stop (USD). Les limites ne slippent pas. */
    slippageUsdOnStop: 0.06,
    /** Slippage sur les ordres limite (0 : une limite se remplit au prix ou mieux). */
    slippageUsdOnLimit: 0,
  },

  // ──────────────────────── SESSIONS / HORAIRES ─────────────────────
  // Toutes les heures sont en GMT tel que decrit par la strategie
  // (referentiel heure d'ete). Voir `anchor` pour le glissement DST.
  sessions: {
    /** 'gmt' = heures GMT figees ; 'local' = ancre sur l'heure locale Londres. */
    londonAnchor: 'gmt',
    /** 'gmt' = heures GMT figees ; 'local' = ancre sur l'heure locale New York. */
    nyAnchor: 'gmt',

    /** Phase 1 : fenetre de construction du range de Londres. */
    londonStart: '07:00',
    londonEnd: '12:00',
    /** Inclure la barre ouvrant exactement a londonEnd dans le range. */
    londonEndInclusive: false,

    /** Phase 2 : fenetre pendant laquelle le balayage (sweep) est valide. */
    sweepStart: '13:00',
    sweepEnd: '14:30',

    /** Phase 3 : dernier instant ou le MSS peut se produire. */
    confirmEnd: '14:45',

    /** Phase 4 : expiration de l'ordre limite d'entree (heure absolue). */
    entryExpiry: '16:00',

    /** Cloture forcee de toute position encore ouverte (fin de journee de trading). */
    forceCloseAt: '20:00',

    /** Fenetre de l'annonce economique US (reference 13:30 GMT). */
    newsTime: '13:30',
    newsWindowMinutes: 15,

    /**
     * Aucun signal n'est accepte avant cette heure : on laisse la bougie de
     * 13h30 balayer la liquidite de Londres de maniere agressive et on
     * n'analyse la reaction qu'ensuite ("a partir de 13h35-13h40").
     */
    signalNotBefore: '13:35',

    /**
     * Fenetre "Silver Bullet" ICT : plage horaire ou le retour dans le FVG se
     * declenche le plus souvent. Activee par `filters.silverBullet`.
     */
    silverBulletStart: '14:00',
    silverBulletEnd: '15:00',

    /** Jours de la semaine autorises (0=dim .. 6=sam). */
    weekdays: [1, 2, 3, 4, 5],

    /** Dates "YYYY-MM-DD" a exclure (feries, demi-seances). */
    skipDates: [],

    /** Nombre minimum de barres M5 requises dans la session de Londres (60 = complete). */
    minLondonBars: 48,

    /**
     * Restriction de la periode evaluee, "YYYY-MM-DD" (null = tout l'historique).
     * L'ATR reste calcule sur l'historique complet : pas de perte de warmup
     * quand on decoupe en in-sample / out-of-sample.
     */
    dateFrom: null,
    dateTo: null,
  },

  // ───────────────────────── PHASE 2 : SWEEP ────────────────────────
  sweep: {
    /** 'both' | 'highOnly' (ventes seules) | 'lowOnly' (achats seuls). */
    side: 'both',
    /**
     * Unite des seuils de penetration : 'pips' | 'atr' | 'pctPrice' | 'rangePct'.
     * 'atr' est le defaut : l'ATR M5 de l'or est passe de 0.96$ (2021) a 5.29$
     * (2026), tout seuil en USD absolu derive completement sur 5 ans.
     */
    penetrationMode: 'atr',
    /** Penetration MINIMUM au-dela du niveau pour valider un balayage. */
    minPenetration: 0.05,
    /**
     * Penetration MAXIMUM : au-dela, c'est une vraie cassure -> jour invalide.
     * 3.0 ATR calibre sur la distribution mesuree (mediane de la penetration
     * au moment du MSS : 1.67 ATR, p75 : 2.85 ATR).
     */
    maxPenetration: 3.0,
    /** Exiger une cloture de retour DANS le range apres le balayage (rejet). */
    requireCloseBack: false,
    /** Nombre max de barres pour que la cloture de retour survienne. */
    closeBackMaxBars: 6,
    /** Nombre max de balayages traites par jour (1 = seulement le premier). */
    maxPerDay: 1,

    /**
     * INDUCEMENT (faux balayage). Les algorithmes posent souvent un petit
     * sommet JUSTE SOUS le Haut de Londres : c'est un aimant a liquidite qui
     * piege les vendeurs presses. Le vrai balayage doit nettoyer ce sommet ET
     * le niveau de Londres d'un seul coup.
     *
     * `requireInducement: true` n'accepte le setup que si un tel aimant
     * existait bien avant le balayage — c'est la signature du piege.
     */
    requireInducement: false,
    /** Profondeur minimale de l'inducement SOUS le niveau de Londres. */
    inducementMinDepth: 0.2,
    /** Unite de inducementMinDepth. */
    inducementDepthMode: 'atr',
    /** Fenetre de recherche de l'inducement avant le balayage (barres). */
    inducementLookbackBars: 24,
    /** Autoriser un balayage du cote oppose apres invalidation du premier. */
    allowOppositeAfterFail: false,
  },

  // ────────────────── PHASE 3 : MSS + DEPLACEMENT + FVG ─────────────
  mss: {
    /**
     * Reference de structure cassee par le MSS :
     *  'fractal'              : dernier swing fractal confirme avant l'extreme du piege
     *  'lowestSinceCross'     : extreme oppose depuis le franchissement du niveau
     *  'priorBar'             : extreme de la barre precedant l'extreme du piege
     */
    ref: 'fractal',
    /** Taille du fractal (n barres de chaque cote). 2 -> fractal 5 barres. */
    swingLookback: 2,
    /** 'close' = la barre doit CLOTURER au-dela ; 'wick' = la meche suffit. */
    breakType: 'close',
    /** Unite de la marge de cassure : 'pips' | 'atr' | 'pctPrice'. */
    breakBufferMode: 'atr',
    /** Marge supplementaire exigee au-dela de la structure. */
    breakBuffer: 0,
    /**
     * Le MSS doit survenir dans les N barres M5 suivant le balayage.
     * 14 couvre le p75 du delai mesure (mediane 7 barres, p75 12, p90 16).
     */
    maxBarsAfterSweep: 14,
    /**
     * Repli si ref='fractal' ne trouve aucun swing confirme :
     * 'lowestSinceCross' (utiliser l'extreme oppose depuis le franchissement)
     * ou 'none' (abandonner le setup).
     */
    fallbackRef: 'lowestSinceCross',

    /** Deplacement ("bougie longue, pleine et violente"). */
    displacement: {
      /** Activer le filtre de deplacement. */
      enabled: true,
      /** Nombre de barres consecutives sur lesquelles mesurer la jambe. */
      lookbackBars: 2,
      /** Corps de la jambe >= N x ATR (mediane mesuree : 1.02 ATR). */
      minBodyAtrMult: 0.5,
      /** Corps / amplitude de la jambe >= N (bougie "pleine"). */
      minBodyRatio: 0.4,
      /** Amplitude de la jambe >= N x ATR. */
      minRangeAtrMult: 0.6,
    },
  },

  fvg: {
    /** Exiger un Fair Value Gap dans la jambe de deplacement. */
    required: true,
    /** Unite de la taille minimale : 'pips' | 'atr'. */
    minSizeMode: 'atr',
    /** Taille minimale du FVG. */
    minSize: 0.05,
    /** Choix du FVG si plusieurs : 'nearest' | 'largest' | 'first'. */
    selection: 'nearest',
    /** Extension AMONT de la recherche de FVG au-dela du debut de jambe (barres). */
    searchBars: 2,
    /** Accepter un FVG deja partiellement comble a l'emission du setup. */
    allowEncroached: true,
  },

  // ──────────────────────── PHASE 4 : ENTREE ────────────────────────
  entry: {
    /**
     * 'fvg'        : limite dans le Fair Value Gap
     * 'orderBlock' : limite sur l'Order Block (derniere bougie opposee avant la chute)
     * 'fvgOrOb'    : FVG si present, sinon Order Block
     * 'ote'        : retracement de Fibonacci de la jambe MSS
     * 'market'     : au marche a la cloture de la barre MSS (pas de pullback)
     */
    model: 'fvg',
    /**
     * Position de la limite dans le FVG :
     *  0.0 = bord proche (remplissage le plus probable, prix le moins bon)
     *  0.5 = milieu (Consequent Encroachment)
     *  1.0 = bord lointain (meilleur prix, remplissage le moins probable)
     *
     * 0.75 retenu : meilleur compromis mesure entre taux de remplissage (46%)
     * et R:R obtenu, et la seule valeur positive 5 annees sur 6.
     */
    fvgLevel: 0.75,
    /** Zone d'Order Block : 'body' | 'full' | 'upperHalf'. */
    obZone: 'body',
    /** Position de la limite dans l'Order Block (meme convention que fvgLevel). */
    obLevel: 0.5,
    /** Nombre max de barres a remonter pour trouver l'Order Block. */
    obLookbackBars: 6,
    /** Niveau de retracement pour le modele 'ote'. */
    oteLevel: 0.705,
    /** Expiration de l'ordre limite en barres M5 apres emission (0 = pas de limite). */
    expiryBars: 24,
    /** Annuler l'ordre si le prix atteint le SL avant d'etre rempli. */
    cancelIfSlTouched: true,
    /** Annuler l'ordre si le prix atteint le TP avant d'etre rempli (mouvement parti sans nous). */
    cancelIfTpTouched: true,
  },

  // ─────────────────────── STOP LOSS / TAKE PROFIT ──────────────────
  stop: {
    /**
     * 'sweepExtreme'     : juste au-dela du sommet du piege (description d'origine)
     * 'fvgDistal'        : bord lointain du FVG
     * 'structureExtreme' : extreme de structure le plus proche
     */
    anchor: 'sweepExtreme',
    /** Unite de la marge au-dela de l'ancre : 'pips' | 'atr' | 'pctPrice'. */
    bufferMode: 'atr',
    /**
     * Marge au-dela de l'ancre. Exprimee en ATR et non en pips fixes : a 2021
     * 0.30 ATR vaut ~2.9 pips, en 2026 ~16 pips — la protection reste
     * proportionnelle au bruit du marche.
     *
     * Le balayage systematique des valeurs montre que les stops SERRES sont
     * la premiere cause de perte : 0.15 ATR donne -9.4 R la ou 0.40 ATR donne
     * +10.5 R sur la meme periode. 0.30 est le milieu de la zone stable.
     */
    buffer: 0.3,

    /** Unite des bornes de distance de SL : 'usd' | 'atr' | 'pctPrice'. */
    distanceMode: 'atr',
    /**
     * Distance de SL minimale acceptee (sinon : bruit, stop-out garanti).
     * La strategie d'origine dit "15 a 30 pips" : c'etait 1.5-3 ATR a l'epoque
     * ou elle a ete ecrite, d'ou les bornes ATR retenues ici.
     */
    minDistance: 0.6,
    /**
     * Distance de SL maximale acceptee (sinon : risque trop large).
     * La distribution mesuree donne une mediane de 3.19 ATR : plafonner a
     * 3.0 ecarterait la moitie des setups valides.
     */
    maxDistance: 5.0,
  },

  target: {
    /**
     * 'oppositeLondon' : bas de Londres pour une vente (objectif d'origine)
     * 'rrMultiple'     : multiple de R fixe
     * 'nearestOf'      : le plus proche entre le niveau de Londres et le multiple de R
     */
    anchor: 'oppositeLondon',
    /** Unite du decalage de TP : 'pips' | 'atr' | 'pctPrice' | 'rangePct'. */
    offsetMode: 'atr',
    /**
     * Decalage du TP. NEGATIF = on se place AVANT le niveau (on devance la
     * liquidite pour garantir le remplissage plutot que d'esperer le tick exact).
     */
    offset: -0.1,
    /** Multiple de R si anchor='rrMultiple' / plafond si anchor='nearestOf'. */
    rrMultiple: 4,
    /**
     * Rejeter le setup si R:R < minRR.
     * La strategie annonce "1:3 a 1:5 minimum" mais le R:R MESURE avec TP au
     * niveau oppose de Londres a une mediane de 2.04 seulement : exiger 3
     * supprime 75% des setups. 2.0 est le seuil reellement atteignable.
     */
    minRR: 2.0,
    /** Rejeter le setup si R:R > maxRR (niveau de Londres aberrant). */
    maxRR: 25,
  },

  manage: {
    /**
     * Prise de profit partielle.
     *  anchor 'rr'                : a un multiple de R fixe
     *  anchor 'internalLiquidity' : au premier "plus bas" a court terme
     *                               rencontre en chemin (liquidite interne) —
     *                               l'or se deplace de poche de liquidite en
     *                               poche de liquidite, c'est la lecture pro
     * closePct : fraction de la position fermee
     * minRR    : partiel ignore s'il est trop proche de l'entree
     */
    partial: {
      enabled: false,
      anchor: 'rr',
      atRR: 2.0,
      closePct: 0.5,
      minRR: 0.8,
    },
    /** Passage au point mort : SL -> entree quand le prix atteint N x R (null = off). */
    breakEvenAtRR: null,
    /** Unite de la marge de point mort : 'pips' | 'atr' | 'pctPrice'. */
    breakEvenOffsetMode: 'atr',
    /** Marge ajoutee au point mort (couvre spread + commission). */
    breakEvenOffset: 0.1,
    /** Trailing stop : 'off' | 'atr'. */
    trail: 'off',
    trailAtrMult: 1.5,
    /** Sortie apres N barres M5 en position (0 = off). */
    maxHoldBars: 48,
  },

  // ───────────────────────────── FILTRES ────────────────────────────
  filters: {
    /** Periode de l'ATR M5 servant a tous les seuils relatifs. */
    atrPeriod: 14,
    /**
     * Regime de volatilite : ATR M5 exprime en % du prix, requis dans
     * [min, max] (null = off). En % du prix car l'ATR absolu de l'or a
     * quintuple sur la periode : 0.05% en 2021 comme en 2026 decrit le
     * meme regime de marche.
     */
    atrPctPriceMin: null,
    atrPctPriceMax: null,
    /** Unite des bornes du range de Londres : 'usd' | 'atr' | 'pctPrice'. */
    londonRangeMode: 'atr',
    /** Amplitude du range de Londres requise dans [min, max] (null = off). */
    londonRangeMin: 3.0,
    londonRangeMax: null,
    /**
     * Filtre news : 'off' | 'require' (le balayage doit tomber dans la fenetre
     * news) | 'avoid' (l'eviter).
     */
    news: 'off',

    /**
     * BLACKOUT DES ANNONCES DESTRUCTRICES (NFP, CPI, FOMC).
     * Ces jours-la les spreads explosent, les stops slippent de plusieurs
     * dizaines de pips et le risque n'est plus maitrisable.
     *
     *   'off'             : desactive
     *   'volatilitySpike' : detecte a l'empreinte (amplitude de la bougie de
     *                       13h30 > newsSpikeAtrMult x ATR). Ne demande AUCUNE
     *                       donnee externe et attrape la vraie publication
     *                       destructrice quel que soit son nom.
     *   'nfp'             : 1er vendredi du mois (calculable sans donnee)
     *   'calendar'        : jours d'impact 'high' du CSV de calendrier fourni
     *   'all'             : l'union des trois
     */
    newsBlackout: 'off',
    /** Seuil du detecteur de choc, en multiples d'ATR. */
    newsSpikeAtrMult: 3.0,
    /** Biais journalier : 'off' | 'dailyOpen' (vendre sous l'open D1 interdit). */
    dailyBias: 'off',
    /** Unite de la proximite PDH/PDL : 'usd' | 'atr' | 'pctPrice'. */
    pdhPdlProximityMode: 'atr',
    /** Confluence : le niveau balaye doit etre a moins de N du PDH/PDL (null = off). */
    pdhPdlProximity: null,
    /**
     * Premium / Discount (juste valeur). Un professionnel ne vend jamais bon
     * marche : l'entree doit se situer dans la moitie HAUTE de la structure
     * pour une vente, dans la moitie BASSE pour un achat.
     *   'off'         : desactive
     *   'londonRange' : mesure sur le range de Londres (High -> Low)
     *   'mssLeg'      : mesure sur la structure de retournement (extreme du
     *                   piege -> bas de la jambe MSS) — c'est la lecture ICT
     *                   stricte de "l'entree doit etre au-dessus des 50%"
     *   'both'        : les deux conditions
     */
    premiumDiscount: 'off',
    /** Seuil de Fibonacci separant premium et discount. */
    premiumThreshold: 0.5,

    /**
     * Filtre horaire Silver Bullet :
     *   'off'    : desactive
     *   'signal' : le MSS doit tomber dans la fenetre Silver Bullet
     *   'fill'   : le remplissage de la limite doit tomber dans la fenetre
     *   'both'   : les deux
     */
    silverBullet: 'off',

    /** Nombre maximum de trades par jour. */
    maxTradesPerDay: 1,
    /** Coupe-circuit : arret apres N pertes consecutives (0 = off). */
    maxConsecutiveLosses: 0,
    /** Coupe-circuit : arret de la journee apres -N R cumules (0 = off). */
    dailyLossLimitR: 0,
  },

  // ───────────── CONFLUENCES INTER-MARCHES (DXY / US10Y) ────────────
  // L'or ne se lit pas en vase clos. Ces filtres restent inactifs si la
  // serie de reference n'est pas fournie (voir `onMissing`).
  refs: {
    /**
     * DXY : correlation inverse mathematique. Le setup vendeur parfait est
     * celui ou, au moment ou l'or franchit son Haut de Londres (fausse
     * hausse), le DXY franchit son Bas de Londres (fausse baisse).
     */
    dxy: {
      /** 'off' | 'require' (bloquant) | 'soft' (annote sans bloquer). */
      mode: 'off',
      /** Comportement si la serie DXY est absente : 'pass' | 'block'. */
      onMissing: 'pass',
      /** Tolerance temporelle autour du balayage de l'or (minutes). */
      lagMinutes: 10,
      /** Penetration minimale du DXY au-dela de son extreme, en % de son prix. */
      minPenetrationPct: 0.02,
      /** Exiger en plus un rejet violent (rebond du DXY sur son support). */
      requireReversal: false,
      /** Fenetre d'observation du rebond (minutes). */
      reversalWithinMinutes: 30,
      /** Amplitude minimale du rebond, en % du prix DXY. */
      minReversalPct: 0.03,
    },

    /**
     * US10Y : concurrent de rendement de l'or. Rendements en hausse pendant
     * l'ouverture de NY -> ne chercher que des ventes sur l'or.
     */
    us10y: {
      /** 'off' | 'alignTrend' (le sens du trade doit suivre la macro). */
      mode: 'off',
      /** Comportement si la serie US10Y est absente : 'pass' | 'block'. */
      onMissing: 'pass',
      /** Nombre de barres servant a mesurer la pente. */
      lookbackBars: 12,
      /** Pente minimale requise, en % de la valeur du rendement. */
      minSlopePct: 0.0,
    },
  },

  // ──────────────────────── RISQUE / CAPITAL ────────────────────────
  risk: {
    initialEquity: 10_000,
    /** 'fixedFractional' (% du capital) | 'fixedLots' | 'fixedCash'. */
    model: 'fixedFractional',
    /** Risque par trade en % du capital. */
    pctPerTrade: 1.0,
    /** Lots fixes si model='fixedLots'. */
    lots: 0.1,
    /** Risque en USD si model='fixedCash'. */
    cashPerTrade: 100,
    /** Capitaliser les gains (sinon risque calcule sur le capital initial). */
    compounding: true,
  },

  // ──────────────────────────── EXECUTION ───────────────────────────
  execution: {
    /**
     * Ordre des evenements a l'interieur d'une barre M5 quand entree et sortie
     * sont toutes deux touchables :
     *  'conservative' : toujours le pire cas (SL avant TP) — defaut honnete
     *  'ohlcPath'     : chemin O->H->L->C (haussiere) / O->L->H->C (baissiere)
     *  'optimistic'   : toujours le meilleur cas (audit uniquement)
     */
    intrabar: 'conservative',
    /** Autoriser remplissage ET sortie dans la meme barre M5. */
    allowSameBarExit: true,
  },
};

/**
 * Fusion profonde (les tableaux sont remplaces, pas concatenes).
 *
 * `null` est une VALEUR SIGNIFIANTE dans cette config : il desactive un filtre
 * (`filters.londonRangeMax: null` = pas de plafond, `manage.breakEvenAtRR:
 * null` = pas de point mort). Un `null` fourni en surcharge doit donc ecraser
 * la valeur de base. Seul `undefined` (clef absente) signifie "ne pas toucher".
 */
export function deepMerge(base, override) {
  if (override === undefined) return base;
  if (override === null) return null;
  if (Array.isArray(base) || Array.isArray(override)) return override;
  if (base === null || base === undefined) return override;
  if (typeof base !== 'object' || typeof override !== 'object') return override;
  const out = { ...base };
  for (const k of Object.keys(override)) {
    out[k] = k in base ? deepMerge(base[k], override[k]) : override[k];
  }
  return out;
}

/** Copie profonde simple. */
export function clone(o) {
  return JSON.parse(JSON.stringify(o));
}

/** Lit une valeur par chemin pointe : get(cfg, 'entry.fvgLevel'). */
export function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

/** Ecrit une valeur par chemin pointe (mutation). */
export function setPath(obj, path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  let cur = obj;
  for (const k of keys) {
    if (cur[k] == null || typeof cur[k] !== 'object') cur[k] = {};
    cur = cur[k];
  }
  cur[last] = value;
  return obj;
}

/**
 * Construit une config complete a partir d'un override partiel, resout les
 * heures "HH:MM" en minutes et valide la coherence.
 * @param {object} [override]
 */
export function buildConfig(override = {}) {
  const cfg = deepMerge(clone(DEFAULTS), override || {});

  // Resolution des heures en minutes depuis minuit GMT.
  const s = cfg.sessions;
  cfg.resolved = {
    londonStart: parseHm(s.londonStart),
    londonEnd: parseHm(s.londonEnd),
    sweepStart: parseHm(s.sweepStart),
    sweepEnd: parseHm(s.sweepEnd),
    confirmEnd: parseHm(s.confirmEnd),
    entryExpiry: parseHm(s.entryExpiry),
    forceCloseAt: parseHm(s.forceCloseAt),
    newsTime: parseHm(s.newsTime),
    signalNotBefore: parseHm(s.signalNotBefore),
    silverBulletStart: parseHm(s.silverBulletStart),
    silverBulletEnd: parseHm(s.silverBulletEnd),
    weekdays: new Set(s.weekdays),
    skipDates: new Set(s.skipDates),
    dateFrom: s.dateFrom,
    dateTo: s.dateTo,
  };

  validateConfig(cfg);
  return cfg;
}

/** Leve une erreur explicite si la config est incoherente. @param {object} cfg */
export function validateConfig(cfg) {
  const r = cfg.resolved;
  const errs = [];
  const ordered = [
    ['londonStart', r.londonStart],
    ['londonEnd', r.londonEnd],
    ['sweepStart', r.sweepStart],
    ['sweepEnd', r.sweepEnd],
    ['confirmEnd', r.confirmEnd],
    ['entryExpiry', r.entryExpiry],
    ['forceCloseAt', r.forceCloseAt],
  ];
  for (let i = 1; i < ordered.length; i++) {
    if (ordered[i][1] < ordered[i - 1][1]) {
      errs.push(
        `sessions.${ordered[i][0]} (${formatHm(ordered[i][1])}) doit etre >= ` +
          `sessions.${ordered[i - 1][0]} (${formatHm(ordered[i - 1][1])})`
      );
    }
  }
  if (cfg.instrument.pipSize <= 0) errs.push('instrument.pipSize doit etre > 0');
  if (cfg.instrument.contractSize <= 0) errs.push('instrument.contractSize doit etre > 0');
  if (!['both', 'highOnly', 'lowOnly'].includes(cfg.sweep.side))
    errs.push(`sweep.side invalide : ${cfg.sweep.side}`);
  for (const [path, allowed] of [
    ['sweep.penetrationMode', DISTANCE_MODES],
    ['mss.breakBufferMode', DISTANCE_MODES],
    ['fvg.minSizeMode', DISTANCE_MODES],
    ['stop.bufferMode', DISTANCE_MODES],
    ['stop.distanceMode', DISTANCE_MODES],
    ['target.offsetMode', DISTANCE_MODES],
    ['manage.breakEvenOffsetMode', DISTANCE_MODES],
    ['filters.londonRangeMode', DISTANCE_MODES],
    ['filters.pdhPdlProximityMode', DISTANCE_MODES],
  ]) {
    const v = getPath(cfg, path);
    if (!allowed.includes(v)) errs.push(`${path} invalide : ${v} (attendu ${allowed.join('|')})`);
  }
  if (cfg.sweep.minPenetration >= cfg.sweep.maxPenetration)
    errs.push('sweep.minPenetration doit etre < sweep.maxPenetration');
  if (!['fractal', 'lowestSinceCross', 'priorBar'].includes(cfg.mss.ref))
    errs.push(`mss.ref invalide : ${cfg.mss.ref}`);
  if (!['lowestSinceCross', 'none'].includes(cfg.mss.fallbackRef))
    errs.push(`mss.fallbackRef invalide : ${cfg.mss.fallbackRef}`);
  if (!['close', 'wick'].includes(cfg.mss.breakType))
    errs.push(`mss.breakType invalide : ${cfg.mss.breakType}`);
  if (cfg.mss.swingLookback < 1) errs.push('mss.swingLookback doit etre >= 1');
  if (!['nearest', 'largest', 'first'].includes(cfg.fvg.selection))
    errs.push(`fvg.selection invalide : ${cfg.fvg.selection}`);
  if (!['fvg', 'orderBlock', 'fvgOrOb', 'ote', 'market'].includes(cfg.entry.model))
    errs.push(`entry.model invalide : ${cfg.entry.model}`);
  if (cfg.entry.fvgLevel < 0 || cfg.entry.fvgLevel > 1)
    errs.push('entry.fvgLevel doit etre dans [0,1]');
  if (!['body', 'full', 'upperHalf'].includes(cfg.entry.obZone))
    errs.push(`entry.obZone invalide : ${cfg.entry.obZone}`);
  if (!['sweepExtreme', 'fvgDistal', 'structureExtreme'].includes(cfg.stop.anchor))
    errs.push(`stop.anchor invalide : ${cfg.stop.anchor}`);
  if (cfg.stop.minDistance >= cfg.stop.maxDistance)
    errs.push('stop.minDistance doit etre < stop.maxDistance');
  if (!['oppositeLondon', 'rrMultiple', 'nearestOf'].includes(cfg.target.anchor))
    errs.push(`target.anchor invalide : ${cfg.target.anchor}`);
  if (cfg.target.minRR >= cfg.target.maxRR)
    errs.push('target.minRR doit etre < target.maxRR');
  if (!['fixedFractional', 'fixedLots', 'fixedCash'].includes(cfg.risk.model))
    errs.push(`risk.model invalide : ${cfg.risk.model}`);
  if (cfg.risk.initialEquity <= 0) errs.push('risk.initialEquity doit etre > 0');
  if (!['conservative', 'ohlcPath', 'optimistic'].includes(cfg.execution.intrabar))
    errs.push(`execution.intrabar invalide : ${cfg.execution.intrabar}`);
  if (!['off', 'require', 'avoid'].includes(cfg.filters.news))
    errs.push(`filters.news invalide : ${cfg.filters.news}`);
  if (!['off', 'volatilitySpike', 'nfp', 'calendar', 'all'].includes(cfg.filters.newsBlackout))
    errs.push(`filters.newsBlackout invalide : ${cfg.filters.newsBlackout}`);
  if (!['rr', 'internalLiquidity'].includes(cfg.manage.partial.anchor))
    errs.push(`manage.partial.anchor invalide : ${cfg.manage.partial.anchor}`);
  if (!DISTANCE_MODES.includes(cfg.sweep.inducementDepthMode))
    errs.push(`sweep.inducementDepthMode invalide : ${cfg.sweep.inducementDepthMode}`);
  if (!['off', 'londonRange', 'mssLeg', 'both'].includes(cfg.filters.premiumDiscount))
    errs.push(`filters.premiumDiscount invalide : ${cfg.filters.premiumDiscount}`);
  if (cfg.filters.premiumThreshold < 0 || cfg.filters.premiumThreshold > 1)
    errs.push('filters.premiumThreshold doit etre dans [0,1]');
  if (!['off', 'signal', 'fill', 'both'].includes(cfg.filters.silverBullet))
    errs.push(`filters.silverBullet invalide : ${cfg.filters.silverBullet}`);
  if (r.silverBulletStart > r.silverBulletEnd)
    errs.push('sessions.silverBulletStart doit etre <= sessions.silverBulletEnd');
  if (!['off', 'require', 'soft'].includes(cfg.refs.dxy.mode))
    errs.push(`refs.dxy.mode invalide : ${cfg.refs.dxy.mode}`);
  if (!['off', 'alignTrend'].includes(cfg.refs.us10y.mode))
    errs.push(`refs.us10y.mode invalide : ${cfg.refs.us10y.mode}`);
  for (const k of ['dxy', 'us10y']) {
    if (!['pass', 'block'].includes(cfg.refs[k].onMissing))
      errs.push(`refs.${k}.onMissing invalide : ${cfg.refs[k].onMissing}`);
  }
  if (!['gmt', 'local'].includes(cfg.sessions.londonAnchor))
    errs.push(`sessions.londonAnchor invalide : ${cfg.sessions.londonAnchor}`);
  if (!['gmt', 'local'].includes(cfg.sessions.nyAnchor))
    errs.push(`sessions.nyAnchor invalide : ${cfg.sessions.nyAnchor}`);

  if (errs.length) throw new Error('Config invalide :\n  - ' + errs.join('\n  - '));
  return true;
}

/** Unites de distance acceptees partout dans la config. */
export const DISTANCE_MODES = ['pips', 'atr', 'pctPrice', 'rangePct', 'usd'];

/**
 * Resout une distance exprimee dans n'importe quelle unite vers des USD de
 * cotation. C'est LA fonction qui rend la strategie stable sur 5 ans de
 * regimes de volatilite differents.
 *
 * @param {object} cfg
 * @param {string} mode 'pips' | 'atr' | 'pctPrice' | 'rangePct' | 'usd'
 * @param {number} value
 * @param {{atr?: number, price?: number, range?: number}} ctx
 * @returns {number} distance en USD de cotation
 */
export function resolveDistance(cfg, mode, value, ctx) {
  if (value === null || value === undefined) return null;
  switch (mode) {
    case 'pips':
      return value * cfg.instrument.pipSize;
    case 'usd':
      return value;
    case 'atr':
      if (!Number.isFinite(ctx.atr)) return NaN;
      return value * ctx.atr;
    case 'pctPrice':
      if (!Number.isFinite(ctx.price)) return NaN;
      return (value / 100) * ctx.price;
    case 'rangePct':
      if (!Number.isFinite(ctx.range)) return NaN;
      return (value / 100) * ctx.range;
    default:
      throw new Error(`Unite de distance inconnue : ${mode}`);
  }
}

/** Convertit des pips en USD de cotation. */
export function pips(cfg, n) {
  return n * cfg.instrument.pipSize;
}

/** Convertit un USD de cotation en pips. */
export function toPips(cfg, usd) {
  return usd / cfg.instrument.pipSize;
}

/** Arrondit un prix a la precision de cotation. */
export function roundPrice(cfg, p) {
  const f = 10 ** cfg.instrument.digits;
  return Math.round(p * f) / f;
}
