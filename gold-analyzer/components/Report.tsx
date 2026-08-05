'use client';

import { MODULES } from '@/lib/modules';
import { gradeMeaning } from '@/lib/scoring';
import type { Analysis, ModuleResult, Status } from '@/lib/types';

const STATUS_COLOR: Record<Status, string> = {
  PASS: 'var(--pass)',
  WARN: 'var(--warn)',
  FAIL: 'var(--fail)',
  UNKNOWN: 'var(--unknown)',
};

const GRADE_COLOR: Record<string, string> = {
  'A+': 'var(--pass)',
  A: 'var(--pass)',
  B: 'var(--warn)',
  C: 'var(--warn)',
  'NO TRADE': 'var(--fail)',
};

export function Report({ a, onJournal }: { a: Analysis; onJournal?: () => void }) {
  const failed = a.gates.filter((g) => !g.passed);
  const tradeable = a.grade !== 'NO TRADE' && a.tradePlan.hasTrade;

  return (
    <>
      {/* ---------- Verdict ---------- */}
      <section>
        <div className="verdict" data-trade={tradeable}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div>
              <div className="grade" style={{ color: GRADE_COLOR[a.grade] }}>
                {a.grade}
              </div>
              <div className="tiny" style={{ marginTop: 4 }}>
                {new Date(a.createdAt).toLocaleString('fr-FR')}
              </div>
            </div>
            {tradeable && (
              <span
                className="badge"
                data-s={a.tradePlan.direction === 'LONG' ? 'PASS' : 'FAIL'}
                style={{ fontSize: 13, padding: '6px 14px' }}
              >
                {a.tradePlan.direction}
              </span>
            )}
          </div>

          <p className="muted" style={{ marginBottom: 0, marginTop: 12 }}>
            {gradeMeaning(a.grade)}
          </p>

          <div className="dials">
            <Dial label="Score pondéré" value={a.score} />
            <Dial label="Confiance" value={a.confidenceScore} />
            <Dial label="Complétude données" value={a.dataQuality.completeness} />
          </div>

          <p className="tiny" style={{ marginTop: 10, marginBottom: 0 }}>
            Le score mesure la qualité du setup. La confiance mesure ce qu’on en sait réellement. Un
            score élevé sur une confiance faible ne vaut rien — c’est pourquoi les deux sont séparés.
          </p>
        </div>
      </section>

      {/* ---------- Conditions éliminatoires ---------- */}
      <section>
        <h2 className="sec">
          Conditions éliminatoires — {a.gates.filter((g) => g.passed).length}/{a.gates.length}
        </h2>
        <div className="card">
          {failed.length > 0 && (
            <p className="note" style={{ marginTop: 0, marginBottom: 14 }}>
              {failed.length} condition(s) non remplie(s). Une seule suffit à annuler le trade, quel
              que soit le score des autres couches.
            </p>
          )}
          {a.gates.map((g) => (
            <div className="gate" key={g.id}>
              <span className="ic" style={{ color: g.passed ? 'var(--pass)' : 'var(--fail)' }}>
                {g.passed ? '✓' : '✕'}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 550 }}>{g.label}</div>
                <div className="tiny" style={{ marginTop: 2 }}>
                  {g.reason}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- Plan de trade ---------- */}
      <section>
        <h2 className="sec">Plan de trade</h2>
        {a.tradePlan.hasTrade ? (
          <div className="card">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <strong style={{ fontSize: 14 }}>{a.tradePlan.setupName}</strong>
              <span className="tiny">
                {a.tradePlan.timeframe} · entrée {entryLabel(a.tradePlan.entryType)}
              </span>
            </div>

            <div className="levels">
              <Level k="Entrée" v={a.tradePlan.entry} />
              <Level k="Stop" v={a.tradePlan.stop} color="var(--fail)" />
              <Level k="TP1" v={a.tradePlan.tp1} color="var(--pass)" />
              <Level k="TP2" v={a.tradePlan.tp2} color="var(--pass)" />
            </div>

            {a.sizing && (
              <div className="scroll-x">
                <table>
                  <tbody>
                    <Row k="Taille de position" v={`${a.sizing.lots} lot(s)`} />
                    <Row k="Distance de stop" v={`${a.sizing.stopDistance} $`} />
                    <Row
                      k="Risque réel"
                      v={`${a.sizing.riskActual} $ (demandé ${a.sizing.riskRequested} $)`}
                    />
                    <Row k="R:R au TP1" v={`${a.sizing.rr1}`} />
                    <Row k="R:R au TP2" v={`${a.sizing.rr2}`} />
                    {a.context.atrDaily && (
                      <Row
                        k="Stop en ATR"
                        v={`${(a.sizing.stopDistance / a.context.atrDaily).toFixed(2)} × ATR journalier`}
                      />
                    )}
                  </tbody>
                </table>
              </div>
            )}

            <Block title="Déclencheur" body={a.tradePlan.trigger} />
            <Block title="Invalidation" body={a.tradePlan.invalidation} />
            <Block title="Raisonnement" body={a.tradePlan.rationale} />

            {a.tradePlan.riskNotes.length > 0 && (
              <>
                <h3 style={h3}>Risques spécifiques</h3>
                <ul style={{ margin: 0, paddingLeft: 17 }}>
                  {a.tradePlan.riskNotes.map((r, i) => (
                    <li key={i} style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--fg-2)' }}>
                      {r}
                    </li>
                  ))}
                </ul>
              </>
            )}

            {onJournal && tradeable && (
              <button className="btn btn-primary btn-block" style={{ marginTop: 16 }} onClick={onJournal}>
                Envoyer au journal et suivre
              </button>
            )}
            {onJournal && !tradeable && (
              <p className="tiny" style={{ marginTop: 14, marginBottom: 0, color: 'var(--warn)' }}>
                Un setup existe mais une condition éliminatoire bloque. Il n’est pas envoyable au
                journal.
              </p>
            )}
          </div>
        ) : (
          <div className="card">
            <strong style={{ fontSize: 14, color: 'var(--fail)' }}>Aucun trade</strong>
            <p className="muted" style={{ marginBottom: 0 }}>
              {a.tradePlan.rationale}
            </p>
          </div>
        )}
      </section>

      {/* ---------- Synthèse ---------- */}
      <section>
        <h2 className="sec">Synthèse</h2>
        <div className="card">
          <div className="scroll-x">
            <table>
              <tbody>
                <Row k="Régime" v={a.synthesis.regime} />
                <Row k="Driver dominant" v={a.synthesis.dominantDriver} />
                <Row k="Biais HTF" v={a.synthesis.bias} />
              </tbody>
            </table>
          </div>
          <Block title="Lecture" body={a.synthesis.summary} />
          <Block title="Réaction au news" body={a.synthesis.reactionCheck} />
          <Block title="Ce qui retournerait cette lecture" body={a.synthesis.whatWouldChangeMyMind} />
        </div>
      </section>

      {/* ---------- Les 14 couches ---------- */}
      <section>
        <h2 className="sec">Les 14 couches</h2>
        {a.modules.map((m) => (
          <ModuleCard key={m.id} m={m} />
        ))}
      </section>

      {/* ---------- Qualité des données ---------- */}
      <section>
        <h2 className="sec">Qualité des données</h2>
        <div className="card">
          <p className="muted" style={{ marginTop: 0 }}>
            {a.dataQuality.notes}
          </p>
          {a.dataQuality.missing.length > 0 && (
            <>
              <h3 style={h3}>Manquant</h3>
              <ul style={{ margin: 0, paddingLeft: 17 }}>
                {a.dataQuality.missing.map((x, i) => (
                  <li key={i} style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--fg-3)' }}>
                    {x}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </section>

      <p className="tiny" style={{ marginTop: 22 }}>
        Cadre d’analyse à but pédagogique. Aucune analyse ne garantit un trade gagnant et la majorité
        des traders particuliers perdent de l’argent sur l’or. Ceci n’est pas un conseil en
        investissement.
      </p>
    </>
  );
}

function ModuleCard({ m }: { m: ModuleResult }) {
  const def = MODULES.find((d) => d.id === m.id);
  const score = m.status === 'UNKNOWN' ? 50 : m.score;
  return (
    <details className="mod">
      <summary>
        <span className="n">{def?.n ?? ''}</span>
        <span className="t">{def?.title ?? m.id}</span>
        {def?.gate && (
          <span className="tiny" style={{ color: 'var(--gold-dim)', flex: 'none' }}>
            élim.
          </span>
        )}
        <span className="sc">{score}</span>
        <span className="badge" data-s={m.status}>
          {m.status}
        </span>
      </summary>
      <div className="body">
        <div className="bar" style={{ marginTop: 0, marginBottom: 12 }}>
          <i style={{ width: `${score}%`, background: STATUS_COLOR[m.status] }} />
        </div>

        {m.findings.length > 0 && (
          <ul>
            {m.findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        )}

        <p className="muted" style={{ marginTop: 0 }}>
          {m.reasoning}
        </p>

        {m.dataGaps.length > 0 && (
          <>
            <h3 style={h3}>Données manquantes</h3>
            <ul className="gaps">
              {m.dataGaps.map((g, i) => (
                <li key={i}>{g}</li>
              ))}
            </ul>
          </>
        )}

        <p className="tiny" style={{ marginBottom: 0 }}>
          Poids {def?.weight ?? 0}/100 · confiance {m.confidence}
        </p>
      </div>
    </details>
  );
}

function Dial({ label, value }: { label: string; value: number }) {
  const color = value >= 70 ? 'var(--pass)' : value >= 50 ? 'var(--warn)' : 'var(--fail)';
  return (
    <div className="dial">
      <div className="v mono" style={{ color }}>
        {value}
      </div>
      <div className="k">{label}</div>
      <div className="bar">
        <i style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color }} />
      </div>
    </div>
  );
}

function Level({ k, v, color }: { k: string; v: number; color?: string }) {
  return (
    <div className="lvl">
      <div className="k">{k}</div>
      <div className="v" style={{ color }}>
        {v ? v.toLocaleString('fr-FR', { minimumFractionDigits: 2 }) : '—'}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <tr>
      <th style={{ width: '42%' }}>{k}</th>
      <td>{v}</td>
    </tr>
  );
}

function Block({ title, body }: { title: string; body: string }) {
  if (!body) return null;
  return (
    <>
      <h3 style={h3}>{title}</h3>
      <p className="muted" style={{ marginTop: 0, marginBottom: 12 }}>
        {body}
      </p>
    </>
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

function entryLabel(t: string): string {
  switch (t) {
    case 'CONFIRMATION':
      return 'sur confirmation';
    case 'LIMIT':
      return 'ordre limite';
    case 'STOP':
      return 'ordre stop';
    case 'MARKET':
      return 'au marché';
    default:
      return '—';
  }
}
