---
title: Migrations
description: 'Alembic piloté par Settings : relecture des migrations autogénérées, un seul migrateur, mode hors ligne refusé.'
---

# Migrations

Le schéma de la base vit sous contrôle de version — Alembic autogénère un brouillon, l'humain
le relit, et un verrou consultatif garantit qu'un seul migrateur l'applique à la fois. Cette
page couvre le cycle complet : génération, relecture, sérialisation et vérifications.

Le schéma est sous contrôle de version depuis BACK-07 : Alembic compare `Base.metadata` — le
registre unique que tous les modèles peuplent — à la base réelle, et chaque écart devient un
fichier de migration rejouable et réversible dans `alembic/versions/`.
Le nom des fichiers commence par un horodatage UTC (`20260825_<rev>_<slug>`), pour que
`ls versions/` raconte l'histoire dans l'ordre.

Le cycle complet tient en trois gestes :

```bash
make migration m="message de la revision"   # génère — puis SE RELIT, voir ci-dessous
make migrate                                # applique jusqu'à head
git add alembic/versions/ && git commit     # la migration relue se committe avec son ticket
```

Le message devient le slug du fichier et la première ligne de sa docstring : français sans
accents, sans point final, moins de 40 caractères.

En pile Docker, personne ne lance `make migrate` : l'entrypoint d'INFRA-04 exécute
`alembic upgrade head` à chaque démarrage du conteneur — l'étape était écrite d'avance, la
simple présence d'`alembic.ini` l'a activée.

## Toute migration autogénérée se relit avant d'être commitée

L'autogénération est un **brouillon**, pas une vérité : elle déduit un plan de la différence
entre les métadonnées et la base, et se trompe en silence dès que l'un des deux n'est pas ce
qu'on croit — base non vierge, modèle pas encore importé, type qu'elle ne sait pas comparer.
La relecture est donc obligatoire, et elle vérifie au minimum :

- **l'ordre des colonnes** : identité, tenance, colonnes du modèle, horodatage — la silhouette
  imposée par les `sort_order` des `mixins` ;
- **les noms passés par `op.f()`** (`pk_accounts`, `ix_custodies_animal_id`) : c'est la
  convention de nommage figée qui parle, pas une fantaisie du générateur. Exception : un index
  d'**expression** (`ix_accounts_email_lower`, INFRA-09) porte un nom écrit à la main — la
  convention compose ses noms à partir de colonnes et ne sait rien nommer d'un `lower(email)` ;
- **l'index unique reste un index** : `unique=True, index=True` sur une colonne produit un
  `op.create_index(..., unique=True)` nommé `ix_…`. Le « corriger » en contrainte `uq_…`
  ferait diverger la base des métadonnées, et `alembic check` le reprocherait à chaque fois ;
- **les `server_default`** attendus (`sa.text("now()")` sur les deux horodatages) — c'est
  `compare_server_default=True` qui permet de les voir apparaître et disparaître ;
- **le `downgrade` symétrique inverse** de l'upgrade, sans opération orpheline ;
- **aucune opération parasite** : une table inconnue signifie une base sale, une suppression
  inattendue signifie un modèle pas importé — dans les deux cas, on corrige la cause, pas la
  migration.

La migration naît déjà propre : les `[post_write_hooks]` d'`alembic.ini` passent chaque
fichier généré par `ruff check --fix` puis `ruff format`, et le gabarit
`script.py.mako` fournit docstrings et annotations. Il ne reste à la
relecture que ce qu'aucun outil ne sait juger : le sens.

## L'URL vient de `Settings`, jamais d'`alembic.ini`

`alembic.ini` ne porte **aucune URL de connexion**, pas même en exemple commenté : l'`env.py`
lit `get_settings().db.sqlalchemy_url`, la même valeur dérivée que le moteur de l'application —
une seule source de vérité, le `.env` strict de BACK-03 compris. Toute commande qui **touche la
base** — `upgrade`, `downgrade`, `current`, `check`, `revision --autogenerate` — exécute
l'`env.py` et valide donc l'environnement complet, exactement comme un démarrage d'API : un
`.env` incomplet donne la même `ConfigurationError` nommant les variables manquantes. Les
commandes purement informatives (`history`, `heads`) ne chargent pas cet environnement et
passent au travers — sans conséquence : elles ne génèrent rien et n'écrivent rien.

L'URL porte le mot de passe en clair ; elle n'est jamais passée à `config.set_main_option` —
qui la soumettrait à l'interpolation de configparser et la rapprocherait des chaînes
journalisées — ni imprimée nulle part.

