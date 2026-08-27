---
title: Structure par domaine
description: "Comment le code d'une application frontend se range par sujet, où passe la frontière entre features, et la règle ESLint qui la tient."
---

# Structure par domaine

Le code applicatif d'un frontend se range par **sujet**, pas par type de fichier. C'est la
transposition de ce que [ADR-0003](../adr/0003-monolithe-modulaire.md) a décidé pour le service
d'API, et la décision est consignée en
[ADR-0028](../adr/0028-frontieres-de-features.md).

## Les quatre espaces d'une application

```text
frontend/frontend-admin/
  app/                              routage Next : des pages qui composent
    (protected)/cliniques/page.tsx
  features/                         les sujets metier
    identity/require-role.ts
    organization/clinics-table.tsx
  components/                       le shell transverse : navigation, fil d'Ariane
  lib/                              la plomberie transverse : session
  proxy.ts
```

Les dépendances vont dans un seul sens :

| Espace         | Peut lire                                     | Ne peut pas lire              |
| -------------- | --------------------------------------------- | ----------------------------- |
| `app/`         | tout, sauf ce que dit la colonne de droite    | l'**intérieur** d'une feature |
| `features/`    | le transverse, la surface des autres features | leur **intérieur**, et `app/` |
| **transverse** | le reste du transverse                        | `features/`, `app/`           |

Ce sont les flèches du contrat 5 d'`import-linter` — `main > modules > shared > core` — appliquées
aux espaces d'une application. Elles ne se relisent pas : elles échouent au lint.

**Le transverse n'est pas une liste de deux dossiers, c'est un complément**, et c'est une correction
de revue : tout dossier de premier niveau qui n'est ni `app/` ni `features/` en fait partie —
`components/`, `lib/`, et le `hooks/` que quelqu'un créera un jour. La première version nommait
`components` et `lib` en dur ; mesuré, trois imports interdits passaient depuis un `hooks/`. Le
monde est fermé, comme l'`exhaustive = true` des contrats de couches du backend.

## Où va ce fichier ?

| Le fichier…                                                        | va dans             |
| ------------------------------------------------------------------ | ------------------- |
| ne porte aucun métier et sert deux applications                    | `@repo/ui`          |
| porte du métier — une clinique, un rendez-vous, un rôle            | `features/<sujet>/` |
| décrit **cette** application : navigation, layout, fil d'Ariane    | `components/`       |
| est de la configuration ou du vocabulaire lu par plusieurs espaces | `lib/`              |
| est une route, un layout ou un fichier de métadonnées Next         | `app/`              |

Une page de `app/` **compose** : elle assemble des features et déclare ses métadonnées. Dès qu'elle
calcule, le calcul appartient à une feature.

## Le nom d'une feature est celui du module backend

