import fs from 'node:fs';
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
 * Racine du monorepo, deduite de l'emplacement de CE fichier -- et non du
 * repertoire de travail, qui vaut ce que vaut l'endroit d'ou l'on lance ESLint.
 */
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));

/*
 * Les tsconfig des workspaces, donnes au resolveur TypeScript ci-dessous.
 *
 * Les deux motifs suivent `pnpm-workspace.yaml`. Un workspace sans tsconfig
 * (les packages de configuration) n'est simplement pas apparie.
 *
 * ILS SONT DEVELOPPES ICI, et c'est tout l'objet de ces lignes. Les confier au
 * resolveur -- ce que faisait la version precedente en lui passant des motifs
 * absolus -- le laisse les developper avec tinyglobby depuis le REPERTOIRE DE
 * TRAVAIL. Or tinyglobby, ainsi appele, ecarte le tsconfig du repertoire ou l'on
 * se trouve : depuis frontend/frontend-admin, le resolveur recevait les trois
 * autres tsconfig du depot et pas le sien. Ses alias `@/*` devenaient alors
 * irresolvables -- les `paths` d'un tsconfig ne valant que pour les fichiers
 * qu'il inclut, aucun des trois restants ne pouvait repondre pour lui.
 *
 * La panne etait invisible depuis la racine, qui n'est le repertoire d'aucun
 * workspace : `pnpm lint` passait, `cd frontend/frontend-admin && eslint .`
 * sortait sur dix imports introuvables. Un editeur qui lance ESLint depuis le
 * dossier du fichier ouvert tombait dans le meme trou.
 *
 * `fs.globSync` prend un `cwd` explicite, ancre ici sur la racine du depot : la
 * liste ne depend plus de l'endroit d'ou le lint est lance. Et parce que le
 * resolveur ne recoit plus que des chemins de fichiers -- aucun motif dynamique
 * -- il ne redeveloppe rien du tout.
 */
const workspaceTsconfigs = fs
  .globSync(['frontend/*/tsconfig.json', 'packages/*/tsconfig.json'], { cwd: repoRoot })
  .map((workspacePath) => path.join(repoRoot, workspacePath))
  // Trie pour que la liste -- donc l'empreinte des options du resolveur -- ne
  // depende pas de l'ordre dans lequel le systeme de fichiers rend ses entrees.
  .sort();

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
  /*
   * Variante TYPE-AWARE du preset recommande (SETUP-06). Elle ajoute a
   * `recommended` les regles qui exigent un programme TypeScript -- promesse non
   * attendue, operation sur un `any` qui s'ignore, `await` sur ce qui n'est pas
   * une promesse -- c'est-a-dire precisement ce qu'une analyse purement
   * syntaxique ne peut pas voir.
   *
   * Ce que la bascule coute en temps est mesure et inscrit au README ; c'est la
   * question qui l'avait fait reporter depuis SETUP-03.
   */
  ...tseslint.configs.recommendedTypeChecked,
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
      parserOptions: {
        /*
         * Ce qui alimente en types les regles ci-dessus (SETUP-06).
         *
         * `projectService` et NON une liste de `project` : c'est l'API que
         * typescript-eslint recommande depuis sa version 8. Elle s'appuie sur le
         * service de projet de TypeScript -- celui des editeurs -- et retrouve
         * seule le tsconfig le plus proche de chaque fichier, ce qu'une liste de
         * motifs devrait redire a chaque workspace ajoute au depot.
         *
         * `tsconfigRootDir` est EXPLICITE, et ce n'est pas decoratif : a defaut,
         * typescript-eslint deduit un repertoire candidat de la pile d'appel (son
         * `getTSConfigRootDirFromStack`, declenche par la lecture meme de
         * `tseslint.configs.*`) -- donc packages/config-eslint, le dossier de CE
         * fichier, jamais la racine du depot. Meme raison que pour les motifs du
         * resolveur ci-dessus : un chemin devine tient tant que rien ne bouge.
         */
        projectService: true,
        tsconfigRootDir: repoRoot,
      },
    },
    rules: sharedRules,
  },

  /*
   * Le JavaScript du depot, hors du typage (SETUP-06).
   *
   * AUCUN fichier .js/.mjs/.cjs n'est couvert par un tsconfig ici, et c'est
   * verifiable : les `include` des trois applications ne retiennent que les .ts
   * et les .tsx, celui de `packages/ui` que ses sources sous src/, et les trois
   * packages de configuration n'ont pas de tsconfig du tout. La frontiere
   * « JavaScript = non type, TypeScript = type » est donc exacte, pas une
   * approximation commode.
   *
   * Sans ce bloc, chacun de ces fichiers sort en « Parsing error: [...] was not
   * found by the project service » -- 17 erreurs sur le depot au moment ou ces
   * lignes sont ecrites, a commencer par les .mjs de la racine et ce fichier-ci.
   * Le code n'est meme pas analyse : le parseur s'arrete avant.
   *
   * `disableTypeChecked` ne se borne pas a eteindre les regles concernees : il
   * pose aussi `parserOptions: { program: null, project: false, projectService:
   * false }`. C'est ce qui empeche le parseur de reclamer un programme pour un
   * fichier qui n'appartient a aucun projet.
   *
   * `tseslint.globs.js` est le glob des quatre extensions JavaScript (mjs, js,
   * cjs, jsx), fourni par le paquet : prefere a un motif recopie a la main, qui
   * divergerait a la premiere extension ajoutee en amont.
   */
  {
    name: '@repo/eslint-config/base-untyped',
    files: [tseslint.globs.js],
    extends: [tseslint.configs.disableTypeChecked],
  },

  // Toujours en DERNIER : eslint-config-prettier ne fait qu'eteindre les regles
  // de mise en forme, pour qu'ESLint et Prettier ne se contredisent jamais.
  // Le deplacer plus haut reactiverait les conflits (critere d'acceptation 4).
  eslintConfigPrettier,
]);
