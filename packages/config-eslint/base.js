import js from '@eslint/js';
import { defineConfig } from 'eslint/config';
import eslintConfigPrettier from 'eslint-config-prettier';
import importX from 'eslint-plugin-import-x';
import globals from 'globals';
import tseslint from 'typescript-eslint';

import { sharedRules } from './rules.js';

/**
 * Preset `base` — socle TypeScript, sans rien de specifique a React.
 *
 * Cible `packages/*` et tout code Node du depot (fichiers de configuration,
 * scripts). Les applications Next passent par le preset `next`, `packages/ui`
 * par le preset `react`.
 *
 * Les plugins sont enregistres a la main plutot que via les presets « flat »
 * des paquets concernes : la forme de ces presets change d'une version majeure
 * a l'autre, la cle `plugins` non.
 */
export default defineConfig([
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    name: '@repo/eslint-config/base',
    files: ['**/*.{js,mjs,cjs,jsx,ts,mts,cts,tsx}'],
    plugins: {
      'import-x': importX,
    },
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.node,
      },
    },
    rules: sharedRules,
  },
  // Toujours en DERNIER : eslint-config-prettier ne fait qu'eteindre les regles
  // de mise en forme, pour qu'ESLint et Prettier ne se contredisent jamais.
  // Le deplacer plus haut reactiverait les conflits (critere d'acceptation 4).
  eslintConfigPrettier,
]);
