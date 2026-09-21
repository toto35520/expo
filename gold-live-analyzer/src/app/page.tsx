'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { BiasTable } from '@/components/BiasTable';
import { Chart } from '@/components/Chart';
import { ConnectionPanel, type ConnectionInfo } from '@/components/ConnectionPanel';
import { LevelsPanel } from '@/components/LevelsPanel';
import { NarrativePanel } from '@/components/NarrativePanel';
import { SettingsPanel } from '@/components/SettingsPanel';
import { SignalFeed } from '@/components/SignalFeed';
import { StrategyPanel } from '@/components/StrategyPanel';
import { Card } from '@/components/ui';
import { useGoldEngine } from '@/hooks/useGoldEngine';
import { useLocalState } from '@/hooks/useLocalState';
import { type AnalyzerSettings, DEFAULT_SETTINGS } from '@/lib/engine/analyzer';
import { DEFAULT_RISK, type RiskSettings } from '@/lib/engine/risk';
import type { Signal } from '@/lib/engine/signals';
import { PriceHeader } from '@/components/PriceHeader';

export default function Page() {
  const [info, setInfo] = useState<ConnectionInfo | null>(null);
  const [settings, setSettings] = useLocalState<AnalyzerSettings>('gla.settings', DEFAULT_SETTINGS);
  const [risk, setRisk] = useLocalState<RiskSettings>('gla.risk', DEFAULT_RISK);
  const [sound, setSound] = useLocalState<{ enabled: boolean }>('gla.sound', { enabled: true });
  const [banner, setBanner] = useState<string | null>(null);

  const soundRef = useRef(sound.enabled);
  soundRef.current = sound.enabled;

  const loadConfig = useCallback(async () => {
    try {
      const res = await fetch('/api/config', { cache: 'no-store' });
      const body = (await res.json()) as ConnectionInfo;
      setInfo(body);
    } catch {
      setInfo({
        configured: false,
        connected: false,
        env: null,
        accountId: null,
        accountLabel: null,
        redirectUri: '',
      });
    }
  }, []);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  // Messages renvoyes par le retour OAuth.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const erreur = params.get('erreur');
    const connecte = params.get('connecte');
    if (erreur) setBanner(erreur);
    else if (connecte) setBanner('Compte cTrader connecte. Selectionnez le compte a analyser.');
    if (erreur || connecte) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  const onSignal = useCallback((signal: Signal) => {
    if (soundRef.current) playAlert(signal.direction);
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      new Notification(`Signal ${signal.direction === 'BUY' ? 'ACHAT' : 'VENTE'} — or`, {
        body: `${signal.strategyName}\nEntree ${signal.entry.toFixed(2)} · Stop ${signal.stopLoss.toFixed(2)}`,
      });
    }
  }, []);

  const engine = useGoldEngine({
    accountId: info?.accountId ?? null,
    symbolId: null,
    settings,
    risk,
    enabled: info !== null,
    onSignal,
  });

  const entryAnalysis = engine.read?.tf[settings.entryTf] ?? null;
  const openSignal = useMemo(
    () => engine.signals.find((s) => s.closedAt === null) ?? null,
    [engine.signals]
  );

  const handleAccountSelected = (accountId: number, label: string) => {
    engine.reset();
    setInfo((prev) => (prev ? { ...prev, accountId, accountLabel: label } : prev));
  };

  return (
    <main className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight">
            Analyseur Or <span className="text-[var(--color-gold)]">Live</span>
          </h1>
          <p className="text-xs text-[var(--color-muted)]">
            Lecture de marche en continu sur XAU/USD et detection de setups acheteurs / vendeurs
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
              void Notification.requestPermission();
            }
          }}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs transition hover:border-[var(--color-gold)]"
        >
          Activer les notifications
        </button>
      </div>

      {banner && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3 text-[13px]">
          <span>{banner}</span>
          <button type="button" onClick={() => setBanner(null)} className="text-[var(--color-muted)]">
            ✕
          </button>
        </div>
      )}

      {engine.error && (
        <div className="mb-4 rounded-lg border border-[rgba(245,165,36,0.35)] bg-[rgba(245,165,36,0.08)] p-3 text-[13px] text-[var(--color-warn)]">
          {engine.error}
        </div>
      )}

      <div className="space-y-4">
        <PriceHeader state={engine} />

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.15fr_1fr_0.85fr]">
          <div className="space-y-4">
            <Card
              title={`Graphique ${settings.entryTf}`}
              subtitle={
                engine.read
                  ? `${engine.read.session.label} · ${engine.read.tf[settings.entryTf].candles.length} bougies`
                  : undefined
              }
            >
              <Chart
                candles={entryAnalysis?.candles ?? []}
                ema20={entryAnalysis?.ema20Series ?? []}
                ema50={entryAnalysis?.ema50Series ?? []}
                ema200={entryAnalysis?.ema200Series ?? []}
                levels={engine.read?.levels.all ?? []}
                signal={openSignal}
                label={`XAU/USD · ${settings.entryTf}`}
              />
            </Card>

            <NarrativePanel narrative={engine.narrative} />
          </div>

          <div className="space-y-4">
            <SignalFeed signals={engine.signals} stats={engine.stats} />
            <StrategyPanel strategies={engine.read?.strategies ?? []} />
          </div>

          <div className="space-y-4">
            <ConnectionPanel
              info={info}
              onAccountSelected={handleAccountSelected}
              onRefresh={() => void loadConfig()}
            />
            <BiasTable read={engine.read} />
            <LevelsPanel levels={engine.read?.levels ?? null} price={engine.quote?.mid ?? null} />
            <SettingsPanel
              settings={settings}
              risk={risk}
              soundEnabled={sound.enabled}
              onSettings={setSettings}
              onRisk={setRisk}
              onSound={(enabled) => setSound({ enabled })}
            />
          </div>
        </div>

        <footer className="pb-6 pt-2 text-[11px] leading-relaxed text-[var(--color-muted)]">
          Outil d&apos;analyse technique a usage personnel. Les signaux affiches sont le resultat de
          regles automatiques appliquees aux cours : ce ne sont pas des conseils en investissement,
          et rien ne garantit leur resultat. L&apos;analyseur ne passe aucun ordre — chaque decision
          de trading reste la votre.
        </footer>
      </div>
    </main>
  );
}

/** Bip genere a la volee : pas de fichier audio a charger. */
function playAlert(direction: 'BUY' | 'SELL') {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = direction === 'BUY' ? 880 : 520;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.45);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.5);
    osc.onended = () => void ctx.close();
  } catch {
    // audio indisponible : l'alerte visuelle suffit
  }
}
