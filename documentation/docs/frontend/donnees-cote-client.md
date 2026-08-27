---
title: Données côté client
description: "Le QueryProvider partagé par les trois applications, la politique de cache en un seul endroit, la fabrique de clés qui porte la frontière de tenance, le traitement global des 401 et l'hydratation côté serveur."
---

# Données côté client

Un seul fournisseur, une seule politique de cache, une seule façon de nommer une entrée de cache —
et les trois applications les partagent. Tout vit dans `@repo/api-client`, à côté du client généré
qu'il sert (FRONT-04).

| Chemin                   | Ce qu'il porte                                                                                   |
| ------------------------ | ------------------------------------------------------------------------------------------------ |
| `src/query-provider.tsx` | Le `QueryProvider` monté dans les trois layouts, et les Devtools.                                |
| `src/query-client.ts`    | La politique de cache : `staleTime`, `retry`, `retryDelay`.                                      |
| `src/query-keys.ts`      | La fabrique de clés et les quatre portées ([ADR-0027](../adr/0027-portee-des-cles-de-cache.md)). |
| `src/unauthorized.ts`    | La couture du 401, que FRONT-07 remplacera.                                                      |
| `src/query-server.ts`    | Le client d'une requête serveur, et l'hydratation.                                               |

## Un seul fournisseur, et c'est une contrainte

```tsx
import { QueryProvider } from '@repo/api-client/query-provider';
import { ThemeProvider } from '@repo/ui/components/theme-provider';

<body className="font-sans antialiased">
  <ThemeProvider>
    <QueryProvider>{children}</QueryProvider>
  </ThemeProvider>
</body>;
```

C'est le montage des trois applications, à la ligne près. Il n'y a **pas** de `app/providers.tsx` :
`QueryProvider` porte déjà `'use client'`, un layout resté composant serveur le monte directement,
comme il monte déjà le `ThemeProvider`.

Les trois applications **ne déclarent pas** `@tanstack/react-query` : seul `@repo/api-client` en
dépend. Ce n'est pas une économie de ligne, c'est la panne qu'on évite — deux exemplaires font deux
contextes React, et le fournisseur devient invisible aux hooks générés **sans la moindre erreur de
compilation**. Tout ce dont une application a besoin est donc **ré-exporté** par le package :
`useQueryClient` depuis `@repo/api-client/query-provider`, `HydrationBoundary` et `dehydrate` depuis
`@repo/api-client/query-server`. Aucune application n'écrit jamais `from '@tanstack/react-query'` —
et le `node_modules` strict de pnpm ne le lui permettrait pas.

Le `QueryClient` est créé dans un **initialiseur de `useState`**, jamais au niveau du module sans
garde. La raison est celle qu'écrit déjà `runtime.ts` : sur le serveur Next, un module est partagé
par toutes les requêtes du processus, et un client de module y servirait le cache d'un utilisateur à
un autre. L'initialiseur délègue donc à une fonction qui fabrique un client **neuf** côté serveur, et
n'en retient un que dans le navigateur.

:::warning Le `useState` seul ne suffit pas, et c'est mesuré
React **jette** l'état d'un composant qui suspend avant d'avoir commité, et rejoue l'initialiseur à
chaque tentative de rendu. Une sonde placée sous le fournisseur, suspendue par un `use(promise)` sans
frontière `<Suspense>` intermédiaire, a compté **deux** `QueryClient` distincts sans le singleton
navigateur, et **un** avec — sur le même protocole, rechargement complet compris. Le client
finalement commité étant neuf, son cache est vide et ses requêtes en vol sont perdues. App Router
n'interpose aucune frontière implicite entre le layout racine et la page : le premier `use()`,
`lazy()` ou composant client asynchrone rouvrirait la panne, sans erreur ni avertissement.
:::

## La politique de cache

Cinq valeurs, écrites une fois, partagées par le client du navigateur et par celui d'une requête
serveur.

| Réglage                | Valeur       | Pourquoi                                                                                                                    |
| ---------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `staleTime`            | 60 s         | En dessous, chaque retour de navigation repart au réseau ; au-dessus, la correction d'un confrère tarde.                    |
| `retryDelay`           | 1 s puis 2 s | Exponentiel, plafonné à 10 s ; le plafond n'est jamais atteint avec deux réessais, il borne la valeur si le nombre montait. |
| `refetchOnWindowFocus` | `false`      | Une liste qui se réordonne sous le curseur au retour d'onglet est une surprise, pas une fraîcheur.                          |
| `retry` (requêtes)     | conditionnel | Voir ci-dessous.                                                                                                            |
| `retry` (mutations)    | `false`      | Rejouer un POST peut créer un second rendez-vous, et un échec de transport ne dit pas si le serveur a écrit.                |

