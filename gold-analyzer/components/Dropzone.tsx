'use client';

import { useCallback, useRef, useState } from 'react';
import { MAX_TOTAL_BYTES, guessTimeframe, prepareImage } from '@/lib/image';
import type { ChartUpload } from '@/lib/types';

const TIMEFRAMES = ['W1', 'D1', 'H4', 'H1', 'M30', 'M15', 'M5', 'M1', 'Autre'];

interface Props {
  charts: ChartUpload[];
  onChange: (charts: ChartUpload[]) => void;
}

export function Dropzone({ charts, onChange }: Props) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    async (files: FileList | File[]) => {
      setError('');
      setBusy(true);
      const next = [...charts];
      try {
        for (const file of Array.from(files)) {
          if (!file.type.startsWith('image/')) continue;
          const img = await prepareImage(file);
          next.push({
            id: `ch_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
            timeframe: guessTimeframe(file.name),
            dataUrl: img.dataUrl,
            mediaType: img.mediaType,
            bytes: img.bytes,
          });
        }
        const total = next.reduce((s, c) => s + c.bytes, 0);
        if (total > MAX_TOTAL_BYTES) {
          setError(
            `Poids total ${(total / 1e6).toFixed(1)} Mo — au-delà de la limite d’envoi. Retire un graphique.`,
          );
        }
        onChange(next);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Échec du traitement de l’image.');
      } finally {
        setBusy(false);
      }
    },
    [charts, onChange],
  );

  const total = charts.reduce((s, c) => s + c.bytes, 0);
  const missingTf = charts.some((c) => !c.timeframe);

  return (
    <div>
      <div
        className="dz"
        data-over={over}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void addFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <div style={{ fontSize: 22, marginBottom: 6 }}>{busy ? <span className="spin" /> : '📈'}</div>
        <div style={{ fontSize: 14, color: 'var(--fg)', fontWeight: 550 }}>
          {busy ? 'Traitement…' : 'Glisse tes graphiques ou touche pour choisir'}
        </div>
        <div className="tiny" style={{ marginTop: 5 }}>
          H4, H1, M30, M5 — plus le Daily/Weekly pour le biais. Redimensionnés automatiquement.
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) void addFiles(e.target.files);
            e.target.value = '';
          }}
        />
      </div>

      {error && (
        <p className="tiny" style={{ color: 'var(--fail)', marginTop: 8 }}>
          {error}
        </p>
      )}

      {charts.length > 0 && (
        <>
          <div className="thumbs">
            {charts.map((c) => (
              <div key={c.id} className="thumb">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={c.dataUrl} alt={c.timeframe || 'graphique'} />
                <button
                  type="button"
                  className="rm"
                  aria-label="Retirer"
                  onClick={() => onChange(charts.filter((x) => x.id !== c.id))}
                >
                  ×
                </button>
                <select
                  className="tf"
                  value={c.timeframe}
                  onChange={(e) =>
                    onChange(
                      charts.map((x) =>
                        x.id === c.id ? { ...x, timeframe: e.target.value } : x,
                      ),
                    )
                  }
                >
                  <option value="">Timeframe ?</option>
                  {TIMEFRAMES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <p className="tiny" style={{ marginTop: 8 }}>
            {charts.length} graphique(s) · {(total / 1e6).toFixed(2)} Mo
            {missingTf && (
              <span style={{ color: 'var(--warn)' }}>
                {' '}
                — indique le timeframe de chaque image, l’analyse multi-TF en dépend.
              </span>
            )}
          </p>
        </>
      )}
    </div>
  );
}
