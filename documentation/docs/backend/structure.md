---
title: Structure du service
description: L'arborescence de backend/api, le rôle de chaque dossier et ce que fait main.py au démarrage.
---

# Structure du service

Avant de plonger dans l'architecture, un plan du terrain — l'arborescence
commentée de `backend/api`, le rôle de chaque dossier, et le module
d'assemblage `main.py`, qui tient l'application debout sans porter aucune
logique métier.

```
backend/api/
├── pyproject.toml     dépendances, métadonnées, configuration des outils
├── uv.lock            versions résolues — versionné, jamais édité à la main
├── .python-version    interpréteur du projet (3.14)
├── .env.example       gabarit d'environnement — miroir des champs de `Settings`
├── Makefile           raccourcis de lint, formatage, typage et migrations
├── alembic.ini        mécanique d'Alembic — aucune URL de base ici (BACK-07)
├── alembic/           mise sous contrôle de version du schéma (BACK-07)
│   ├── env.py             cible `Base.metadata`, URL depuis `Settings`, verrou consultatif
│   ├── script.py.mako     gabarit des fichiers de migration, conforme à Ruff
│   └── versions/          les migrations, nommées par horodatage
└── src/app/
    ├── main.py             assemblage de l'application et des routeurs
    ├── core/               réglages du processus, ni domaine ni infrastructure
    │   ├── config.py       configuration typée (BACK-03)
    │   ├── correlation.py  contextvars du contexte de requête (BACK-15, BACK-11)
    │   └── logging.py      formateurs, masquage, `configure_logging` (BACK-11)
    ├── shared/             noyau partagé — pas un module métier
    │   ├── domain/
    │   │   ├── exceptions.py   hiérarchie des erreurs métier, codes namespacés (BACK-09)
    │   │   └── ports/          ports techniques : cache, stockage, transaction, jetons
    │   │       ├── cache.py        port `Cache` et décorateur `@cached` (BACK-14)
    │   │       ├── file_storage.py port `FileStorage` et `UploadPolicy` (BACK-13)
    │   │       ├── repository.py   protocole générique `Repository` (BACK-06a)
    │   │       └── unit_of_work.py port `AbstractUnitOfWork` (BACK-06a)
    │   └── infrastructure/
    │       ├── tenancy.py      contextvar du groupe actif (BACK-14)
    │       ├── db/             socle de persistance (BACK-05, BACK-06a)
    │       │   ├── base.py         `Base`, convention de nommage, `check_schema`
    │       │   ├── mixins.py       identité, horodatage, tenance opt-in
    │       │   ├── engine.py       moteur asyncpg et pool de connexions
    │       │   ├── session.py      fabrique de sessions et accès à `app.state`
    │       │   ├── unit_of_work.py adaptateur SQLAlchemy de l'unité de travail
    │       │   └── repositories/   dépôt générique dont les modules héritent
    │       ├── clients/        adaptateurs des ports techniques (BACK-14, BACK-13)
    │       │   ├── cache_keys.py   composition des clés physiques de cache
    │       │   ├── redis_cache.py  adaptateur Redis du port `Cache`
    │       │   ├── storage_keys.py convention de nommage des clés d'objets
    │       │   └── s3_storage.py   adaptateur S3 du port `FileStorage`
    │       ├── tasks/          tâches de fond TaskIQ (BACK-15)
    │       │   ├── broker.py       le broker — chemin figé par la CLI du worker
    │       │   ├── middlewares.py  corrélation, reprise et file de rejets
    │       │   ├── lifecycle.py    ressources du worker (`WORKER_STARTUP`)
    │       │   ├── discovery.py    import des tâches déclarées par les modules
    │       │   └── demo.py         patron de référence : `record_ping`
    │       └── api/            socle HTTP (BACK-08, BACK-09, BACK-11)
    │           ├── health.py       sondes `/health/live` et `/health/ready`
    │           ├── router.py       routeur racine `/api/v1`, assemblé par `main.py`
    │           ├── error_handlers.py traduction `DomainError` → HTTP, format unique (BACK-09)
    │           ├── middlewares.py  identifiant de requête, journal d'accès, CORS (BACK-11)
    │           ├── pagination.py   `PageParams`, `sort_param`, enveloppe `Page` (BACK-24)
    │           └── schemas/error.py  corps d'erreur { code, message, details, request_id }
    └── modules/            contextes métier, étanches les uns aux autres
        ├── identity/       module pilote — le seul complet à ce stade
        │   ├── domain/         entities, policies, ports, exceptions
        │   ├── application/    use_cases/
        │   ├── infrastructure/ db/ (modèle, dépôt), api/ (schémas, routeur)
        │   └── unit_of_work.py unité de travail du module, `get_identity_uow` (BACK-06a)
        ├── medical_records/ dossier de l'animal : fiche et détention datée (BACK-19)
        │   ├── domain/         entités, enums, règle « une seule détention active », ports
        │   ├── infrastructure/ db/ (2 tables, dépôts non tenant — pas encore d'api/)
        │   └── unit_of_work.py `get_medical_records_uow`
        ├── notifications/  qui prévenir, par quel canal (BACK-22)
        │   ├── domain/         préférences par événement, catalogue, résolution des canaux
        │   ├── application/    use_cases/ (remise d'une notification)
        │   ├── infrastructure/ db/ (1 table), clients/ (un envoyeur par canal), tasks/, memory/
        │   └── unit_of_work.py `get_notifications_uow`
        ├── organization/   groupes, cliniques, appartenances, affectations (BACK-16)
        │   ├── domain/         entités, rôles, règle d'affectation, les 3 ports
        │   ├── infrastructure/ db/ (4 tables, dépôts — pas encore d'api/)
        │   └── unit_of_work.py `get_organization_uow`
        └── scheduling/     fiche technique du praticien : horaires et espèces (BACK-21)
            ├── domain/         entité, plage hebdomadaire, catalogue d'espèces, les 2 lectures
            ├── infrastructure/ db/ (3 tables, dépôt tenant — pas encore d'api/)
            └── unit_of_work.py `get_scheduling_uow`
```

