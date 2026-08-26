---
title: ADR-0019 — Le contrat OpenAPI est exporté dans un fichier versionné
description: Le schéma est produit hors serveur par un script Python et committé dans packages/api-client/openapi.json ; Orval lit ce fichier, jamais une URL, et une seule vérification tient les deux moitiés de la chaîne.
---

# ADR-0019 — Le contrat OpenAPI est exporté dans un fichier versionné

| Statut      | Date       | Tickets   |
| ----------- | ---------- | --------- |
| **Accepté** | 2026-08-26 | SHARED-03 |

## Contexte

L'[ADR-0007](./0007-client-api-genere-orval.md) décide qu'Orval génère le client des frontends et
que sa sortie est versionnée, la CI échouant sur toute régénération qui produit un diff. Elle ne dit
rien de la **provenance du schéma** — et SHARED-03, en l'appliquant, a découvert que cette question
n'est pas un détail d'outillage.

La voie évidente est l'URL : FastAPI sert son schéma sur `/openapi.json`. Trois faits l'écartent.
D'abord, cette route est **fermée en production**
([ADR-0011](./0011-routage-versionne-par-module.md)) : il n'existe aucun environnement déployé à
interroger. Ensuite, la vérification de CI n'a **aucun serveur** — la lancer supposerait de démarrer
PostgreSQL, Redis et l'API pour lire un document que le code contient déjà. Enfin, FastAPI sert son
schéma en JSON compact, sur une seule ligne : le diff que l'ADR-0007 veut rendre lisible en revue
serait précisément illisible.

Or le schéma n'a besoin d'aucune de ces ressources. `create_app().openapi()` le construit en
mémoire, sans lifespan, sans base et sans `.env` — le module `app.main` étant importable sans effet
de bord, ce que la docstring de son lifespan annonçait déjà « pour les futurs exports d'OpenAPI ».

## Décision

**Le schéma est exporté par `backend/api/scripts/export_openapi.py` vers
`packages/api-client/openapi.json`, qui est committé. Orval lit ce fichier, jamais une URL.**

- **Une forme canonique**, fixée dans le script : deux espaces d'indentation, accents en clair,
  clefs triées, saut de ligne final. La sérialisation est ainsi indépendante de l'ordre dans lequel
  FastAPI et Pydantic composent leurs dictionnaires, et le diff se lit ligne à ligne.
- **Le fichier vit avec ce qu'il produit**, et non avec ce qui le produit. Le contrat et sa
  traduction tiennent dans un seul chemin : la vérification se borne à
  `git diff -- packages/api-client`, et le workflow n'a qu'un dossier à surveiller.
- **Deux commandes, une seule obligatoire.** `make generate-api` réexporte puis régénère : c'est
  l'étape qui suit toute modification d'un contrat d'API. `pnpm generate:api` régénère depuis le
  contrat committé, sans `uv` sur le poste — de quoi corriger un réglage d'Orval ou le mutator sans
  installer la chaîne Python.
- **Une seule vérification tient les deux moitiés.** `make generate-api-check` rejoue la chaîne
  entière et échoue sur tout diff ; `.github/workflows/api-client.yml` ne lance rien d'autre, si
  bien qu'un échec de CI se reproduit à l'identique sur le poste.

## Alternatives écartées

### Lire `/openapi.json` sur un serveur démarré

La voie que la carte du ticket proposait en premier. Elle fait dépendre la génération d'un backend
qui tourne — donc de PostgreSQL, de Redis et d'un `.env` — pour un document que le code suffit à
produire. En CI, elle imposerait de démarrer la pile ; en production, elle ne fonctionne pas du tout,
la route étant fermée. Et le JSON servi sur une ligne unique aurait annulé le bénéfice même du
versionnement.

### Ne pas versionner le schéma, l'exporter à la volée

Symétrique de l'alternative « générer à la volée » déjà écartée par l'ADR-0007, et elle échoue pour
la même raison, en pire : sans fichier committé, `git diff` ne compare plus rien. La vérification
anti-dérive n'aurait plus de référence, et un changement de contrat cesserait d'être visible en
revue.

### Ranger le fichier dans `backend/api/`

Défendable — c'est le backend qui le produit. Mais il faudrait alors deux chemins à surveiller au
lieu d'un, Orval devrait traverser deux niveaux hors de son workspace, et le fichier entrerait dans
le contexte de build de l'image d'API sans y servir. Le schéma exporté est un artefact **destiné au
client** ; il se range avec son consommateur.

### Un module `app/cli/` plutôt qu'un script

Le contrat d'architecture `service-spaces` (BACK-04b) est déclaré `exhaustive` sur le paquet `app` :
un nouveau dossier à sa racine fait échouer `make lint` tant que sa place dans la hiérarchie n'est
pas écrite. Loger un exportateur là aurait signifié déclarer que le service a un **espace CLI**
permanent — élargir la définition de l'architecture pour ranger un outil.

## Conséquences

**Ce que cela donne.** La génération ne dépend plus de rien qui tourne : ni serveur, ni base, ni
réseau. Un développeur frontend régénère sans installer Python. La CI vérifie les deux moitiés de la
chaîne — contrat et client — d'un seul `git diff`, et le contrat lui-même devient lisible en revue :
un champ ajouté côté backend se voit dans le diff du schéma avant même de se voir dans celui du
client.

**Ce que cela coûte.** Un second artefact généré à tenir à jour, et une étape de plus dans le flux de
travail : `pnpm generate:api` seul ne voit pas un changement de contrat, il faut `make generate-api`.
La CI paie l'installation des deux chaînes d'outils, uv et pnpm, pour un seul contrôle. Et le fichier
échappe à Prettier — deux formateurs sur le même JSON se réécriraient indéfiniment —, exclusion qui
doit rester motivée sur place.

## Références

- `backend/api/scripts/export_openapi.py` — l'export et le motif de chacune de ses options de
  sérialisation.
- `backend/api/Makefile` — la cible `openapi`, et le `uv run --locked` qui aligne le poste sur la CI.
- `Makefile` — les cibles `generate-api` et `generate-api-check`, et le message d'échec.
- `.github/workflows/api-client.yml` — la vérification anti-dérive.
- `.prettierignore` — l'exclusion du schéma exporté, motivée sur place.
- [ADR-0007](./0007-client-api-genere-orval.md) — la décision que celle-ci complète : le client est
  généré, et le généré est versionné.
- [ADR-0011](./0011-routage-versionne-par-module.md) — la fermeture de `/openapi.json` en production.
- [Le client d'API généré](../frontend/client-api-genere.md) — la régénération vue du poste.
