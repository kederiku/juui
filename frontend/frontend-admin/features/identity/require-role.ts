import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

import { SESSION_COOKIE_NAME, sessionFromToken } from '@/lib/session';

import type { Role, Session } from '@/lib/session';

/**
 * Garde de role cote serveur du back-office (FRONT-03).
 *
 * CE QU'ELLE VAUT
 * Un CONFORT D'AFFICHAGE, et rien de plus. Elle evite d'afficher un ecran a qui
 * n'a rien a y faire ; elle ne protege aucune donnee. La verification qui fait
 * foi est celle du backend -- la fabrique `require_role(...)` de BACK-10, du
 * cote ou la reponse est produite. Un contournement de cette garde-ci ne donne
 * acces a rien d'autre qu'une page vide, tant que l'API refuse la requete.
 *
 * L'ecrire noir sur blanc a l'endroit ou l'on serait tente de croire l'inverse :
 * c'est le seul interet de ce commentaire.
 *
 * DANS `features/identity/` DEPUIS FRONT-09, et plus dans `lib/`. Une garde de
 * role est du METIER d'identite : elle sait ce qu'est un role, ce qu'est une
 * session, et ou renvoyer qui n'en a pas. Le nom de la feature suit celui du
 * module backend `identity` -- et non `auth`, qui n'existe cote API que comme
 * prefixe d'URL. Le vocabulaire de session, lui, est reste dans `lib/session.ts`
 * : ce fichier-ci explique pourquoi.
 */

/**
 * Session de la requete courante, lue dans le cookie.
 *
 * Fonction serveur : `cookies()` n'existe ni dans le navigateur ni dans le
 * proxy.
 */
export async function getSession(): Promise<Session | null> {
  const cookieStore = await cookies();

  return sessionFromToken(cookieStore.get(SESSION_COOKIE_NAME)?.value);
}

/**
 * Exige l'un des roles donnes, ou renvoie vers la page de connexion.
 *
 * Pas de page 403 : un back-office n'a personne a qui expliquer qu'il existe.
 * Session absente ou role insuffisant menent au meme endroit, et le `next`
 * ramene a la page demandee une fois la connexion faite -- meme parametre que
 * celui du proxy, pour qu'un seul mecanisme de retour existe.
 */
export async function requireRole(...allowed: Array<Role>): Promise<Session> {
  const session = await getSession();

  if (!session || !allowed.includes(session.role)) {
    redirect('/login');
  }

  return session;
}
