import { defineConfig } from 'eslint/config';
import eslintConfigPrettier from 'eslint-config-prettier';
import jsxA11yX from 'eslint-plugin-jsx-a11y-x';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

import base from './base.js';
import { a11yComponents, a11yRules, REACT_VERSION } from './rules.js';

/**
 * Preset `react` — React sans Next.
 *
 * Cible `packages/ui` (SHARED-01) : une bibliotheque de composants consommee par
 * les trois applications, qui n'a donc pas a heriter des regles propres au
 * routeur ou aux images de Next.
 *
 * Se compose bien a partir de `base`, contrairement au preset `next` : les
 * plugins ajoutes ici viennent tous du meme `node_modules` que ceux de `base`.
 *
 * C'EST ICI QUE VIVENT LES REGLES D'ACCESSIBILITE (SETUP-07), et non dans
 * `next` d'ou SETUP-03 les avait ecartees : `packages/ui` porte les composants,
 * c'est donc lui le premier concerne, et `next` en herite de toute facon.
 */
export default defineConfig([
  ...base,
  {
    name: '@repo/eslint-config/react',
    files: ['**/*.{js,mjs,cjs,jsx,ts,mts,cts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      /*
       * Accessibilite (SETUP-07). Le paquet est `eslint-plugin-jsx-a11y-x`, et
       * NON `eslint-plugin-jsx-a11y` : ce dernier plafonne toujours sa peer
       * `eslint` a ^9 et n'a rien publie depuis octobre 2024, ce qui est
       * exactement le motif de son retrait en SETUP-03. La variante « -x »
       * annonce `^9 || ^10` et porte a son changelog un « Add support for
       * ESLint 10 » explicite -- meme famille, et meme raisonnement, que le
       * remplacement d'eslint-plugin-import par import-x.
       *
       * Consequence a connaitre : le prefixe des regles est `jsx-a11y-x/`, et
       * la cle de reglages `settings['jsx-a11y-x']`. Le nom d'enregistrement
       * suit celui du paquet plutot que l'ancien -- le renommer ici tromperait
       * sur ce qui est reellement installe, et desaccorderait le prefixe des
       * regles de la cle de reglages, que le plugin lit en dur.
       */
      'jsx-a11y-x': jsxA11yX,
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
      'jsx-a11y-x': { components: a11yComponents },
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      /*
       * Le jeu `recommended` du plugin, dont on ne prend QUE la cle `rules`.
       * L'objet de configuration complet porte aussi une cle `plugins` et un
       * `languageOptions` que ce bloc possede deja ; les etaler ici les
       * dupliquerait, et lierait ce preset a la forme du leur -- ce que la
       * remarque de `base.js` sur les presets « flat » met en garde de faire.
       */
      ...jsxA11yX.configs.recommended.rules,
      ...a11yRules,
    },
  },
  // Re-applique apres les ajouts ci-dessus, pour rester le dernier maillon.
  eslintConfigPrettier,
]);
