---
title: 'ADR-0028 — Une application frontend se découpe par domaine, et sa frontière est tenue par ESLint'
description: "Le code applicatif d'un frontend se range par sujet et non par type de fichier ; la surface publique d'une feature est la racine de son dossier, et les zones qui l'imposent sont engendrées depuis le disque plutôt qu'écrites à la main."
---

# ADR-0028 — Une application frontend se découpe par domaine, et sa frontière est tenue par ESLint

| Statut      | Date       | Tickets                                                              |
| ----------- | ---------- | -------------------------------------------------------------------- |
| **Accepté** | 2026-08-27 | FRONT-09, FRONT-07 (à venir), FRONT-11 (à venir), FRONT-19 (à venir) |

## Contexte

Décision rendue par FRONT-09, qui range le code des trois applications Next.

Le backend a tranché la même question deux fois. [ADR-0003](./0003-monolithe-modulaire.md) a
découpé le service en modules métier plutôt qu'en couches techniques globales, et BACK-04 a écarté
un `domain/entities/` plat au motif qu'il regroupe par **type de fichier** ce qui devrait se
regrouper par **sujet**. BACK-04b a ensuite rendu ces frontières mécaniques avec cinq contrats
`import-linter`, en posant la phrase qui commande tout le reste : un garde-fou qui ne tourne que
sur le poste de celui qui écrit le code n'est pas un garde-fou.

Côté frontend, un dossier `components/` plat est exactement le `domain/entities/` plat : il
accumule le tableau des cliniques, la barre latérale, le formulaire de connexion et la sonde de
santé au seul motif que ce sont tous des composants. Au moment de la décision, les trois
applications totalisent six fichiers de code applicatif — c'est peu, et c'est précisément pourquoi
la question se tranche maintenant : FRONT-14, FRONT-19, FRONT-20 et FRONT-21 déclarent tous écrire
dans `features/organization/` ou `features/identity/`, et poser la convention après eux coûterait
un déplacement de plusieurs dizaines de fichiers.

Trois questions restaient ouvertes, et ce sont elles que cet ADR tranche : **où passe la
frontière**, **par quoi se déclare la surface publique d'un domaine**, et **comment la frontière
est tenue** — le dépôt refusant les barils, et `import-x/no-restricted-paths` ne sachant pas
exprimer un joker équivalent au `containers = ["app.modules.*"]` des contrats backend.

## Décision

**Une application se découpe en quatre espaces, et les dépendances entre eux vont dans un seul
sens.**

```
app/         routage Next : des pages qui composent, jamais de la logique
features/    les sujets metier, un dossier par sujet
components/  le shell transverse : layout, navigation, fil d'Ariane
lib/         la plomberie transverse : session, configuration
```

`app/` peut lire tout le monde ; une feature peut lire le transverse ; le transverse ne connaît
aucune feature ; personne ne remonte vers `app/`. Ce sont les mêmes flèches que le contrat 5 de
BACK-04b — `main > modules > shared > core` — sur les espaces d'une application.

**Le troisième espace n'est pas une liste de deux dossiers, c'est un complément** : tout dossier de
premier niveau qui n'est ni `app/` ni `features/` est transverse, et le garde-fou le découvre. La
première rédaction nommait `components` et `lib` ; un `hooks/` créé demain n'aurait été gardé par
rien — mesuré en revue. C'est l'`exhaustive = true` des contrats de couches du backend, transposé.

**Une feature porte le nom du module backend correspondant.** `identity` et non `auth` : `auth`
n'existe côté API que comme préfixe d'URL, le module s'appelle `identity`, et c'est le nom du
fichier qu'Orval produit en mode `tags-split` ([ADR-0007](./0007-client-api-genere-orval.md)). Une
feature qui s'appellerait autrement que le dossier généré qu'elle consomme rétablirait une couche
de traduction entre les deux côtés du contrat.

**La surface publique d'une feature, ce sont les modules posés à la racine de son dossier ; tout
sous-dossier lui appartient en propre.** Il n'y a donc rien à réexporter, et aucun baril à écrire.
C'est l'idiome déjà retenu par le dépôt pour ses packages : `@repo/ui` expose `./components/*` et
`@repo/api-client` n'a aucun export racine — la surface se déclare par un **motif de chemin**, pas
par un fichier de réexport.

