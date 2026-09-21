'use client';

import { useCallback, useEffect, useState } from 'react';

import { Badge, Card } from './ui';

export interface AccountInfo {
  id: number;
  isLive: boolean;
  login: number;
  broker: string;
}

export interface ConnectionInfo {
  configured: boolean;
  connected: boolean;
  env: 'live' | 'demo' | null;
  accountId: number | null;
  accountLabel: string | null;
  redirectUri: string;
}

/** Panneau de connexion cTrader : OAuth puis choix du compte a analyser. */
export function ConnectionPanel({
  info,
  onAccountSelected,
  onRefresh,
}: {
  info: ConnectionInfo | null;
  onAccountSelected: (accountId: number, label: string) => void;
  onRefresh: () => void;
}) {
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/ctrader/accounts', { cache: 'no-store' });
      const body = (await res.json()) as { accounts?: AccountInfo[]; error?: string };
      if (!res.ok) throw new Error(body.error ?? 'Impossible de lister les comptes.');
      setAccounts(body.accounts ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur inconnue.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (info?.connected) void loadAccounts();
  }, [info?.connected, loadAccounts]);

  const select = async (account: AccountInfo) => {
    const label = `${account.broker} · ${account.login}${account.isLive ? ' (reel)' : ' (demo)'}`;
    setLoading(true);
    try {
      const res = await fetch('/api/ctrader/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accountId: account.id, accountLabel: label }),
      });
      if (!res.ok) throw new Error('Selection du compte refusee.');
      onAccountSelected(account.id, label);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur inconnue.');
    } finally {
      setLoading(false);
    }
  };

  const disconnect = async () => {
    await fetch('/api/ctrader/logout', { method: 'POST' });
    setAccounts([]);
    onRefresh();
  };

  if (!info) {
    return (
      <Card title="Connexion cTrader">
        <p className="text-sm text-[var(--color-muted)]">Verification de la configuration...</p>
      </Card>
    );
  }

  if (!info.configured) {
    return (
      <Card title="Connexion cTrader" action={<Badge tone="baisse">Non configure</Badge>}>
        <p className="text-[13px] leading-relaxed text-[var(--color-text)]/85">
          L&apos;application n&apos;a pas encore ses identifiants cTrader. Ajoutez ces variables
          d&apos;environnement sur Vercel, puis redeployez :
        </p>
        <pre className="num mt-2 overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3 text-[11px] leading-relaxed">
{`CTRADER_CLIENT_ID=...
CTRADER_CLIENT_SECRET=...
CTRADER_REDIRECT_URI=${info.redirectUri}`}
        </pre>
        <p className="mt-2 text-[12px] text-[var(--color-muted)]">
          Les identifiants se creent sur <span className="text-[var(--color-gold)]">openapi.ctrader.com</span>,
          dans votre espace developpeur. L&apos;URI de redirection ci-dessus doit etre declaree
          telle quelle dans la fiche de l&apos;application.
        </p>
      </Card>
    );
  }

  if (!info.connected) {
    return (
      <Card title="Connexion cTrader" action={<Badge tone="alerte">Deconnecte</Badge>}>
        <p className="mb-3 text-[13px] leading-relaxed text-[var(--color-text)]/85">
          Connectez votre compte pour que l&apos;analyseur recoive le flux de l&apos;or de votre
          broker. L&apos;autorisation se fait chez cTrader — vos identifiants ne transitent jamais
          par cette application.
        </p>
        <div className="flex flex-wrap gap-2">
          <a
            href="/api/ctrader/login?env=live"
            className="rounded-lg bg-[var(--color-gold)] px-4 py-2 text-sm font-semibold text-[#0a0d14] transition hover:brightness-110"
          >
            Connecter mon compte reel
          </a>
          <a
            href="/api/ctrader/login?env=demo"
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-semibold text-[var(--color-text)] transition hover:border-[var(--color-gold)]"
          >
            Compte demo
          </a>
        </div>
        <p className="mt-3 text-[11px] text-[var(--color-muted)]">
          L&apos;analyseur est en lecture seule : il lit les cours et n&apos;envoie jamais
          d&apos;ordre sur votre compte.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Connexion cTrader"
      subtitle={info.env === 'live' ? 'Environnement reel' : 'Environnement demo'}
      action={<Badge tone="hausse">Connecte</Badge>}
    >
      {error && (
        <p className="mb-3 rounded-lg border border-[rgba(240,85,108,0.35)] bg-[rgba(240,85,108,0.1)] p-2 text-[12px] text-[var(--color-bear)]">
          {error}
        </p>
      )}

      {info.accountId && (
        <div className="mb-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-2.5">
          <p className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">Compte analyse</p>
          <p className="num mt-0.5 text-[13px] font-semibold">{info.accountLabel ?? info.accountId}</p>
        </div>
      )}

      <div className="space-y-1.5">
        {loading && <p className="text-[12px] text-[var(--color-muted)]">Chargement des comptes...</p>}
        {!loading && accounts.length === 0 && !error && (
          <p className="text-[12px] text-[var(--color-muted)]">Aucun compte trouve pour ce token.</p>
        )}
        {accounts.map((account) => {
          const selected = info.accountId === account.id;
          return (
            <button
              key={account.id}
              type="button"
              onClick={() => void select(account)}
              className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition ${
                selected
                  ? 'border-[var(--color-gold)] bg-[rgba(240,180,41,0.08)]'
                  : 'border-[var(--color-border)] hover:border-[var(--color-muted)]'
              }`}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-semibold">{account.broker}</p>
                <p className="num text-[11px] text-[var(--color-muted)]">Compte {account.login}</p>
              </div>
              <Badge tone={account.isLive ? 'or' : 'neutre'}>{account.isLive ? 'Reel' : 'Demo'}</Badge>
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => void loadAccounts()}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-[12px] transition hover:border-[var(--color-gold)]"
        >
          Rafraichir
        </button>
        <button
          type="button"
          onClick={() => void disconnect()}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-[12px] text-[var(--color-bear)] transition hover:border-[var(--color-bear)]"
        >
          Deconnecter
        </button>
      </div>
    </Card>
  );
}
