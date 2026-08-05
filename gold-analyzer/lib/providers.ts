/**
 * Fournisseurs de modèles à palier gratuit.
 *
 * Aucune clé n'est stockée sur le serveur : elle vient du navigateur de
 * l'utilisateur à chaque requête, la route ne fait que relayer. Conséquence,
 * l'hébergement Vercel reste sur l'offre gratuite et chaque utilisateur
 * apporte sa propre clé gratuite.
 */

export type ProviderId = 'gemini' | 'groq' | 'openrouter' | 'manual';

export interface ProviderDef {
  id: ProviderId;
  label: string;
  /** Ce qu'il faut savoir avant de choisir. */
  summary: string;
  /** Où créer une clé gratuite. */
  keyUrl: string;
  keyHint: string;
  /** Modèles vision utilisables sur le palier gratuit. */
  models: Array<{ id: string; label: string; note?: string }>;
  /** Avertissements honnêtes — affichés tels quels dans l'interface. */
  caveats: string[];
}

export const PROVIDERS: ProviderDef[] = [
  {
    id: 'gemini',
    label: 'Google Gemini',
    summary:
      'Le meilleur rapport qualité/prix des options gratuites pour lire des graphiques. Palier gratuit sans carte bancaire, schéma JSON natif.',
    keyUrl: 'https://aistudio.google.com/apikey',
    keyHint: 'Commence par AIza…',
    models: [
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', note: 'recommandé — meilleure lecture des graphiques' },
      { id: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash Lite', note: 'plus rapide, quotas plus larges' },
      { id: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash', note: 'repli si les quotas 2.5 sont atteints' },
    ],
    caveats: [
      'Le palier gratuit est limité en requêtes par minute et par jour. En cas de dépassement, l’app affiche l’erreur et il suffit d’attendre.',
      'Google indique pouvoir utiliser les contenus envoyés via le palier gratuit pour améliorer ses produits. N’envoie rien que tu ne veuilles pas partager.',
    ],
  },
  {
    id: 'groq',
    label: 'Groq',
    summary: 'Très rapide, palier gratuit. Modèles vision Llama — lecture de graphiques plus grossière que Gemini.',
    keyUrl: 'https://console.groq.com/keys',
    keyHint: 'Commence par gsk_…',
    models: [
      { id: 'meta-llama/llama-4-maverick-17b-128e-instruct', label: 'Llama 4 Maverick', note: 'le plus capable des deux' },
      { id: 'meta-llama/llama-4-scout-17b-16e-instruct', label: 'Llama 4 Scout', note: 'plus rapide' },
    ],
    caveats: [
      'Lecture des chandeliers nettement moins fiable que Gemini : attends-toi à plus de couches UNKNOWN, ce qui est le comportement souhaité.',
      'Limite de taille par image plus stricte — réduis le nombre de graphiques si la requête est rejetée.',
    ],
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    summary:
      'Passerelle vers de nombreux modèles, dont des variantes gratuites. Pratique comme roue de secours quand un autre quota est épuisé.',
    keyUrl: 'https://openrouter.ai/keys',
    keyHint: 'Commence par sk-or-…',
    models: [
      { id: 'google/gemini-2.0-flash-exp:free', label: 'Gemini 2.0 Flash (gratuit)' },
      { id: 'meta-llama/llama-4-maverick:free', label: 'Llama 4 Maverick (gratuit)' },
      { id: 'qwen/qwen2.5-vl-72b-instruct:free', label: 'Qwen2.5 VL 72B (gratuit)' },
    ],
    caveats: [
      'Les modèles suffixés « :free » sont fortement limités et parfois indisponibles. Si un modèle ne répond pas, essaie le suivant.',
      'La disponibilité de ces variantes change souvent — ce n’est pas une source stable.',
    ],
  },
  {
    id: 'manual',
    label: 'Manuel — aucune API',
    summary:
      'Tu notes toi-même les 14 couches, l’app applique les conditions éliminatoires, le score et le dimensionnement. Gratuit pour toujours, sans compte, sans quota, fonctionne hors ligne.',
    keyUrl: '',
    keyHint: '',
    models: [],
    caveats: [
      'C’est toi l’analyste : la qualité du verdict vaut celle de ton honnêteté en remplissant les couches.',
      'C’est aussi le mode qui fait le plus progresser — il force à passer chaque couche au lieu de la survoler.',
    ],
  },
];

export const PROVIDER_BY_ID = Object.fromEntries(PROVIDERS.map((p) => [p.id, p])) as Record<
  ProviderId,
  ProviderDef
>;

export interface ProviderSettings {
  provider: ProviderId;
  model: string;
  apiKey: string;
}

export const DEFAULT_PROVIDER: ProviderSettings = {
  provider: 'gemini',
  model: 'gemini-2.5-flash',
  apiKey: '',
};

// ---------------------------------------------------------------------------
// Appels
// ---------------------------------------------------------------------------

export interface CallInput {
  model: string;
  apiKey: string;
  system: string;
  userText: string;
  images: Array<{ mediaType: string; base64: string; caption: string }>;
  /** Schéma JSON de la réponse attendue. */
  schema: Record<string, unknown>;
  signal?: AbortSignal;
}

export interface CallResult {
  text: string;
  /** Renseigné quand le fournisseur le communique. */
  usage?: { input?: number; output?: number };
}

export async function callProvider(id: ProviderId, input: CallInput): Promise<CallResult> {
  switch (id) {
    case 'gemini':
      return callGemini(input);
    case 'groq':
      return callOpenAICompatible('https://api.groq.com/openai/v1', input);
    case 'openrouter':
      return callOpenAICompatible('https://openrouter.ai/api/v1', input, {
        'HTTP-Referer': 'https://github.com/gold-desk',
        'X-Title': 'Gold Desk',
      });
    case 'manual':
      throw new Error('Le mode manuel ne passe par aucune API.');
  }
}

// --- Google Gemini ---------------------------------------------------------

async function callGemini(input: CallInput): Promise<CallResult> {
  const parts: unknown[] = [];
  for (const img of input.images) {
    parts.push({ text: img.caption });
    parts.push({ inline_data: { mime_type: img.mediaType, data: img.base64 } });
  }
  parts.push({ text: input.userText });

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(
    input.model,
  )}:generateContent`;

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-goog-api-key': input.apiKey },
    signal: input.signal,
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: input.system }] },
      contents: [{ role: 'user', parts }],
      generationConfig: {
        responseMimeType: 'application/json',
        responseSchema: toGeminiSchema(input.schema),
        maxOutputTokens: 30000,
      },
    }),
  });

  if (!res.ok) throw new Error(await providerError(res, 'Gemini'));

  const data = (await res.json()) as {
    candidates?: Array<{
      content?: { parts?: Array<{ text?: string }> };
      finishReason?: string;
    }>;
    promptFeedback?: { blockReason?: string };
    usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number };
  };

  if (data.promptFeedback?.blockReason) {
    throw new Error(`Requête bloquée par Gemini (${data.promptFeedback.blockReason}).`);
  }

  const cand = data.candidates?.[0];
  if (cand?.finishReason === 'MAX_TOKENS') {
    throw new Error(
      'Réponse tronquée : le modèle a atteint sa limite de sortie. Réduis le nombre de graphiques.',
    );
  }

  const text = (cand?.content?.parts ?? []).map((p) => p.text ?? '').join('');
  if (!text) throw new Error('Gemini a renvoyé une réponse vide.');

  return {
    text,
    usage: {
      input: data.usageMetadata?.promptTokenCount,
      output: data.usageMetadata?.candidatesTokenCount,
    },
  };
}

/**
 * Gemini attend un sous-ensemble d'OpenAPI, pas du JSON Schema complet :
 * `additionalProperties` et `$schema` provoquent une erreur 400.
 */
function toGeminiSchema(schema: unknown): unknown {
  if (Array.isArray(schema)) return schema.map(toGeminiSchema);
  if (schema && typeof schema === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(schema as Record<string, unknown>)) {
      if (k === 'additionalProperties' || k === '$schema') continue;
      out[k] = toGeminiSchema(v);
    }
    // Conserve l'ordre des champs pour éviter que le modèle réordonne la sortie.
    if (out.type === 'object' && out.properties && !out.propertyOrdering) {
      out.propertyOrdering = Object.keys(out.properties as Record<string, unknown>);
    }
    return out;
  }
  return schema;
}

// --- OpenAI-compatible (Groq, OpenRouter) ----------------------------------

async function callOpenAICompatible(
  base: string,
  input: CallInput,
  extraHeaders: Record<string, string> = {},
): Promise<CallResult> {
  const content: unknown[] = [];
  for (const img of input.images) {
    content.push({ type: 'text', text: img.caption });
    content.push({
      type: 'image_url',
      image_url: { url: `data:${img.mediaType};base64,${img.base64}` },
    });
  }
  content.push({ type: 'text', text: input.userText });

  const res = await fetch(`${base}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${input.apiKey}`,
      ...extraHeaders,
    },
    signal: input.signal,
    body: JSON.stringify({
      model: input.model,
      max_tokens: 16000,
      // Beaucoup de modèles gratuits ne gèrent pas `json_schema` strict ; le mode
      // `json_object` est accepté largement, et le schéma est rappelé en toutes
      // lettres dans le prompt.
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: input.system },
        { role: 'user', content },
      ],
    }),
  });

  if (!res.ok) throw new Error(await providerError(res, base.includes('groq') ? 'Groq' : 'OpenRouter'));

  const data = (await res.json()) as {
    choices?: Array<{ message?: { content?: string }; finish_reason?: string }>;
    error?: { message?: string };
    usage?: { prompt_tokens?: number; completion_tokens?: number };
  };

  if (data.error?.message) throw new Error(data.error.message);

  const choice = data.choices?.[0];
  if (choice?.finish_reason === 'length') {
    throw new Error('Réponse tronquée : limite de sortie atteinte. Réduis le nombre de graphiques.');
  }

  const text = choice?.message?.content ?? '';
  if (!text) throw new Error('Le modèle a renvoyé une réponse vide.');

  return {
    text,
    usage: { input: data.usage?.prompt_tokens, output: data.usage?.completion_tokens },
  };
}

// --- Erreurs ---------------------------------------------------------------

async function providerError(res: Response, name: string): Promise<string> {
  let detail = '';
  try {
    const body = (await res.json()) as { error?: { message?: string } | string };
    detail =
      typeof body.error === 'string' ? body.error : (body.error?.message ?? '');
  } catch {
    detail = await res.text().catch(() => '');
  }
  detail = detail.slice(0, 300);

  // Google renvoie 400 (et non 401) pour une clé invalide.
  if (/api key not valid|invalid api key|api_key_invalid/i.test(detail)) {
    return `Clé ${name} invalide. Vérifie-la dans les réglages de l’app.`;
  }

  switch (res.status) {
    case 400:
      return `${name} a refusé la requête. ${detail}`;
    case 401:
    case 403:
      return `Clé ${name} invalide ou sans accès à ce modèle. Vérifie-la dans les réglages.`;
    case 404:
      return `Modèle introuvable chez ${name}. Choisis-en un autre dans la liste.`;
    case 413:
      return `Requête trop lourde pour ${name}. Retire un graphique.`;
    case 429:
      return `Quota gratuit ${name} atteint. Attends quelques minutes, ou bascule sur un autre fournisseur.`;
    case 503:
      return `${name} est momentanément surchargé. Réessaie dans un instant.`;
    default:
      return `Erreur ${name} ${res.status}. ${detail}`;
  }
}

/**
 * Extrait le JSON d'une réponse : les modèles gratuits l'encadrent souvent de
 * blocs Markdown ou de texte d'introduction.
 */
export function extractJson(text: string): unknown {
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '');
  try {
    return JSON.parse(cleaned);
  } catch {
    /* on tente l'extraction par accolades */
  }
  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  if (start >= 0 && end > start) {
    return JSON.parse(cleaned.slice(start, end + 1));
  }
  throw new Error('Réponse illisible : le modèle n’a pas produit de JSON valide.');
}