Le paquet s'appelle `app` alors que le projet se nomme `juui-api` : la
correspondance est déclarée par `[tool.uv.build-backend] module-name`.

Ce que chaque espace a le droit d'importer, et pourquoi, est une **règle** : elle vit dans la
section [Architecture](../architecture/ecrire-un-module-conforme.md#le-sens-des-dépendances).
L'état des lieux de ce découpage — les trois espaces tels qu'ils sont posés — reste sur
[Architecture du service](./architecture-du-service.md).

## `main.py`

Le module d'assemblage, et rien d'autre : aucune logique métier n'y a sa place.

- **`create_app()`** construit une instance neuve de l'application — sondes de
  santé et routeur v1 montés, [métadonnées OpenAPI](./surface-http.md) posées, et
  documentation fermée quand `ENVIRONMENT=production`. Les tests (BACK-12) en
  dépendront pour repartir d'une application propre à chaque cas.
- **`app = create_app()`** est le point d'entrée ASGI, celui que désigne
  `uvicorn app.main:app`. Un serveur ASGI attend un objet, pas une fonction.
- **`_MODULE_ROUTERS`** est la liste des routeurs de modules, montés sous
  `/api/v1` via `build_api_router` (BACK-08). Un tuple plutôt qu'une suite
  d'appels : la liste des contextes servis par l'API se lit d'un coup d'œil, et
  chaque module reste maître de son préfixe de ressource. C'est le seul endroit
  du service autorisé à connaître plusieurs modules à la fois — raison pour
  laquelle le routeur racine, qui vit dans `shared`, reçoit cette liste en
  argument au lieu de l'importer.
- **`lifespan`** est le point d'accroche des ressources de longue durée. Il pose
  la règle que toutes devront suivre : rien ne s'ouvre à l'import du module, tout
  passe par lui, et l'ordre de fermeture est l'inverse exact de l'ordre
  d'ouverture. Quatre occupants à ce jour — la validation de la configuration
  (BACK-03), qui précède par construction toute ouverture de ressource, puis le
  [moteur PostgreSQL](./persistance.md) (BACK-05), puis le [cache Redis](./cache.md)
  (BACK-14), puis le [stockage objet](./stockage-objet.md) (BACK-13), puis le
  [broker TaskIQ](./taches-de-fond.md) (BACK-15, versant client seulement, sous la
  garde `is_worker_process`) — chacun fermé avant celui qui l'a ouvert. Ils ne
  traitent pas l'indisponibilité de la même façon, et c'est délibéré :
  [le tableau de l'asymétrie](./stockage-objet.md#lasymétrie-du-service-a-trois-temps-pas-deux) dit
  laquelle choisir pour la ressource suivante.
