'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  attribute,
  computeExcursions,
  computeExpectancy,
  kelly,
  monteCarloDrawdown,
  tradeR,
} from '@/lib/stats';
import { deleteTrade, exportAll, getTrades, importAll, saveTrade } from '@/lib/storage';
import type { JournalTrade, TradeStatus } from '@/lib/types';

export default function JournalPage() {
  const [trades, setTrades] = useState<JournalTrade[]>([]);
  const [tab, setTab] = useState<'trades' | 'stats'>('trades');
  const [msg, setMsg] = useState('');

  useEffect(() => setTrades(getTrades()), []);

  const refresh = () => setTrades(getTrades());

  const update = (t: JournalTrade) => {
    saveTrade(t);
    refresh();
  };

  const closed = useMemo(() => trades.filter((t) => t.status === 'CLOSED'), [trades]);

  return (
    <>
      <section>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div className="tabs" style={{ marginLeft: 0 }}>
            <button
              className="tab"
              data-active={tab === 'trades'}
              onClick={() => setTab('trades')}
              style={{ background: 'none', border: '1px solid transparent' }}
            >
              Trades ({trades.length})
            </button>
            <button
              className="tab"
              data-active={tab === 'stats'}
              onClick={() => setTab('stats')}
              style={{ background: 'none', border: '1px solid transparent' }}
            >
              Statistiques
            </button>
          </div>
        </div>
      </section>

      {tab === 'trades' ? (
        <section>
          {trades.length === 0 ? (
            <div className="card">
              <p className="muted" style={{ margin: 0 }}>
                Aucun trade enregistré. Lance une <Link href="/">analyse</Link> — seuls les setups
                qui passent toutes les conditions éliminatoires peuvent être envoyés ici.
              </p>
            </div>
          ) : (
            trades.map((t) => (
              <TradeCard
                key={t.id}
                t={t}
                onUpdate={update}
                onDelete={(id) => {
                  deleteTrade(id);
                  refresh();
                }}
              />
            ))
          )}
        </section>
      ) : (
        <Stats trades={trades} closed={closed} />
      )}

      <section>
        <h2 className="sec">Sauvegarde</h2>
        <div className="card">
          <p className="tiny" style={{ marginTop: 0 }}>
            Les données sont stockées dans ce navigateur uniquement. Rien n’est envoyé sur un
            serveur. Exporte régulièrement — vider le cache du navigateur efface tout.
          </p>
          <div className="row">
            <button
              className="btn btn-sm"
              onClick={() => {
                const blob = new Blob([exportAll()], { type: 'application/json' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = `gold-desk-${new Date().toISOString().slice(0, 10)}.json`;
                a.click();
                URL.revokeObjectURL(a.href);
              }}
            >
              Exporter
            </button>
            <label className="btn btn-sm" style={{ marginBottom: 0 }}>
              Importer
              <input
                type="file"
                accept="application/json"
                hidden
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  try {
                    const r = importAll(await f.text());
                    setMsg(`${r.trades} trade(s) et ${r.analyses} analyse(s) importés.`);
                    refresh();
                  } catch {
                    setMsg('Fichier invalide.');
                  }
                  e.target.value = '';
                }}
              />
            </label>
          </div>
          {msg && (
            <p className="tiny" style={{ marginTop: 8, marginBottom: 0 }}>
              {msg}
            </p>
          )}
        </div>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------

function TradeCard({
  t,
  onUpdate,
  onDelete,
}: {
  t: JournalTrade;
  onUpdate: (t: JournalTrade) => void;
  onDelete: (id: string) => void;
}) {
  const r = tradeR(t);
  const set = <K extends keyof JournalTrade>(k: K, v: JournalTrade[K]) => onUpdate({ ...t, [k]: v });
  const num = (v: string) => {
    const n = parseFloat(v.replace(',', '.'));
    return Number.isFinite(n) ? n : null;
  };

  return (
    <details className="mod">
      <summary>
        <span className="badge" data-s={t.direction === 'LONG' ? 'PASS' : 'FAIL'}>
          {t.direction}
        </span>
        <span className="t">{t.setupName}</span>
        {r !== null && (
          <span className="sc" style={{ color: r > 0 ? 'var(--pass)' : 'var(--fail)' }}>
            {r > 0 ? '+' : ''}
            {r} R
          </span>
        )}
        <span className="badge" data-s={statusBadge(t.status)}>
          {statusLabel(t.status)}
        </span>
      </summary>

      <div className="body">
        <div className="scroll-x">
          <table>
            <tbody>
              <tr>
                <th>Ouvert</th>
                <td>{new Date(t.createdAt).toLocaleString('fr-FR')}</td>
              </tr>
              <tr>
                <th>Note d’analyse</th>
                <td>
                  {t.grade} · score {t.score}
                </td>
              </tr>
              <tr>
                <th>Niveaux</th>
                <td className="mono">
                  E {t.entry} · SL {t.stop} · TP1 {t.tp1} · TP2 {t.tp2}
                </td>
              </tr>
              <tr>
                <th>Taille</th>
                <td className="mono">
                  {t.lots} lot(s) · risque {t.riskUSD} $
                </td>
              </tr>
              <tr>
                <th>Session</th>
                <td>{t.session}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3 style={h3}>Statut</h3>
        <div className="row">
          {(['PENDING', 'ACTIVE', 'CLOSED', 'CANCELLED'] as TradeStatus[]).map((s) => (
            <button
              key={s}
              className="btn btn-sm"
              style={
                t.status === s
                  ? { borderColor: 'var(--gold)', color: 'var(--gold)' }
                  : undefined
              }
              onClick={() =>
                onUpdate({
                  ...t,
                  status: s,
                  closedAt: s === 'CLOSED' ? (t.closedAt ?? new Date().toISOString()) : null,
                })
              }
            >
              {statusLabel(s)}
            </button>
          ))}
        </div>

        {t.status === 'CLOSED' && (
          <>
            <h3 style={h3}>Clôture</h3>
            <div className="grid">
              <div className="field">
                <label htmlFor={`ex-${t.id}`}>Prix de sortie</label>
                <input
                  id={`ex-${t.id}`}
                  className="mono"
                  inputMode="decimal"
                  value={t.exit ?? ''}
                  onChange={(e) => set('exit', num(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor={`mae-${t.id}`}>MAE ($ contre toi)</label>
                <input
                  id={`mae-${t.id}`}
                  className="mono"
                  inputMode="decimal"
                  placeholder="ex. 4,20"
                  value={t.mae ?? ''}
                  onChange={(e) => set('mae', num(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor={`mfe-${t.id}`}>MFE ($ en ta faveur)</label>
                <input
                  id={`mfe-${t.id}`}
                  className="mono"
                  inputMode="decimal"
                  placeholder="ex. 18,50"
                  value={t.mfe ?? ''}
                  onChange={(e) => set('mfe', num(e.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor={`eg-${t.id}`}>Exécution (1-5)</label>
                <select
                  id={`eg-${t.id}`}
                  value={t.executionGrade ?? ''}
                  onChange={(e) => set('executionGrade', num(e.target.value))}
                >
                  <option value="">—</option>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <p className="tiny" style={{ marginTop: 8 }}>
              MAE = distance maximale parcourue contre toi avant que le prix reparte. MFE = maximum
              atteint en ta faveur. Note l’exécution indépendamment du résultat : un trade gagnant
              mal exécuté reste un mauvais trade.
            </p>
          </>
        )}

        <h3 style={h3}>Notes</h3>
        <textarea
          value={t.notes}
          placeholder="Ce que tu as bien fait, ce que tu as mal fait, ce que tu referais autrement."
          onChange={(e) => set('notes', e.target.value)}
        />

        <div className="row" style={{ marginTop: 12 }}>
          {(t.status === 'PENDING' || t.status === 'ACTIVE') && (
            <Link className="btn btn-sm" href={`/?followUp=${t.id}`}>
              Réévaluer la thèse
            </Link>
          )}
          <button
            className="btn btn-sm btn-danger"
            onClick={() => {
              if (confirm('Supprimer définitivement ce trade ?')) onDelete(t.id);
            }}
          >
            Supprimer
          </button>
        </div>
      </div>
    </details>
  );
}

// ---------------------------------------------------------------------------

function Stats({ trades, closed }: { trades: JournalTrade[]; closed: JournalTrade[] }) {
  const e = computeExpectancy(closed);
  const exc = computeExcursions(closed);
  const mc = monteCarloDrawdown(closed);
  const k = kelly(e);

  if (e.n === 0) {
    return (
      <section>
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>
            Aucun trade clôturé. Renseigne un prix de sortie sur un trade au statut « Clôturé » pour
            que les statistiques se calculent.
          </p>
        </div>
      </section>
    );
  }

  return (
    <>
      <section>
        <h2 className="sec">Espérance</h2>
        <div className="card">
          <div className="scroll-x">
            <table>
              <tbody>
                <Row k="Trades clôturés" v={String(e.n)} />
                <Row k="Taux de réussite" v={`${e.winRate} % (${e.wins}G / ${e.losses}P)`} />
                <Row k="Gain moyen" v={`${e.avgWinR} R`} />
                <Row k="Perte moyenne" v={`${e.avgLossR} R`} />
                <Row
                  k="Espérance par trade"
                  v={`${e.expectancyR > 0 ? '+' : ''}${e.expectancyR} R`}
                  color={e.expectancyR > 0 ? 'var(--pass)' : 'var(--fail)'}
                />
                <Row
                  k="R cumulé"
                  v={`${e.totalR > 0 ? '+' : ''}${e.totalR} R`}
                  color={e.totalR > 0 ? 'var(--pass)' : 'var(--fail)'}
                />
                <Row
                  k="Profit factor"
                  v={Number.isFinite(e.profitFactor) ? String(e.profitFactor) : '∞'}
                />
              </tbody>
            </table>
          </div>
          {!e.significant && (
            <p className="note" style={{ marginTop: 12, marginBottom: 0 }}>
              {e.n} trade(s) — il en faut environ 100 avant que ton taux de réussite veuille dire
              quelque chose. En dessous, c’est du bruit.
            </p>
          )}
        </div>
      </section>

      <section>
        <h2 className="sec">MAE / MFE</h2>
        <div className="card">
          <div className="scroll-x">
            <table>
              <tbody>
                <Row k="Trades documentés" v={String(exc.n)} />
                <Row k="MAE moyenne des gagnants" v={`${exc.avgMaeWinnersR} R`} />
                <Row k="MFE moyenne des gagnants" v={`${exc.avgMfeWinnersR} R`} />
                <Row k="R effectivement capturé" v={`${exc.avgCapturedR} R`} />
                <Row k="MFE moyenne des perdants" v={`${exc.avgMfeLosersR} R`} />
              </tbody>
            </table>
          </div>
          {exc.verdicts.map((v, i) => (
            <p className="note" key={i} style={{ marginTop: 12, marginBottom: 0 }}>
              {v}
            </p>
          ))}
        </div>
      </section>

      <section>
        <h2 className="sec">Attribution</h2>
        <p className="tiny" style={{ marginTop: -4 }}>
          Le résultat typique : un seul setup génère tout le profit et les autres saignent. Supprimer
          les setups perdants rapporte plus que d’en chercher un nouveau.
        </p>
        {(['setupName', 'session', 'direction', 'grade'] as const).map((by) => {
          const rows = attribute(closed, by);
          if (rows.length === 0) return null;
          return (
            <div className="card" key={by}>
              <h3 style={{ ...h3, marginTop: 0 }}>{attributionLabel(by)}</h3>
              <div className="scroll-x">
                <table>
                  <thead>
                    <tr>
                      <th>{attributionLabel(by)}</th>
                      <th className="num">N</th>
                      <th className="num">R cumulé</th>
                      <th className="num">Espérance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.key}>
                        <td>{row.key}</td>
                        <td className="num">{row.n}</td>
                        <td
                          className="num"
                          style={{ color: row.totalR > 0 ? 'var(--pass)' : 'var(--fail)' }}
                        >
                          {row.totalR > 0 ? '+' : ''}
                          {row.totalR}
                        </td>
                        <td className="num">{row.expectancyR}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </section>

      <section>
        <h2 className="sec">Risque</h2>
        <div className="card">
          {mc.n >= 10 ? (
            <>
              <h3 style={{ ...h3, marginTop: 0 }}>Monte-Carlo sur ta séquence (2000 tirages)</h3>
              <div className="scroll-x">
                <table>
                  <tbody>
                    <Row k="Drawdown médian" v={`${mc.median} R`} />
                    <Row k="Drawdown au 95e centile" v={`${mc.p95} R`} color="var(--warn)" />
                    <Row k="Pire cas observé" v={`${mc.worst} R`} color="var(--fail)" />
                  </tbody>
                </table>
              </div>
              <p className="note" style={{ marginTop: 12 }}>
                Ce sont tes propres trades remélangés 2000 fois. Le drawdown au 95e centile arrive
                une fois sur vingt : c’est celui pour lequel il faut dimensionner, pas le médian.
              </p>
            </>
          ) : (
            <p className="tiny" style={{ margin: 0 }}>
              Monte-Carlo à partir de 10 trades clôturés ({mc.n} pour l’instant).
            </p>
          )}

          {k && (
            <>
              <h3 style={h3}>Kelly</h3>
              <div className="scroll-x">
                <table>
                  <tbody>
                    <Row k="Kelly plein" v={`${k.full} % du capital`} />
                    <Row k="Kelly 1/4 (recommandé)" v={`${k.quarter} %`} color="var(--gold)" />
                  </tbody>
                </table>
              </div>
              <p className="note" style={{ marginTop: 12, marginBottom: 0 }}>
                Kelly plein suppose des paramètres connus avec certitude — ce n’est jamais le cas — et
                est psychologiquement intenable. On trade à 1/4 ou 1/2 Kelly.
              </p>
            </>
          )}
        </div>
      </section>

      <p className="tiny">
        {trades.length - closed.length} trade(s) encore ouvert(s) ou en attente, non comptabilisé(s).
      </p>
    </>
  );
}

function Row({ k, v, color }: { k: string; v: string; color?: string }) {
  return (
    <tr>
      <th style={{ width: '52%' }}>{k}</th>
      <td className="mono" style={{ color }}>
        {v}
      </td>
    </tr>
  );
}

const h3: React.CSSProperties = {
  fontSize: 10.5,
  textTransform: 'uppercase',
  letterSpacing: '0.07em',
  color: 'var(--fg-3)',
  margin: '14px 0 6px',
  fontWeight: 600,
};

function statusLabel(s: TradeStatus): string {
  return { PENDING: 'En attente', ACTIVE: 'Ouvert', CLOSED: 'Clôturé', CANCELLED: 'Annulé' }[s];
}

function statusBadge(s: TradeStatus): string {
  return { PENDING: 'WARN', ACTIVE: 'PASS', CLOSED: 'UNKNOWN', CANCELLED: 'UNKNOWN' }[s];
}

function attributionLabel(by: string): string {
  return (
    { setupName: 'Par setup', session: 'Par session', direction: 'Par direction', grade: 'Par note' }[
      by
    ] ?? by
  );
}
