import { fileURLToPath } from 'node:url';

import type { NextConfig } from 'next';

/**
 * Configuration Next de frontend-professional (FRONT-01).
 *
 * Premiere des trois applications du depot ; FRONT-02 et FRONT-03 reprendront ce
 * fichier tel quel, seul le port du script `dev` les distinguera.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,

  // `@repo/api-client` et `@repo/ui` sont publies en SOURCE TypeScript, sans
  // etape de build : sans cette ligne, Next servirait du .tsx a un navigateur.
  // C'est la contrepartie assumee des choix de SHARED-01 et SHARED-03 -- aucune
  // compilation a orchestrer entre les packages, et le Fast Refresh traverse la
  // frontiere du monorepo. Le premier porte le client genere par Orval, dont la
  // sortie vit dans src/generated/.
  transpilePackages: ['@repo/api-client', '@repo/ui'],

  // Sortie autonome : Next copie dans .next/standalone le serveur et les SEULS
  // modules qu'il a vu importer. C'est ce que reclame INFRA-05 pour produire une
  // image sans node_modules complet.
  output: 'standalone',

  // Racine a partir de laquelle tracer ces modules. Le defaut est le dossier de
  // l'application, ce qui suffit a un depot mono-projet mais pas ici : les
  // dependances vivent dans le node_modules de la RACINE, atteintes par des liens
  // symboliques pnpm que le tracage ne remonterait pas. La sortie compilerait
  // sans erreur puis echouerait au demarrage sur un module introuvable.
  //
  // Resolu depuis ce fichier plutot que depuis `process.cwd()`, qui vaut ce que
  // vaut le repertoire d'appel.
  outputFileTracingRoot: fileURLToPath(new URL('../..', import.meta.url)),

  // Next 16 depose de lui-meme un AGENTS.md et un CLAUDE.md a chaque `next dev`,
  // pour les assistants de code. Refuse ici : le depot n'a aucun fichier de ce
  // genre, ils sont reecrits a chaque demarrage -- donc soit une modification
  // non commitee en permanence, soit de la prose generee a relire a chaque PR --
  // et leur contenu s'adresse a un outil tiers, pas aux personnes qui lisent ce
  // code. La documentation du depot, c'est le README et `documentation/`.
  agentRules: false,
};

export default nextConfig;
