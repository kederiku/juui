---
title: 'ADR-0027 — Une clé de cache déclare sa portée : publique, groupe, clinique'
description: "Le cache du navigateur prolonge la frontière de tenance : chaque clé de requête porte en tête la portée à laquelle sa réponse appartient, le groupe actif avant l'opération, et le typage refuse de composer une clé de groupe sans groupe."
---

# ADR-0027 — Une clé de cache déclare sa portée : publique, groupe, clinique

| Statut      | Date       | Tickets                                          |
| ----------- | ---------- | ------------------------------------------------ |
| **Accepté** | 2026-08-27 | FRONT-04, FRONT-07 (à venir), FRONT-08 (à venir) |

## Contexte

Décision rendue par FRONT-04, qui pose la couche de récupération de données des trois applications.

L'[ADR-0004](./0004-tenance-par-groupe.md) fait du groupe de cliniques la frontière d'isolation, et
l'[ADR-0012](./0012-perimetre-de-requete.md) la fait voyager dans le claim `active_group_id` du
jeton : le serveur filtre donc chaque réponse sur le groupe actif, et **la même URL rend des données
différentes selon le jeton présenté**. Cette moitié-là est solide, testée, et n'est pas en cause.

Le navigateur, lui, conserve ces réponses. TanStack Query les range dans un cache mémoire indexé par
une **clé de requête**, et le client généré par Orval en exporte une par opération —
`getCheckReadinessQueryKey()` rend `['/health/ready']`. Cette clé identifie une **route**, et rien
d'autre. Elle ne sait rien du jeton qui a produit la réponse.

Un vétérinaire remplaçant appartient à plusieurs groupes ([ADR-0005](./0005-appartenance-datee.md))
et bascule de l'un à l'autre. S'en tenir à la clé d'Orval, c'est ranger sous la même entrée la
réponse du groupe A et celle du groupe B : après la bascule, l'écran affiche les données de la
structure précédente pendant tout le `staleTime`, sans un appel réseau, sans une erreur, sans une
trace. Sur des données médicales entre deux groupes distincts, ce n'est pas un défaut d'affichage.

La question n'était donc pas s'il fallait porter la portée dans la clé, mais **où**, **laquelle**, et
**comment empêcher qu'on l'oublie**.

## Décision

**Une clé de cache commence par sa portée, et la portée précède l'opération.** Trois familles, plus
le préfixe qui recouvre les deux dernières :

| Fabrique                   | Clé                                             | Ce qu'elle désigne                                   |
| -------------------------- | ----------------------------------------------- | ---------------------------------------------------- |
| `publicQueryKey(k)`        | `['public', ...k]`                              | Lisible sans jeton : sondes, vitrine publique.       |
| `groupQueryKey(scope, k)`  | `['tenant', groupId, ...k]`                     | Les données du groupe actif.                         |
| `clinicQueryKey(scope, k)` | `['tenant', groupId, 'clinic', clinicId, ...k]` | Les données d'une clinique du groupe.                |
| `tenantScopeKey(scope)`    | `['tenant', groupId]`                           | Le préfixe de purge — les deux familles précédentes. |

**L'ordre des segments est le contrat, et il n'est pas négociable.** TanStack Query n'apparie ses
clés que **par préfixe** : du plus général au plus précis est la seule disposition où
`tenantScopeKey(scope)` désigne « tout ce groupe, et lui seul ». L'inverse — l'opération d'abord, le
groupe ensuite — rendrait la purge d'un groupe muette : mesuré sur un vrai `QueryCache`,
`removeQueries` réussit, ne supprime rien, et ne lève pas.

**La clé d'Orval est reprise intacte, et en queue** — paramètres de requête compris, qu'Orval range
déjà dans la sienne. La fabrique préfixe, elle ne réécrit pas. C'est la condition que
`orval.config.ts` avait posée en activant `shouldExportQueryKey` : recopier un chemin à la main
rendrait l'invalidation silencieusement fausse le jour où le backend renomme une route, ce que
l'[ADR-0007](./0007-client-api-genere-orval.md) existe pour rendre visible.