**Les zones qui imposent tout cela sont engendrées depuis le disque, jamais écrites à la main.**
`packages/config-eslint/boundaries.js` développe `frontend/*/app/` puis
`frontend/*/features/*/` et en dérive trois familles de zones par application, que le preset `next`
pose en `error`. Une feature créée demain est gardée sans qu'une ligne de configuration soit
ajoutée — c'est ce que le joker `app.modules.*` fait pour les contrats backend, et c'est la seule
propriété qui empêche un garde-fou de s'éteindre en silence.

**Une entorse s'écrit en dérogation motivée, jamais en éteignant la règle** —
`// eslint-disable-next-line import-x/no-restricted-paths -- MOTIF : … REVUE : AAAA-MM-JJ`, même
discipline que le `ignore_imports` d'un contrat `import-linter`.

**Le garde-fou est prouvé, et la preuve tourne en intégration continue.**
`packages/config-eslint/scripts/verify-boundaries.js` joue onze contrôles — dont les violations sur
le code réel, avec la configuration que les applications chargent vraiment — et le workflow
`ci-frontend.yml` l'exécute sur chaque pull request. Il est créé par ce ticket alors que QA-02 n'est
pas livré, exactement comme BACK-04b avait créé `ci-backend.yml` avant QA-01.

## Alternatives écartées

### Garder `components/` plat et s'en remettre à la revue

C'était l'état livré par FRONT-01 à FRONT-03, et il tenait sans peine à six fichiers. Écartée : la
revue n'attrape un mauvais rangement que si quelqu'un le cherche, et les quatre tickets d'écran à
venir écrivent chacun dix à vingt fichiers. Un rangement qui ne survit pas à sa propre croissance
n'est pas un rangement.

### Un baril `features/<nom>/index.ts` par feature

Le pendant littéral du `__init__.py` et de son `__all__` côté backend, et la façon la plus
répandue de déclarer une surface publique. Écartée pour trois raisons : le dépôt n'a aucun baril et
l'a décidé explicitement en SHARED-03 ; `import-x/no-cycle` est en `error`, et un baril rend l'ordre
d'initialisation dépendant du point d'entrée ; enfin `proxy.ts` n'a besoin que d'**un** module de la
feature `identity`, et un baril l'obligerait à passer par un fichier qui réexporte aussi
`require-role.ts` et ses API serveur — un couplage écrit, que rien n'oblige à payer.

Cette dernière raison a d'abord été écrite autrement, et il faut le dire parce que la formulation
circule encore ailleurs dans le dépôt : « `proxy.ts` s'exécute dans le runtime Edge, où
`next/headers` n'existe pas ». **C'est faux depuis Next 16**, qui a renommé la convention en
`proxy.ts` et l'exécute en runtime `nodejs` — le manifeste de build le déclare noir sur blanc
(`.next/server/functions-config-manifest.json`, `"runtime": "nodejs"`). La conclusion ne bouge pas ;
le motif, si.

### L'indépendance totale entre features, comme le contrat 3 du backend

Plus strict, et gratuit aujourd'hui puisque aucune feature n'en importe une autre. Écartée : le
ticket autorise explicitement le passage par ce qu'une feature exporte, et les écrans à venir en
auront besoin — un formulaire de rendez-vous affichera la fiche de la clinique. Côté backend, un
besoin partagé descend dans `shared` ; côté client, le forcer dans `lib/` fabriquerait une couche
transverse artificielle pour du vocabulaire métier, ce que
[ADR-0026](./0026-fiche-technique-praticien.md) refuse déjà en sens inverse.

### Une liste de features tenue à la main, dans chaque `eslint.config.mjs`

C'est la portée littérale du ticket, et c'est ce que `no-restricted-paths` invite à écrire —
« tout le monde sauf moi » ne s'exprime pas sans nommer les sœurs. Écartée deux fois : trois copies
du même arbitrage contredisent le mot d'ordre du ticket lui-même (« trois applications, une seule
convention ») ; et une liste à tenir se périme, ce que BACK-04b avait déjà refusé en préférant un
joker à l'énumération des modules. Le développement depuis le disque coûte trente lignes et
supprime les deux problèmes.

