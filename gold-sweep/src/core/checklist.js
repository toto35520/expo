/**
 * Carte de decision : dimensionnement et checklist de validation.
 *
 * Module PUR (aucun acces disque, aucun module Node) : le moniteur live en
 * CLI et le tableau de bord web l'utilisent tous les deux, donc la carte
 * affichee sur votre ecran est la meme dans les deux cas.
 */

import { formatHm, utcMinuteOfDay } from './time.js';

/**
 * Dimensionne la position pour un setup.
 *
 * @param {object} cfg
 * @param {{entry:number, sl:number, tp:number, targets?:Array}} setup
 * @param {number} equity capital de reference
 * @returns {object}
 */
export function sizePosition(cfg, setup, equity) {
  const inst = cfg.instrument;
  const slDist = Math.abs(setup.sl - setup.entry);
  if (!(slDist > 0)) return { lots: 0, reason: 'distance de stop nulle' };

  let riskCash;
  let lots;
  if (cfg.risk.model === 'fixedLots') {
    lots = cfg.risk.lots;
    riskCash = slDist * lots * inst.contractSize;
  } else {
    riskCash =
      cfg.risk.model === 'fixedCash' ? cfg.risk.cashPerTrade : equity * (cfg.risk.pctPerTrade / 100);
    lots = riskCash / (slDist * inst.contractSize);
  }
  const stepped = Math.floor(lots / inst.lotStep + 1e-9) * inst.lotStep;
  const snapped = Math.min(inst.maxLots, Math.round(stepped / inst.lotStep) * inst.lotStep);
  const finalLots = snapped < inst.minLots ? 0 : Number(snapped.toFixed(4));

  /**
   * Gain attendu cran par cran.
   *
   * Le dernier cran ferme LE RESTE de la position, pas 100 % : sa fraction
   * vaut 1 moins la somme des precedentes. C'est la meme convention que le
   * moteur (`closePosition` sur `pos.lots` restant) — sans quoi le gain
   * affiche serait surestime.
   */
  const raw =
    setup.targets && setup.targets.length
      ? setup.targets
      : [{ name: 'TP', price: setup.tp, closePct: 1, rr: Math.abs(setup.tp - setup.entry) / slDist }];
  const ladder = [];
  let consumed = 0;
  raw.forEach((t, k) => {
    const isLast = k === raw.length - 1;
    const pct = isLast ? Math.max(0, 1 - consumed) : Math.min(t.closePct, 1 - consumed);
    consumed += pct;
    ladder.push({
      ...t,
      closeFraction: pct,
      lots: Number((finalLots * pct).toFixed(4)),
      cash: Math.abs(t.price - setup.entry) * finalLots * pct * inst.contractSize,
    });
  });

  return {
    lots: finalLots,
    apiVolume: Math.round(finalLots * inst.apiVolumePerLot),
    riskCash: slDist * finalLots * inst.contractSize,
    riskPctOfEquity: equity ? ((slDist * finalLots * inst.contractSize) / equity) * 100 : NaN,
    slDistUsd: slDist,
    slDistPips: slDist / inst.pipSize,
    ladder,
    /** Gain total si TOUS les crans sont atteints. */
    rewardCash: ladder.reduce((a, t) => a + t.cash, 0),
    equity,
    reason: finalLots
      ? null
      : `volume < minLots (${inst.minLots}) — capital ou risque insuffisant pour un stop de ${(slDist / inst.pipSize).toFixed(0)} pips`,
  };
}

/**
 * Checklist de validation avant entree — les 5 cases a cocher.
 * Chaque ligne est CALCULEE depuis les donnees du setup, jamais declarative.
 *
 * `ok` vaut true (validee), false (non validee) ou null (non evaluable,
 * typiquement un filtre desactive ou une serie de reference absente).
 *
 * @param {object} cfg
 * @param {object} setup
 * @returns {Array<{label:string, ok:boolean|null, detail:string}>}
 */
