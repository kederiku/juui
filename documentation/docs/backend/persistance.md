---
title: Persistance
description: Le moteur SQLAlchemy et son pool, la convention de nommage figée, les trois mixins et la tenance opt-in.
---

# Persistance

Le socle SQLAlchemy du service — le moteur asynchrone et son pool, la convention de
nommage qui fige les migrations, les trois mixins que chaque agrégat adopte ou non,
et la garde mécanique de la tenance.

Le service parle à PostgreSQL avec **SQLAlchemy 2.0 en asynchrone**, sur le pilote
`asyncpg`. Le socle vit dans `shared/infrastructure/db/`,
et ce qui l'organise n'est pas la couche mais la **durée de vie** :

| Fichier      | Ce qu'il porte                                                  | Vit le temps |
| ------------ | --------------------------------------------------------------- | ------------ |
| `base.py`    | la `Base` déclarative, la convention de nommage, `check_schema` | de l'import  |
| `mixins.py`  | `UUIDPrimaryKey`, `TimestampMixin`, `TenantMixin`               | de l'import  |
| `engine.py`  | le moteur et son pool de connexions                             | du processus |
| `session.py` | la fabrique de sessions et l'accès aux ressources ouvertes      | du processus |

Rien ne s'ouvre à l'import : c'est le [`lifespan`](./structure.md#mainpy) qui construit le moteur,
éprouve la connexion, range le tout dans `app.state`, puis referme. La fermeture est dans
un `finally` — un moteur construit avant un `SELECT 1` en échec doit être libéré lui aussi,
faute de quoi une boucle de redémarrage de conteneur fuit un pool à chaque tour.

## Le moteur et son pool

`build_engine(settings)` prend sa configuration **en argument** au lieu d'appeler
`get_settings()`. Cette fonction est mise en cache : un constructeur qui l'appellerait de
l'intérieur ne saurait pas fabriquer un moteur différent de celui du processus. Or
l'`env.py` d'Alembic (BACK-07) tourne hors de l'application, et les fixtures de BACK-12
auront besoin d'un moteur à elles.

| Variable                        | Défaut | Ce qu'elle règle                                      |
| ------------------------------- | ------ | ----------------------------------------------------- |
| `POSTGRES_POOL_SIZE`            | 5      | connexions gardées ouvertes en permanence             |
| `POSTGRES_MAX_OVERFLOW`         | 10     | connexions supplémentaires tolérées en pointe         |
| `POSTGRES_POOL_RECYCLE_SECONDS` | 1800   | âge au-delà duquel une connexion est retirée du pool  |
| `POSTGRES_ECHO`                 | false  | journalise chaque requête SQL, **paramètres compris** |

Ce sont des réglages **client** malgré le préfixe : ils décrivent ce que ce processus garde
ouvert, pas ce que le serveur accepte. Le calcul à ne pas perdre de vue est
`workers × (pool_size + max_overflow)` — quatre workers suffisent à réclamer 60 connexions,
avant le worker TaskIQ (BACK-15) et pgAdmin, contre un `max_connections` de 100 par défaut.

`pool_pre_ping` est activé et ne se règle pas : il vérifie chaque connexion à l'emprunt.
`pool_recycle` ne fait pas double emploi avec lui — le ping attendrait le délai TCP sur une
socket coupée en silence par un intermédiaire, là où le recyclage retire les connexions
avant d'en arriver là.

**`POSTGRES_ECHO` est un champ à soi, et non une déduction de `LOG_LEVEL`.** `echo` journalise
les paramètres liés : les adresses e-mail aujourd'hui, les empreintes de mot de passe à
partir de BACK-10b, le secret TOTP à partir de BACK-18. Passer `LOG_LEVEL=DEBUG` pour suivre
un problème de routage ne doit pas les déverser dans la chaîne de journalisation par effet de
bord. Le moteur l'ignore de toute façon quand `ENVIRONMENT` vaut `production`.

Chaque connexion s'annonce enfin sous le nom `juui-api/<environnement>` dans
`pg_stat_activity` et dans pgAdmin. Sans cela toutes les connexions sont anonymes, et rien ne
distingue l'API du worker, d'une migration ou d'une session ouverte à la main le jour où il
faut comprendre qui sature le serveur.

## L'API ne démarre plus sans base

`verify_connectivity` exécute un `SELECT 1` au démarrage. Un mot de passe faux ou un serveur
absent arrêtent alors le processus, plutôt que de produire une erreur 500 pour le premier
utilisateur — et le healthcheck du conteneur (INFRA-04), qui déclare l'API saine dès qu'elle
répond en HTTP, redevient honnête.

