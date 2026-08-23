/**
 * Configuration PostCSS de la bibliotheque de composants (SHARED-01).
 *
 * Tailwind v4 n'a plus de fichier `tailwind.config.js` : tout passe par ce
 * plugin PostCSS, et le theme vit dans `src/styles/globals.css`.
 *
 * Les trois applications ne redefinissent pas ce fichier, elles le
 * re-exportent -- une seule chaine PostCSS pour tout le monorepo :
 *
 *   // frontend/frontend-professional/postcss.config.mjs
 *   export { default } from '@repo/ui/postcss.config';
 *
 * @type {import('postcss-load-config').Config}
 */
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};