### `dependency-cruiser` ou `eslint-plugin-boundaries`

Deux outils dédiés, plus expressifs que `no-restricted-paths` — le second sait raisonner en
« types d'éléments » et exprimerait l'indépendance sans énumérer. Écartée : ce serait une
dépendance de plus et un second graphe d'imports à tenir, là où `eslint-plugin-import-x` est déjà
installé, déjà configuré avec le résolveur TypeScript, et déjà exécuté sur tout le dépôt. Le prix
de ce refus est écrit ci-dessous.

### Se contenter des deux zones que le ticket nomme

Le ticket demande l'interdiction de l'import croisé entre features et de l'import de `features/`
depuis `components/`. Écartée telle quelle, pour une raison qu'il faut énoncer exactement :
`no-restricted-paths` ne voit **qu'une arête à la fois**, là où un contrat `import-linter` attrape
les chaînes indirectes. La première famille, elle, ne se contourne pas — son `target` nomme déjà
`app/`, donc une page ne peut pas davantage atteindre l'intérieur d'une feature. **C'est la
deuxième qui se contournerait en deux sauts** : sans la troisième famille, `components/` pourrait
importer une page, et une page importe légitimement une feature — le transverse dépendrait alors
d'un domaine par transitivité, ce que la deuxième famille existe précisément pour empêcher. S'y
ajoute la raison de fond : `app/` est la racine de composition, et une racine ne se consomme pas.

## Conséquences

**Ce que cela donne.** Le rangement d'un fichier neuf se décide en une question — porte-t-il du
métier ? — et la réponse est vérifiée par le lint, pas par la revue. La correspondance entre une
feature et un module backend devient visible des deux côtés du contrat. Le déplacement a produit sa
première leçon dès le jour de sa pose : `lib/session.ts` ne pouvait pas descendre dans
`features/identity/`, parce que la barre latérale lit son type `Role` et que le transverse n'a pas
le droit d'importer une feature. C'est la frontière qui a désigné la place du fichier, et non
l'inverse.

**Ce que cela coûte.** Trois familles de zones là où le ticket en demandait deux, et une
énumération des sœurs que le backend n'a pas à écrire. Une arborescence de démonstration de six
fichiers dans `packages/config-eslint/fixtures/`, sans laquelle la privauté de l'intérieur d'une
feature ne serait prouvée par rien — la règle ne se déclenchant que sur un import qui **se résout
réellement**, et aucune feature n'ayant encore de sous-dossier. La configuration étant développée
au chargement, un dossier de feature créé pendant qu'un serveur ESLint tourne n'est vu qu'après son
redémarrage.

**Ce que le garde-fou ne verra jamais.** Un composant chargé de métier déclaré « transverse » et
rangé dans `components/` : aucun outil ne juge de la présence de métier, et ce critère-là reste
affaire de revue. Une logique recopiée d'une feature à l'autre plutôt qu'importée. Une frontière
franchie par un `fetch` plutôt que par un `import`.

**Ce qui reste ouvert.** `lib/session.ts` monte dans `@repo/api-client` avec FRONT-07, et la feature
`identity` retrouvera alors son vocabulaire. La deuxième feature de `frontend-professional` et la
première de `frontend-individual` armeront chez elles la famille de zones qui n'a aujourd'hui
qu'une seule feature à garder.

## Références

- `packages/config-eslint/boundaries.js` — le développement des zones depuis le disque.
- `packages/config-eslint/scripts/verify-boundaries.js` — les neuf contrôles, et les deux façons de
  passer à vide qu'ils refusent.
- `.github/workflows/ci-frontend.yml` — le job qui les exécute sur chaque pull request.
- [La structure des applications](../frontend/structure-par-domaine.md) — la page qui explique le
  rangement au quotidien.
- [ADR-0003](./0003-monolithe-modulaire.md) — la même décision, côté serveur.
- [ADR-0007](./0007-client-api-genere-orval.md) — le mode `tags-split` dont les features reprennent
  les noms.
