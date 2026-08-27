---
title: Le client d'API généré
description: "Le package @repo/api-client : ce qu'Orval génère depuis l'OpenAPI de FastAPI, comment régénérer, pourquoi src/generated/ ne s'édite jamais, et comment consommer un hook."
---

# Le client d'API généré

Un seul package porte tout ce que les trois frontends savent de l'API — types, hooks de requête et
schémas de validation — et **rien n'y est écrit à la main**. Le serveur FastAPI est l'unique source
de vérité ; Orval en dérive le reste ([ADR-0007](../adr/0007-client-api-genere-orval.md)).

Comme `@repo/ui`, le package n'est **jamais compilé** : il s'exporte en source TypeScript, et chaque
application le transpile.

| Chemin                | Contenu                                                                                                           |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `openapi.json`        | Le contrat exporté depuis FastAPI, versionné ([ADR-0019](../adr/0019-contrat-openapi-exporte.md)).                |
| `orval.config.ts`     | Les deux sorties du générateur — les hooks, puis les schémas Zod.                                                 |
| `src/mutator.ts`      | L'unique porte de sortie HTTP : base URL, en-têtes, erreurs.                                                      |
| `src/errors.ts`       | `ApiError` et la normalisation du format d'erreur unique.                                                         |
| `src/runtime.ts`      | L'adresse de l'API et le point d'injection de l'identité.                                                         |
| `src/query-*`         | La couche de cache : fournisseur, politique, clés, hydratation ([Données côté client](./donnees-cote-client.md)). |
| `src/unauthorized.ts` | La couture du 401 : un gestionnaire global, un verrou par épisode.                                                |
| `src/generated/`      | La sortie d'Orval. **Jamais éditée.**                                                                             |

## Ce que le package contient

Orval produit trois choses à partir du même contrat, et chacune couvre ce que les deux autres ne
couvrent pas :

- **Les types TypeScript** — le contrat à la compilation. Un champ renommé côté backend casse le
  build des frontends au lieu de casser la production.
- **Les hooks TanStack Query** — `useCheckReadiness`, et la fonction `checkReadiness` qu'il appelle.
  Le cache, l'état de chargement et l'annulation viennent avec.
- **Les schémas Zod** — la validation à l'exécution. Un type TypeScript ne vérifie rien une fois
  compilé ; un schéma Zod, si. C'est lui que réutilisera la validation des formulaires (FRONT-05),
  avec exactement les contraintes du backend.

Le découpage suit les **étiquettes OpenAPI**, une par module backend : `src/generated/api/health/`
aujourd'hui, `identity/` et `organization/` à mesure que les routes arrivent. La frontière métier du
backend devient ainsi visible côté client, sans qu'on ait à la redessiner
([Surface HTTP](../backend/surface-http.md), [ADR-0011](../adr/0011-routage-versionne-par-module.md)).

Les imports passent par la carte `exports`, jamais par un chemin relatif :

```ts
import { useCheckReadiness } from '@repo/api-client/api/health';
import type { ReadinessReport } from '@repo/api-client/model/readiness-report';
import { isApiError } from '@repo/api-client/errors';
```

Il n'existe **aucun export racine** : `import … from '@repo/api-client'` est refusé par le
résolveur. Ce n'est pas un oubli — c'est ce qui garantit qu'aucun baril ne se formera, et que chaque
application n'embarque que les étiquettes qu'elle utilise réellement.

## Régénérer

Une seule commande, et c'est l'étape **obligatoire** après toute modification d'un contrat d'API :

```bash
make generate-api
```

Elle enchaîne deux gestes : exporter le schéma depuis FastAPI, puis lancer Orval. L'export ne demande
ni serveur, ni base de données — le schéma se construit en mémoire.

Pour ne régénérer que le client, depuis le contrat déjà committé et sans `uv` sur le poste :

```bash
pnpm generate:api
```

Utile pour corriger un réglage d'Orval ou le mutator. Mais cette commande **ne voit pas** un
changement de contrat : elle relit le fichier tel qu'il est committé. Après une modification du
backend, c'est `make generate-api` qu'il faut.

La règle de travail qui découle de l'ADR-0007 : toute modification d'un contrat d'API s'accompagne
d'une régénération **dans la même pull request**. Le diff gonfle — c'est le bénéfice recherché, pas
un défaut : un champ retiré se lit en revue plutôt que dans un journal de build.

Rien à formater ni à corriger ensuite : `src/generated/` est hors du périmètre de Prettier comme
d'ESLint.

## `src/generated/` ne s'édite pas

L'interdiction est portée par trois mécanismes, chacun motivé sur place :

| Où                                 | Ce qui est posé                                                  |
| ---------------------------------- | ---------------------------------------------------------------- |
| `eslint.config.mjs`                | `**/generated/**` exclu du lint, à la racine et dans le package. |
| `.prettierignore`                  | `**/generated/` — le reformater serait perdu.                    |
| `.github/workflows/api-client.yml` | La CI rejoue la chaîne et échoue sur tout diff.                  |

Une édition manuelle ne produit donc pas d'avertissement : elle est **perdue** à la régénération
suivante, et la CI la signale par un diff. Ce qu'il faut faire à la place, dans l'ordre :

1. **Corriger le backend, puis régénérer.** C'est presque toujours la réponse : si le client est
   faux, c'est que le contrat l'est.
2. **Étendre le mutator**, quand le besoin est transversal — un en-tête, une règle de nouvelle
   tentative, un traitement d'erreur.
3. **Écrire son propre code à côté** du dossier généré, jamais dedans.

## Consommer un hook

Le nom du hook dérive de l'`operation_id` de la route : `check_readiness` côté Python devient
`useCheckReadiness` côté TypeScript.

