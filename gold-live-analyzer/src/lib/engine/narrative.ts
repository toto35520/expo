import { formatUtcTime } from '../market/sessions';
import type { Timeframe } from '../market/types';
import type { MarketRead } from './analyzer';

/**
 * Traduit la lecture technique en phrases. C'est la sortie "ce que je vois" :
 * elle doit dire l'etat du marche, pas seulement afficher des chiffres.
 */

export interface NarrativeLine {
  tone: 'HAUSSIER' | 'BAISSIER' | 'NEUTRE' | 'ALERTE';
  text: string;
}

export interface Narrative {
  headline: string;
  context: NarrativeLine[];
  structure: NarrativeLine[];
  momentum: NarrativeLine[];
  levels: NarrativeLine[];
  verdict: NarrativeLine[];
  updatedAt: string;
}

const money = (value: number) => `${value.toFixed(2)} $`;

function toneFromScore(score: number): NarrativeLine['tone'] {
  if (score >= 20) return 'HAUSSIER';
  if (score <= -20) return 'BAISSIER';
  return 'NEUTRE';
}

export function buildNarrative(read: MarketRead, entryTf: Timeframe, contextTf: Timeframe): Narrative {
  const entry = read.tf[entryTf];
  const context = read.tf[contextTf];
  const price = read.quote.mid;

  const headline = (() => {
    if (read.globalBias === 'HAUSSIER') {
      return `Biais acheteur sur l'or — ${read.alignment} % des unites de temps alignees a la hausse.`;
    }
    if (read.globalBias === 'BAISSIER') {
      return `Biais vendeur sur l'or — ${read.alignment} % des unites de temps alignees a la baisse.`;
    }
    return "Pas de direction tranchee sur l'or : le marche se cherche.";
  })();

  // --- Contexte -----------------------------------------------------------
  const contextLines: NarrativeLine[] = [];
  contextLines.push({
    tone: toneFromScore(context.score),
    text: `${contextTf} : ${context.structure.label}, score directionnel ${context.score > 0 ? '+' : ''}${context.score}/100.`,
  });

  if (context.ema200 !== null) {
    const above = price > context.ema200;
    contextLines.push({
      tone: above ? 'HAUSSIER' : 'BAISSIER',
      text: `Le prix evolue ${above ? 'au-dessus' : 'en dessous'} de l'EMA200 ${contextTf} (${money(context.ema200)}) : ${above ? 'les acheteurs gardent la main sur le fond' : 'les vendeurs gardent la main sur le fond'}.`,
    });
  }

  contextLines.push({
    tone: read.session.name === 'HORS_SESSION' ? 'ALERTE' : 'NEUTRE',
    text: `Seance en cours : ${read.session.label}.`,
  });

  // --- Structure ----------------------------------------------------------
  const structureLines: NarrativeLine[] = [];
  structureLines.push({
    tone: toneFromScore(entry.score),
    text: `${entryTf} : ${entry.structure.label}.`,
  });

  if (entry.structure.choch) {
    structureLines.push({
      tone: 'ALERTE',
      text: `Changement de caractere ${entry.structure.choch.direction === 'UP' ? 'haussier' : 'baissier'} : le niveau ${money(entry.structure.choch.level)} a cede. Premier signe de retournement sur ${entryTf}.`,
    });
  } else if (entry.structure.bos) {
    structureLines.push({
      tone: entry.structure.bos.direction === 'UP' ? 'HAUSSIER' : 'BAISSIER',
      text: `Cassure de structure ${entry.structure.bos.direction === 'UP' ? 'haussiere' : 'baissiere'} confirmee sur ${money(entry.structure.bos.level)} : la tendance ${entryTf} se prolonge.`,
    });
  }

  if (entry.ema20 !== null && entry.ema50 !== null) {
    const distance = ((price - entry.ema20) / entry.ema20) * 100;
    const position =
      Math.abs(distance) < 0.05
        ? `colle a son EMA20 (${money(entry.ema20)})`
        : distance > 0
          ? `${money(price - entry.ema20)} au-dessus de son EMA20 (${money(entry.ema20)})`
          : `${money(entry.ema20 - price)} sous son EMA20 (${money(entry.ema20)})`;
    structureLines.push({
      tone: 'NEUTRE',
      text: `Le prix est ${position}, EMA50 a ${money(entry.ema50)}.`,
    });
  }

  if (entry.structure.lastLeg) {
    const leg = entry.structure.lastLeg;
    structureLines.push({
      tone: leg.direction === 'UP' ? 'HAUSSIER' : 'BAISSIER',
      text: `Derniere impulsion ${leg.direction === 'UP' ? 'haussiere' : 'baissiere'} de ${money(leg.amplitude)}, de ${money(leg.from.price)} a ${money(leg.to.price)}.`,
    });
  }

  // --- Momentum et volatilite --------------------------------------------
  const momentumLines: NarrativeLine[] = [];
  if (entry.rsi !== null) {
    const rsi = entry.rsi;
    const read2 =
      rsi >= 70
        ? 'zone de surachat : les poursuites acheteuses deviennent risquees'
        : rsi <= 30
          ? 'zone de survente : les poursuites vendeuses deviennent risquees'
          : rsi >= 55
            ? 'momentum acheteur en place'
            : rsi <= 45
              ? 'momentum vendeur en place'
              : 'momentum neutre, pas de camp dominant';
    momentumLines.push({
      tone: rsi >= 70 || rsi <= 30 ? 'ALERTE' : toneFromScore(rsi - 50),
      text: `RSI ${entryTf} a ${rsi.toFixed(0)} — ${read2}.`,
    });
  }

  if (entry.adx !== null) {
    momentumLines.push({
      tone: entry.adx >= 25 ? toneFromScore(entry.score) : 'NEUTRE',
      text:
        entry.adx >= 25
          ? `Tendance ${entryTf} soutenue (ADX ${entry.adx.toFixed(0)}) : les replis ont de bonnes chances d'etre rachetes.`
          : `Tendance ${entryTf} molle (ADX ${entry.adx.toFixed(0)}) : contexte de range, les cassures ont tendance a echouer.`,
    });
  }

  if (entry.atr !== null) {
    const label =
      read.volatility === 'ELEVEE'
        ? "volatilite elevee : elargir les stops et reduire la taille"
        : read.volatility === 'FAIBLE'
          ? 'volatilite faible : marche endormi, peu d opportunites propres'
          : 'volatilite normale';
    momentumLines.push({
      tone: read.volatility === 'FAIBLE' ? 'ALERTE' : 'NEUTRE',
      text: `ATR ${entryTf} a ${money(entry.atr)} — ${label}.`,
    });
  }

  if (entry.bollinger !== null && entry.bandwidthPercentile !== null) {
    const pct = Math.round(entry.bandwidthPercentile * 100);
    if (pct < 25) {
      momentumLines.push({
        tone: 'ALERTE',
        text: `Bandes de Bollinger comprimees (${pct}e percentile) : l'energie s'accumule, une expansion est probable.`,
      });
    } else if (pct > 85) {
      momentumLines.push({
        tone: 'ALERTE',
        text: `Bandes de Bollinger tres ecartees (${pct}e percentile) : mouvement deja etendu, attention aux entrees tardives.`,
      });
    }
  }

  momentumLines.push({
    tone: read.quote.spread > 0.5 ? 'ALERTE' : 'NEUTRE',
    text: `Spread courant ${money(read.quote.spread)} (achat ${money(read.quote.ask)} / vente ${money(read.quote.bid)}).`,
  });

  // --- Niveaux ------------------------------------------------------------
  const levelLines: NarrativeLine[] = [];
  const above = read.levels.above[0];
  const below = read.levels.below[0];

  if (above) {
    levelLines.push({
      tone: 'NEUTRE',
      text: `Premier obstacle au-dessus : ${above.label} a ${money(above.price)} (${money(above.price - price)} de marge).`,
    });
  }
  if (below) {
    levelLines.push({
      tone: 'NEUTRE',
      text: `Premier appui en dessous : ${below.label} a ${money(below.price)} (${money(price - below.price)} de marge).`,
    });
  }
  if (read.levels.asiaHigh !== null && read.levels.asiaLow !== null) {
    const inside = price <= read.levels.asiaHigh && price >= read.levels.asiaLow;
    levelLines.push({
      tone: inside ? 'NEUTRE' : 'ALERTE',
      text: inside
        ? `Le prix est encore dans le range asiatique (${money(read.levels.asiaLow)} - ${money(read.levels.asiaHigh)}).`
        : `Le range asiatique (${money(read.levels.asiaLow)} - ${money(read.levels.asiaHigh)}) est casse ${price > read.levels.asiaHigh ? 'par le haut' : 'par le bas'}.`,
    });
  }
  if (read.levels.dayHigh !== null && read.levels.dayLow !== null) {
    levelLines.push({
      tone: 'NEUTRE',
      text: `Amplitude du jour : ${money(read.levels.dayLow)} - ${money(read.levels.dayHigh)} soit ${money(read.levels.dayHigh - read.levels.dayLow)}.`,
    });
  }

  // --- Verdict ------------------------------------------------------------
  const verdictLines: NarrativeLine[] = [];

  if (read.candidates.length > 0) {
    for (const candidate of read.candidates) {
      verdictLines.push({
        tone: candidate.direction === 'BUY' ? 'HAUSSIER' : 'BAISSIER',
        text: `SIGNAL ${candidate.direction} — ${candidate.name} (score ${candidate.score}/100). ${candidate.watching}`,
      });
    }
  } else if (read.blockers.length > 0) {
    for (const blocker of read.blockers) {
      verdictLines.push({ tone: 'ALERTE', text: `Aucun signal diffuse : ${blocker}` });
    }
  } else {
    const best = read.strategies[0];
    if (best && best.readiness > 0.35) {
      verdictLines.push({
        tone: best.direction === 'BUY' ? 'HAUSSIER' : best.direction === 'SELL' ? 'BAISSIER' : 'NEUTRE',
        text: `Setup le plus avance : ${best.name} (${Math.round(best.readiness * 100)} % des conditions). ${best.watching}`,
      });
      if (best.missing.length > 0) {
        verdictLines.push({ tone: 'NEUTRE', text: `Il manque : ${best.missing.slice(0, 2).join(' ; ')}.` });
      }
    } else {
      verdictLines.push({
        tone: 'NEUTRE',
        text: "Rien d'exploitable pour l'instant : je reste en observation et je previens des qu'un setup se forme.",
      });
    }
  }

  return {
    headline,
    context: contextLines,
    structure: structureLines,
    momentum: momentumLines,
    levels: levelLines,
    verdict: verdictLines,
    updatedAt: formatUtcTime(read.ts),
  };
}
