import type { MetadataRoute } from 'next';

/**
 * `/robots.txt` de frontend-admin (FRONT-03).
 *
 * L'exact inverse de celui de frontend-individual, qui l'annoncait deja : ici un
 * `disallow` complet, et aucun sitemap -- il n'y a pas de page publique a
 * enumerer.
 *
 * Fichier de metadonnees Next : le nom `robots.ts` dans `app/` suffit a servir
 * la route `/robots.txt`. Aucune API dynamique n'etant appelee, Next le genere
 * au BUILD, en fichier statique -- et c'est tres bien : ce fichier n'a rien de
 * confidentiel, il ne dit que « n'entrez pas ».
 *
 * IL DOIT RESTER ATTEIGNABLE. Le `matcher` de `middleware.ts` l'exclut
 * explicitement : un robot redirige vers la page de connexion ne lirait aucune
 * directive, et cette interdiction-ci n'aurait ete ecrite pour personne.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      disallow: '/',
    },
  };
}
