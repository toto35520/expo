/**
 * Hook de resolution ESM pour les tests.
 *
 * Le code source utilise des imports sans extension (resolution "bundler",
 * comme attendu par Next.js). Node, lui, exige un specificateur complet : ce
 * hook reessaie avec `.ts` puis `/index.ts` avant d'abandonner.
 */
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (!specifier.startsWith('.') || /\.(ts|tsx|js|mjs|json)$/.test(specifier)) {
      throw error;
    }
    for (const suffix of ['.ts', '/index.ts', '.tsx']) {
      try {
        return await nextResolve(specifier + suffix, context);
      } catch {
        // on essaie le suffixe suivant
      }
    }
    throw error;
  }
}
