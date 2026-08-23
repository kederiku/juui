import path from 'node:path';
import { fileURLToPath } from 'node:url';

import js from '@eslint/js';
import { defineConfig } from 'eslint/config';
import eslintConfigPrettier from 'eslint-config-prettier';
import { createTypeScriptImportResolver } from 'eslint-import-resolver-typescript';
import importX from 'eslint-plugin-import-x';
import globals from 'globals';
import tseslint from 'typescript-eslint';

import { sharedRules } from './rules.js';

/*
 * Racine du monorepo, deduite de l'emplacement de CE fichier.
 *
 * Les motifs passes au resolveur TypeScript ci-dessous sont sinon resolus depuis
 * le repertoire de travail : `pnpm lint` part de la racine, mais un lint lance
 * depuis un workspace -- ou par un editeur -- ne trouverait plus aucun tsconfig,
 * et les imports aliases redeviendraient silencieusement irresolvables.
 *
 * Les deux motifs suivent `pnpm-workspace.yaml`. Un workspace sans tsconfig
 * (les packages de configuration) n'est simplement pas apparie.
 */
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));
const workspaceTsconfigs = [
  path.join(repoRoot, 'frontend/*/tsconfig.json'),
  path.join(repoRoot, 'packages/*/tsconfig.json'),
];

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
    settings: {
      /*
       * Resolveur d'imports (FRONT-01). C'est lui qui donne leur objet aux
       * regles `import-x/no-unresolved` et `import-x/no-cycle` de rules.js :
       * sans resolveur, elles ne signalent jamais rien.
       *
       * Il faut la variante TypeScript, et non le resolveur node : elle seule
       * lit les `paths` des tsconfig -- les alias `@/*` et `@repo/ui/*` des
       * applications -- et la carte `exports` des packages du depot, par
       * laquelle passe chaque import de `@repo/ui`.
       *
       * `import-x/resolver-next` et non `import-x/resolver` : la cle historique
       * attend un nom de module a charger, la nouvelle un resolveur deja
       * construit. Sous le node_modules strict de pnpm, la forme par nom serait
       * resolue depuis le repertoire de travail et casserait des qu'ESLint
       * serait lance ailleurs qu'a la racine.
       *
       * `alwaysTryTypes` etend la recherche aux paquets `@types/*` pour les
       * dependances qui n'embarquent pas leurs declarations.
       */
      'import-x/resolver-next': [
        createTypeScriptImportResolver({
          alwaysTryTypes: true,
          project: workspaceTsconfigs,
          // Le resolveur avertit des qu'on lui designe plusieurs projets. C'est
          // ici la situation normale et voulue : un monorepo a un tsconfig par
          // workspace, et il faut les lui donner tous.
          noWarnOnMultipleProjects: true,
        }),
      ],
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