`refetchOnReconnect` reste à son défaut : **lui** couvre le vrai cas, la perte de réseau.

:::note Pas de `gcTime`, et c'est une correction
Une première version en posait un, en motivant qu'il devait dépasser le `staleTime` « sinon l'écran
repasse par un état vide ». C'est faux, source à l'appui : `addObserver` annule la minuterie
d'éviction et `optionalRemove` ne retire que `if (!this.observers.length)` — une entrée **observée**
n'est jamais évincée, quel que soit le `gcTime`, qui mesure le temps _sans_ observateur. Les deux
valeurs sont orthogonales. Le laisser au défaut donne en outre les deux bons comportements : 5 min
dans le navigateur, et `Infinity` sur le serveur — c'est-à-dire **aucune minuterie**, là où une
valeur finie faisait retenir le `QueryClient` de chaque rendu, données comprises.
:::

### Ce qui se réessaie, et ce qui ne se réessaie pas

Le prédicat lit l'`ApiError` que le mutator lève ([Le client d'API généré](./client-api-genere.md)) :

| Erreur                              | Réessai | Motif                                                                       |
| ----------------------------------- | ------- | --------------------------------------------------------------------------- |
| Rendu **serveur**, quel qu'il soit  | jamais  | Deux tentatives coûtent jusqu'à trois secondes de page blanche.             |
| `ApiConfigurationError`             | jamais  | L'API n'a rien refusé : c'est le déploiement qui est faux.                  |
| Erreur qui n'est pas une `ApiError` | jamais  | On ne réessaie pas ce qu'on ne sait pas nommer.                             |
| **4xx**                             | jamais  | Le serveur a compris et a refusé ; la même requête obtiendra le même refus. |
| **5xx**                             | 2 fois  | 1 s puis 2 s.                                                               |
| `status === 0` (aucune réponse)     | 2 fois  | Réseau, DNS, 500 sans en-têtes CORS, préflight refusé.                      |

:::warning Le défaut serveur de TanStack ne s'applique pas ici
« Zéro tentative sur le serveur » n'est le défaut de TanStack Query **que si `retry` est absent**.
Poser une fonction hérite donc la politique du navigateur au rendu serveur : la garde est explicite
dans `query-client.ts`, et un contrôle la joue.
:::

## La clé de cache porte la frontière de tenance

C'est le sujet le plus important de cette page, et il a son ADR :
[ADR-0027](../adr/0027-portee-des-cles-de-cache.md).

La clé qu'Orval exporte identifie une **route** — `getCheckReadinessQueryKey()` rend
`['/health/ready']`. Or la même route rend des données différentes selon le groupe actif du jeton
([ADR-0012](../adr/0012-perimetre-de-requete.md)). S'en tenir à elle, c'est ranger sous une seule
entrée la réponse de deux groupes : après une bascule, l'écran affiche les données de la structure
précédente pendant tout le `staleTime`, sans appel réseau et sans erreur.

Chaque clé commence donc par sa **portée**, et la fabrique préfixe la clé générée sans jamais la
réécrire :

```ts
// Seule l'étiquette `health` est générée à ce jour ; `medical-records` et
// `scheduling` arriveront avec leurs routes.
import { getCheckReadinessQueryKey } from '@repo/api-client/api/health';
import { clinicQueryKey, groupQueryKey, publicQueryKey } from '@repo/api-client/query-keys';

publicQueryKey(getCheckReadinessQueryKey());
// ['public', '/health/ready']

groupQueryKey({ groupId }, getListPetsQueryKey());
// ['tenant', '<groupe>', '/api/v1/pets']

clinicQueryKey({ groupId, clinicId }, getListAppointmentsQueryKey());
// ['tenant', '<groupe>', 'clinic', '<clinique>', '/api/v1/appointments']
```

| Fabrique         | Pour quoi                                                             |
| ---------------- | --------------------------------------------------------------------- |
| `publicQueryKey` | Lisible sans jeton : sondes de santé, vitrine publique.               |
| `groupQueryKey`  | Les données du groupe actif.                                          |
| `clinicQueryKey` | Les données d'une clinique — **seulement** si la ressource en dépend. |
| `tenantScopeKey` | Le préfixe de purge d'un groupe entier.                               |

