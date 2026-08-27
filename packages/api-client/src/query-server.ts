/**
 * FRONT-04 -- L'hydratation : un QueryClient par requete SERVEUR, et de quoi
 * transmettre son contenu au navigateur.
 *
 * `cache()` DE REACT, ET NON UNE VARIABLE DE MODULE
 * C'est l'avertissement en tete de runtime.ts, applique au cache : sur le
 * serveur Next, un module est partage par TOUTES les requetes du processus, et
 * un QueryClient de module servirait le dossier d'un animal a l'utilisateur
 * suivant. `cache()` memorise par requete serveur et rien au-dela -- plusieurs
 * composants serveur d'une meme page obtiennent le MEME client, deux visiteurs
 * jamais. C'est le pendant serveur de l'initialiseur `useState` du navigateur.
 *
 * PAS DE ROUTAGE DES 401 ICI, contrairement au client du navigateur. Un 401
 * recu pendant un rendu serveur doit remonter a la page, qui redirigera
 * (FRONT-07), et non declencher une deconnexion globale dans un processus qui
 * sert tout le monde.
 *
 * MAIS CE N'EST PAS CETTE FABRIQUE QUI L'EMPECHE, ET LA REVUE CONTRADICTOIRE A
 * CORRIGE CE QUI ETAIT ECRIT ICI. On lisait « l'isolation est structurelle --
 * deux fabriques ». C'est faux : React execute les initialiseurs de `useState`
 * AU RENDU SERVEUR, donc `createQueryClient()` -- celui qui branche le routage
 * -- est bien fabrique a chaque passe SSR (mesure sur `renderToString`). Ce qui
 * protege reellement, c'est la garde d'environnement des trois fonctions
 * d'unauthorized.ts. Ne pas la supprimer en croyant les deux fabriques
 * suffisantes.
 *
 * La politique de cache, elle, est la MEME : `queryDefaultOptions` est partage,
 * pour qu'il n'y ait pas deux verites sur le staleTime.
 *
 * POURQUOI LES DEUX RE-EXPORTS, ET CE N'EST PAS DE LA COMMODITE
 * Les trois applications ne declarent pas `@tanstack/react-query` (ecart
 * SHARED-03 : « un seul exemplaire, donc un seul contexte React »), et le
 * node_modules strict de pnpm interdit d'importer ce qu'on ne declare pas.
 * Sans ces deux noms, aucune page ne POURRAIT hydrater. Meme geste que le
 * `useTheme` re-exporte par `@repo/ui` : le package est la seule frontiere avec
 * cette bibliotheque.
 *
 * `shouldDehydrateQuery` RESTE AU DEFAUT -- les requetes reussies, et elles
 * seules. Inclure les requetes EN COURS ferait traverser au flux RSC une
 * promesse serialisee, dont le rejet arrive apres l'envoi du squelette et se
 * presente au client sous forme redigee (« redacted »). Sans elles, un
 * prechargement non attendu se solde par un rechargement cote navigateur :
 * PLUS LENT, JAMAIS FAUX. Le piege a connaitre est l'autre face de ce choix --
 * un `void queryClient.prefetchQuery(...)` sans `await` deshydrate
 * SILENCIEUSEMENT RIEN. A rouvrir par FRONT-18a, en connaissance de cause.
 *
 * A N'IMPORTER QUE DEPUIS UN COMPOSANT SERVEUR -- ET RIEN NE LE TIENT, CE QUI
 * SE PAIE PRECISEMENT ICI. Un composant `'use client'` peut importer ce
 * fichier : cela compile, cela s'execute, et le resultat A L'AIR CORRECT.
 * Mesure : dans le build CLIENT de React 19, `cache` n'est pas une
 * memoisation mais un simple passe-plat (`return fn.apply(null, arguments)`).
 * `getServerQueryClient()` y rend donc un QueryClient NEUF a chaque appel --
 * cache jamais partage avec le fournisseur, aucun routage du 401, et un client
 * refabrique a chaque rendu. Le rendre mecanique demande `import 'server-only'`
 * et la dependance qui va avec ; l'ecart est consigne au registre, et il revient
 * au premier ticket qui prechargera reellement.
 */

import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query';
import { cache } from 'react';

import { queryDefaultOptions } from './query-client';

/**
 * Le QueryClient de la requete serveur en cours : le meme objet pour tous les
 * composants serveur d'un meme rendu, un objet neuf a la requete suivante.
 *
 * Montage attendu d'une page qui precharge :
 *
 *   export default async function Page({ groupId }: { groupId: GroupId }) {
 *     const queryClient = getServerQueryClient();
 *     await queryClient.prefetchQuery(
 *       getListPetsQueryOptions({
 *         query: { queryKey: groupQueryKey({ groupId }, getListPetsQueryKey()) },
 *       }),
 *     );
 *     return (
 *       <HydrationBoundary state={dehydrate(queryClient)}>
 *         <ListePatients />
 *       </HydrationBoundary>
 *     );
 *   }
 *
 * LA CLEF DE PORTEE N'EST PAS UN ORNEMENT DANS CET EXEMPLE. Un prechargement
 * ecrit sans elle deshydrate la reponse sous la clef NUE d'Orval : elle
 * atterrit dans le cache du navigateur la ou ni `tenantScopeKey` ni aucun autre
 * prefixe de la fabrique ne l'atteint, et survit donc a la bascule de groupe.
 * C'est la panne que l'ADR-0027 existe pour rendre impossible, et c'est
 * l'exemple canonique qui la reintroduirait.
 */
export const getServerQueryClient = cache(
  (): QueryClient => new QueryClient({ defaultOptions: queryDefaultOptions }),
);

export { dehydrate, HydrationBoundary };
