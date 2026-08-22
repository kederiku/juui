import base from '@repo/eslint-config/base';
import { defineConfig, globalIgnores } from 'eslint/config';

/**
 * Configuration ESLint de la racine du monorepo (SETUP-03).
 *
 * Depuis ESLint 10, la recherche de configuration part du repertoire du FICHIER
 * analyse et remonte l'arborescence (l'ancien drapeau
 * `v10_config_lookup_from_file`, devenu le comportement par defaut). Un seul
 * `eslint .` lance ici applique donc a chaque workspace son propre
 * `eslint.config.mjs` s'il en a un, et retombe sur ce fichier sinon — c'est ce
 * qui permet au script racine `pnpm lint` de couvrir tout le depot en une passe.
 *
 * Ce fichier n'utilise que le preset `base` : il ne couvre que les fichiers de
 * la racine et les workspaces qui n'ont pas encore de configuration propre. Les
 * applications Next declareront leur `eslint.config.mjs` sur le preset `next`
 * (FRONT-01), `packages/ui` sur le preset `react` (SHARED-01).
 */
export default defineConfig([
  // Les motifs sont resolus relativement a CE fichier. Les configurations des
  // workspaces portent leurs propres exclusions : celles-ci ne descendent pas.
  globalIgnores([
    '**/node_modules/**',
    '**/dist/**',
    '**/.next/**',
    '**/out/**',
    '**/coverage/**',
    '**/*.tsbuildinfo',

    // Sortie generee par Orval (SHARED-03), jamais editee a la main.
    '**/generated/**',

    // Docusaurus : cache de build et site genere (DOC-01).
    'documentation/.docusaurus/**',
    'documentation/build/**',

    // Projet Python, outille par uv et Ruff — hors du perimetre d'ESLint. Sans
    // cette ligne, le lint descendrait dans backend/api/.venv/, ou les paquets
    // Python embarquent quantite de JavaScript tiers.
    'backend/**',
  ]),

  ...base,
]);