```tsx
'use client';

import { useCheckReadiness } from '@repo/api-client/api/health';

export function ServiceStatus() {
  const { data, isPending, error } = useCheckReadiness();

  if (isPending) return <p>Vérification…</p>;
  if (error) return <p>Service injoignable.</p>;

  // `data.status` et `data.components.postgres` sont typés par le contrat.
  return <p>{data.status === 'ready' ? 'Service prêt' : 'Service dégradé'}</p>;
}
```

Le schéma Zod du même contrat s'importe depuis `@repo/api-client/zod/health`, pour valider une saisie
avec les contraintes exactes du backend.

:::note Un fournisseur est nécessaire, et une portée aussi
Un hook de requête exige un `QueryClientProvider` au-dessus de lui : c'est le `QueryProvider` de
**FRONT-04**, dans ce même package, monté dans les trois layouts.

L'exemple ci-dessus laisse le hook se ranger sous la clé nue d'Orval — `['/health/ready']` —, ce qui
ne convient qu'à une ressource **publique**. Dès qu'une réponse dépend du groupe actif, la clé doit
porter sa portée, sans quoi une bascule de groupe affiche les données de la structure précédente.
Tout est sur [Données côté client](./donnees-cote-client.md) et dans
l'[ADR-0027](../adr/0027-portee-des-cles-de-cache.md).
:::

## Le mutator et ses points d'extension

Le code généré ne sait rien de l'environnement ni de l'authentification : il construit une URL et un
corps, puis délègue à `customFetch`. Tout ce que les trois applications partagent d'un appel HTTP
tient donc dans un seul fichier.

Ce qu'il fait aujourd'hui :

- **La base URL selon le contexte d'exécution.** `NEXT_PUBLIC_API_URL` dans le navigateur,
  `API_INTERNAL_URL` côté serveur Next — en conteneur, `http://api:8000`. Un composant serveur qui
  appellerait `localhost` n'atteindrait que son propre conteneur. Rappel du gabarit d'environnement :
  Next remplace `NEXT_PUBLIC_API_URL` **au build**, pas à l'exécution.
- **La normalisation des erreurs.** Toute réponse en échec devient une `ApiError` portant `status`,
  `code`, `details` et `requestId`, que la réponse ait respecté le format unique
  ([ADR-0014](../adr/0014-traduction-des-erreurs-a-la-bordure.md)) ou non — une passerelle en panne
  et un préflight CORS refusé ne parlent pas ce format, et l'appelant n'a pas à le savoir.
- **L'identifiant de corrélation**, lu de l'en-tête `X-Request-ID` et attaché à l'erreur : c'est lui
  qu'on cite dans un rapport d'incident pour retrouver la requête dans les journaux.

Ce qu'il **prévoit sans le faire** — deux crochets laissés ouverts, pour que les tickets suivants
remplacent une fonction au lieu de récrire le mutator :

- **Le jeton d'authentification** et l'en-tête `X-Clinic-Id`
  ([ADR-0012](../adr/0012-perimetre-de-requete.md)), posés par `setRequestIdentityProvider` — c'est
  **FRONT-07** qui branchera la vraie source.
- Le fournisseur retient **une fonction, jamais un jeton**. Sur le serveur Next, ce module est
  partagé par toutes les requêtes du processus : y ranger une valeur ferait fuir la session d'un
  utilisateur vers la requête d'un autre.

## Le nommage vient du backend

Deux conventions du service décident des noms publics du client : l'**étiquette** OpenAPI donne le
fichier, l'**`operation_id`** donne le nom du hook.

Conséquence directe, et c'est la raison d'être de cette section : renommer l'un ou l'autre **après**
SHARED-03 est une rupture de contrat sur trois applications à la fois. Cela se traite comme une
migration de schéma — délibérément, et dans la même pull request que la régénération. Le détail des
conventions est sur [Surface HTTP](../backend/surface-http.md).

## Vérifier sans lancer d'application

Quatre contrôles, du moins cher au plus complet :

```bash
pnpm typecheck
```

Le client généré compile sous les options strictes du socle partagé, et les trois applications le
résolvent.

```bash
make generate-api-check
```

Rejoue la chaîne entière et échoue si le résultat diffère de ce qui est committé — **une sortie vide
est la preuve** que le client correspond au contrat. C'est exactement ce que fait la CI, message
d'erreur compris.

```bash
pnpm --filter @repo/api-client test
```

La portée des clés de cache, **hors ligne** : ni pile, ni compilation, ni dépendance. C'est la seule
preuve mécanique de la frontière de tenance côté navigateur tant que QA-02 n'a pas posé de runner —
détaillée sur [Données côté client](./donnees-cote-client.md#vérifier-sans-lancer-dapplication).

```bash
make verify-api-client
```

Appelle réellement l'API avec les fonctions du client généré et vérifie la forme des données
rendues, ainsi que la normalisation d'une erreur. Depuis FRONT-04, la même passe joue aussi la
couche de cache posée au-dessus — politique de réessai, appariement par préfixe, routage des 401.
Exige la pile démarrée (`make dev`) : c'est le vrai service qui est interrogé, pas un double.

## Ce qui viendra

- **FRONT-05** — le patron de formulaire, qui réutilisera les schémas Zod de ce package.
- **FRONT-07** — le flux d'authentification : jeton dans le mutator, rafraîchissement sur 401.
- **QA-02** — l'outillage de test frontend, qui rejouera les hooks eux-mêmes et remplacera le
  montage de compilation jetable de `make verify-api-client`.

Les écarts assumés avec le ticket SHARED-03 sont consignés au
[registre des écarts](../ecarts/shared.md#écarts-assumés-avec-le-ticket-shared-03).