export function buildChecklist(cfg, setup) {
  const mod = utcMinuteOfDay(setup.signalTs);
  const sbStart = cfg.resolved.silverBulletStart;
  const sbEnd = cfg.resolved.silverBulletEnd;
  const newsT = cfg.resolved.newsTime;
  const thr = cfg.filters.premiumThreshold;
  const isSell = setup.dir === 'sell';

  const penAtr = setup.atrAtSignal > 0 ? setup.sweepPenetrationUsd / setup.atrAtSignal : NaN;
  const fib = Number.isFinite(setup.fibLeg) ? setup.fibLeg : setup.fibLondon;
  const premiumOk = Number.isFinite(fib) ? (isSell ? fib >= thr : fib <= 1 - thr) : null;

  return [
    {
      label: 'Haut/Bas de Londres balaye par une meche agressive',
      ok: Number.isFinite(penAtr) && penAtr >= cfg.sweep.minPenetration && penAtr <= cfg.sweep.maxPenetration,
      detail:
        `penetration ${setup.sweepPenetrationUsd.toFixed(2)} $ = ${penAtr.toFixed(2)} ATR ` +
        `(seuil ${cfg.sweep.minPenetration}, plafond ${cfg.sweep.maxPenetration} ATR)`,
    },
    {
      label: 'Cassure de structure (MSS) avec bougie de deplacement',
      ok: setup.displacementBody > 0,
      detail:
        `corps de jambe ${setup.displacementBody.toFixed(2)} $ = ` +
        `${(setup.displacementBody / setup.atrAtSignal).toFixed(2)} ATR sur ${setup.displacementLen} barre(s) ; ` +
        `structure cassee a ${setup.structureLevel.toFixed(2)} (${setup.structureSrc})`,
    },
    {
      label: `Entree en zone ${isSell ? 'Premium' : 'Discount'} (au-dela de ${(thr * 100).toFixed(0)} % de la structure)`,
      ok: premiumOk,
      detail: Number.isFinite(fib)
        ? `position dans la jambe de retournement : ${(fib * 100).toFixed(0)} %` +
          (Number.isFinite(setup.fibLondon)
            ? ` | dans le range de Londres : ${(setup.fibLondon * 100).toFixed(0)} %`
            : '')
        : 'non evalue (filters.premiumDiscount desactive)',
    },
    {
      label: 'DXY confirme (correlation inverse respectee)',
      ok: setup.dxy ? (setup.dxy.available ? setup.dxy.swept : null) : null,
      detail: setup.dxy
        ? setup.dxy.available
          ? `le DXY a balaye son ${setup.dxy.mirrorSide === 'low' ? 'Bas' : 'Haut'} de Londres de ` +
            `${setup.dxy.penetration.toFixed(3)}${setup.dxy.reversal ? ' avec rejet' : ''}`
          : 'serie DXY absente ou non couverte a cet horodatage'
        : 'non evalue (refs.dxy.mode = off)',
    },
    {
      label: `Horaire dans la fenetre ${formatHm(newsT)}-${formatHm(sbEnd)} GMT`,
      ok: mod >= newsT && mod <= sbEnd,
      detail:
        `signal a ${formatHm(mod)} GMT | fenetre Silver Bullet ${formatHm(sbStart)}-${formatHm(sbEnd)}` +
        (mod >= sbStart && mod <= sbEnd ? ' (dedans)' : ' (hors Silver Bullet)'),
    },
  ];
}

/**
 * Ce qu'il reste a attendre, quand aucun setup n'est sorti.
 * Traduit l'etat interne de la journee en une consigne lisible.
 *
 * @param {object} cfg
 * @param {object|null} day resume produit par SweepStrategy.summarizeDay()
 * @returns {{statut:string, titre:string, detail:string, attente:string|null}}
 */
