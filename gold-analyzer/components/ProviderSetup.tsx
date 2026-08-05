'use client';

import { useState } from 'react';
import { PROVIDERS, PROVIDER_BY_ID, type ProviderSettings } from '@/lib/providers';

interface Props {
  settings: ProviderSettings;
  onChange: (s: ProviderSettings) => void;
}

export function ProviderSetup({ settings, onChange }: Props) {
  const [reveal, setReveal] = useState(false);
  const def = PROVIDER_BY_ID[settings.provider];
  const needsKey = settings.provider !== 'manual';
  const ready = !needsKey || settings.apiKey.trim().length > 0;

  return (
    <section>
      <h2 className="sec">Moteur d’analyse</h2>
      <div className="card">
        <div className="providers">
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              type="button"
              className="prov"
              data-active={p.id === settings.provider}
              onClick={() =>
                onChange({
                  provider: p.id,
                  model: p.models[0]?.id ?? '',
                  apiKey: p.id === settings.provider ? settings.apiKey : '',
                })
              }
            >
              <span className="nm">{p.label}</span>
              {p.id === 'manual' && <span className="free">0 €, sans compte</span>}
              {p.id === 'gemini' && <span className="free">conseillé</span>}
            </button>
          ))}
        </div>

        <p className="muted" style={{ marginTop: 12 }}>
          {def.summary}
        </p>

        {needsKey && (
          <>
            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="model">Modèle</label>
              <select
                id="model"
                value={settings.model}
                onChange={(e) => onChange({ ...settings, model: e.target.value })}
              >
                {def.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {m.note ? ` — ${m.note}` : ''}
                  </option>
                ))}
              </select>
            </div>

            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="key">
                Clé API {def.label} · {def.keyHint}
              </label>
              <div className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
                <input
                  id="key"
                  type={reveal ? 'text' : 'password'}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="Colle ta clé gratuite ici"
                  value={settings.apiKey}
                  onChange={(e) => onChange({ ...settings, apiKey: e.target.value })}
                />
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ flex: 'none' }}
                  onClick={() => setReveal((r) => !r)}
                >
                  {reveal ? 'Cacher' : 'Voir'}
                </button>
              </div>
            </div>

            <p className="tiny" style={{ marginTop: 8 }}>
              <a href={def.keyUrl} target="_blank" rel="noreferrer">
                Créer une clé gratuite →
              </a>{' '}
              La clé reste dans le stockage local de ce navigateur. Elle transite par le serveur
              uniquement le temps d’un appel, et n’y est jamais enregistrée.
            </p>

            {!ready && (
              <p className="tiny" style={{ color: 'var(--warn)', marginTop: 6 }}>
                Sans clé, seul le mode manuel est disponible.
              </p>
            )}
          </>
        )}

        <details style={{ marginTop: 12 }}>
          <summary>Ce qu’il faut savoir sur ce choix</summary>
          <ul style={{ margin: 0, paddingLeft: 17 }}>
            {def.caveats.map((c, i) => (
              <li key={i} style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--fg-2)' }}>
                {c}
              </li>
            ))}
          </ul>
        </details>

        {needsKey && (
          <p className="note" style={{ marginTop: 12, marginBottom: 0 }}>
            Un modèle gratuit lit les graphiques moins finement qu’un modèle haut de gamme : attends-toi
            à davantage de couches UNKNOWN. C’est le comportement voulu — le score et les conditions
            éliminatoires, eux, sont calculés par l’app et ne changent pas d’un fournisseur à l’autre.
          </p>
        )}
      </div>
    </section>
  );
}
