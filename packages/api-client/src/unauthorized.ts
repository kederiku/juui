/**
 * FRONT-04 -- La couture du 401 : un seul endroit ou brancher « la session est
 * finie », et un seul traitement quel que soit le nombre de requetes tombees.
 *
 * UN GESTIONNAIRE, JAMAIS UNE SESSION -- MEME AVERTISSEMENT QU'EN TETE DE runtime.ts
 * Ce module retient une FONCTION et un verrou, rien qui decrive un utilisateur.
 * Sur le serveur Next, un module est partage par TOUTES les requetes du
 * processus : y ranger l'etat d'un utilisateur ferait fuir sa session vers la
 * requete d'un autre.
 *
 * ET C'EST POURQUOI RIEN NE SE PASSE COTE SERVEUR -- NI POSE, NI DECLENCHEMENT
 * Traiter un 401, c'est une action d'INTERFACE -- rediriger, effacer un cookie,
 * purger un cache. Le gestionnaire pose dans ce module serait, cote serveur,
 * celui d'un AUTRE utilisateur que celui dont on rend la requete. Les TROIS
 * fonctions publiques portent donc la garde, et non leurs appelants : un module
 * `'use client'` est EXECUTE au rendu serveur, si bien qu'un
 * `setUnauthorizedHandler` ecrit au niveau d'un module y deposerait la
 * fermeture d'un utilisateur dans un etat partage par tout le processus. Poser
 * la garde sur le seul `reportUnauthorized` aurait laisse ce depot possible, a
 * une ligne pres. Un 401 rencontre pendant un rendu serveur se traite la ou il
 * arrive : `proxy.ts` et `require-role.ts` (FRONT-03), puis FRONT-07.
 *
 * POURQUOI UN VERROU
 * Un ecran affiche dix listes ; le jeton expire ; les dix requetes tombent en
 * 401 dans le meme battement. Sans verrou, FRONT-07 lancerait dix
 * rafraichissements concurrents, et neuf echoueraient sur un jeton de
 * rafraichissement deja consomme -- une expiration ordinaire transformee en
 * deconnexion. La MEME promesse est donc rendue a tous les appelants : le
 * traitement n'a lieu qu'une fois, et chacun sait quand il s'acheve.
 *
 * CE QUE CE FICHIER NE FAIT PAS
 * Il ne rafraichit aucun jeton, ne met aucune requete en file d'attente et ne
 * rejoue rien : c'est FRONT-07, dans `src/auth/`, et cela se passe dans le
 * MUTATOR, pas dans le cache. Ici il n'y a qu'une prise de courant.
 */

import { isApiError } from './errors/api-error';

import type { ApiError } from './errors/api-error';

/** Ce que l'application fait quand l'API declare la session finie. */
export type UnauthorizedHandler = (error: ApiError) => void | Promise<void>;

/**
 * Le defaut, tant que FRONT-07 n'a pas livre : il TRACE, et rien d'autre.
 *
 * Ni redirection ni purge -- il n'y a ni page de connexion partagee ni session a
 * fermer avant FRONT-07, et un `window.location` ecrit ici serait la troisieme
 * copie d'une route que les trois applications ne definissent pas encore.
 * `warn` est l'un des deux niveaux que le socle autorise (SETUP-06), et c'est
 * le bon : un 401 sans traitement n'est pas un cas nominal, il doit se voir --
 * y compris en production, ou il signale que l'amorcage n'a pas eu lieu.
 */
const DEFAULT_HANDLER: UnauthorizedHandler = (error) => {
  console.warn(
    `FRONT-04 : 401 recu (${error.code}) et aucun traitement branche. ` +
      "FRONT-07 posera setUnauthorizedHandler a l'amorcage de l'application.",
  );
};

let handler: UnauthorizedHandler = DEFAULT_HANDLER;
let pending: Promise<void> | null = null;

/**
 * Branche le traitement du 401. A appeler UNE fois, a l'amorcage de chaque
 * application (FRONT-07) : rafraichissement du jeton, puis deconnexion en cas
 * d'echec. Voir l'avertissement en tete de fichier -- la fonction posee ne doit
 * capturer aucun jeton.
 */
export function setUnauthorizedHandler(next: UnauthorizedHandler): void {
  if (typeof window === 'undefined') {
    return;
  }
  handler = next;
}

/**
 * Revient au traitement par defaut -- celui qui TRACE, voir plus haut : ce
 * module ne deconnecte rien tant que FRONT-07 n'a pas livre.
 *
 * Sert a la deconnexion et a l'isolation entre controles. Il ABANDONNE
 * l'episode en cours plutot que de l'attendre : un signalement qui suivrait
 * immediatement ouvrirait donc un second traitement. C'est le comportement
 * voulu -- on remet a zero -- mais il ne faut pas l'appeler en plein episode
 * pour une autre raison que celle-la.
 */
export function resetUnauthorizedHandler(): void {
  if (typeof window === 'undefined') {
    return;
  }
  handler = DEFAULT_HANDLER;
  pending = null;
}

/**
 * Signale une erreur au traitement global. Ne fait rien si ce n'est pas un 401,
 * ni hors du navigateur.
 *
 * @param error L'erreur telle que le cache la recoit -- de type `unknown`, le
 *   `TError` du code genere ne valant pas `ApiError`.
 * @returns La promesse du traitement en cours, partagee par tous les appelants
 *   d'un meme episode. Elle dit QUAND le traitement s'acheve, rien de plus : le
 *   REJEU d'une requete ne peut pas se faire depuis le cache, qui n'a plus la
 *   requete -- il appartient au mutator, et donc a FRONT-07.
 */
export function reportUnauthorized(error: unknown): Promise<void> {
  if (typeof window === 'undefined') {
    return Promise.resolve();
  }
  if (!isApiError(error) || error.status !== 401) {
    return Promise.resolve();
  }
  if (pending !== null) {
    return pending;
  }

  // `Promise.resolve().then(...)` ET NON `Promise.resolve(handler(error))`, ce
  // que la revue contradictoire a corrige : la seconde forme EVALUE
  // `handler(error)` avant d'attacher le `.catch()`, si bien qu'un gestionnaire
  // qui leve SYNCHRONEMENT traverse cette fonction, remonte dans
  // `QueryCache.onError` et y REMPLACE le 401 d'origine -- mesure. Sous cette
  // forme, la levee est capturee comme un rejet.
  //
  // Pas de fonction `async` non plus : `@typescript-eslint/require-await`
  // (SETUP-06) l'interdirait sans `await`, et une enveloppe `async` rendrait
  // une promesse NEUVE par appel, ce qui defait le partage d'episode.
  const episode = Promise.resolve()
    .then(() => handler(error))
    .catch((cause: unknown) => {
      // LE TAIRE SERAIT LE PIRE. Un rafraichissement rate qui ne dit rien
      // laisse l'utilisateur devant un ecran vide, sans jamais le renvoyer a la
      // connexion.
      console.error('FRONT-04 : le traitement du 401 a echoue.', cause);
    })
    .finally(() => {
      // Le verrou ne se relache que si c'est bien CET episode qui le tient :
      // `resetUnauthorizedHandler` a pu le remettre a zero entre-temps.
      if (pending === episode) {
        pending = null;
      }
    });

  pending = episode;
  return episode;
}