L'échec lève `DatabaseUnavailableError`, **distincte de `ConfigurationError`** : celle-là dit
« une variable manque, corriger le `.env` », celle-ci dit « le fichier est juste, démarrer
PostgreSQL ». Les confondre enverrait relire un fichier correct. Le message nomme l'hôte, le
port, la base et l'utilisateur — jamais `settings.db.sqlalchemy_url`, qui porte le mot de
passe en clair.

Sous uvicorn, l'échec au démarrage donne `Application startup failed. Exiting.` et un **code
de sortie 3**. En pile Docker, une boucle de redémarrage du service `api` se lit donc
« PostgreSQL n'est pas là », et non « l'API est cassée ».

## La convention de nommage est figée

`Base.metadata` porte les cinq motifs qui nomment toutes les contraintes et tous les index du
service : `pk_`, `fk_`, `ix_`, `uq_`, `ck_`. Sans eux, deux exécutions d'Alembic sur le même
schéma ne produisent pas les mêmes noms, et donc pas la même migration.

Deux détails ne sont pas des préférences.

**`column_0_N_name`, et surtout pas `column_0_label`.** Avec la seconde forme, deux index
composites commençant par la même colonne reçoivent le **même nom**, sans erreur ni
avertissement — jusqu'à ce que PostgreSQL refuse la seconde création. Or `TenantMixin` impose
précisément que tout index d'une table de tenance commence par `group_id` : la collision
serait la règle, pas l'exception.

**63 octets.** Au-delà, SQLAlchemy ne lève rien : il tronque, en remplaçant la fin du nom par
un condensat. Le DDL passe, la migration aussi — puis Alembic relit en base le nom tronqué, le
compare au nom entier des métadonnées, et propose une suppression suivie d'une recréation à
chaque autogénération, indéfiniment. `check_schema(Base.metadata)`, appelée par le `lifespan`,
refuse le schéma avant d'en arriver là ; l'`env.py` d'Alembic l'appelle aussi — un schéma
fautif n'empêche pas seulement le démarrage, il empêche la migration d'exister (voir
[Migrations](./migrations.md)).

Le motif `ck_` réclame un `%(constraint_name)s`. **Toute `CheckConstraint` doit donc porter un
`name=`**, ainsi que tout `Enum(...)` construit de valeurs littérales, sinon la construction de
la table lève `InvalidRequestError` et c'est l'import du modèle qui échoue. Un `Mapped[bool]`
n'est pas concerné : PostgreSQL a un booléen natif.

Ces cinq motifs **se figent à la première migration** (BACK-07). En changer un ensuite
donnerait à chaque contrainte déjà créée un nom que les métadonnées ne savent plus reproduire.

## Les trois mixins

Ce ne sont pas des classes de base : ils ne sont pas mappés, ils n'ont pas de table, et chaque
agrégat décide de les prendre ou non.

| Mixin            | Ce qu'il ajoute                               | Qui le prend                                  |
| ---------------- | --------------------------------------------- | --------------------------------------------- |
| `UUIDPrimaryKey` | `id`, en tête de table                        | tout agrégat                                  |
| `TimestampMixin` | `created_at` et `updated_at`, en fin de table | tout agrégat                                  |
| `TenantMixin`    | `group_id`                                    | les seuls agrégats **produits par un groupe** |

`sort_order` donne partout la même silhouette — identité, tenance, colonnes propres au modèle,
horodatage. Sans lui, les colonnes héritées se rangent selon l'ordre de résolution des classes.
La première migration (BACK-07) a figé cette silhouette : la changer coûte désormais une
migration.

**`UUIDPrimaryKey` n'a aucun défaut, et c'est le point.** C'est le domaine qui bat la monnaie —
`Account.create()` produit l'identifiant avant qu'il soit question de persistance, et le dépôt
le passe toujours explicitement. Un `default=` ne serait jamais atteint, et laisserait croire
que la stratégie d'identité se décide dans l'infrastructure.

Le domaine tire des **UUID de version 7**. Leurs 48 premiers bits sont un horodatage : les
insertions se rangent en fin d'index B-tree, sur quelques pages chaudes, là où la version 4 —
uniformément aléatoire — vise une feuille au hasard à chaque ligne, multiplie les divisions de
page et alourdit le journal d'écriture. Sur des tables qui ne font que croître (rendez-vous,
actes cliniques, journal de notifications), l'écart se paie à l'échelle.

La contrepartie est réelle et se dit : cet horodatage est **en clair**. Qui détient un
identifiant connaît la date de création de la ligne à la milliseconde, et deux identifiants
livrent leur ordre et le temps qui les sépare. Ce n'est pas une faille d'énumération — 74 bits
restent aléatoires — mais c'est une fuite d'antériorité. Un agrégat qui aurait besoin d'un
identifiant public réellement opaque devra porter un second identifiant aléatoire, plutôt que
dégrader la clé primaire de toutes les tables.