**Le groupe est un argument obligatoire, et il est typé `GroupId`, pas `string`.** `groupQueryKey`
ne compile pas sans portée ; un `GroupId` ne s'obtient que par `asGroupId`, qui refuse la chaîne
vide ou blanche **et refuse une chaîne déjà marquée** — un `ClinicId` ne peut donc pas être
re-marqué en groupe. Un identifiant de clinique ou de compte ne peut pas prendre la place du groupe
par simple compatibilité de `string` : la clé obtenue aurait été valide, stable, et fausse.

**La clinique entre dans la clé, mais seulement pour les ressources de niveau clinique.** L'ADR-0012
la fait basculer côté client sans réémission de jeton, et le mutator l'envoie par requête en
`X-Clinic-Id` : dans un même onglet, changer de clinique ne change ni la route ni la clé d'Orval, et
la seconde lirait l'entrée de la première. À l'inverse, la mettre dans **toutes** les clés de tenance
dupliquerait le cache d'une donnée qui n'en dépend pas — la liste des cliniques du groupe — et
l'invalidation après mutation manquerait les entrées sœurs. C'est la **ressource** qui décide, pas le
site d'appel.

**Aucun segment ne vaut jamais `undefined`** — l'empreinte de TanStack est un `JSON.stringify`, où
`{ x: undefined }` et `{}` produisent la même chaîne, donc la même entrée. Les clés d'aujourd'hui
sont plates et ne portent ni objet ni segment optionnel ; le jour où l'une en portera, ce sera `null`
explicite.

**La bascule de groupe annule, puis purge par ce préfixe.** Le groupe visé est celui qu'on **quitte**,
à capturer avant la réémission du jeton :

```ts
await queryClient.cancelQueries({ queryKey: tenantScopeKey(precedent) });
queryClient.removeQueries({ queryKey: tenantScopeKey(precedent) });
```

Sans l'annulation, une réponse du groupe précédent qui arrive après la purge recrée son entrée.
FRONT-08 n'a que ces deux lignes à écrire.

## Alternatives écartées

### S'en tenir à la clé d'Orval

Zéro code, et c'est ce que fait le client généré si on ne fait rien. Écartée : c'est le bug décrit
en contexte, et il est silencieux — ni erreur de compilation, ni appel réseau, ni trace. Le premier
symptôme est un dossier médical affiché dans la mauvaise structure.

### Le groupe en suffixe, après l'opération

Sépare bien les entrées, et se lit mieux dans les Devtools — « toutes les entrées de `/pets` sont
groupées ». Écartée après lecture du code de `query-core` et mesure : l'appariement est un préfixe
positionnel, donc « tout ce groupe » cesserait d'être exprimable, et le seul préfixe qui attraperait
encore quelque chose serait celui de la route — qui emporte **tous les groupes à la fois**.

### La clinique hors de la clé

Le ticket ne la demandait pas — seul le groupe y figure. Écartée : c'est la même panne un cran plus
bas, à l'intérieur d'un périmètre pourtant autorisé, et l'ADR-0012 fait de la bascule de clinique un
geste quotidien.

### Une famille `account`, livrée d'avance

Envisagée, puis retirée après revue. Une clé de compte n'isole rien si elle ne porte pas
**l'identifiant du compte** — sans lui, le profil d'Alice reste servi à Bob après une reconnexion
dans le même onglet, mesuré. Or rien ne sait dire quel compte est connecté avant FRONT-07. Livrer la
famille sans son discriminant, c'était livrer la seule des quatre dont la justesse reposait
entièrement sur un ticket qui n'existe pas.

### Un contexte React `useRequestScope()` fournissant la portée

Chaque site d'appel écrirait `groupQueryKey(useRequestScope(), k)` sans avoir à connaître le groupe.
Écartée pour deux raisons cumulées : personne ne sait dire quel est le groupe actif avant FRONT-07,
si bien qu'un contexte livré ici rendrait `null` — c'est-à-dire une clé de tenance **sans groupe**,
exactement ce que cet ADR interdit ; et un contexte rendrait la fabrique impossible à exécuter hors
de React, donc impossible à prouver tant que le dépôt n'a pas de runner de test frontend (QA-02).

