import nextPlugin from '@next/eslint-plugin-next';
import { defineConfig } from 'eslint/config';
import eslintConfigPrettier from 'eslint-config-prettier';

import react from './react.js';

/**
 * Preset `next` — les trois applications Next (FRONT-01 et suivants).
 *
 * Bati sur `@next/eslint-plugin-next`, le plugin autonome qui porte reellement
 * les 22 regles de Next, et NON sur son emballage `eslint-config-next`.
 *
 * Raison : `eslint-config-next` fait un `require('next/dist/compiled/babel/
 * eslint-parser')` alors qu'il ne declare `next` ni en dependance ni en peer.
 * La dependance est fantome — invisible dans une application Next, ou `next`
 * est de toute facon installe, mais fatale dans un package de configuration
 * isole comme celui-ci : sous le node_modules strict de pnpm, le chargement du
 * preset echoue sur « Cannot find module 'next/...' ». Y remedier imposerait de
 * tirer tout le framework Next dans ce package, et donc d'en figer la version
 * avant meme que FRONT-01 ne l'ait choisie.
 *
 * Le plugin autonome, lui, n'a aucune peer dependency et ne connait pas `next`.
 * Ce preset se compose donc normalement a partir de `react` (et donc de `base`),
 * ce qui garantit un socle de regles strictement identique aux trois presets.
 *
 * Non repris de `eslint-config-next` : `eslint-plugin-jsx-a11y` (accessibilite)
 * et `eslint-plugin-react`. Tous deux plafonnent leur peer `eslint` a ^9 et
 * n'annoncent pas ESLint 10 — meme motif que le remplacement d'
 * eslint-plugin-import par import-x. A reconsiderer en FRONT-01, ou
 * l'accessibilite du parcours de prise de rendez-vous se jouera vraiment.
 */
export default defineConfig([
  ...react,

  // `core-web-vitals` est un sur-ensemble de `recommended` : memes 22 regles,
  // avec les regles liees aux Core Web Vitals relevees de `warn` a `error`.
  nextPlugin.configs['core-web-vitals'],

  {
    name: '@repo/eslint-config/next-overrides',
    rules: {
      // Regle heritee du Pages Router : elle cherche un dossier `pages/` et
      // journalise « Pages directory cannot be found » a chaque execution quand
      // il n'existe pas. Les trois frontends de Juui sont en App Router, ou
      // cette regle n'a plus d'objet — elle ne produirait que du bruit.
      '@next/next/no-html-link-for-pages': 'off',
    },
  },

  // Toujours en dernier — voir base.js.
  eslintConfigPrettier,
]);
