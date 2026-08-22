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

  // NB : `import-x/no-cycle` et `import-x/no-unresolved` ne sont pas activees.
  // Elles exigent un resolveur capable de suivre les chemins TypeScript
  // (eslint-import-resolver-typescript), donc un tsconfig.json — sans lui elles
  // n'echouent pas, elles ne voient simplement rien. A poser en FRONT-01.
};

/**
 * Version de React declaree aux presets `react` et `next`.
 *
 * ESLint 10 a supprime `context.getFilename()`, sur lequel repose la detection
 * automatique (`"detect"`) d'eslint-plugin-react — embarque par
 * eslint-config-next. Sans cette valeur explicite, le lint plante.
 * A remonter quand FRONT-01 figera la version de React des applications.
 */
export const REACT_VERSION = '19.2';