**Le typage refuse d'oublier le groupe.** `groupQueryKey` exige une portée, et son `groupId` est un
type marqué : un identifiant de clinique ou de compte ne peut pas prendre sa place par simple
compatibilité de `string`. On obtient un `GroupId` par `asGroupId`, qui refuse la chaîne vide.

**L'ordre des segments est le contrat.** TanStack Query n'apparie ses clés que par **préfixe** :
la portée d'abord, l'opération ensuite. C'est ce qui rend l'invalidation prévisible sans qu'on ait
à l'écrire opération par opération.

```ts
// Tout ce groupe, cliniques comprises — ce que fera FRONT-08 à la bascule. Le
// groupe visé est celui qu'on QUITTE, à capturer avant la réémission du jeton.
await queryClient.cancelQueries({ queryKey: tenantScopeKey({ groupId: precedent }) });
queryClient.removeQueries({ queryKey: tenantScopeKey({ groupId: precedent }) });
```

Sans l'annulation, une réponse du groupe précédent qui arrive après la purge recrée son entrée.

:::note Tant que la session charge
Un écran de tenance ne peut pas composer sa clé avant de connaître le groupe — c'est le but. La
forme à écrire d'ici FRONT-07 est un hook désactivé (`enabled: scope !== null`) avec une clé de
remplacement explicite ; ce que ce ticket **n'a pas** livré, c'est une fabrique pour cette
clé-là. Elle appartient à FRONT-07, qui possède `useAuth` et sait donc distinguer « pas encore
chargé » de « pas de groupe ».
:::

## Le 401, en un seul endroit

Le `QueryCache` **et** le `MutationCache` routent leurs erreurs vers un traitement global — une
mutation partie avec un jeton expiré tombe en 401 comme une requête, et c'est même le cas le plus
pénible : l'utilisateur venait d'écrire.

```ts
import { setUnauthorizedHandler } from '@repo/api-client/unauthorized';

setUnauthorizedHandler(async (error) => {
  // FRONT-07 : rafraichir le jeton, puis deconnecter en cas d'echec.
});
```

Même patron que `setRequestIdentityProvider` : le module retient une **fonction**, jamais une
session. Deux propriétés comptent, et un contrôle joue chacune :

- **Un seul traitement par épisode.** Dix requêtes qui tombent ensemble reçoivent la **même**
  promesse. Sans ce verrou, FRONT-07 lancerait dix rafraîchissements concurrents, dont neuf sur un
  jeton déjà consommé — une expiration ordinaire transformée en déconnexion.
- **Rien ne se déclenche côté serveur.** Traiter un 401 est une action d'interface ; sur le serveur
  Next, la fonction posée dans ce module serait celle d'un **autre** utilisateur que celui dont on
  rend la requête. Un 401 rencontré au rendu serveur remonte à la page, qui redirige.

Tant que FRONT-07 n'a pas livré, le traitement par défaut **trace** et ne fait rien d'autre : un
`no-op` muet rendrait le critère inobservable, et une redirection écrite ici inventerait une route
de connexion que les trois applications ne partagent pas encore.

## L'hydratation côté serveur

Un composant serveur qui précharge obtient **son** client par `getServerQueryClient()` — mémorisé
par `cache()` de React, donc partagé par tous les composants serveur d'un même rendu, et jamais
entre deux visiteurs.

```tsx
import { dehydrate, getServerQueryClient, HydrationBoundary } from '@repo/api-client/query-server';

export default async function Page() {
  const queryClient = getServerQueryClient();
  await queryClient.prefetchQuery(
    getListPetsQueryOptions({
      query: { queryKey: groupQueryKey({ groupId }, getListPetsQueryKey()) },
    }),
  );

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ListePatients />
    </HydrationBoundary>
  );
}
```

:::danger La clé de portée n'est pas un ornement dans cet exemple
Un préchargement écrit sans elle déshydrate la réponse sous la clé **nue** d'Orval : elle atterrit
dans le cache du navigateur là où ni `tenantScopeKey` ni aucun autre préfixe de la fabrique ne
l'atteint, et **survit donc à la bascule de groupe**. C'est la panne que
l'[ADR-0027](../adr/0027-portee-des-cles-de-cache.md) existe pour rendre impossible, et c'est
l'exemple canonique qui la réintroduirait.
:::