`identity`, `organization`, `scheduling`, `medical_records`, `notifications` : ce sont les cinq
modules de `backend/api/src/app/modules/`. Une feature en reprend le nom quand la correspondance
existe, parce que c'est aussi le nom du dossier qu'Orval produit en mode `tags-split`
([Le client d'API généré](./client-api-genere.md)) : `features/organization/` consomme
`@repo/api-client/api/organization`, et la frontière métier devient visible des deux côtés.

**Pas `auth`.** Le module s'appelle `identity` ; `auth` n'est qu'un préfixe d'URL. Une feature
nommée d'après l'URL rétablirait une traduction entre le client et le contrat.

État actuel : `identity` et `organization` dans `frontend-admin`, `health` dans
`frontend-professional`. Cette dernière est un cas particulier assumé — `health` est une étiquette
OpenAPI et non un module métier, mais c'est le seul fichier qu'Orval produise aujourd'hui, et le
composant qui le consomme n'avait pas d'autre nom juste.

## La surface publique d'une feature

> **Les modules posés à la racine du dossier sont publics. Tout sous-dossier est l'intérieur de la
> feature, et personne d'autre qu'elle n'y entre.**

```text
features/identity/
  require-role.ts        <- surface publique : @/features/identity/require-role
  components/            <- interieur, ferme
  hooks/                 <- interieur, ferme
```

Aucun baril, aucun `index.ts` : la surface se déclare par un motif de chemin, comme le
`"./components/*"` de `@repo/ui`. Ce n'est pas qu'une question de goût — `proxy.ts` n'a besoin que
d'**un** module de la feature `identity`, et un baril l'obligerait à passer par un fichier qui
réexporte aussi `require-role.ts` et ses API serveur.

:::warning Le proxy ne tourne pas en runtime Edge

On lit encore, ici et là dans le dépôt, que `proxy.ts` s'exécute en runtime **Edge** et que
`next/headers` n'y existe pas. C'était vrai de `middleware.ts` ; ce ne l'est plus depuis que Next 16
a renommé la convention. Le manifeste de build le déclare : `.next/server/functions-config-manifest.json`
porte `"runtime": "nodejs"` pour `/_middleware`. L'argument reste bon — le proxy n'a aucune raison de
tirer les API serveur d'une feature — mais ce n'est pas le runtime qui l'interdit.

:::

## Ajouter une feature

1. Créer `frontend/<application>/features/<sujet>/` et y poser le premier fichier.
2. Rien d'autre. Les zones du garde-fou sont **développées depuis le disque** à chaque chargement de
   la configuration : la feature est gardée dès son premier fichier, et ses sœurs sont gardées
   contre elle.
3. Redémarrer le serveur ESLint de l'éditeur, qui a lu la configuration une fois pour toutes.

## Le garde-fou

La règle est `import-x/no-restricted-paths`, posée en `error` par le preset `next`
([Configurations partagées](./configurations-partagees.md)) et engendrée par
`packages/config-eslint/boundaries.js`. Trois familles de zones, par application :

| Famille                                    | Ce qu'elle interdit                                             |
| ------------------------------------------ | --------------------------------------------------------------- |
| 1. L'intérieur d'une feature est privé     | Atteindre `features/x/<sous-dossier>/…` depuis ailleurs que `x` |
| 2. Le transverse ne connaît aucune feature | `components/` ou `lib/` qui importe `features/…`                |
| 3. Personne ne remonte vers `app/`         | Une feature, `components/` ou `lib/` qui importe une page       |

La troisième n'est pas décorative, mais elle ne protège pas ce qu'on croit. La première ne se
contourne pas : son `target` nomme déjà `app/`, donc une page ne peut pas atteindre l'intérieur
d'une feature. **C'est la deuxième que la troisième referme** : `no-restricted-paths` ne voit qu'une
arête à la fois, et sans elle `components/` importerait une page, qui importe légitimement une
feature — le transverse dépendrait d'un domaine en deux sauts. S'y ajoute la raison de fond :
`app/` est la racine de composition, et une racine ne se consomme pas.

### Lire un échec

```text
frontend/frontend-admin/components/navigation.ts
  1:29  error  Unexpected path "@/features/identity/require-role" imported in restricted zone.
               un module transverse (components, lib) ne depend d'aucune feature. Deplacer ce
               code dans la feature qui l'utilise, ou le rendre generique (FRONT-09)
               import-x/no-restricted-paths
```

La réponse est presque toujours de **déplacer du code**, jamais de réécrire l'import. Ici, deux
issues : le composant appartient à la feature, ou bien ce qu'il lui emprunte est du vocabulaire
transverse et descend dans `lib/`. C'est exactement l'arbitrage qu'a demandé `lib/session.ts` le
jour de la pose du garde-fou — la barre latérale lit son type `Role`, donc ce fichier n'est pas
l'intérieur d'un domaine.

### Écrire une entorse

Dans la ligne, avec son motif et sa date de revue — jamais en éteignant la règle :

```ts
// eslint-disable-next-line import-x/no-restricted-paths -- MOTIF : <pourquoi c'est tolerable>
//                                                          REVUE : 2027-03-01
```

Même discipline que le `ignore_imports` d'un contrat `import-linter`
([Qualité et typage](../backend/qualite-et-typage.md)).

## Le garde-fou est lui-même vérifié

`packages/config-eslint/scripts/verify-boundaries.js` — lancé par `pnpm test`, par
`make test-front` et par le workflow `ci-frontend.yml` — joue onze contrôles. Les violations
tournent sur le **code réel**, avec la configuration que les applications chargent vraiment :
`lintText` reçoit le chemin d'un fichier existant et un contenu en mémoire, sans rien écrire sur le
disque.

Retirer une partie du garde-fou fait tomber des contrôles précis, et c'est mesuré :

| Ce qu'on retire de `boundaries.js`                        | Contrôles qui tombent |
| --------------------------------------------------------- | --------------------- |
| Toutes les zones                                          | 8 sur 11              |
| La famille 1 (intérieur privé)                            | 3                     |
| La famille 2 (transverse)                                 | 4                     |
| La famille 3 (personne ne remonte vers `app/`)            | 1                     |
| La découverte du transverse, figée sur `components`/`lib` | 1                     |

Deux façons de passer **à vide** sont refusées explicitement, parce qu'elles rendraient le verdict
mensonger plutôt que faux :

- **Un import qui ne se résout pas.** `no-restricted-paths` appelle le résolveur et sort si l'import
  est introuvable : un contrôle négatif serait alors vrai sans que rien n'ait été examiné. Chaque
  contrôle exige donc aussi zéro `import-x/no-unresolved`. C'est ce qui a fait apparaître un piège
  réel — le résolveur TypeScript retrouve le `tsconfig` d'une application à partir du **répertoire
  de travail**, si bien qu'un programme lancé depuis `packages/config-eslint` ne mappait plus un
  seul `@/*`.
- **Un fichier qui ne parse pas.** Le socle est type-aware : un fichier hors `tsconfig` sort en
  erreur de parsing et n'est pas analysé du tout. Chaque contrôle exige zéro message `fatal`.

Une **arborescence de démonstration** de six fichiers vit dans `packages/config-eslint/fixtures/`.
Elle ne sert qu'à la famille 1 : aucune feature réelle n'ayant encore de sous-dossier, il n'existe
aucun intérieur à viser, donc aucun import à résoudre, donc rien à prouver sur le vrai dépôt.

## Ce que le garde-fou ne voit pas

- Un composant chargé de métier déclaré « transverse » et rangé dans `components/`. Aucun outil ne
  juge de la présence de métier : ce critère-là reste affaire de revue.
- Une logique recopiée d'une feature à l'autre plutôt qu'importée.
- Une frontière franchie par un appel réseau plutôt que par un `import`.
- `typeof import('@/features/…')` en **position de type** : `no-restricted-paths` ne visite pas les
  `TSImportType`. Le lint échoue quand même, mais grâce à
  `@typescript-eslint/consistent-type-imports`, qui refuse cette forme — un filet tenu par une autre
  règle, qu'un assouplissement futur rouvrirait.
