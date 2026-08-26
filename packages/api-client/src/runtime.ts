/**
 * SHARED-03 -- Ce que le mutator doit savoir du monde : ou est l'API, et au nom
 * de qui elle est appelee.
 *
 * DEUX BASES URL, ET C'EST LA RAISON D'ETRE DE CE FICHIER
 * Les trois .env.local.example declarent deux adresses, et elles ne sont pas
 * interchangeables : NEXT_PUBLIC_API_URL est celle du NAVIGATEUR
 * (http://localhost:8000), API_INTERNAL_URL celle du SERVEUR Next -- en
 * conteneur, http://api:8000, le nom du service compose. Un composant serveur
 * qui appellerait localhost n'atteindrait que son propre conteneur. Le choix se
 * fait donc a l'EXECUTION, cote par cote : c'est pourquoi la base URL n'est PAS
 * confiee au `baseUrl` d'Orval, qui figerait une seule expression au moment de
 * la generation.
 *
 * UN FOURNISSEUR, JAMAIS UN JETON -- A LIRE AVANT DE TOUCHER A CE FICHIER
 * Ce module retient une FONCTION, pas une valeur. La difference n'est pas de
 * style : sur le serveur Next, ce module est partage par TOUTES les requetes du
 * processus. Y ranger un jeton ferait fuir la session d'un utilisateur vers la
 * requete d'un autre. La fonction posee par FRONT-07 doit donc lire une source
 * PROPRE A LA REQUETE -- `cookies()` cote serveur, le contexte React cote
 * navigateur -- et jamais une variable capturee au demarrage.
 *
 * CE QUE CE FICHIER NE FAIT PAS
 * Ni connexion, ni rafraichissement de jeton, ni file d'attente sur 401 : c'est
 * FRONT-07, dans `src/auth/`. Ici il n'y a qu'une prise de courant.
 */

import { ApiConfigurationError } from './errors';

/** De quoi le mutator a besoin pour signer une requete (ADR-0012). */
export type RequestIdentity = {
  /** Le jeton porteur, ou `null` pour un appel anonyme. */
  token: string | null;
  /** La clinique active, envoyee en `X-Clinic-Id`, ou `null` hors perimetre. */
  clinicId: string | null;
};

export type RequestIdentityProvider = () => RequestIdentity | Promise<RequestIdentity>;

const ANONYMOUS: RequestIdentity = { token: null, clinicId: null };

let provider: RequestIdentityProvider = () => ANONYMOUS;

/**
 * Branche la source d'identite. A appeler UNE fois, a l'amorcage de chaque
 * application (FRONT-07). Voir l'avertissement en tete de fichier : la fonction
 * posee doit lire une source propre a la requete, jamais une valeur capturee.
 */
export function setRequestIdentityProvider(next: RequestIdentityProvider): void {
  provider = next;
}

/** Revient a l'appel anonyme -- deconnexion, et isolation entre cas de test. */
export function resetRequestIdentityProvider(): void {
  provider = () => ANONYMOUS;
}

/**
 * Lit l'identite de la requete en cours.
 *
 * Pas de fonction `async` sans `await` : `@typescript-eslint/require-await` est
 * active par le socle type-aware (SETUP-06). `Promise.resolve` accepte aussi
 * bien un fournisseur synchrone qu'asynchrone.
 */
export function readRequestIdentity(): Promise<RequestIdentity> {
  return Promise.resolve(provider());
}

/**
 * L'origine de l'API, sans barre finale.
 *
 * ECRITE LITTERALEMENT, ET IL LE FAUT : Next REMPLACE le texte
 * `process.env.NEXT_PUBLIC_API_URL` au BUILD. Une destructuration
 * (`const { NEXT_PUBLIC_API_URL } = process.env`) ne serait pas remplacee et
 * vaudrait `undefined` dans le navigateur.
 *
 * LEVE PLUTOT QUE DE SE REPLIER. Une base absente ferait partir les requetes
 * vers l'origine du frontend, ou elles rendraient des 404 du routeur Next -- une
 * panne qui ne nomme jamais sa cause. Meme regle que la configuration du backend
 * (BACK-03) : echouer en nommant la variable manquante.
 */
export function resolveBaseUrl(): string {
  const isServer = typeof window === 'undefined';
  const raw = isServer
    ? (process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL)
    : process.env.NEXT_PUBLIC_API_URL;

  if (raw === undefined || raw === '') {
    throw new ApiConfigurationError(
      isServer
        ? 'API_INTERNAL_URL (ou NEXT_PUBLIC_API_URL) est absente : copier .env.local.example en .env.local.'
        : 'NEXT_PUBLIC_API_URL est absente du bundle : la renseigner puis RECONSTRUIRE -- Next la remplace au build, un redemarrage ne changera rien.',
    );
  }

  // Les gabarits d'environnement l'ecrivent sans barre finale ; on ne s'y fie
  // pas -- l'URL construite par le code genere commence toujours par « / », et
  // deux barres feraient un chemin que le routeur de FastAPI ne connait pas.
  return raw.replace(/\/+$/, '');
}
