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
 * Ce module est importe par `proxy.ts`, qui s'execute dans le runtime Edge ou
 * `next/headers` n'existe pas. Il reste donc pur : la lecture du cookie se fait
 * chez l'appelant -- le proxy a sa `request.cookies`, les composants serveur ont
 * `getSession()` dans `features/identity/require-role.ts`.
 *
 * POURQUOI IL N'EST PAS DESCENDU DANS `features/identity/` EN FRONT-09
 * C'est la frontiere elle-meme qui a repondu. `components/navigation.ts` et
 * `components/admin-sidebar.tsx` lisent le type `Role` pour filtrer les entrees
 * de la barre laterale, et le garde-fou de FRONT-09 interdit a `components/`
 * d'importer une feature -- y compris un import de TYPE, verifie. Le deplacer
 * aurait donc fait echouer le lint le jour de sa pose.
 *
 * La bonne lecture n'est pas d'assouplir la regle : ce fichier n'est pas
 * l'interieur d'un domaine, c'est le VOCABULAIRE DE SESSION de l'application,
 * lu par trois consommateurs de rangs differents -- le proxy, le shell, et la
 * feature `identity`. `lib/` est exactement ce rang, et FRONT-07 le fera monter
 * d'un cran de plus, dans `packages/api-client`.
 *
 * A REPRENDRE EN FRONT-07 : ce ticket-la stocke le jeton de rafraichissement en
 * cookie httpOnly et remonte le contexte d'authentification dans
 * `packages/api-client`, partage par les trois applications. Le nom du cookie
 * comme le type `Role` migreront la-bas ; ils sont ici en un seul exemplaire
 * pour que ce deplacement ne soit qu'un deplacement.
 */

/**
 * Nom du cookie de session. Une seule declaration dans l'application : le
 * proxy et les composants serveur lisent la meme chaine, faute de quoi la
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
 *
 * LES VALEURS SONT CELLES DE L'API, recopiees de l'`AccountType` du module
 * `identity` (`professional`, `individual`, `admin`). Elles etaient en francais
 * jusqu'a FRONT-09, ce qui aurait produit une comparaison toujours fausse le
 * jour ou le jeton serait reellement lu -- une panne qu'aucun typage n'aurait
 * signalee, les deux cotes etant des chaines.
 */
export type Role = 'admin' | 'professional' | 'individual';

export type Session = {
  role: Role;
};

/**
 * Ce que l'ecran affiche pour chaque role.
 *
 * MEME RAISON QUE LES STATUTS DE `clinics-table.tsx` : les valeurs sont celles
 * du contrat, en anglais ; les libelles sont ceux de l'interface, en francais.
 * Sans cette table, la barre laterale ecrirait « professional » a un
 * utilisateur francophone des que FRONT-07 decodera un vrai jeton -- rien ne
 * l'aurait signale avant, `sessionFromToken` ne rendant aujourd'hui que
 * `'admin'`, qui s'ecrit pareil dans les deux langues.
 */
export const ROLE_LABELS: Record<Role, string> = {
  admin: 'administrateur',
  professional: 'professionnel',
  individual: 'particulier',
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
