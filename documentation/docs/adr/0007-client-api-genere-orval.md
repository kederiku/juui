---
title: ADR-0007 — Le client d'API des frontends est généré par Orval
description: Types, hooks TanStack Query et schémas Zod sont générés depuis l'OpenAPI de FastAPI ; le code généré est versionné et interdit d'édition.
---

# ADR-0007 — Le client d'API des frontends est généré par Orval

| Statut      | Date       | Tickets             |
| ----------- | ---------- | ------------------- |
| **Accepté** | 2026-08-25 | SHARED-03 (à venir) |

## Contexte

Décision portée par SHARED-03, dont l'application est à venir — mais elle est prise, et le dépôt
en porte déjà les traces : la configuration ESLint et le `.prettierignore` excluent nommément la
future sortie générée, et le scope de commit `api-client` lui est réservé.

Trois frontends consomment la même API. FastAPI produit déjà un schéma OpenAPI exact, dérivé des
routes et des modèles Pydantic. Écrire à la main les types TypeScript et les appels — trois fois —
c'est trois occasions de dériver du contrat, et la dérive est silencieuse : elle ne se voit ni à
la compilation ni en revue, seulement en production, quand un champ renommé côté backend arrive
`undefined` côté client.

## Décision

**Orval génère le client depuis l'OpenAPI : les types TypeScript, les hooks TanStack Query et les
schémas Zod.** La validation des formulaires réutilise ainsi exactement les contraintes du
backend. Un mutator personnalisé encapsule l'instance HTTP — jeton d'authentification, base URL,
normalisation des erreurs.

Le dossier généré est **versionné, et interdit d'édition** : la CI échoue si une régénération
produit un diff, garantie que le client committé correspond toujours au contrat. Toute
modification d'un contrat d'API s'accompagne donc d'une régénération, dans la même pull request.

## Alternatives écartées

### Écrire les appels à la main

Le point de départ naturel, écarté pour la raison du contexte : la dérive contrat-client est
silencieuse et se découvre en production — multipliée par trois applications. Le coût d'écriture
initial est le moindre problème ; c'est le coût de synchronisation permanente qui condamne cette
voie.

### openapi-typescript

Il génère des types, et seulement des types : ni hooks TanStack Query — l'outillage de données
des trois applications —, ni validation à l'exécution. Or un type TypeScript ne vérifie rien au
runtime ; un schéma Zod, si. Il aurait fallu écrire à la main précisément les couches où la
dérive s'installe.

### openapi-generator

Le générateur historique, toute la chaîne Java et ses templates — pour une sortie qui ne cible ni
TanStack Query ni Zod. Orval vise exactement la pile du dépôt ; l'adapter aurait demandé de
maintenir des templates, c'est-à-dire de réécrire le générateur.

### Générer à la volée, sans versionner

La sortie générée dans le build, jamais committée : le build d'un frontend dépendrait alors d'un
backend démarré ou d'un schéma exporté à jour. Versionner le généré rend au contraire tout
changement de contrat **visible en diff de pull request** — un champ retiré se lit dans la revue,
pas dans un log de build — et la CI garde l'accord.

## Conséquences

**Ce que cela donne.** Le serveur FastAPI est l'unique source de vérité du contrat : les types,
les hooks et les validations en découlent mécaniquement, pour les trois applications à la fois.
Un breaking change backend casse la compilation des frontends au lieu de casser la production.

**Ce que cela coûte.** Les diffs de pull request gonflent à chaque évolution de contrat — c'est
le prix de la visibilité. La qualité du client généré dépend de la rigueur du backend : des
`operation_id` lisibles, des modèles de réponse complets (BACK-08). Et la régénération est une
étape obligatoire du flux de travail, qui doit rester une commande unique.

## Références

- `.prettierignore` — l'exclusion du dossier généré, motivée sur place.
- `eslint.config.mjs` — la même exclusion côté lint.
- `commitlint.config.mjs` — le scope `api-client` réservé.