### Un sceau vérifié à l'exécution par `queryKeyHashFn`

C'est le seul point de passage obligé de **toute** clé — `useQuery`, `getQueryData`, `setQueryData`,
`prefetchQuery` y passent tous. Un contrôle posé là refuserait une clé qui n'est pas passée par la
fabrique, y compris celle d'un hook généré appelé directement. Envisagée sérieusement, puis écartée
pour ce ticket : elle transforme tout usage direct du client généré en plantage, alors qu'aucune
couche d'enveloppement n'existe encore (FRONT-09), et qu'elle contredirait l'exemple publié sur la
page du client d'API.

### Fermer `./api/*` dans la carte `exports` de `@repo/api-client`

La seule parade réellement mécanique : l'import direct d'un hook généré cesserait de résoudre, à la
compilation. Écartée : elle réécrit la surface publique de SHARED-03 et bloquerait aussi les
fonctions de requête, légitimes depuis un composant serveur.

## Conséquences

**Ce que cela donne.** Deux groupes ne partagent aucune entrée de cache **dès lors que la clé passe
par la fabrique** — et là, c'est le compilateur qui le tient : `groupQueryKey` ne se compose pas sans
`GroupId`. La purge de la bascule vise un préfixe unique, donc exact. L'invalidation après une
mutation reste prévisible sans qu'on ait à la documenter opération par opération : le préfixe se lit
dans la forme de la clé. Et la frontière de tenance se **voit** dans les Devtools, au lieu de se
déduire d'une absence.

**Ce que cela coûte.** On ne peut pas invalider « cette route, tous groupes confondus » — c'est
précisément ce qu'on ne veut jamais faire, mais la contrepartie est réelle. Chaque appel d'un hook
de tenance doit passer la portée, ce qui alourdit le site d'appel d'un argument — et n'a pas de forme
prévue tant que la session charge encore, ce qui est le sujet de FRONT-07. La marque `DataTag`
qu'Orval attache à sa clé **ne survit pas à l'enveloppement** : `getQueryData(publicQueryKey(k))` rend
`unknown` là où `getQueryData(options.queryKey)` rendait le type de la réponse — ce n'est pas une
régression par rapport à la clé nue, qui rend `unknown` elle aussi, mais c'est un typage perdu que
FRONT-09 devra reprendre dans sa couche d'enveloppement.

Et surtout, **rien n'oblige mécaniquement à passer par la fabrique** : un hook généré appelé
directement se range encore sous la clé nue d'Orval, et une clé de portée peut être enfermée dans une
autre — `publicQueryKey(groupQueryKey(...))` compile — ce qui la rendrait invisible à la purge. Dans
les deux cas la donnée survit à la bascule. La convention est tenue par la revue, par la page
[Données côté client](../frontend/donnees-cote-client.md), et par la façon dont chaque enveloppement
sera écrit.

**Ce qui reste ouvert.** La source du groupe actif — le claim `active_group_id` lu du jeton —
appartient à FRONT-07 ; jusque-là, aucun écran n'a de portée de tenance à passer, et `asGroupId` ne
sera un vrai point de passage obligé que le jour où ce ticket en fera son unique porte d'entrée
depuis le jeton. La famille `account`, avec son discriminant, lui revient également. La purge à la
bascule appartient à FRONT-08. Et les deux parades mécaniques écartées ci-dessus restent sur la
table : le jour où une clé nue apparaîtra en revue, c'est le signal qu'il faut en poser une.

## Références

- `packages/api-client/src/query-keys.ts` — les portées, les types marqués, et l'invariant
  « aucun import de valeur » qui rend le fichier exécutable sans compilation.
- `packages/api-client/scripts/verify-query-keys.ts` — la preuve hors ligne de la bascule.
- `packages/api-client/scripts/verify.ts` — l'appariement par préfixe joué sur un vrai `QueryCache`.
- [ADR-0004](./0004-tenance-par-groupe.md) — la frontière que la clé transporte.
- [ADR-0012](./0012-perimetre-de-requete.md) — le groupe dans le jeton, la clinique dans l'en-tête.