:::warning Le `await` n'est pas facultatif
Seules les requêtes **réussies** sont déshydratées. Un `void prefetchQuery(...)` sans `await`
transmet donc silencieusement **rien**, et l'écran repart au réseau côté navigateur. C'est un choix
— inclure les requêtes en cours ferait traverser une promesse sérialisée au flux RSC, dont le rejet
arrive après l'envoi du squelette : plus lent, mais jamais faux.
:::

Le client serveur partage la politique de cache, mais **pas** le routage des 401 : l'isolation est
structurelle — deux fabriques — plutôt qu'un test d'environnement.

## Les Devtools, et ce que la mesure a dit

Les React Query Devtools sont montées par le `QueryProvider` hors production. Elles n'apparaissent
dans **aucun** artefact de build de production, et c'est mesuré plutôt que supposé :

```bash
rm -rf frontend/*/.next && pnpm build
grep -rl "Devtools is already mounted" frontend/*/.next/static frontend/*/.next/server
grep -rl "@tanstack/query-devtools" frontend/*/.next/static frontend/*/.next/server --include='*.js'
```

Les deux commandes ne trouvent rien. Le `rm -rf` n'est pas décoratif : Turbopack écrit la sortie de
développement sous `.next/dev/`, et une recherche non bornée sur un poste qui a lancé `make dev`
trouverait le marqueur là — sans que cela dise quoi que ce soit du build de production.

La contre-épreuve, sans laquelle ces deux commandes ne concluraient rien : la même recherche élargie
au dossier de développement (`grep -rl "Devtools is already mounted" frontend/*/.next/dev`) trouve le
marqueur dans quatre fichiers — deux de code, deux cartes de source. Le motif est donc valide, et son
absence en production veut dire quelque chose.

Une seconde contre-épreuve a corrigé une affirmation qu'on aurait écrite sans elle : garde retirée,
`next build` rejoué, le **panneau** — les quelque 600 Ko de `@tanstack/query-devtools` — reste absent
dans les deux cas ; seul l'élément JSX réapparaît, pour 174 octets. L'exclusion ne vient donc pas de
la garde du `QueryProvider` mais du paquet lui-même, dont le point d'entrée vaut
`process.env.NODE_ENV !== 'development' ? () => null : …`. Ce sont **deux** mécanismes, et c'est le
second qui tient le critère ; la garde reste pour retirer l'élément de l'arbre plutôt qu'y rendre une
souche, et pour écrire l'intention à l'endroit du montage.

## Vérifier sans lancer d'application

```bash
pnpm --filter @repo/api-client test
```

Six contrôles **hors ligne**, sans pile démarrée, sans compilation et sans dépendance : la bascule
de groupe, la clé d'Orval reprise intacte, la portée publique sans tenance, le préfixe de purge qui
n'atteint que son groupe, deux cliniques qui ne partagent pas d'entrée, et le refus d'un identifiant
vide ou blanc.

C'est possible parce que `src/query-keys.ts` n'a **aucun import de valeur** : Node 24 efface les
types à la volée et exécute le fichier tel quel. **Cette pureté est porteuse** — un seul import de
valeur ferait tomber la propriété, et avec elle la seule preuve mécanique dont ce sujet dispose tant
que QA-02 n'a pas posé de runner de test frontend.

```bash
make verify-api-client
```

Ajoute ce qui a besoin de `@tanstack/react-query` : la politique réellement posée, le prédicat de
réessai sur sept cas, l'appariement par préfixe joué sur un **vrai** `QueryCache`, le routage des
401 et sa déduplication, le préchargement et la déshydratation du client serveur — plus la
**jonction**, qui compare la clé recopiée par le programme hors ligne à celle qu'Orval exporte.
Exige la pile démarrée (`make dev`).

## Ce qui viendra

- **FRONT-05** — le patron de formulaire, qui réutilisera les schémas Zod du même package.
- **FRONT-07** — le flux d'authentification : c'est lui qui posera `setUnauthorizedHandler` et qui
  saura dire quel est le groupe actif.
- **FRONT-08** — la bascule de groupe, et la purge par `tenantScopeKey`.
- **FRONT-10** et **FRONT-18a** — l'affichage des erreurs et les états de chargement, restés hors de
  la politique de cache à dessein.
- **QA-02** — le runner de test frontend, qui rejouera les hooks eux-mêmes.

Les écarts assumés avec le ticket FRONT-04 sont consignés au
[registre des écarts](../ecarts/front.md#écarts-assumés-avec-le-ticket-front-04).
