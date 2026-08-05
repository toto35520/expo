import { NextRequest } from 'next/server';
import { ANALYSIS_SCHEMA } from '@/lib/schema';
import { buildFollowUpPrompt, buildSystemPrompt, buildUserPrompt } from '@/lib/prompt';
import { callProvider, extractJson, PROVIDER_BY_ID, type ProviderId } from '@/lib/providers';
import { assembleAnalysis } from '@/lib/assemble';
import type { AnalysisContext, ChartUpload, RawAnalysis } from '@/lib/types';

export const runtime = 'nodejs';
export const maxDuration = 300;

const ALLOWED_MEDIA = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

type Event =
  | { type: 'status'; message: string }
  | { type: 'result'; data: unknown }
  | { type: 'error'; message: string };

export async function POST(req: NextRequest) {
  let body: {
    provider: ProviderId;
    model: string;
    apiKey?: string;
    context: AnalysisContext;
    charts: ChartUpload[];
    followUp?: Parameters<typeof buildFollowUpPrompt>[0];
  };
  try {
    body = await req.json();
  } catch {
    return json({ error: 'Corps de requête illisible.' }, 400);
  }

  const provider = body.provider;
  if (!provider || !PROVIDER_BY_ID[provider]) {
    return json({ error: 'Fournisseur inconnu.' }, 400);
  }
  if (provider === 'manual') {
    return json({ error: 'Le mode manuel se calcule dans le navigateur, sans appel serveur.' }, 400);
  }

  // La clé vient du navigateur de l'utilisateur. Une variable d'environnement
  // sert uniquement de repli pour qui préfère la poser une fois sur Vercel.
  const apiKey = (body.apiKey || '').trim() || envKey(provider);
  if (!apiKey) {
    return json(
      {
        error: `Aucune clé ${PROVIDER_BY_ID[provider].label}. Ajoute-la dans les réglages de l’app — elle reste dans ton navigateur.`,
      },
      400,
    );
  }

  const charts = body.charts ?? [];
  if (charts.some((c) => !ALLOWED_MEDIA.includes(c.mediaType))) {
    return json({ error: 'Format d’image non supporté. Utilise PNG, JPEG, WebP ou GIF.' }, 400);
  }

  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      let closed = false;
      const send = (e: Event) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(JSON.stringify(e) + '\n'));
        } catch {
          closed = true;
        }
      };

      // Le fournisseur répond en un bloc : on entretient la connexion pour que
      // ni le navigateur ni la plateforme ne coupent pendant l'attente.
      const started = Date.now();
      const beat = setInterval(() => {
        const s = Math.round((Date.now() - started) / 1000);
        send({ type: 'status', message: `Analyse des 14 couches — ${s} s écoulées…` });
      }, 4000);

      try {
        send({ type: 'status', message: 'Préparation des graphiques…' });

        const images = charts.map((c, i) => ({
          mediaType: c.mediaType,
          base64: stripDataUrl(c.dataUrl),
          caption: `Graphique ${i + 1} — ${c.timeframe || 'timeframe non précisé'}`,
        }));

        const userText = body.followUp
          ? `${buildFollowUpPrompt(body.followUp)}\n\n---\n\n${buildUserPrompt(body.context, charts)}`
          : buildUserPrompt(body.context, charts);

        send({ type: 'status', message: 'Envoi au modèle…' });

        const result = await callProvider(provider, {
          model: body.model,
          apiKey,
          system: buildSystemPrompt(provider !== 'gemini'),
          userText,
          images,
          schema: ANALYSIS_SCHEMA as unknown as Record<string, unknown>,
          signal: req.signal,
        });

        clearInterval(beat);
        send({ type: 'status', message: 'Calcul du score et des conditions éliminatoires…' });

        const raw = extractJson(result.text) as RawAnalysis;
        send({ type: 'result', data: assembleAnalysis(raw, body.context) });
      } catch (err) {
        clearInterval(beat);
        send({ type: 'error', message: err instanceof Error ? err.message : 'Erreur inconnue.' });
      } finally {
        clearInterval(beat);
        closed = true;
        try {
          controller.close();
        } catch {
          /* déjà fermé */
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'application/x-ndjson; charset=utf-8',
      'Cache-Control': 'no-store, no-transform',
      'X-Accel-Buffering': 'no',
    },
  });
}

/** Repli optionnel : une clé posée en variable d'environnement Vercel. */
function envKey(provider: ProviderId): string {
  const map: Record<string, string | undefined> = {
    gemini: process.env.GEMINI_API_KEY,
    groq: process.env.GROQ_API_KEY,
    openrouter: process.env.OPENROUTER_API_KEY,
  };
  return (map[provider] ?? '').trim();
}

function stripDataUrl(dataUrl: string): string {
  const i = dataUrl.indexOf(',');
  return i >= 0 ? dataUrl.slice(i + 1) : dataUrl;
}

function json(data: unknown, status: number) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