**`TimestampMixin` fait de PostgreSQL l'horloge.** `server_default=func.now()` plutôt qu'un
défaut calculé en Python : trois processus uvicorn, un worker, une migration et une session
`psql` n'ont aucune raison d'être d'accord entre eux. C'est aussi ce qui donne un horodatage
aux lignes insérées à la main, ce qu'un défaut Python ne fait jamais. `func.now()` vaut
`transaction_timestamp()` : la valeur est **gelée pour toute la transaction**, donc toutes les
lignes d'un même commit partagent exactement le même `created_at` — « créées ensemble » devient
une égalité.

`updated_at` a une limite qu'il faut connaître : `onupdate` est orchestré par SQLAlchemy, donc
un `UPDATE` qui ne passe pas par l'ORM — migration de données, correction en `psql` — ne le
déclenche pas. `server_onupdate` ne réglerait rien, il est purement informatif. Le jour où
`updated_at` deviendra porteur pour une synchronisation, il faudra un déclencheur
`BEFORE UPDATE`, et sa place sera dans une migration.

## La tenance est opt-in, et la garde est mécanique

`TenantMixin` ne se déclare que sur les agrégats **produits par un groupe et conservés sous sa
garde** — les contre-exemples qui valent règle (`Consultation` le porte, `Animal` et le compte
non) et leurs motifs sont consignés dans les ADR
[0004](../adr/0004-tenance-par-groupe.md),
[0005](../adr/0005-appartenance-datee.md) et
[0006](../adr/0006-dossier-medical-animal.md). Le filtre correspondant ne
sera **jamais** appliqué globalement dans le dépôt de base : c'est BACK-06b qui l'appliquera,
aux seuls agrégats déclarant le mixin.

Déclarer le mixin **oblige** la table à porter un index — ou une contrainte d'unicité, que
PostgreSQL sert par un index — dont la première colonne est `group_id`. Le contrôle vit dans
`__init_subclass__` et tombe donc à l'**import** du modèle, où un simple
`python -c "import app.main"` le rencontre. Les points d'accroche `__declare_last__` et
`after_configured`, eux, n'auraient tiré qu'à la première requête ORM — c'est-à-dire en erreur
500 depuis une route.

Pourquoi une garde plutôt qu'une consigne : un index manquant ne casse rien. Il produit un
balayage séquentiel, donc une requête lente, invisible sur un jeu de développement et sensible
le jour où un client a des données. Ce genre d'oubli ne se rattrape pas à la relecture.

`group_id` ne porte **pas** de clé étrangère vers `groups`. La table n'existe pas avant
BACK-16, et une `ForeignKey` posée d'avance casserait `metadata.sorted_tables` — donc
`alembic revision --autogenerate` pour tout le projet — dès le premier modèle adoptant le mixin.
La dette est assumée dans
l'[ADR-0004](../adr/0004-tenance-par-groupe.md) : BACK-16 posera la
contrainte table par table, quand `groups` existera.

## Ce que la session promet, et ce qu'elle coûte

`build_sessionmaker(engine)` livre la **fabrique**, pas la session. La différence n'est pas de
style : ouvrir une session, la refermer et décider du commit sont le travail de l'unité de
travail (BACK-06a), dont le but déclaré est que la couche application ne voie jamais une
`AsyncSession`. Une dépendance `get_session()` publiée ici serait exactement l'affordance qui
rend cette promesse intenable.

`expire_on_commit=False` n'est pas facultatif en asynchrone : avec le défaut, `commit()` périme
les instances suivies, et le premier accès à un attribut déclenche un `SELECT` paresseux qui,
hors contexte greenlet, lève `MissingGreenlet`. Ce que cela coûte, honnêtement : les objets
gardent les valeurs de **leur** transaction, donc une ligne modifiée entre-temps par une autre
requête ne se voit pas. Avec une session par requête, la fenêtre dure une requête, et le passage
par une entité du domaine fait que la péremption ne sort jamais de l'infrastructure.

Deux pièges que l'[unité de travail](./unite-de-travail.md) (BACK-06a) affronte désormais : le
premier reste à connaître — `rollback()` périme les instances **quoi qu'il arrive**, donc
journaliser `account.email` après l'annulation lève `MissingGreenlet` au lieu de rendre une
valeur périmée, et ce qu'on veut tracer se capture avant. Le second est résolu mécaniquement :
une session réutilisée d'un bloc `async with` à l'autre resservirait son identity map sans
relire la base, et l'unité de travail ouvre pour cela une session **neuve** à chaque bloc.

`autoflush=False` enfin : avec le défaut, un `find_by_email()` appelé après un `add()` provoque
un flush implicite, et la violation d'unicité remonte alors depuis la **lecture**, au mauvais
endroit et sous le mauvais nom.

