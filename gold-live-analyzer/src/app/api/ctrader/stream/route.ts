import {
  ensureFreshSession,
  readAppConfig,
  readSession,
} from '@/lib/ctrader/oauth';
import {
  decodeTrendbar,
  num,
  RELATIVE_PRICE_SCALE,
  TrendbarPeriod,
} from '@/lib/ctrader/protocol';
import { CTraderSession } from '@/lib/ctrader/session';
import type { Timeframe } from '@/lib/market/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
/**
 * Duree de vie d'une connexion. Vercel plafonne l'execution d'une fonction :
 * on coupe proprement avant la limite et le navigateur se reconnecte tout
 * seul (EventSource le fait nativement). Sur le plan Hobby la coupure peut
 * arriver plus tot — c'est transparent, l'etat du moteur vit dans la page.
 */
export const maxDuration = 300;

const STREAM_LIFETIME_MS = 240_000;

/** Periodes dont on veut les bougies faisant autorite. */
const LIVE_BARS: Timeframe[] = ['M1', 'M5', 'M15'];

const PERIOD_TO_TF = new Map<number, Timeframe>([
  [TrendbarPeriod.M1, 'M1'],
  [TrendbarPeriod.M5, 'M5'],
  [TrendbarPeriod.M15, 'M15'],
  [TrendbarPeriod.H1, 'H1'],
  [TrendbarPeriod.H4, 'H4'],
]);

export async function GET(request: Request) {
  const config = readAppConfig();
  const stored = await readSession();

  if (!config) {
    return sseError('Application non configuree (identifiants cTrader absents).', 500);
  }
  if (!stored) {
    return sseError('Non connecte a cTrader.', 401);
  }

  const url = new URL(request.url);
  const accountId = Number(url.searchParams.get('accountId') ?? stored.accountId ?? 0);
  const symbolIdParam = Number(url.searchParams.get('symbolId') ?? 0);
  if (!accountId) return sseError('Aucun compte selectionne.', 400);

  let session = stored;
  try {
    session = (await ensureFreshSession(stored, config)).session;
  } catch (err) {
    return sseError(
      `Token cTrader invalide : ${err instanceof Error ? err.message : 'erreur'}`,
      401
    );
  }

  const encoder = new TextEncoder();
  const client = new CTraderSession({
    env: session.env,
    clientId: config.clientId,
    clientSecret: config.clientSecret,
    accessToken: session.accessToken,
  });

  let closed = false;
  let lifetimeTimer: ReturnType<typeof setTimeout> | null = null;
  let keepAliveTimer: ReturnType<typeof setInterval> | null = null;

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (event: string, data: unknown) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        } catch {
          closed = true;
        }
      };

      const finish = (reason: string, event = 'reconnect') => {
        if (closed) return;
        send(event, { reason });
        closed = true;
        if (lifetimeTimer) clearTimeout(lifetimeTimer);
        if (keepAliveTimer) clearInterval(keepAliveTimer);
        client.close();
        try {
          controller.close();
        } catch {
          // deja fermee
        }
      };

      // Demande au navigateur de se reconnecter vite apres une coupure.
      controller.enqueue(encoder.encode('retry: 2000\n\n'));

      try {
        await client.connect();
        await client.authorizeAccount(accountId);

        let symbolId = symbolIdParam;
        let symbolName = session.symbolName ?? 'XAUUSD';

        if (!symbolId) {
          const symbols = await client.listSymbols(accountId);
          const gold = CTraderSession.pickGoldSymbol(symbols, process.env.GOLD_SYMBOL);
          if (!gold) {
            finish("Aucun symbole or (XAU/USD) disponible sur ce compte.", 'fatal');
            return;
          }
          symbolId = num(gold.symbolId);
          symbolName = gold.symbolName ?? symbolName;
        }

        client.onSpot = (spot) => {
          if (num(spot.symbolId) !== symbolId) return;
          const ts = num(spot.timestamp) || Date.now();

          const bid = spot.bid !== undefined ? num(spot.bid) / RELATIVE_PRICE_SCALE : null;
          const ask = spot.ask !== undefined ? num(spot.ask) / RELATIVE_PRICE_SCALE : null;
          if (bid !== null || ask !== null) {
            send('tick', { bid, ask, ts });
          }

          for (const bar of spot.trendbar ?? []) {
            const tf = PERIOD_TO_TF.get(bar.period ?? 0);
            if (!tf) continue;
            send('bar', { tf, candle: decodeTrendbar(bar) });
          }
        };

        client.onClose = (reason) => finish(`Session cTrader fermee : ${reason}`);

        await client.subscribeSpots(accountId, symbolId);
        for (const tf of LIVE_BARS) {
          try {
            await client.subscribeLiveTrendbar(accountId, symbolId, tf);
          } catch {
            // Certains brokers limitent le nombre d'abonnements : les ticks
            // suffisent a reconstruire ce timeframe.
          }
        }

        send('hello', {
          symbolId,
          symbolName,
          accountId,
          env: session.env,
          lifetimeMs: STREAM_LIFETIME_MS,
        });

        // Commentaire SSE periodique : empeche les proxies de couper la socket.
        keepAliveTimer = setInterval(() => {
          if (closed) return;
          try {
            controller.enqueue(encoder.encode(`: ping ${Date.now()}\n\n`));
          } catch {
            closed = true;
          }
        }, 15_000);

        lifetimeTimer = setTimeout(
          () => finish('Rotation planifiee de la connexion.'),
          STREAM_LIFETIME_MS
        );
      } catch (err) {
        finish(err instanceof Error ? err.message : 'Echec de connexion a cTrader.', 'fatal');
      }

      request.signal.addEventListener('abort', () => finish('Client deconnecte.', 'bye'));
    },

    cancel() {
      closed = true;
      if (lifetimeTimer) clearTimeout(lifetimeTimer);
      if (keepAliveTimer) clearInterval(keepAliveTimer);
      client.close();
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}

function sseError(message: string, status: number): Response {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
