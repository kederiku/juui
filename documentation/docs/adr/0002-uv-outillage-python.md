---
title: ADR-0002 — uv comme outillage Python unique
description: uv gère l'interpréteur, l'environnement, les dépendances, le verrou et le build du backend — épinglé partout à la même plage de versions.
---

# ADR-0002 — uv comme outillage Python unique

| Statut      | Date       | Tickets |
| ----------- | ---------- | ------- |
| **Accepté** | 2026-08-25 | BACK-01 |

## Contexte

Décision rendue par BACK-01, à l'initialisation du service d'API. L'outillage Python doit couvrir
cinq besoins — installer l'interpréteur, créer l'environnement virtuel, résoudre les dépendances,
verrouiller les versions, construire le paquet — et les couvrir **à l'identique** dans trois
environnements : le poste de développement, la CI et l'image Docker. Chaque outil supplémentaire
dans cette chaîne est un accord de versions de plus à tenir entre ces trois environnements.

## Décision

**uv est le seul outil Python du dépôt.** Il installe l'interpréteur déclaré dans
`.python-version`, gère l'environnement et les dépendances, produit `uv.lock` — versionné, pour
que la CI installe en `--locked` et que l'image Docker construise en `--frozen` — et sert de
backend de build (`uv_build`).

Sa version est **exigée, pas suggérée** : `[tool.uv] required-version` déclare une plage
(`>=0.12.5,<0.13`), et un uv hors de cette plage s'arrête net au lieu de travailler différemment
en silence. Une plage et non un `==` : une montée de patch côté Homebrew passe, un saut de mineur
se voit. Le poste, la CI (`setup-uv`) et le Dockerfile (`ARG UV_VERSION`) s'alignent sur cette
même déclaration.

## Alternatives écartées

### Poetry

L'outil dominant au moment de la décision, et un vrai progrès sur ce qu'il remplaçait. Mais son
résolveur est nettement plus lent — un coût payé à chaque installation de CI —, son format de
verrou lui est propre, et il ne gère pas la version de Python elle-même : il aurait fallu lui
adjoindre pyenv ou équivalent. uv couvre l'interpréteur, l'environnement, le verrou et le build
avec un seul binaire à installer partout.

### pip et pip-tools

La voie minimaliste et standard. Elle éclate pourtant la chaîne en trois outils à orchestrer —
pyenv pour l'interpréteur, venv pour l'environnement, pip-compile pour le verrou — là où
l'expérience du projet a montré qu'un seul accord de versions est déjà difficile à tenir : la CI
et le poste ont divergé de version d'uv pendant des semaines, avec pour seul symptôme un
avertissement murmuré dans les logs.

### PDM ou Hatch

Crédibles et conformes aux standards, sans l'avantage décisif — la vitesse, la gestion de
l'interpréteur, le binaire unique — qui a fait pencher la balance. Les écarter n'est pas les
juger mauvais : c'est refuser un choix médian qui n'aurait simplifié aucun des trois
environnements.

## Conséquences

**Ce que cela donne.** L'accord de versions entre le poste, la CI et Docker est une **contrainte
mécanique**, plus une convention — le même arbitrage que les contrats d'architecture de
[l'ADR-0003](./0003-monolithe-modulaire.md) : une règle qu'aucun mécanisme ne tient n'est pas une
règle. Les builds sont reproductibles depuis `uv.lock`, et un poste vierge n'installe qu'un
outil.

**Ce que cela coûte.** uv est jeune et sort vite : la plage `required-version` et la borne du
backend de build (`uv_build>=0.11.7,<0.13.0`) sont une maintenance récurrente et délibérée. Les
deux bornes s'arrêtent ensemble à 0.13, pour que les ruptures d'uv soient rediscutées une fois et
non concédées l'une après l'autre.

## Références

- `backend/api/pyproject.toml` — `[tool.uv]`, `[build-system]` et leurs justifications.
- [Dépendances](../backend/dependances.md), section « La version d'uv, et la borne du backend de
  build » — l'incident de dérive qui a mené à l'épinglage.
- `docker/api/Dockerfile` — le troisième environnement aligné.
