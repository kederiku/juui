import { SITE_URL } from './site-url';

import type { MetadataRoute } from 'next';

/**
 * `/sitemap.xml` de frontend-individual (FRONT-02).
 *
 * Fichier de metadonnees Next, comme `robots.ts` : le nom suffit a servir la
 * route, et l'absence d'API dynamique le fait generer au BUILD.
 *
 * Une seule entree aujourd'hui, l'accueil : c'est la seule page de
 * l'application. Les pages publiques a venir -- annuaire des cliniques, fiche
 * de clinique, parcours de prise de rendez-vous -- s'ajouteront ici, et celles
 * qui se declinent par identifiant seront enumerees depuis l'API plutot
 * qu'ecrites a la main.
 *
 * PAS DE `lastModified`. La seule valeur qu'on saurait donner ici serait la
 * date du build, qui change a chaque deploiement meme lorsque la page, elle,
 * n'a pas bouge. Annoncer une modification qui n'a pas eu lieu est un mauvais
 * signal, et un moteur qui s'en apercoit cesse d'y accorder du credit. Le champ
 * reviendra quand une vraie date de mise a jour existera.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: `${SITE_URL}/`,
      changeFrequency: 'weekly',
      priority: 1,
    },
  ];
}