export function explainDay(cfg, day) {
  if (!day) {
    return { statut: 'aucune', titre: 'Aucune donnee', detail: 'Chargez un historique de barres M5.', attente: null };
  }
  const r = cfg.resolved;
  const win = `${cfg.sessions.sweepStart}-${cfg.sessions.sweepEnd} GMT`;

  if (day.setups > 0) {
    return {
      statut: 'setup',
      titre: 'Setup emis',
      detail: `${day.setups} setup${day.setups > 1 ? 's' : ''} sur la journee.`,
      attente: null,
    };
  }
  if (day.phase === 'SKIPPED') {
    const motifs = {
      dayOutOfRange: 'journee hors de la periode analysee',
      dayWeekday: 'jour non trade (configuration weekdays)',
      daySkipDate: 'date exclue manuellement',
      dayNewsBlackout: 'blackout : annonce a fort impact ce jour',
      dayLondonIncomplete: `session de Londres incomplete (${day.londonBars} barres, minimum ${cfg.sessions.minLondonBars})`,
      dayLondonRangeTooSmall: 'range de Londres trop etroit',
      dayLondonRangeTooLarge: 'range de Londres trop large',
      dayAtrRegime: 'regime de volatilite hors bornes',
    };
    const k = day.lastRejection?.reason;
    return {
      statut: 'ecarte',
      titre: 'Journee ecartee',
      detail: motifs[k] || `motif : ${k || 'inconnu'}`,
      attente: null,
    };
  }
  if (day.phase === 'IDLE') {
    return {
      statut: 'attente',
      titre: 'Range de Londres en construction',
      detail: `Le Haut et le Bas de Londres se figent a ${cfg.sessions.londonEnd} GMT (${day.londonBars} barres relevees).`,
      attente: `Attendre ${cfg.sessions.londonEnd} GMT.`,
    };
  }
  if (day.phase === 'ARMED') {
    return {
      statut: 'arme',
      titre: 'Arme — en attente du balayage',
      detail:
        `Range de Londres fige : ${day.londonLow?.toFixed(2)} – ${day.londonHigh?.toFixed(2)} ` +
        `(${day.londonRange?.toFixed(2)} $ sur ${day.londonBars} barres).`,
      attente:
        `Le prix doit depasser ${day.londonHigh?.toFixed(2)} (setup VENTE) ou casser sous ` +
        `${day.londonLow?.toFixed(2)} (setup ACHAT), dans la fenetre ${win}.`,
    };
  }
  if (day.phase === 'SWEPT') {
    const sw = day.sweep;
    return {
      statut: 'balaye',
      titre: `Balayage du ${sw?.side === 'high' ? 'HAUT' : 'BAS'} — en attente de la cassure de structure`,
      detail:
        `Niveau ${sw?.level?.toFixed(2)} balaye a ${formatHm(utcMinuteOfDay(sw?.at))} GMT ; ` +
        `extreme du piege ${sw?.extreme?.toFixed(2)} (${sw?.penetration?.toFixed(2)} $ au-dela).`,
      attente:
        `Attendre un MSS ${sw?.dir === 'sell' ? 'baissier' : 'haussier'} avec bougie de deplacement, ` +
        `au plus tard ${cfg.sessions.confirmEnd} GMT. Aucun signal n'est accepte avant ` +
        `${cfg.sessions.signalNotBefore} GMT.`,
    };
  }
  // DONE sans setup : un filtre a bloque, on nomme lequel.
  const motifs = {
    sweepNone: `aucun balayage dans la fenetre ${win}`,
    sweepTooFar: 'penetration excessive — vraie cassure, pas un piege',
    sweepNoCloseBack: 'pas de cloture de retour dans le range',
    sweepSideDisabled: 'cote desactive par la configuration',
    mssTimeout: 'aucune cassure de structure dans le delai imparti',
    mssNoBreak: 'la structure n a pas ete cassee',
    mssNoStructure: 'aucune structure de reference identifiable',
    mssNoDisplacement: 'cassure sans bougie de deplacement suffisante',
    fvgMissing: 'aucun Fair Value Gap dans la jambe',
    fvgTooSmall: 'Fair Value Gap trop petit',
    entryBehindMarket: 'zone d entree deja consommee par le prix',
    entryNoZone: 'aucune zone d entree constructible',
    slTooTight: 'stop trop serre (bruit)',
    slTooWide: 'stop trop large (risque)',
    rrTooLow: 'R:R insuffisant pour l objectif',
    rrTooHigh: 'R:R aberrant',
    filterPremium: 'entree hors zone Premium/Discount',
    filterSilverBullet: 'hors fenetre Silver Bullet',
    filterSignalTooEarly: `signal avant ${cfg.sessions.signalNotBefore} GMT`,
    filterNewsSpike: 'choc de volatilite detecte a l annonce',
    filterInducement: 'aucun inducement avant le balayage',
    filterDxy: 'le DXY ne confirme pas',
    filterUs10y: 'US10Y non aligne',
    filterNews: 'filtre news',
    filterDailyBias: 'biais journalier contraire',
    filterPdhPdl: 'pas de confluence PDH/PDL',
    filterRefMissing: 'serie de reference indisponible',
  };
  const k = day.lastRejection?.reason;
  return {
    statut: 'bloque',
    titre: 'Journee terminee sans setup',
    detail: motifs[k] || `motif : ${k || 'aucun balayage exploitable'}`,
    attente: null,
  };
}
