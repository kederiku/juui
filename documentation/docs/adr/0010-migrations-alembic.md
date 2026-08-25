---
title: ADR-0010 — Migrations Alembic pilotées par Settings, un migrateur à la fois
description: L'env.py d'Alembic lit sa configuration dans Settings — rien dans alembic.ini — et sérialise les migrateurs concurrents par un verrou consultatif PostgreSQL ; toute migration autogénérée se relit avant d'être commitée.
---

# ADR-0010 — Migrations Alembic pilotées par Settings, un migrateur à la fois

| Statut      | Date       | Tickets           |
| ----------- | ---------- | ----------------- |
| **Accepté** | 2026-08-25 | BACK-07, INFRA-04 |

## Contexte

Décision rendue par BACK-07, qui met le schéma PostgreSQL sous contrôle de version avec
Alembic. La mise en place pose trois questions qui engagent plus loin que le ticket.

**D'où vient l'URL de connexion ?** Alembic propose de l'écrire dans `alembic.ini`
(`sqlalchemy.url`), quand l'application la dérive déjà de `Settings` (BACK-03) — composants
`POSTGRES_*` validés, `.env` strict, mot de passe jamais journalisé. Deux sources de vérité
divergeraient un jour, et le fichier ini soumettrait l'URL — mot de passe compris — à
l'interpolation de configparser.

**Qui a le droit de migrer, et quand ?** L'entrypoint d'INFRA-04 exécute
`alembic upgrade head` à chaque démarrage de conteneur, et il est partagé par les services
`api` et `worker` — ce dernier mis à l'échelle par `--scale` (INFRA-05b). Plusieurs migrateurs
peuvent donc partir en même temps sur la même base : une course, laissée explicitement
« à arbitrer en BACK-07 » par le commentaire de l'entrypoint.

**Que vaut une migration autogénérée ?** L'autogénération déduit un plan de la différence
entre `Base.metadata` et la base réelle ; elle se trompe en silence dès que l'un des deux n'est
pas ce qu'on croit — base non vierge, modèle pas encore importé dans l'`env.py`, type qu'elle
ne sait pas comparer.

## Décision

**L'`env.py` est un consommateur de `Settings`, le verrou consultatif sérialise les
migrateurs, et l'autogénération est un brouillon qui se relit.** Trois volets :

1. **`Settings` pour seule configuration.** `alembic.ini` ne porte aucune URL, pas même en
   exemple : l'`env.py` lit `get_settings().db.sqlalchemy_url`, la même valeur dérivée que le
   moteur de l'application. Toute commande qui touche la base — `upgrade`, `downgrade`,
   `current`, `check`, `revision --autogenerate` — exécute l'`env.py` et valide donc
   l'environnement complet, exactement comme un démarrage d'API ; `check_schema(Base.metadata)`
   y est appelée au chargement : un schéma fautif n'empêche pas seulement le démarrage, il
   empêche la migration d'exister. Les commandes purement informatives (`history`, `heads`) ne
   chargent pas cet environnement — sans conséquence, elles ne génèrent rien et n'écrivent
   rien.

2. **Un migrateur à la fois.** L'`env.py` prend un verrou consultatif PostgreSQL de session
   (`pg_advisory_lock`, clé figée `0x6A757569`) sur la connexion qui migre, avant de dérouler
   les migrations : le premier migrateur passe, les suivants attendent puis rejouent un plan
   devenu vide. Le mode hors ligne (`--sql`), qui échapperait au verrou faute de connexion,
   est refusé explicitement. Un migrateur suspendu se diagnostique dans `pg_stat_activity`,
   sous `application_name = 'juui-alembic/…'` et `wait_event = 'advisory'`.

3. **Relecture obligatoire.** Une migration autogénérée ne se committe qu'après relecture —
   ordre des colonnes, noms passés par `op.f()`, `server_default`, `downgrade` symétrique,
   aucune opération parasite ; la checklist vit dans le README du backend. `alembic check`
   (`make migrate-check`) garde la synchronisation modèles/migrations et entrera en CI avec
   QA-01.

## Alternatives écartées

### L'URL dans `alembic.ini`, ou une variable `ALEMBIC_DATABASE_URL`

La forme canonique d'Alembic, et une seconde source de vérité dans les deux cas : un poste dont
le `.env` et l'ini divergent migre une autre base que celle qu'il croit. C'est exactement le
scénario que la valeur **dérivée** `sqlalchemy_url` de BACK-03 élimine — la réintroduire par
l'outil de migration annulerait l'arbitrage.

### Un service de migration dédié dans le fichier compose

Un conteneur one-shot jouant les migrations, dont `api` et `worker` dépendraient via
`condition: service_completed_successfully`. Cela règle la course dans la pile compose — et
seulement là : deux `make migrate` lancés à la main, ou un déploiement futur hors compose,
recréeraient la course. Le verrou tient en quelques lignes dans l'`env.py` et couvre tous les
chemins, puisqu'il vit dans le migrateur lui-même. La pièce d'orchestration supplémentaire
resterait par ailleurs à maintenir dans chaque environnement.

### Des migrations écrites entièrement à la main

Renoncer à l'autogénération supprime ses pièges, mais perd la comparaison mécanique entre
modèles et base — précisément ce qui détecte la dérive (`compare_type`,
`compare_server_default`, `alembic check`). La relecture obligatoire garde le meilleur des deux
: la machine propose, l'humain dispose.

### `Base.metadata.create_all()` au démarrage

Déjà proscrit par BACK-05 : un schéma créé hors migration existerait avant la première
migration, et `alembic upgrade head` échouerait sur une table déjà là. L'interdiction est
commentée dans `main.py` ; cet ADR la consigne.

## Conséquences

**Ce que cela donne.** Une seule source de vérité pour la connexion, du poste de travail au
conteneur. Des démarrages concurrents sûrs par construction — `docker compose up` avec un
worker à l'échelle ne demande aucune précaution d'ordre. Un historique de schéma rejouable et
réversible, dont la dérive est détectable mécaniquement (`make migrate-check`), et des fichiers
de migration horodatés qui se lisent dans l'ordre. La convention de nommage des contraintes,
figée par la première migration, rend les autogénérations reproductibles d'un poste à l'autre.

**Ce que cela coûte.** Toute commande qui touche la base exige un `.env` complet — y compris
les variables sans rapport avec elle (JWT, S3) : c'est le prix d'un `Settings` unique et
strict. Un migrateur suspendu bloque les démarrages suivants tant que le verrou n'est pas
rendu — le comportement voulu, mais il se **diagnostique** (`pg_stat_activity`) au lieu
d'échouer bruyamment. Enfin, la relecture obligatoire est une discipline, pas une garantie
mécanique : elle repose sur la revue, outillée par `alembic check` en local aujourd'hui, en CI
avec QA-01.

## Références

- `backend/api/alembic/env.py` — l'`env.py` : `Settings`, `check_schema`, verrou consultatif
  et refus du mode hors ligne, chaque arbitrage commenté.
- `backend/api/alembic.ini` — la mécanique de l'outil, et aucune URL.
- `backend/api/README.md`, section « Migrations » — le cycle, la checklist de relecture et les
  vérifications reproductibles.
- `docker/api/entrypoint.sh` — l'étape `alembic upgrade head` écrite d'avance par INFRA-04,
  activée par la présence d'`alembic.ini`, et l'arbitrage de la course consigné sur place.
- [ADR-0003](./0003-monolithe-modulaire.md) — la `Base` déclarative unique : Alembic ne voit
  qu'un registre de métadonnées à la fois.
