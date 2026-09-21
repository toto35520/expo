'use client';

import type { AnalyzerSettings } from '@/lib/engine/analyzer';
import type { RiskSettings } from '@/lib/engine/risk';
import { TIMEFRAMES, type Timeframe } from '@/lib/market/types';
import { Card } from './ui';

export function SettingsPanel({
  settings,
  risk,
  soundEnabled,
  onSettings,
  onRisk,
  onSound,
}: {
  settings: AnalyzerSettings;
  risk: RiskSettings;
  soundEnabled: boolean;
  onSettings: (next: AnalyzerSettings) => void;
  onRisk: (next: RiskSettings) => void;
  onSound: (next: boolean) => void;
}) {
  return (
    <Card title="Reglages" subtitle="Ils s'appliquent immediatement au moteur">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Select
            label="Unite de temps d'execution"
            value={settings.entryTf}
            options={TIMEFRAMES}
            onChange={(v) => onSettings({ ...settings, entryTf: v as Timeframe })}
          />
          <Select
            label="Unite de temps de contexte"
            value={settings.contextTf}
            options={TIMEFRAMES}
            onChange={(v) => onSettings({ ...settings, contextTf: v as Timeframe })}
          />
        </div>

        <Range
          label="Score minimal pour diffuser un signal"
          value={settings.minScore}
          min={40}
          max={95}
          step={1}
          suffix="/100"
          hint="Plus haut = moins de signaux, mieux filtres"
          onChange={(v) => onSettings({ ...settings, minScore: v })}
        />

        <Range
          label="Spread maximal tolere"
          value={settings.maxSpread}
          min={0.1}
          max={2}
          step={0.05}
          suffix=" $"
          hint="Au-dela, aucun signal n'est diffuse"
          onChange={(v) => onSettings({ ...settings, maxSpread: v })}
        />

        <Range
          label="Volatilite minimale (ATR)"
          value={settings.minAtr}
          min={0.2}
          max={5}
          step={0.1}
          suffix=" $"
          hint="Evite de trader un marche endormi"
          onChange={(v) => onSettings({ ...settings, minAtr: v })}
        />

        <div className="border-t border-[var(--color-border)] pt-4">
          <Range
            label="Capital de reference"
            value={risk.balance}
            min={500}
            max={200_000}
            step={500}
            suffix=" $"
            hint="Sert uniquement au calcul de la taille de position"
            onChange={(v) => onRisk({ ...risk, balance: v })}
          />
          <div className="mt-4">
            <Range
              label="Risque par trade"
              value={risk.riskPercent}
              min={0.1}
              max={3}
              step={0.1}
              suffix=" %"
              hint={`Soit ${((risk.balance * risk.riskPercent) / 100).toFixed(0)} $ par position`}
              onChange={(v) => onRisk({ ...risk, riskPercent: v })}
            />
          </div>
        </div>

        <div className="space-y-2 border-t border-[var(--color-border)] pt-4">
          <Toggle
            label="Autoriser les setups contre-tendance"
            checked={settings.allowCounterTrend}
            onChange={(v) => onSettings({ ...settings, allowCounterTrend: v })}
          />
          <Toggle
            label="Limiter aux seances Londres / New York"
            checked={settings.sessionFilter}
            onChange={(v) => onSettings({ ...settings, sessionFilter: v })}
          />
          <Toggle label="Alerte sonore a chaque signal" checked={soundEnabled} onChange={onSound} />
        </div>
      </div>
    </Card>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="num mt-1 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1.5 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-gold)]"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function Range({
  label,
  value,
  min,
  max,
  step,
  suffix,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  hint?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">{label}</span>
        <span className="num text-xs font-semibold text-[var(--color-gold)]">
          {value.toLocaleString('fr-FR')}
          {suffix}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1.5 w-full accent-[var(--color-gold)]"
      />
      {hint && <span className="text-[10px] text-[var(--color-muted)]">{hint}</span>}
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3">
      <span className="text-[12px] text-[var(--color-text)]/85">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? 'bg-[var(--color-gold)]' : 'bg-[var(--color-surface-2)] border border-[var(--color-border)]'
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-[18px]' : 'translate-x-0.5'
          }`}
        />
      </button>
    </label>
  );
}