L'`env.py` construit son moteur lui-même plutôt que par `build_engine` : une migration vit le
temps d'une commande (`NullPool`, incompatible avec les réglages de pool que `build_engine`
transmet toujours) et s'annonce sous son propre nom — `juui-alembic/<environnement>` — dans
`pg_stat_activity`, là où réutiliser le moteur de l'API la rendrait indiscernable de l'API.

## Un seul migrateur à la fois

Les conteneurs `api` et `worker` partagent le même entrypoint, et le worker se met à l'échelle
par `--scale` : plusieurs `alembic upgrade head` peuvent donc partir en même temps sur la même
base. L'`env.py` les sérialise par un **verrou consultatif PostgreSQL de session**
(`pg_advisory_lock`, clé figée `0x6A757569`, soit `1786082665`) : le premier migrateur passe,
les suivants **attendent** puis rejouent un plan devenu vide. Un migrateur suspendu se
diagnostique dans `pg_stat_activity`, sous `application_name = 'juui-alembic/…'` et
`wait_event = 'advisory'`.

Le détail qui n'est pas un détail : après la prise du verrou, l'`env.py` **committe** avant de
dérouler les migrations. L'`execute` du verrou a ouvert une transaction (autobegin de
SQLAlchemy 2.0) ; si elle restait ouverte, Alembic la détecterait et cesserait de gérer la
sienne — charge à l'appelant de committer, ce que la fermeture de la connexion ne fait pas :
tout le DDL serait déroulé en arrière à la déconnexion, **sans erreur**. Le verrou, lui, est de
niveau session et survit au commit.

## Le mode hors ligne est refusé

`alembic upgrade head --sql` — générer le SQL sans l'exécuter — lève une `CommandError`
explicite : personne ne consomme de script SQL généré, et le verrou ci-dessus ne peut rien
sérialiser sans connexion. Le refus est écrit et motivé dans l'`env.py` ; c'est là qu'il se
rouvre si un besoin réel apparaît.

## Ajouter un module de modèles

`Base.metadata` ne recense que les tables des modèles effectivement **importés**. Tout
nouveau module métier qui gagne un `infrastructure/db/models.py` doit s'ajouter au tuple
`_MODEL_MODULES` de l'`env.py` — même geste que `_MODULE_ROUTERS` dans `main.py` : la liste
des tables sous contrôle de version se lit d'un coup d'œil. L'oubli ne pardonne pas :
l'autogénération proposerait de **supprimer** les tables du module absent. Le filet est
`make migrate-check` (`alembic check`) : sur une base à jour, il échoue dès que modèles et
migrations divergent — il attend son entrée en CI avec QA-01.

## Vérifier que le cycle tient

PostgreSQL démarré (`docker compose --project-directory . -f docker/docker-compose.yml up -d
postgres` depuis la racine), depuis `backend/api/` :

```bash
uv run alembic upgrade head     # applique tout
uv run alembic current          # -> 91eefe8e775b (head)
uv run alembic downgrade base   # revient à zéro — geste de vérification, base de dev uniquement
uv run alembic current          # -> (vide)
uv run alembic upgrade head     # rejoue sans erreur
uv run alembic check            # -> "No new upgrade operations detected."
```

Attendu : le cycle complet sans erreur, et le `check` final silencieux — la preuve que tous
les modèles sont importés et que la première migration est l'image exacte des métadonnées.
`make downgrade`, lui, ne recule que d'un cran : revenir à `base` est un geste qui s'écrit en
toutes lettres.

Les noms en base sont ceux de la convention figée :

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec postgres \
  psql -U juui -d juui -c '\d accounts'
```

Attendu : `"pk_accounts" PRIMARY KEY` et `"ix_accounts_email_lower" UNIQUE, btree
(lower(email::text))` — la forme exacte qu'affiche psql pour l'index d'expression d'INFRA-09.

## Vérifier que la comparaison voit vraiment quelque chose

Un `alembic check` silencieux ne prouve rien si la comparaison est aveugle. Élargir
temporairement une colonne — `String(30)` → `String(40)` sur `phone` dans le modèle — puis :

```bash
uv run alembic check   # -> FAILED: New upgrade operations detected: [modify_type ...]
```

Attendu : l'échec, grâce à `compare_type` ; puis restaurer le modèle. Pour le verrou : tenir
`SELECT pg_advisory_lock(1786082665);` dans une session `psql`, lancer `make migrate` dans un
autre terminal — il bloque, visible dans `pg_stat_activity` sous `juui-alembic/…` — puis
`SELECT pg_advisory_unlock(1786082665);` le libère et la commande termine.

Les écarts assumés avec le ticket BACK-07 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-07).
