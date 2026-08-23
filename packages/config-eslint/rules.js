/**
 * Les decisions de regles de `@repo/eslint-config`, isolees de la plomberie.
 *
 * Les trois presets forment une chaine — `next` etend `react`, qui etend
 * `base`, qui applique ce fragment — donc toute regle ajoutee ici vaut pour les
 * trois. C'est le seul endroit a modifier pour durcir ou assouplir le socle.
 *
 * Volontairement un objet de REGLES NU, sans cle `plugins` : l'enregistrement
 * des plugins reste dans les presets, ce fichier ne porte que des arbitrages.
 *
 * Aucune regle dite « type-aware » (celles qui exigent un programme TypeScript)
 * n'y figure : il n'existe encore aucun tsconfig.json dans le depot. Le passage
 * a `tseslint.configs.recommendedTypeChecked` relevera de FRONT-01.
 */
export const sharedRules = {
  // `console.log` oublie en production ; warn et error restent legitimes.
  'no-console': ['warn', { allow: ['warn', 'error'] }],

  // Le prefixe `_` est la convention pour marquer un binding volontairement
  // inutilise (parametre de callback, element ignore d'un destructuring).
  '@typescript-eslint/no-unused-vars': [
    'error',
    {
      argsIgnorePattern: '^_',
      varsIgnorePattern: '^_',
      caughtErrorsIgnorePattern: '^_',
      destructuredArrayIgnorePattern: '^_',
    },
  ],

  // `import type` explicite : le transpileur peut effacer l'import sans avoir a
  // resoudre le module, ce dont dependent `isolatedModules` et Turbopack.
  '@typescript-eslint/consistent-type-imports': [
    'error',
    { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
  ],

  // Tri des imports (le « tri des imports » du ticket SETUP-03).
  'import-x/order': [
    'warn',
    {
      groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index', 'type'],
      pathGroups: [{ pattern: '@repo/**', group: 'internal', position: 'before' }],
      'newlines-between': 'always',
      alphabetize: { order: 'asc', caseInsensitive: true },
    },
  ],
  'import-x/no-duplicates': 'error',

  // Les deux regles qui exigent un resolveur capable de suivre les chemins
  // TypeScript. Elles attendaient FRONT-01, qui a apporte le premier tsconfig
  // d'application et, avec lui, les alias `@/*` et `@repo/ui/*` qu'une
  // resolution purement node ne suit pas. `base.js` branche desormais
  // eslint-import-resolver-typescript ; sans ce resolveur, ces deux regles
  // n'echoueraient pas -- elles ne verraient simplement rien.
  //
  // Un import casse est une erreur d'execution que rien d'autre n'attrape avant
  // le build : `tsc` ignore ce qui n'est pas type, et le lint est la seule passe
  // qui parcourt tous les fichiers du depot.
  'import-x/no-unresolved': 'error',
  // Un cycle d'imports ne casse pas toujours, et c'est ce qui le rend penible :
  // il rend l'ordre d'initialisation des modules dependant du point d'entree, si
  // bien que le meme code fonctionne en developpement et rend `undefined` une
  // fois groupe pour la production.
  'import-x/no-cycle': 'error',
};

/**
 * Version de React declaree aux presets `react` et `next`.
 *
 * ESLint 10 a supprime `context.getFilename()`, sur lequel repose la detection
 * automatique (`"detect"`) d'eslint-plugin-react — embarque par
 * eslint-config-next. Sans cette valeur explicite, le lint plante.
 *
 * Figee par FRONT-01 : les trois applications epinglent react 19.2.8, comme
 * `packages/ui`. A remonter le jour ou elles changeront de mineure -- toutes
 * ensemble, ce socle etant partage.
 */
export const REACT_VERSION = '19.2';
