/**
 * Chaine PostCSS partagee par tout le depot (SHARED-02).
 *
 * Tailwind v4 n'a plus de fichier `tailwind.config.js` : tout passe par ce
 * plugin, et le theme vit dans le `theme.css` voisin.
 *
 * Les trois applications ne redefinissent pas ce fichier, elles le
 * re-exportent -- une seule chaine PostCSS pour tout le monorepo :
 *
 *   // frontend/frontend-professional/postcss.config.mjs
 *   export { default } from '@repo/tailwind-config/postcss.config';
 *
 * @type {import('postcss-load-config').Config}
 */
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};
