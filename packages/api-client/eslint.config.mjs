import react from '@repo/eslint-config/react';
import { defineConfig, globalIgnores } from 'eslint/config';

/**
 * Configuration ESLint de `@repo/api-client` (SHARED-03).
 *
 * LE `globalIgnores` CI-DESSOUS N'EST PAS UNE REDITE DE CELUI DE LA RACINE.
 * Depuis ESLint 10, la recherche de configuration part du repertoire du FICHIER
 * analyse : ce fichier REMPLACE celui de la racine pour ce workspace, ses
 * exclusions comprises -- le `**\/generated\/**` de la racine ne descend pas
 * jusqu'ici. Sans cette ligne, `pnpm lint` analyserait la sortie d'Orval, que la
 * prochaine generation reecrira de toute facon. Meme geste que le `dist/**` de
 * packages/ui et le `.next/**` des trois applications.
 *
 * Preset `react` et non `base` : la surface publique de ce package EST un jeu de
 * hooks React, et FRONT-04 (query-provider.tsx) puis FRONT-07 (src/auth/) y
 * ajouteront des composants clients. `rules-of-hooks` et `exhaustive-deps` sont
 * les regles qui comptent pour ce code-la. Le preset apporte aussi les globales
 * du navigateur, dont `window`, que le socle `base` -- oriente Node -- ne
 * declare pas.
 */
export default defineConfig([globalIgnores(['src/generated/**', '.verify/**']), ...react]);
