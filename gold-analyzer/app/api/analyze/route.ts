import Anthropic from '@anthropic-ai/sdk';
import { NextRequest } from 'next/server';
import { ANALYSIS_SCHEMA } from '@/lib/schema';
import { buildFollowUpPrompt, buildSystemPrompt, buildUserPrompt } from '@/lib/prompt';
import { computeConfidence, computeGates, computeGrade, computeScore, orderModules } from '@/lib/scoring';
import { computeSizing } from '@/lib/sizing';
import type { Analysis, AnalysisContext, ChartUpload, RawAnalysis } from '@/lib/types';

export const runtime = 'nodejs';
// Une analyse vision sur 4-6 graphiques à effort élevé prend couramment 60-150 s.
export const maxDuration = 300;

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-5';
const MAX_TOKENS = 32000;
const ALLOWED_MEDIA = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

type Event =
  | { type: 'status'; message: string }
  | { type: 'progress'; chars: number; thinking: boolean }
  | { type: 'result'; data: Analysis }
  | { type: 'error'; message: string };

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return json(
      { error: 'ANTHROPIC_API_KEY absente. Ajoute-la dans les variables d’environnement Vercel.' },
      500,
    );
  }

  let body: {
    context: AnalysisContext;
    charts: ChartUpload[];
    followUp?: Parameters<typeof buildFollowUpPrompt>[0];
  };
  try {
    body = await req.json();
  } catch {
    return json({ error: 'Corps de requête illisible.' }, 400);
  }

  const charts = (body.charts ?? []).filter((c) => ALLOWED_MEDIA.includes(c.mediaType));
  if (charts.length !== (body.charts ?? []).length) {
    return json({ error: 'Format d’image non supporté. Utilise PNG, JPEG, WebP ou GIF.' }, 400);
  }

  const client = new Anthropic({ apiKey });
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (e: Event) => {
        try {
          controller.enqueue(encoder.encode(JSON.stringify(e) + '\n'));
        } catch {
          /* client parti */
        }
      };

      try {
        send({ type: 'status', message: 'Lecture des graphiques…' });

        const content: Anthropic.ContentBlockParam[] = [];
        for (const c of charts) {
          content.push({
            type: 'text',
            text: `Graphique — ${c.timeframe}`,
          });
          content.push({
            type: 'image',
            source: {
              type: 'base64',
              media_type: c.mediaType as 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif',
              data: stripDataUrl(c.dataUrl),
            },
          });
        }
        content.push({
          type: 'text',
          text: body.followUp
            ? `${buildFollowUpPrompt(body.followUp)}\n\n---\n\n${buildUserPrompt(body.context, charts)}`
            : buildUserPrompt(body.context, charts),
        });

        send({ type: 'status', message: 'Analyse des 14 couches en cours…' });

        let chars = 0;
        let thinking = false;
        const ms = client.messages.stream({
          model: MODEL,
          max_tokens: MAX_TOKENS,
          system: buildSystemPrompt(),
          // Sur Opus 5 le raisonnement est actif par défaut ; `summarized` permet
          // de renvoyer une progression à l'écran plutôt qu'un long silence.
          thinking: { type: 'adaptive', display: 'summarized' },
          output_config: {
            effort: 'high',
            format: { type: 'json_schema', schema: ANALYSIS_SCHEMA },
          },
          messages: [{ role: 'user', content }],
        });

        for await (const ev of ms) {
          if (ev.type === 'content_block_start') {
            thinking = ev.content_block.type === 'thinking';
            if (thinking) send({ type: 'status', message: 'Raisonnement…' });
            else send({ type: 'status', message: 'Rédaction de l’analyse…' });
          } else if (ev.type === 'content_block_delta') {
            const d = ev.delta as { type: string; text?: string; thinking?: string };
            const chunk = d.text ?? d.thinking ?? '';
            if (chunk) {
              chars += chunk.length;
              if (chars % 400 < chunk.length) send({ type: 'progress', chars, thinking });
            }
          }
        }

        const message = await ms.finalMessage();

        if (message.stop_reason === 'refusal') {
          send({
            type: 'error',
            message:
              'La requête a été déclinée par les classifieurs de sécurité. Reformule la demande ou retire les éléments non liés à l’analyse de marché.',
          });
          controller.close();
          return;
        }

        if (message.stop_reason === 'max_tokens') {
          send({
            type: 'error',
            message:
              'Réponse tronquée (limite de tokens atteinte). Réduis le nombre de graphiques ou réessaie.',
          });
          controller.close();
          return;
        }

        const text = message.content
          .filter((b): b is Anthropic.TextBlock => b.type === 'text')
          .map((b) => b.text)
          .join('');

        let raw: RawAnalysis;
        try {
          raw = JSON.parse(text);
        } catch {
          send({ type: 'error', message: 'Réponse du modèle illisible (JSON invalide).' });
          controller.close();
          return;
        }

        send({ type: 'status', message: 'Calcul du score et des conditions éliminatoires…' });
        send({ type: 'result', data: assemble(raw, body.context) });
        controller.close();
      } catch (err) {
        send({ type: 'error', message: describeError(err) });
        controller.close();
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

/**
 * Le modèle ne produit ni score global ni verdict : ils sont calculés ici, à
 * partir de règles fixes. Le modèle juge chaque couche, l'application tranche.
 */
function assemble(raw: RawAnalysis, context: AnalysisContext): Analysis {
  const modules = orderModules(raw.modules ?? []);
  const normalized: RawAnalysis = { ...raw, modules };

  const sizing = computeSizing(raw.tradePlan, context);
  const gates = computeGates(normalized, sizing, context);
  const score = computeScore(modules);
  const confidenceScore = computeConfidence(modules);
  const grade = computeGrade(score, gates, confidenceScore, raw.dataQuality?.completeness ?? 0);

  return {
    ...normalized,
    score,
    confidenceScore,
    gates,
    grade,
    sizing,
    createdAt: new Date().toISOString(),
    id: cryptoId(),
    context,
  };
}

function stripDataUrl(dataUrl: string): string {
  const i = dataUrl.indexOf(',');
  return i >= 0 ? dataUrl.slice(i + 1) : dataUrl;
}

function describeError(err: unknown): string {
  if (err instanceof Anthropic.AuthenticationError) {
    return 'Clé API invalide. Vérifie ANTHROPIC_API_KEY dans les variables Vercel.';
  }
  if (err instanceof Anthropic.RateLimitError) {
    return 'Limite de requêtes atteinte. Réessaie dans un moment.';
  }
  if (err instanceof Anthropic.BadRequestError) {
    return `Requête refusée par l’API : ${err.message}`;
  }
  if (err instanceof Anthropic.APIConnectionError) {
    return 'Connexion à l’API impossible.';
  }
  if (err instanceof Anthropic.APIError) {
    return `Erreur API ${err.status ?? ''} : ${err.message}`;
  }
  return err instanceof Error ? err.message : 'Erreur inconnue.';
}

function cryptoId(): string {
  return `an_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function json(data: unknown, status: number) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
