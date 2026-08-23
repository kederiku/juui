import react from '@repo/eslint-config/react';
import { defineConfig, globalIgnores } from 'eslint/config';

/**
 * Configuration ESLint de `@repo/ui` (SHARED-01).
 *
 * Preset `react` : le socle TypeScript de `base` plus les regles des hooks,
 * sans les regles propres a Next -- cette bibliotheque est du React nu, elle
 * n'a ni routeur ni `next/image`. C'est exactement la cible que decrivait
 * packages/config-eslint/react.js.
 *
 * Depuis ESLint 10, la recherche de configuration part du repertoire du fichier
 * analyse : le `pnpm lint` de la racine trouve donc ce fichier tout seul pour
 * les fichiers de ce workspace, et n'applique plus celui de la racine.
 */
export default defineConfig([globalIgnores(['dist/**']), ...react]);
