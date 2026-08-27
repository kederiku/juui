/**
 * FRONT-04 -- La politique de cache des trois applications, en un seul endroit.
 *
 * POURQUOI CE FICHIER N'EST PAS DANS query-provider.tsx
 * Deux raisons, et aucune n'est de style.
 *   1. `tsconfig.verify.json` n'inclut PAS les `.tsx`. Tout ce qui vit dans le
 *      composant est hors de portee de `make verify-api-client` -- le seul
 *      harnais d'execution du frontend jusqu'a QA-02. La politique de cache et
 *      le predicat de reessai sont du TypeScript pur : ici, ils s'executent,
 *      donc ils se prouvent.
 *   2. Un module `'use client'` n'exporte que des references client : un
 *      composant serveur ne peut pas y appeler une fonction ordinaire. Sans ce
 *      fichier, query-server.ts ne partagerait pas ces defauts, et
 *      l'hydratation repartirait sur une SECONDE politique de cache -- ce que
 *      le ticket refuse en un mot : « pas trois configurations divergentes ».
 *
 * AUCUNE INSTANCE DE MODULE ICI, ET C'EST LE CRITERE LUI-MEME.
 * `createQueryClient` fabrique, elle ne retient pas. Meme avertissement qu'en
 * tete de runtime.ts : sur le serveur Next, ce module est partage par TOUTES
 * les requetes du processus, et un QueryClient de module servirait le cache
 * d'un utilisateur a un autre. C'est aussi pourquoi le verrou du 401 vit dans
 * unauthorized.ts : ce fichier-ci ne doit contenir aucun `let`.
 *
 * `queryDefaultOptions` EST TOUT DE MEME UN OBJET PARTAGE, et le dire vaut
 * mieux que le taire : `new QueryClient({ defaultOptions })` le conserve PAR
 * REFERENCE, cote navigateur comme dans chaque client de requete serveur. Le
 * muter en place -- `queryClient.getDefaultOptions().queries.staleTime = 0` --
 * traverserait donc tout le processus. Rien ne le fait, query-core recopiant
 * dans `defaultQueryOptions` ; c'est un bord tranchant, pas une panne, et il
 * est nomme ici plutot qu'ecarte par un `Object.freeze` qui ne serait que de
 * surface.
 *
 * CE QUE CE FICHIER NE FAIT PAS
 * Il ne pose pas `throwOnError` : renvoyer les erreurs a une frontiere d'erreur
 * est une decision d'AFFICHAGE, elle appartient a FRONT-10 -- et les etats de
 * chargement a FRONT-18a. Il ne touche ni a `networkMode` ni a
 * `structuralSharing`, dont les defauts n'ont ete mis en defaut par aucune
 * mesure. A rouvrir si l'une le demande.
 */

import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';

import { isApiError } from './errors';
import { reportUnauthorized } from './unauthorized';

import type { DefaultOptions } from '@tanstack/react-query';

/**
 * Nombre de RE-essais, apres la tentative initiale. Deux : la sequence complete
 * dure au pire 1 s puis 2 s, soit trois secondes avant qu'un ecran d'erreur
 * s'affiche. Au-dela, l'utilisateur croit l'application figee et recharge la
 * page -- ce qui repart de zero.
 */
const MAX_QUERY_RETRIES = 2;

/** Duree pendant laquelle une donnee est servie sans aller au reseau. */
const STALE_TIME_MS = 60_000;

/**
 * Faut-il rejouer cette requete ?
 *
 * LA SIGNATURE VIENT DE TANSTACK, PAS DU GENERE, ET LA DIFFERENCE EST OPERANTE.
 * Le `TError` des hooks d'Orval vaut `unknown` (liveness) ou `ReadinessReport`
 * (readiness) ; celui des defauts du QueryClient vaut `Error`. Ni l'un ni
 * l'autre n'est `ApiError`. Ce qui ARRIVE reellement est ce que le mutator a
 * leve -- d'ou la garde `isApiError` plutot qu'un acces direct a `.status`, qui
 * ne compilerait pas et, s'il compilait, mentirait.
 */
