// Le plugin est importe comme OBJET, et non declare par son nom.
//
// Prettier passe les chaines du tableau `plugins` a `import()`, resolu depuis le
// repertoire de travail et non depuis le fichier de configuration. Sous le
// node_modules strict de pnpm (`shamefullyHoist: false`), « prettier-plugin-
// tailwindcss » n'est resolvable que depuis CE package : la forme chaine
// casserait des que Prettier serait lance depuis un sous-dossier. L'objet
// importe, lui, est resolu par Node au chargement de ce fichier.
import * as tailwindcss from 'prettier-plugin-tailwindcss';

/**
 * Configuration Prettier partagee par tout le monorepo (SETUP-03).
 *
 * Source de verite unique : le `prettier.config.mjs` de la racine se contente de
 * la re-exporter. Une application qui aurait besoin d'une surcharge locale ecrit
 * son propre `prettier.config.mjs` :
 *
 *   import base from '@repo/prettier-config';
 *   export default { ...base, tailwindStylesheet: './src/app/globals.css' };
 *
 * @type {import('prettier').Config}
 */
const config = {
  // `semi: true` — defaut Prettier, et formatage deja en place sur le projet
  // precedent (VetoLib). Le ticket SETUP-03 laissait le choix ouvert.
  semi: true,
  singleQuote: true,
  trailingComma: 'all',
  printWidth: 100,

  // Alignes sur .editorconfig et .gitattributes, pour qu'un editeur qui ne lit
  // que l'un des deux produise le meme resultat.
  tabWidth: 2,
  useTabs: false,
  endOfLine: 'lf',

  arrowParens: 'always',
  bracketSpacing: true,

  // Ne jamais reformater la prose : le Markdown du depot est retaille a la main
  // pour rester lisible en diff. Prettier normalise malgre tout les tableaux,
  // les listes et les blocs de code.
  proseWrap: 'preserve',

  plugins: [tailwindcss],

  // A COMPLETER EN SHARED-01 : une fois `packages/ui/src/styles/globals.css`
  // cree, ajouter ici
  //   tailwindStylesheet: './packages/ui/src/styles/globals.css'
  // (chemin resolu relativement au fichier de configuration Prettier qui porte
  // l'option). Sans elle, le plugin retombe silencieusement sur la configuration
  // Tailwind par defaut : le tri des classes fonctionne, mais ignore le theme et
  // les utilitaires maison.
};

export default config;
