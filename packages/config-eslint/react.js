import { defineConfig } from 'eslint/config';
import eslintConfigPrettier from 'eslint-config-prettier';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

import base from './base.js';
import { REACT_VERSION } from './rules.js';

/**
 * Preset `react` — React sans Next.
 *
 * Cible `packages/ui` (SHARED-01) : une bibliotheque de composants consommee par
 * les trois applications, qui n'a donc pas a heriter des regles propres au
 * routeur ou aux images de Next.
 *
 * Se compose bien a partir de `base`, contrairement au preset `next` : les
 * plugins ajoutes ici viennent tous du meme `node_modules` que ceux de `base`.
 */
export default defineConfig([
  ...base,
  {
    name: '@repo/eslint-config/react',
    files: ['**/*.{js,mjs,cjs,jsx,ts,mts,cts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
    },
    languageOptions: {
      globals: {
        ...globals.browser,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    settings: {
      react: { version: REACT_VERSION },
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
  // Re-applique apres les ajouts ci-dessus, pour rester le dernier maillon.
  eslintConfigPrettier,
]);
