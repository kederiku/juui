import { fileURLToPath } from 'node:url';

import type { NextConfig } from 'next';

/**
 * Configuration Next de frontend-individual (FRONT-02).
 *
 * Reprise a l'identique de celle de frontend-professional (FRONT-01), qui sert
 * de patron aux trois applications : rien n'y est propre au B2C. Ce qui
 * distingue cette application-ci -- indexation, metadonnees, sitemap -- se joue
 * dans `app/`, pas ici.
 *
 * Chaque cle est commentee dans le fichier d'origine ; le resume tient en
 * quatre lignes.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,

  // `@repo/api-client` et `@repo/ui` sont publies en SOURCE TypeScript, sans
  // etape de build.
  transpilePackages: ['@repo/api-client', '@repo/ui'],

  // Sortie autonome, reclamee par INFRA-05 pour produire une image legere.
  output: 'standalone',

  // Racine du tracage des modules : sans elle, les dependances atteintes par
  // les liens symboliques pnpm manqueraient a la sortie standalone, qui se
  // construirait sans erreur puis echouerait au demarrage.
  outputFileTracingRoot: fileURLToPath(new URL('../..', import.meta.url)),

  // Refus des AGENTS.md / CLAUDE.md que Next 16 depose a chaque `next dev` : la
  // documentation du depot, c'est le README et `documentation/`.
  agentRules: false,
};

export default nextConfig;
