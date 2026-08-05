'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ContextForm, DEFAULT_CONTEXT } from '@/components/ContextForm';
import { Dropzone } from '@/components/Dropzone';
import { Report } from '@/components/Report';
import { MAX_TOTAL_BYTES } from '@/lib/image';
import {
  getSavedContext,
  getTrades,
  saveAnalysis,
  saveContext,
  saveTrade,
  tradeFromAnalysis,
} from '@/lib/storage';
import type { Analysis, AnalysisContext, ChartUpload, JournalTrade } from '@/lib/types';

type Phase = 'idle' | 'running' | 'done' | 'error';

export default function AnalyzePage() {
  const router = useRouter();
  const [ctx, setCtx] = useState<AnalysisContext>(DEFAULT_CONTEXT);
  const [charts, setCharts] = useState<ChartUpload[]>([]);
  const [phase, setPhase] = useState<Phase>('idle');
  const [status, setStatus] = useState('');
  const [chars, setChars] = useState(0);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Analysis | null>(null);
  const [followUp, setFollowUp] = useState<JournalTrade | null>(null);

  // Contexte mémorisé d'une session à l'autre (sauf les notes, propres au trade).
  useEffect(() => {
    const saved = getSavedContext<Partial<AnalysisContext>>({});
    setCtx({ ...DEFAULT_CONTEXT, ...saved, notes: '' });

    const id = new URLSearchParams(window.location.search).get('followUp');
    if (id) {
      const t = getTrades().find((x) => x.id === id);
      if (t) setFollowUp(t);
    }
  }, []);

  useEffect(() => {
    if (phase !== 'running') saveContext({ ...ctx, notes: '' });
  }, [ctx, phase]);

  const totalBytes = useMemo(() => charts.reduce((s, c) => s + c.bytes, 0), [charts]);
  const tooHeavy = totalBytes > MAX_TOTAL_BYTES;
  const canRun = charts.length > 0 && !tooHeavy && phase !== 'running';

  async function run() {
    setPhase('running');
    setError('');
    setResult(null);
    setChars(0);
    setStatus('Envoi…');

    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          context: ctx,
          charts,
          followUp: followUp
            ? {
                direction: followUp.direction,
                setupName: followUp.setupName,
                entry: followUp.entry,
                stop: followUp.stop,
                tp1: followUp.tp1,
                tp2: followUp.tp2,
                invalidation: followUp.snapshot?.tradePlan.invalidation ?? '',
                rationale: followUp.snapshot?.tradePlan.rationale ?? '',
                openedAt: new Date(followUp.createdAt).toLocaleString('fr-FR'),
              }
            : undefined,
        }),
      });

      if (!res.ok || !res.body) {
        const msg = await res.text().catch(() => '');
        throw new Error(safeMessage(msg) || `Erreur ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.type === 'status') setStatus(ev.message);
          else if (ev.type === 'progress') setChars(ev.chars);
          else if (ev.type === 'error') throw new Error(ev.message);
          else if (ev.type === 'result') {
            setResult(ev.data);
            saveAnalysis(ev.data);
            setPhase('done');
            window.scrollTo({ top: 0, behavior: 'smooth' });
          }
        }
      }
      setPhase((p) => (p === 'running' ? 'error' : p));
      setError((e) => e || 'Flux interrompu avant la fin de l’analyse.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur inconnue.');
      setPhase('error');
    }
  }

  function sendToJournal() {
    if (!result) return;
    const t = tradeFromAnalysis(result);
    saveTrade(t);
    router.push('/journal');
  }

  return (
    <>
      {followUp && (
        <section>
          <div className="card" style={{ borderColor: 'var(--gold-dim)' }}>
            <strong style={{ fontSize: 13 }}>Suivi de trade</strong>
            <p className="muted" style={{ marginBottom: 8 }}>
              {followUp.direction} {followUp.setupName} — entrée {followUp.entry}, stop{' '}
              {followUp.stop}. Charge les graphiques actuels : l’analyse portera sur la validité de
              la thèse, pas sur un nouveau setup.
            </p>
            <button
              className="btn btn-sm"
              onClick={() => {
                setFollowUp(null);
                router.replace('/');
              }}
            >
              Annuler le suivi
            </button>
          </div>
        </section>
      )}

      <section>
        <h2 className="sec">Graphiques</h2>
        <Dropzone charts={charts} onChange={setCharts} />
      </section>

      <ContextForm ctx={ctx} onChange={setCtx} />

      {phase === 'running' && (
        <section>
          <div className="card">
            <div className="row">
              <span className="spin" />
              <strong style={{ fontSize: 13.5 }}>{status}</strong>
            </div>
            <p className="tiny" style={{ marginTop: 8, marginBottom: 0 }}>
              {chars > 0 && `${chars.toLocaleString('fr-FR')} caractères produits. `}
              Les 14 couches sont traitées une par une — compte 1 à 3 minutes. Ne ferme pas l’onglet.
            </p>
          </div>
        </section>
      )}

      {phase === 'error' && (
        <section>
          <div className="card" style={{ borderColor: '#4a2b2b' }}>
            <strong style={{ fontSize: 13.5, color: 'var(--fail)' }}>Analyse interrompue</strong>
            <p className="muted" style={{ marginBottom: 0 }}>
              {error}
            </p>
          </div>
        </section>
      )}

      {result && <Report a={result} onJournal={followUp ? undefined : sendToJournal} />}

      <div className="sticky-cta">
        <div className="inner">
          <button className="btn btn-primary btn-block" disabled={!canRun} onClick={() => void run()}>
            {phase === 'running'
              ? 'Analyse en cours…'
              : charts.length === 0
                ? 'Ajoute au moins un graphique'
                : tooHeavy
                  ? 'Graphiques trop lourds'
                  : followUp
                    ? 'Réévaluer le trade'
                    : `Analyser (${charts.length} graphique${charts.length > 1 ? 's' : ''})`}
          </button>
        </div>
      </div>
    </>
  );
}

function safeMessage(body: string): string {
  try {
    return (JSON.parse(body) as { error?: string }).error ?? '';
  } catch {
    return '';
  }
}
