'use client';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@repo/ui/components/breadcrumb';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Fragment } from 'react';

import { labelForHref } from '@/components/navigation';

/**
 * Fil d'Ariane du back-office (FRONT-03).
 *
 * DERIVE DU CHEMIN, jamais renseigne page par page : une page qui declare
 * elle-meme sa position finit toujours par mentir apres un deplacement de
 * route. Les libelles viennent de `navigation.ts`, la meme liste que la barre
 * laterale -- c'est ce qui garantit que le menu et le fil d'Ariane appellent une
 * section du meme nom.
 *
 * Un segment inconnu de la liste s'affiche tel quel plutot que de laisser un
 * trou : les pages profondes a venir (une fiche de clinique, par exemple)
 * afficheront leur identifiant en attendant que le libelle soit resolu.
 */
export function AdminBreadcrumb() {
  const pathname = usePathname();
  const segments = pathname.split('/').filter(Boolean);

  /*
   * Le tableau de bord ouvre toujours le fil : c'est la racine de
   * l'application, et le seul point de retour commun a toutes les pages.
   */
  const trail = [
    { href: '/', label: labelForHref('/') ?? 'Accueil' },
    ...segments.map((segment, index) => {
      const href = `/${segments.slice(0, index + 1).join('/')}`;

      return { href, label: labelForHref(href) ?? decodeURIComponent(segment) };
    }),
  ];

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {trail.map((step, index) => {
          const isLast = index === trail.length - 1;

          return (
            /*
             * Le separateur est un frere de l'element, pas son enfant : les deux
             * sont des <li>, et un <li> dans un <li> est un balisage invalide que
             * les lecteurs d'ecran restituent de travers.
             */
            <Fragment key={step.href}>
              <BreadcrumbItem>
                {isLast ? (
                  <BreadcrumbPage>{step.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild>
                    <Link href={step.href}>{step.label}</Link>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {isLast ? null : <BreadcrumbSeparator />}
            </Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
