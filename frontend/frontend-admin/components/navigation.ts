import { HospitalIcon, LayoutDashboardIcon, UsersIcon } from 'lucide-react';

import type { Role } from '@/lib/session';
import type { LucideIcon } from 'lucide-react';

/**
 * Les sections du back-office, declarees une seule fois.
 *
 * POURQUOI UN FICHIER POUR TROIS LIGNES
 * Deux composants lisent cette liste : la navigation laterale, qui en fait des
 * liens, et le fil d'Ariane, qui en tire ses libelles. Deux copies
 * divergeraient au premier renommage, et la divergence serait de celles qu'on
 * ne remarque pas tout de suite -- un menu qui annonce « Cliniques » au-dessus
 * d'un fil d'Ariane qui dit « cliniques ».
 *
 * Les ecrans reels remplaceront ces trois entrees ; la liste, elle, restera le
 * seul endroit ou une section du back-office se declare.
 */

export type NavigationEntry = {
  href: string;
  label: string;
  icon: LucideIcon;
  /**
   * Roles autorises a voir l'entree. Le back-office n'ouvre qu'aux
   * administrateurs aujourd'hui ; le champ existe parce que le filtrage doit
   * etre en place des maintenant -- l'ajouter apres coup supposerait de repasser
   * sur chaque entree, et c'est ainsi qu'on en oublie une.
   */
  roles: Array<Role>;
};

export const NAVIGATION: Array<NavigationEntry> = [
  { href: '/', label: 'Tableau de bord', icon: LayoutDashboardIcon, roles: ['admin'] },
  { href: '/cliniques', label: 'Cliniques', icon: HospitalIcon, roles: ['admin'] },
  { href: '/utilisateurs', label: 'Utilisateurs', icon: UsersIcon, roles: ['admin'] },
];

/** Les entrees qu'un role donne a le droit de voir. */
export function navigationForRole(role: Role): Array<NavigationEntry> {
  return NAVIGATION.filter((entry) => entry.roles.includes(role));
}

/**
 * Libelle d'une adresse, ou `undefined` si elle ne correspond a aucune section
 * declaree -- le fil d'Ariane retombe alors sur le segment brut, ce qui vaut
 * mieux qu'une case vide sur une page profonde.
 */
export function labelForHref(href: string): string | undefined {
  return NAVIGATION.find((entry) => entry.href === href)?.label;
}
