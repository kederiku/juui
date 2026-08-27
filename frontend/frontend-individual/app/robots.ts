import { SITE_URL } from '@/lib/site-url';

import type { MetadataRoute } from 'next';

/**
 * `/robots.txt` de frontend-individual (FRONT-02).
 *
 * Cette application est la seule des trois a devoir etre indexee : c'est la
 * vitrine grand public. `frontend-professional` et `frontend-admin` sont des
 * espaces authentifies, et FRONT-03 posera l'inverse de ce fichier -- un
 * `disallow` complet.
 *
 * Fichier de metadonnees Next : le nom `robots.ts` dans `app/` suffit a servir
 * la route `/robots.txt`. Rien a router, rien a declarer ailleurs. Aucune API
 * dynamique n'etant appelee ici, Next la genere au BUILD, en fichier statique.
 *
 * Le renvoi vers le sitemap n'est pas decoratif : c'est le seul endroit ou un
 * robot decouvre l'existence du sitemap sans qu'on le lui soumette a la main.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