function shouldRetryQuery(failureCount: number, error: Error): boolean {
  // JAMAIS DE REESSAI COTE SERVEUR, et ce n'est pas decoratif : le defaut « 0
  // tentative sur le serveur » de TanStack ne s'applique QUE si `retry` est
  // absent. Poser une fonction herite donc la politique du navigateur au rendu
  // serveur, ou deux reessais coutent jusqu'a trois secondes de page blanche
  // pour une requete qui, en echec, ne sera de toute facon pas deshydratee.
  if (typeof window === 'undefined') {
    return false;
  }

  if (failureCount >= MAX_QUERY_RETRIES) {
    return false;
  }

  // TOUT CE QUI N'EST PAS UNE ApiError SORT ICI, ET C'EST L'ARBITRAGE.
  // `ApiConfigurationError` est une classe A PART (errors.ts : « L'API n'a rien
  // refuse : c'est le deploiement qui est faux ») : une base URL absente ne
  // devient pas presente parce qu'on redemande. Un `instanceof ApiConfigurationError` explicite serait du code
  // mort -- cette ligne l'attrape deja. La panne qu'il eviterait est reelle,
  // alors elle est nommee ici plutot qu'ecrite : quiconque remplacera ce
  // `return false` par un repli permissif fera reessayer trois fois une erreur
  // de deploiement, avec le message « reessayer » a l'ecran.
  if (!isApiError(error)) {
    return false;
  }

  // `status: 0` SIGNIFIE « AUCUNE REPONSE N'EST PARVENUE » (errors.ts) : reseau,
  // DNS, 500 sans en-tetes CORS, preflight refuse. C'est le cas ou reessayer
  // sert le plus, et celui qu'il ne faut surtout pas confondre avec un refus de
  // l'API -- errors.ts le dit deja : « un `if (error.status === 401)` ne doit
  // jamais confondre l'API a refuse et l'API n'a pas repondu ».
  if (error.status === 0) {
    return true;
  }

  // 4xx JAMAIS, ce que le ticket demande nommement : l'API a compris et a
  // refuse ; la meme requete obtiendra le meme refus, trois fois plus lentement.
  // 408 et 429 ont ete envisages en exception, puis rejetes apres lecture de
  // BACK-09 : le backend n'emet aujourd'hui ni l'un ni l'autre, et une exception
  // sans emetteur est une regle que personne ne verifie. A rouvrir le jour ou
  // une route repond 429 avec un `Retry-After` -- qui donnerait alors le delai
  // au lieu de le deviner.
  return error.status >= 500;
}

/**
 * Les defauts partages par les trois applications ET par les deux clients --
 * celui du navigateur, celui d'une requete serveur. Exportes pour qu'il n'y ait
 * jamais deux politiques a tenir alignees.
 */
export const queryDefaultOptions: DefaultOptions = {
  queries: {
    // 60 s, le compromis demande par le ticket. En dessous, chaque retour de
    // navigation repart au reseau ; au-dessus, une correction saisie par un
    // confrere met trop longtemps a apparaitre.
    staleTime: STALE_TIME_MS,

    // PAS DE `gcTime`, ET LA REVUE CONTRADICTOIRE A CORRIGE CE QUI ETAIT ECRIT
    // ICI. On avait pose `5 * STALE_TIME_MS` en motivant qu'une entree evincee
    // avant d'etre perimee ferait repasser l'ecran par un etat vide. C'est
    // faux : `addObserver` ANNULE la minuterie d'eviction et `optionalRemove`
    // ne retire que `if (!this.observers.length)` -- une entree observee n'est
    // jamais evincee, quel que soit le gcTime, qui mesure le temps SANS
    // observateur. Les deux valeurs sont orthogonales.
    //
    // La valeur ecrite valait de surcroit exactement le defaut du navigateur
    // (5 min), tout en couplant les deux constantes -- abaisser le staleTime
    // aurait fait tomber le gcTime en silence. Et sur le SERVEUR, le defaut est
    // `Infinity`, ce qui ne programme AUCUNE minuterie : une valeur finie y
    // faisait retenir le QueryClient de chaque rendu pendant cinq minutes,
    // donnees comprises. Ne rien ecrire donne les deux bons comportements.

    // Le ticket le demande ; voici le motif. Un veterinaire quitte l'onglet pour
    // une consultation et revient : une liste qui se reordonne sous le curseur
    // au retour est une surprise, pas une fraicheur. `refetchOnReconnect` reste
    // a son defaut -- LUI couvre le vrai cas, la perte de reseau.
    refetchOnWindowFocus: false,

    retry: shouldRetryQuery,

    // 1 s puis 2 s. Le plafond n'est jamais atteint avec deux reessais ; il est
    // ecrit pour borner la valeur si MAX_QUERY_RETRIES montait un jour, et pour
    // que le pire cas se lise ici plutot que dans la documentation de TanStack.
    retryDelay: (attemptIndex) => Math.min(1_000 * 2 ** attemptIndex, 10_000),
  },
  mutations: {
    // JAMAIS, ET CE N'EST PAS LA SYMETRIE DES REQUETES. Un GET rejoue ne coute
    // qu'un aller-retour ; un POST rejoue peut creer un SECOND rendez-vous, ou
    // une seconde ligne de dossier medical. Et le seul cas ou reessayer semble
    // sur -- aucune reponse parvenue, `status: 0` -- est precisement celui ou
    // l'on ignore si le serveur a ecrit.
    retry: false,
  },
};

/**
 * Fabrique le QueryClient DU NAVIGATEUR : la politique ci-dessus, plus le
 * routage global des 401.
 *
 * A appeler dans un initialiseur de `useState` (query-provider.tsx), jamais au
 * niveau du module. Le pendant serveur est `getServerQueryClient`
 * (query-server.ts), qui partage la politique mais PAS le routage.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    // LE QueryCache ET LE MutationCache, pas seulement le premier. Une mutation
    // partie avec un jeton expire tombe en 401 exactement comme une requete, et
    // c'est meme le cas le plus penible : l'utilisateur venait d'ecrire.
    queryCache: new QueryCache({
      onError: (error) => {
        void reportUnauthorized(error);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error) => {
        void reportUnauthorized(error);
      },
    }),
    defaultOptions: queryDefaultOptions,
  });
}
