'use client';

import type { AnalysisContext } from '@/lib/types';

interface Props {
  ctx: AnalysisContext;
  onChange: (ctx: AnalysisContext) => void;
}

export const DEFAULT_CONTEXT: AnalysisContext = {
  accountSize: 10000,
  riskPercent: 0.5,
  contractSize: 100,
  minLot: 0.01,
  currentPrice: null,
  atrDaily: null,
  atrH1: null,
  spread: null,
  session: 'Londres',
  horizon: 'Intraday (quelques heures)',
  dxy: '',
  realYields: '',
  fedExpectations: '',
  upcomingNews: '',
  cot: '',
  etfFlows: '',
  gex: '',
  ivVsRv: '',
  curve: '',
  shanghaiPremium: '',
  comexInventories: '',
  silverRatio: '',
  cbBuying: '',
  lastNewsReaction: '',
  notes: '',
};

/** Chaque champ hors graphique, avec où le trouver gratuitement. */
const EXTERNAL: Array<{
  key: keyof AnalysisContext;
  label: string;
  placeholder: string;
  source: string;
}> = [
  {
    key: 'dxy',
    label: 'DXY / dollar',
    placeholder: 'ex. 103,4 — en hausse depuis 3 séances',
    source: 'TradingView : DXY',
  },
  {
    key: 'realYields',
    label: 'Taux réels US 10y (TIPS)',
    placeholder: 'ex. 1,85 % — en baisse',
    source: 'FRED : DFII10',
  },
  {
    key: 'fedExpectations',
    label: 'Anticipations Fed',
    placeholder: 'ex. 68 % de baisse pricée en septembre',
    source: 'CME FedWatch',
  },
  {
    key: 'upcomingNews',
    label: 'Événements à venir',
    placeholder: 'ex. CPI dans 2 h, FOMC mercredi',
    source: 'Forex Factory (filtre impact fort)',
  },
  {
    key: 'lastNewsReaction',
    label: 'Réaction à la dernière donnée',
    placeholder: 'ex. NFP au-dessus du consensus, or a monté quand même',
    source: 'Ta propre observation — la couche la plus rentable',
  },
  {
    key: 'cot',
    label: 'COT / managed money',
    placeholder: 'ex. net long au plus haut depuis 2 ans',
    source: 'CFTC, publié vendredi',
  },
  {
    key: 'etfFlows',
    label: 'Flux ETF (GLD, IAU)',
    placeholder: 'ex. 4 semaines d’entrées consécutives',
    source: 'World Gold Council',
  },
  {
    key: 'cbBuying',
    label: 'Achats banques centrales',
    placeholder: 'ex. PBoC acheteur 8 mois d’affilée',
    source: 'WGC / données FMI',
  },
  {
    key: 'gex',
    label: 'GEX / gamma dealer',
    placeholder: 'ex. dealers short gamma sous 3300',
    source: 'SpotGamma, Menthor Q',
  },
  {
    key: 'ivVsRv',
    label: 'Vol implicite (GVZ) vs réalisée',
    placeholder: 'ex. GVZ 18 vs RV 24 — implicite sous-évaluée',
    source: 'CBOE : GVZ',
  },
  {
    key: 'curve',
    label: 'Courbe futures / EFP',
    placeholder: 'ex. contango normal, EFP calme',
    source: 'CME',
  },
  {
    key: 'comexInventories',
    label: 'Stocks COMEX',
    placeholder: 'ex. registered en baisse depuis 3 semaines',
    source: 'CME daily metals report',
  },
  {
    key: 'shanghaiPremium',
    label: 'Prime / décote Shanghai',
    placeholder: 'ex. décote de 8 $ — la Chine n’achète plus',
    source: 'Shanghai Gold Exchange',
  },
  {
    key: 'silverRatio',
    label: 'Argent & ratio or/argent',
    placeholder: 'ex. ratio 82, argent surperforme',
    source: 'TradingView : XAUXAG',
  },
];

