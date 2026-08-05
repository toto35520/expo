'use client';

import { useMemo, useState } from 'react';
import { MODULES, type ModuleId } from '@/lib/modules';
import { assembleAnalysis } from '@/lib/assemble';
import type { Analysis, AnalysisContext, Direction, Status } from '@/lib/types';

/**
 * Mode manuel : aucune API, aucun quota, aucun compte.
 * L'utilisateur note les 14 couches, l'app applique exactement les mêmes
 * conditions éliminatoires, le même score et le même dimensionnement.
 */

const STATUS_SCORE: Record<Status, number> = { PASS: 85, WARN: 55, FAIL: 20, UNKNOWN: 50 };
const STATUS_LABEL: Record<Status, string> = {
  PASS: 'Soutient',
  WARN: 'Réserve',
  FAIL: 'Contredit',
  UNKNOWN: 'Inconnu',
};

interface Entry {
  status: Status;
  note: string;
}

type Plan = {
  hasTrade: boolean;
  direction: Direction;
  setupName: string;
  timeframe: string;
  entry: string;
  stop: string;
  tp1: string;
  tp2: string;
  trigger: string;
  invalidation: string;
  rationale: string;
};

const EMPTY_PLAN: Plan = {
  hasTrade: true,
  direction: 'LONG',
  setupName: '',
  timeframe: '',
  entry: '',
  stop: '',
  tp1: '',
  tp2: '',
  trigger: '',
  invalidation: '',
  rationale: '',
};

