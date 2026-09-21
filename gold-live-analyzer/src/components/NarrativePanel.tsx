'use client';

import type { Narrative, NarrativeLine } from '@/lib/engine/narrative';
import { Card } from './ui';

const TONE_COLOR: Record<NarrativeLine['tone'], string> = {
  HAUSSIER: 'var(--color-bull)',
  BAISSIER: 'var(--color-bear)',
  NEUTRE: 'var(--color-muted)',
  ALERTE: 'var(--color-warn)',
};

/** Le panneau "ce que je vois" : la lecture du marche en clair. */
export function NarrativePanel({ narrative }: { narrative: Narrative | null }) {
  if (!narrative) {
    return (
      <Card title="Ce que je vois en direct">
        <p className="text-sm text-[var(--color-muted)]">
          En attente des premieres donnees de marche...
        </p>
      </Card>
    );
  }

  const sections: { title: string; lines: NarrativeLine[] }[] = [
    { title: 'Contexte', lines: narrative.context },
    { title: 'Structure', lines: narrative.structure },
    { title: 'Momentum et volatilite', lines: narrative.momentum },
    { title: 'Niveaux', lines: narrative.levels },
  ];

  return (
    <Card title="Ce que je vois en direct" subtitle={`Mis a jour a ${narrative.updatedAt}`}>
      <p className="mb-4 border-l-2 border-[var(--color-gold)] pl-3 text-[15px] font-semibold leading-snug">
        {narrative.headline}
      </p>

      <div className="space-y-4">
        {sections.map((section) => (
          <div key={section.title}>
            <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-muted)]">
              {section.title}
            </h3>
            <ul className="space-y-1.5">
              {section.lines.map((line, i) => (
                <li key={i} className="flex gap-2 text-[13px] leading-relaxed">
                  <span
                    className="mt-[7px] h-1 w-1 shrink-0 rounded-full"
                    style={{ background: TONE_COLOR[line.tone] }}
                  />
                  <span className="text-[var(--color-text)]/90">{line.text}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}

        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
          <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-gold)]">
            Verdict
          </h3>
          <ul className="space-y-1.5">
            {narrative.verdict.map((line, i) => (
              <li
                key={i}
                className="text-[13px] font-medium leading-relaxed"
                style={{ color: TONE_COLOR[line.tone] }}
              >
                {line.text}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