export function ContextForm({ ctx, onChange }: Props) {
  const set = <K extends keyof AnalysisContext>(k: K, v: AnalysisContext[K]) =>
    onChange({ ...ctx, [k]: v });

  const num = (v: string): number | null => {
    const n = parseFloat(v.replace(',', '.'));
    return Number.isFinite(n) ? n : null;
  };

  const filled = EXTERNAL.filter((f) => String(ctx[f.key] ?? '').trim()).length;
  const riskUSD = (ctx.accountSize * ctx.riskPercent) / 100;

  return (
    <>
      <section>
        <h2 className="sec">Compte & risque</h2>
        <div className="card">
          <div className="grid">
            <div className="field">
              <label htmlFor="cap">Capital ($)</label>
              <input
                id="cap"
                className="mono"
                inputMode="decimal"
                value={ctx.accountSize}
                onChange={(e) => set('accountSize', num(e.target.value) ?? 0)}
              />
            </div>
            <div className="field">
              <label htmlFor="risk">Risque par trade (%)</label>
              <input
                id="risk"
                className="mono"
                inputMode="decimal"
                value={ctx.riskPercent}
                onChange={(e) => set('riskPercent', num(e.target.value) ?? 0)}
              />
            </div>
            <div className="field">
              <label htmlFor="cs">Onces / lot</label>
              <input
                id="cs"
                className="mono"
                inputMode="decimal"
                value={ctx.contractSize}
                onChange={(e) => set('contractSize', num(e.target.value) ?? 100)}
              />
            </div>
            <div className="field">
              <label htmlFor="ml">Lot minimum</label>
              <input
                id="ml"
                className="mono"
                inputMode="decimal"
                value={ctx.minLot}
                onChange={(e) => set('minLot', num(e.target.value) ?? 0.01)}
              />
            </div>
          </div>
          <p className="tiny" style={{ marginTop: 10, marginBottom: 0 }}>
            Risque autorisé : <strong className="mono">{riskUSD.toFixed(2)} $</strong> par trade.
            {ctx.riskPercent > 1 && (
              <span style={{ color: 'var(--warn)' }}>
                {' '}
                Au-delà de 1 %, le risque de ruine devient significatif sur un edge modeste.
              </span>
            )}
          </p>
        </div>
      </section>

      <section>
        <h2 className="sec">Marché</h2>
        <div className="card">
          <div className="grid">
            <div className="field">
              <label htmlFor="px">Prix actuel ($)</label>
              <input
                id="px"
                className="mono"
                inputMode="decimal"
                placeholder="3345,20"
                value={ctx.currentPrice ?? ''}
                onChange={(e) => set('currentPrice', num(e.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="atrd">ATR journalier ($)</label>
              <input
                id="atrd"
                className="mono"
                inputMode="decimal"
                placeholder="42"
                value={ctx.atrDaily ?? ''}
                onChange={(e) => set('atrDaily', num(e.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="atrh">ATR H1 ($)</label>
              <input
                id="atrh"
                className="mono"
                inputMode="decimal"
                placeholder="6,5"
                value={ctx.atrH1 ?? ''}
                onChange={(e) => set('atrH1', num(e.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="sp">Spread ($)</label>
              <input
                id="sp"
                className="mono"
                inputMode="decimal"
                placeholder="0,25"
                value={ctx.spread ?? ''}
                onChange={(e) => set('spread', num(e.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="ses">Session</label>
              <select id="ses" value={ctx.session} onChange={(e) => set('session', e.target.value)}>
                <option>Asie</option>
                <option>Londres</option>
                <option>New York</option>
                <option>Chevauchement Londres/NY</option>
                <option>Hors session</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="hz">Horizon</label>
              <select
                id="hz"
                value={ctx.horizon}
                onChange={(e) => set('horizon', e.target.value)}
              >
                <option>Scalp (minutes)</option>
                <option>Intraday (quelques heures)</option>
                <option>Swing (jours)</option>
                <option>Position (semaines)</option>
              </select>
            </div>
          </div>
          {ctx.atrDaily === null && (
            <p className="tiny" style={{ color: 'var(--warn)', marginTop: 10, marginBottom: 0 }}>
              Sans ATR journalier, la condition éliminatoire sur le stop échoue automatiquement — un
              stop non calibré à l’ATR n’est pas validable sur l’or.
            </p>
          )}
        </div>
      </section>

      <section>
        <h2 className="sec">Données hors graphique</h2>
        <div className="card">
          <p className="muted" style={{ marginTop: 0 }}>
            Un graphique ne montre ni le GEX, ni le COT, ni la prime de Shanghai. Chaque champ laissé
            vide rend sa couche <strong>UNKNOWN</strong> et fait baisser la confiance — il ne fait
            jamais monter le score.
          </p>
          <p className="tiny" style={{ marginBottom: 14 }}>
            {filled} / {EXTERNAL.length} renseigné(s).
          </p>

          <details>
            <summary>Ouvrir les {EXTERNAL.length} champs</summary>
            <div style={{ display: 'grid', gap: 12 }}>
              {EXTERNAL.map((f) => (
                <div className="field" key={String(f.key)}>
                  <label htmlFor={String(f.key)}>
                    {f.label}
                    <span style={{ color: 'var(--fg-3)', fontWeight: 400 }}> · {f.source}</span>
                  </label>
                  <input
                    id={String(f.key)}
                    placeholder={f.placeholder}
                    value={String(ctx[f.key] ?? '')}
                    onChange={(e) => set(f.key, e.target.value as never)}
                  />
                </div>
              ))}
            </div>
          </details>

          <div className="field" style={{ marginTop: 14 }}>
            <label htmlFor="notes">Notes libres</label>
            <textarea
              id="notes"
              placeholder="Ce que tu vois, ce que tu attends, ce qui t’inquiète."
              value={ctx.notes}
              onChange={(e) => set('notes', e.target.value)}
            />
          </div>
        </div>
      </section>
    </>
  );
}