export function ManualForm({
  ctx,
  onResult,
}: {
  ctx: AnalysisContext;
  onResult: (a: Analysis) => void;
}) {
  const [entries, setEntries] = useState<Record<ModuleId, Entry>>(() =>
    Object.fromEntries(MODULES.map((m) => [m.id, { status: 'UNKNOWN' as Status, note: '' }])) as Record<
      ModuleId,
      Entry
    >,
  );
  const [plan, setPlan] = useState<Plan>(EMPTY_PLAN);
  const [regime, setRegime] = useState('');
  const [driver, setDriver] = useState('');

  const graded = useMemo(
    () => MODULES.filter((m) => entries[m.id].status !== 'UNKNOWN').length,
    [entries],
  );

  const setStatus = (id: ModuleId, status: Status) =>
    setEntries((e) => ({ ...e, [id]: { ...e[id], status } }));
  const setNote = (id: ModuleId, note: string) =>
    setEntries((e) => ({ ...e, [id]: { ...e[id], note } }));

  function compute() {
    // Complétude pondérée : une couche notée compte pour son poids réel.
    const totalWeight = MODULES.reduce((s, m) => s + m.weight, 0);
    const gradedWeight = MODULES.filter((m) => entries[m.id].status !== 'UNKNOWN').reduce(
      (s, m) => s + m.weight,
      0,
    );

    const raw = {
      dataQuality: {
        completeness: Math.round((gradedWeight / totalWeight) * 100),
        notes:
          graded === MODULES.length
            ? 'Analyse manuelle : les 14 couches ont été évaluées.'
            : `Analyse manuelle : ${graded} couche(s) sur ${MODULES.length} évaluée(s). Les autres restent UNKNOWN.`,
        missing: MODULES.filter((m) => entries[m.id].status === 'UNKNOWN').map((m) => m.title),
      },
      modules: MODULES.map((m) => {
        const e = entries[m.id];
        return {
          id: m.id,
          status: e.status,
          score: STATUS_SCORE[e.status],
          // En mode manuel, c'est l'utilisateur qui affirme : une couche notée
          // est donc une couche assumée.
          confidence: e.status === 'UNKNOWN' ? 'NONE' : 'HIGH',
          findings: e.note.trim() ? [e.note.trim()] : [],
          dataGaps: e.status === 'UNKNOWN' ? ['Non évaluée.'] : [],
          reasoning: e.note.trim() || `Noté « ${STATUS_LABEL[e.status]} » en analyse manuelle.`,
        };
      }),
      tradePlan: {
        ...plan,
        entryType: 'CONFIRMATION',
        entry: plan.entry,
        stop: plan.stop,
        tp1: plan.tp1,
        tp2: plan.tp2,
        riskNotes: [],
      },
      synthesis: {
        regime,
        dominantDriver: driver,
        bias: '',
        summary: 'Analyse manuelle — le raisonnement est celui de l’utilisateur.',
        reactionCheck: ctx.lastNewsReaction || '',
        whatWouldChangeMyMind: plan.invalidation,
      },
    };

    onResult(assembleAnalysis(raw, ctx));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  return (
    <>
      <section>
        <h2 className="sec">
          Notation des couches — {graded}/{MODULES.length}
        </h2>
        <p className="tiny" style={{ marginTop: -4, marginBottom: 10 }}>
          Laisse « Inconnu » ce que tu n’as pas vérifié. Cocher au hasard fait monter le score sans
          rien apporter — c’est le seul moyen de tromper cet outil, et ce serait te tromper toi.
        </p>

        {MODULES.map((m) => {
          const e = entries[m.id];
          return (
            <details className="mod" key={m.id}>
              <summary>
                <span className="n">{m.n}</span>
                <span className="t">{m.title}</span>
                {m.gate && (
                  <span className="tiny" style={{ color: 'var(--gold-dim)', flex: 'none' }}>
                    élim.
                  </span>
                )}
                <span className="badge" data-s={e.status}>
                  {STATUS_LABEL[e.status]}
                </span>
              </summary>
              <div className="body">
                <p className="tiny" style={{ marginTop: 0 }}>
                  {m.brief}
                </p>
                <div className="row" style={{ gap: 6 }}>
                  {(['PASS', 'WARN', 'FAIL', 'UNKNOWN'] as Status[]).map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="btn btn-sm"
                      data-on={e.status === s}
                      style={
                        e.status === s
                          ? { borderColor: 'var(--gold)', color: 'var(--gold)' }
                          : undefined
                      }
                      onClick={() => setStatus(m.id, s)}
                    >
                      {STATUS_LABEL[s]}
                    </button>
                  ))}
                </div>
                <div className="field" style={{ marginTop: 10 }}>
                  <label htmlFor={`n-${m.id}`}>Constat (facultatif)</label>
                  <input
                    id={`n-${m.id}`}
                    value={e.note}
                    placeholder="Ce que tu observes concrètement"
                    onChange={(ev) => setNote(m.id, ev.target.value)}
                  />
                </div>
                <p className="tiny" style={{ marginBottom: 0, marginTop: 8 }}>
                  Poids {m.weight}/100
                </p>
              </div>
            </details>
          );
        })}
      </section>

      <section>
        <h2 className="sec">Le trade envisagé</h2>
        <div className="card">
          <div className="row" style={{ gap: 6, marginBottom: 12 }}>
            {(['LONG', 'SHORT'] as Direction[]).map((d) => (
              <button
                key={d}
                type="button"
                className="btn btn-sm"
                style={
                  plan.hasTrade && plan.direction === d
                    ? { borderColor: 'var(--gold)', color: 'var(--gold)' }
                    : undefined
                }
                onClick={() => setPlan((p) => ({ ...p, hasTrade: true, direction: d }))}
              >
                {d}
              </button>
            ))}
            <button
              type="button"
              className="btn btn-sm"
              style={!plan.hasTrade ? { borderColor: 'var(--gold)', color: 'var(--gold)' } : undefined}
              onClick={() => setPlan((p) => ({ ...p, hasTrade: false }))}
            >
              Aucun trade
            </button>
          </div>

          {plan.hasTrade && (
            <>
              <div className="grid">
                <Field
                  id="m-entry"
                  label="Entrée ($)"
                  value={plan.entry}
                  onChange={(v) => setPlan((p) => ({ ...p, entry: v }))}
                />
                <Field
                  id="m-stop"
                  label="Stop ($)"
                  value={plan.stop}
                  onChange={(v) => setPlan((p) => ({ ...p, stop: v }))}
                />
                <Field
                  id="m-tp1"
                  label="TP1 ($)"
                  value={plan.tp1}
                  onChange={(v) => setPlan((p) => ({ ...p, tp1: v }))}
                />
                <Field
                  id="m-tp2"
                  label="TP2 ($)"
                  value={plan.tp2}
                  onChange={(v) => setPlan((p) => ({ ...p, tp2: v }))}
                />
              </div>

              <div className="grid" style={{ marginTop: 10 }}>
                <Field
                  id="m-setup"
                  label="Nom du setup"
                  value={plan.setupName}
                  numeric={false}
                  onChange={(v) => setPlan((p) => ({ ...p, setupName: v }))}
                />
                <Field
                  id="m-tf"
                  label="Timeframe"
                  value={plan.timeframe}
                  numeric={false}
                  onChange={(v) => setPlan((p) => ({ ...p, timeframe: v }))}
                />
              </div>

              <div className="field" style={{ marginTop: 10 }}>
                <label htmlFor="m-trig">Déclencheur</label>
                <input
                  id="m-trig"
                  placeholder="Ce que tu attends avant d’entrer"
                  value={plan.trigger}
                  onChange={(e) => setPlan((p) => ({ ...p, trigger: e.target.value }))}
                />
              </div>
              <div className="field" style={{ marginTop: 10 }}>
                <label htmlFor="m-inval">Invalidation</label>
                <input
                  id="m-inval"
                  placeholder="Ce qui casse la thèse, indépendamment du stop"
                  value={plan.invalidation}
                  onChange={(e) => setPlan((p) => ({ ...p, invalidation: e.target.value }))}
                />
              </div>
            </>
          )}

          <div className="field" style={{ marginTop: 10 }}>
            <label htmlFor="m-rat">
              {plan.hasTrade ? 'Raisonnement' : 'Pourquoi tu ne prends pas ce trade'}
            </label>
            <textarea
              id="m-rat"
              value={plan.rationale}
              onChange={(e) => setPlan((p) => ({ ...p, rationale: e.target.value }))}
            />
          </div>

          <div className="grid" style={{ marginTop: 10 }}>
            <Field
              id="m-reg"
              label="Régime observé"
              value={regime}
              numeric={false}
              onChange={setRegime}
            />
            <Field
              id="m-drv"
              label="Driver dominant"
              value={driver}
              numeric={false}
              onChange={setDriver}
            />
          </div>
        </div>
      </section>

      <div className="sticky-cta">
        <div className="inner">
          <button className="btn btn-primary btn-block" onClick={compute}>
            Calculer le verdict
          </button>
        </div>
      </div>
    </>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  numeric = true,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  numeric?: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className={numeric ? 'mono' : undefined}
        inputMode={numeric ? 'decimal' : undefined}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
