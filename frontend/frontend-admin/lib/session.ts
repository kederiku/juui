/**
 * La session du back-office, telle que FRONT-03 peut la connaitre.
 *
 * CE QUE CE FICHIER FAIT, ET CE QU'IL NE FAIT PAS
 * Il ne verifie RIEN. Il constate la presence d'un jeton et en deduit une
 * session, sans lire sa signature ni sa date d'expiration -- le service JWT est
 * l'objet de BACK-10, son pendant navigateur celui de FRONT-07, et aucun des
 * deux n'existe. Ce qui est pose ici, c'est la FORME que prendra la reponse :
 * une session ou rien, et un role a comparer.
 *
 * VOLONTAIREMENT SANS `next/headers`
 * Ce module est importe par `middleware.ts`, qui s'execute dans le runtime Edge
 * ou `next/headers` n'existe pas. Il reste donc pur : la lecture du cookie se
 * fait chez l'appelant -- le middleware a sa `request.cookies`, les composants
 * serveur ont `getSession()` dans `require-role.ts`.
 *
 * A REPRENDRE EN FRONT-07 : ce ticket-la stocke le jeton de rafraichissement en
 * cookie httpOnly et remonte le contexte d'authentification dans
 * `packages/api-client`, partage par les trois applications. Le nom du cookie
 * comme le type `Role` migreront la-bas ; ils sont ici en un seul exemplaire
 * pour que ce deplacement ne soit qu'un deplacement.
 */

/**
 * Nom du cookie de session. Une seule declaration dans l'application : le
 * middleware et les composants serveur lisent la meme chaine, faute de quoi la
 * redirection et la garde de role pourraient etre en desaccord -- l'une
 * laissant passer ce que l'autre refuse.
 */
export const SESSION_COOKIE_NAME = 'juui_session';

/**
 * Les trois types de compte du produit, tels que BACK-10 les inscrit dans le
 * claim applicatif du jeton. Le back-office n'ouvre qu'au premier ; les deux
 * autres figurent ici parce que le jeton, lui, peut les porter -- et qu'une
 * garde de role qui ne connaitrait que le role autorise ne saurait pas
 * distinguer « mauvais role » de « valeur inconnue ».
 */
export type Role = 'admin' | 'professionnel' | 'particulier';

export type Session = {
  role: Role;
};

/**
 * Deduit une session de la valeur du cookie.
 *
 * Tant que FRONT-07 n'a pas livre, le contenu du jeton n'est pas lu : sa seule
 * PRESENCE vaut session d'administrateur. C'est ce qui permet, sur le poste, de
 * voir le back-office en posant le cookie a la main -- la procedure est decrite
 * sur la page « Les trois applications » du site de documentation.
 */
export function sessionFromToken(token: string | undefined): Session | null {
  if (!token) {
    return null;
  }

  return { role: 'admin' };
}