Les ressources ouvertes se récupèrent par `get_database(request)`, qui rend un `Database`
portant le moteur et la fabrique. Une clé, un type, un accesseur : c'est la forme que
reprendront le client Redis (BACK-14) et le broker TaskIQ (BACK-15). L'`isinstance` qu'il
contient n'est pas de la défense pour rien — `app.state` est typé `Any`, Mypy strict refuse d'en
retourner la valeur telle quelle, et le contrôle transforme au passage une application
construite sans son `lifespan` en message lisible.

## Vérifier que le socle tient

Quatre sondes, dans le même esprit que celles de la
[configuration](./configuration.md#vérifier-que-le-filet-tient). Depuis `backend/api/`, avec la pile levée.

La première montre le démarrage, puis le refus. Le port hors service se passe en variable
d'environnement, ce qui évite d'arrêter PostgreSQL pour le reste de la pile :

```bash
uv run uvicorn app.main:app --port 8001
```

Attendu : `Application startup complete.`, et un arrêt propre au `Ctrl-C`. Puis :

```bash
POSTGRES_PORT=5999 uv run uvicorn app.main:app --port 8001 ; echo "code de sortie : $?"
```

Attendu : `PostgreSQL injoignable sur localhost:5999 (base « juui », utilisateur « juui »)`,
suivi de `Application startup failed. Exiting.` et de `code de sortie : 3`.

La deuxième imprime le schéma réellement produit pour `accounts` :

```bash
uv run python -c "
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from app.modules.identity.infrastructure.db.models import AccountModel
print(CreateTable(AccountModel.__table__).compile(dialect=postgresql.dialect()))
"
```

Attendu : les colonnes dans l'ordre `id`, … , `created_at`, `updated_at`, avec `id UUID`,
`TIMESTAMP WITH TIME ZONE DEFAULT now()`, et surtout `CONSTRAINT pk_accounts PRIMARY KEY (id)`
— la convention de nommage à l'œuvre.

La troisième éprouve la garde de tenance, dans les deux sens :

```bash
uv run python - <<'PY'
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, SchemaConventionError
from app.shared.infrastructure.db.mixins import TenantMixin, UUIDPrimaryKey

try:

    class SansIndex(UUIDPrimaryKey, TenantMixin, Base):
        __tablename__ = "sonde_sans_index"
        label: Mapped[str] = mapped_column(String(10))

except SchemaConventionError as error:
    print("REFUSE :", error)


class AvecIndex(UUIDPrimaryKey, TenantMixin, Base):
    __tablename__ = "sonde_avec_index"
    label: Mapped[str] = mapped_column(String(10))
    __table_args__ = (Index(None, "group_id", "label"),)


print("ACCEPTE :", [index.name for index in AvecIndex.__table__.indexes])
PY
```

Attendu : le refus nomme la table et donne la ligne à écrire, puis
`ACCEPTE : ['ix_sonde_avec_index_group_id_label']`.

La quatrième fait un aller-retour réel. Elle travaille sur `app_test`, la base que INFRA-01
crée pour les opérations destructrices — **jamais** sur la base applicative :

```bash
uv run python - <<'PY'
import asyncio

from sqlalchemy import text

from app.core import get_settings
from app.modules.identity.domain.entities import Account, AccountType
from app.modules.identity.infrastructure.db.models import AccountModel
from app.modules.identity.infrastructure.db.repositories import SqlAlchemyAccountRepository
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.engine import build_engine, verify_connectivity
from app.shared.infrastructure.db.session import build_sessionmaker

settings = get_settings()
settings = settings.model_copy(update={"db": settings.db.model_copy(update={"db": "app_test"})})


async def main() -> None:
    engine = build_engine(settings)
    try:
        await verify_connectivity(engine, settings)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with build_sessionmaker(engine)() as session:
            account = Account.create(
                email="Sonde@Example.COM ",
                first_name="Sonde",
                last_name="BACK-05",
                account_type=AccountType.INDIVIDUAL,
            )
            await SqlAlchemyAccountRepository(session).add(account)
            await session.commit()

            # Lire APRES le commit : c'est ce que `expire_on_commit=False` rend possible.
            model = await session.get(AccountModel, account.id)
            print("apres commit :", model.email, model.created_at)
            print("version uuid :", account.id.version)
            print("nom annonce  :", await session.scalar(
                text("SELECT application_name FROM pg_stat_activity WHERE pid = pg_backend_pid()")
            ))
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


asyncio.run(main())
PY
```

Attendu : l'adresse normalisée en minuscules, un horodatage **avec fuseau**, `version uuid : 7`,
et `nom annonce : juui-api/development`.

Les écarts assumés avec le ticket BACK-05 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-05).
