# Juui — service d'API

API du SaaS vétérinaire Juui : FastAPI, architecture hexagonale et DDD.

Ce projet est **hors des workspaces pnpm** à dessein. C'est un projet Python,
outillé par [`uv`](https://docs.astral.sh/uv/) ; les deux chaînes d'outils
coexistent dans le monorepo sans se croiser.

## Prérequis

**`uv` seul.** Nul besoin d'installer Python soi-même ni de créer un
environnement virtuel : `uv` lit [`.python-version`](.python-version), télécharge
l'interpréteur 3.14 s'il manque, et gère `.venv/` de bout en bout.

```bash
brew install uv
```

## Installation

Depuis ce dossier :

```bash
uv sync
```

La commande crée `.venv/`, y installe les dépendances applicatives **et** celles
du groupe `dev`, puis le projet lui-même en mode éditable — c'est ce qui rend le
paquet `app` importable depuis `src/`.

Deux drapeaux interdisent la re-résolution, et ils ne disent pas la même chose.
`--frozen` installe ce que contient [`uv.lock`](uv.lock) **sans le regarder** :
un `pyproject.toml` modifié sans `uv lock` passe en silence. `--locked` refuse de
partir dans ce cas — « the lockfile at `uv.lock` needs to be updated ». C'est
`--locked` qu'emploie la [CI backend](../../.github/workflows/ci-backend.yml),
pour que l'environnement vérifié soit exactement celui du dépôt ; le build Docker
(INFRA-04) et QA-01 s'en tiennent à `--frozen`.

## Démarrage

Un fichier `.env` est nécessaire depuis BACK-03 : l'API valide sa configuration au
démarrage et refuse de partir sans elle. Les valeurs livrées conviennent telles quelles
sur un poste vierge.

**PostgreSQL doit tourner** depuis BACK-05 : l'API ouvre son pool de connexions au
démarrage et refuse de partir si le serveur ne répond pas. Le plus simple est de lever
la base seule depuis la racine du dépôt :

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d postgres
```

Puis, depuis `backend/api/` :

```bash
cp .env.example .env
uv run uvicorn app.main:app --reload
```

La documentation interactive répond alors sur <http://localhost:8000/docs>, et
le contrat OpenAPI sur <http://localhost:8000/openapi.json>.

> L'API sert les [sondes de santé](#surface-http) (`/health/live`,
> `/health/ready`, BACK-08) ; les routes **métier**, elles, restent à venir —
> le routeur du module `identity` est bien monté sous `/api/v1` (BACK-04,
> BACK-08), mais ses routes relèvent de BACK-28 et BACK-29. `/docs` n'affiche
> donc que le groupe `health`, et c'est attendu.

## Structure

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
    │   └── config.py       configuration typée (BACK-03)
    ├── shared/             noyau partagé — pas un module métier
    │   ├── domain/
    │   │   ├── exceptions.py   `DomainError`, racine des erreurs métier
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
    │       └── api/            socle HTTP (BACK-08 ; puis BACK-09, BACK-11)
    │           ├── health.py       sondes `/health/live` et `/health/ready`
    │           └── router.py       routeur racine `/api/v1`, assemblé par `main.py`
    └── modules/            contextes métier, étanches les uns aux autres
        ├── identity/       module pilote — le seul complet à ce stade
        │   ├── domain/         entities, policies, ports, exceptions
        │   ├── application/    use_cases/
        │   ├── infrastructure/ db/ (modèle, dépôt), api/ (schémas, routeur)
        │   └── unit_of_work.py unité de travail du module, `get_identity_uow` (BACK-06a)
        └── organization/   groupes et appartenances (BACK-16)
```

Le paquet s'appelle `app` alors que le projet se nomme `juui-api` : la
correspondance est déclarée par `[tool.uv.build-backend] module-name`.

Le détail de ce découpage — ce que chaque espace a le droit d'importer, et
pourquoi — est l'objet de la section [Architecture](#architecture).

### `main.py`

Le module d'assemblage, et rien d'autre : aucune logique métier n'y a sa place.

- **`create_app()`** construit une instance neuve de l'application — sondes de
  santé et routeur v1 montés, [métadonnées OpenAPI](#surface-http) posées, et
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
  d'ouverture. Trois occupants à ce jour — la validation de la configuration
  (BACK-03), qui précède par construction toute ouverture de ressource, puis le
  [moteur PostgreSQL](#persistance) (BACK-05), puis le [cache Redis](#cache)
  (BACK-14), puis le [stockage objet](#stockage-objet) (BACK-13) — chacun fermé
  avant celui qui l'a ouvert. Le broker TaskIQ (BACK-15) suivra. Les trois ne
  traitent pas l'indisponibilité de la même façon, et c'est délibéré :
  [le tableau de l'asymétrie](#lasymétrie-du-service-a-trois-temps-pas-deux) dit
  laquelle choisir pour la ressource suivante.

## Architecture

Hexagonale — ports et adaptateurs — **à l'intérieur de modules métier**, et non un domaine plat :
c'est le **module** qui porte la frontière, la couche ne décrit que le sens des dépendances. Le
pourquoi de ce découpage, et les alternatives écartées, sont consignés dans
l'[ADR-0003](../../documentation/docs/adr/0003-monolithe-modulaire.md).

Les règles ci-dessous sont **mécaniques** depuis BACK-04b : les contrats
d'[Import Linter](#import-linter) font échouer la CI sur toute violation.

### Les trois espaces

| Espace     | Ce qu'il porte                                                                           | Ce qu'il importe   |
| ---------- | ---------------------------------------------------------------------------------------- | ------------------ |
| `core/`    | réglages du **processus** : configuration (BACK-03), journalisation (BACK-11)            | rien du métier     |
| `shared/`  | noyau **partagé** : racine des erreurs, ports techniques, socles de persistance et d'API | `core/`            |
| `modules/` | les **contextes métier**, étanches les uns aux autres                                    | `core/`, `shared/` |

La relation entre les deux derniers est à sens unique : `modules/` → `shared/` est autorisé,
`shared/` → `modules/` ne l'est jamais — c'est le contrat `service-spaces`
d'[Import Linter](#import-linter) qui le tient.

`core/` **reste en place** et n'a pas été fondu dans `shared/` : ce qu'il contient règle le
processus, pas l'architecture.

### Un module, trois couches

| Couche            | Contient                                                | Connaît                                   |
| ----------------- | ------------------------------------------------------- | ----------------------------------------- |
| `domain/`         | entités, politiques, ports métier, exceptions           | la bibliothèque standard, `shared.domain` |
| `application/`    | cas d'usage, un fichier par intention                   | `domain/`                                 |
| `infrastructure/` | modèle SQLAlchemy et dépôt, schémas Pydantic et routeur | `domain/` et `application/`               |

**Les dépendances pointent vers l'intérieur** : l'infrastructure dépend du domaine, jamais
l'inverse. C'est la seule direction que l'architecture interdit, et elle se vérifie d'une ligne —
aucun import de `fastapi`, `sqlalchemy` ou `pydantic` dans un `domain/`.

Trois anti-patrons sont proscrits, tous nommés par le guide de référence : l'entité **anémique**
(une dataclass sans méthode, dont les règles vivent ailleurs), la **session** de base injectée
dans un cas d'usage, et l'`HTTPException` levée depuis le domaine — qui rendrait le même code
inutilisable depuis une tâche de fond, où personne n'attend de code HTTP.

### La règle des 3 modèles

Chaque couche a **son** modèle, et le passage de l'un à l'autre s'écrit à la main.

| Modèle                | Fichier                         | Technologie    | Rôle                                                            |
| --------------------- | ------------------------------- | -------------- | --------------------------------------------------------------- |
| Schéma d'API          | `infrastructure/api/schemas.py` | Pydantic       | valider l'entrée, mettre en forme la sortie, documenter OpenAPI |
| Entité du domaine     | `domain/entities.py`            | dataclass      | les règles et l'état ; zéro dépendance technique                |
| Modèle de persistance | `infrastructure/db/models.py`   | SQLAlchemy 2.0 | colonnes, types et contraintes                                  |

Un `Account(**model.__dict__)` fonctionnerait aujourd'hui et casserait **en silence** au premier
champ que le domaine nomme autrement que la base, en remplissant l'entité de valeurs par défaut.
Le mapping explicite, lui, échoue chez Mypy et non en production ; il rend aussi visibles les
conversions qui comptent — `str` en base, `AccountType` dans le domaine.

### Le trajet, sur le module pilote

`identity` est le module de référence posé par BACK-04, et le seul complet à ce stade. Une
création de compte le traverse ainsi :

| #   | Étape                                                                        | Fichier                                      |
| --- | ---------------------------------------------------------------------------- | -------------------------------------------- |
| 1   | `AccountCreate` valide le JSON reçu                                          | `infrastructure/api/schemas.py`              |
| 2   | `.to_command()` en fait une `CreateAccountCommand`, sans vocabulaire HTTP    | `infrastructure/api/schemas.py`              |
| 3   | `CreateAccount.execute()` normalise, contrôle l'unicité, appelle la fabrique | `application/use_cases/create_account.py`    |
| 4   | `Account.create()` applique les règles et attribue l'identifiant             | `domain/entities.py`                         |
| 5   | `AccountRepository.add()` reçoit **l'entité**, jamais un modèle              | `domain/ports.py`                            |
| 6   | `_to_model()` traduit l'entité en ligne de la table `accounts`               | hérité de `shared/…/db/repositories/base.py` |
| 7   | `AccountRead.from_entity()` remonte l'entité en réponse JSON                 | `infrastructure/api/schemas.py`              |

La commande de l'étape 2 n'est **pas** un quatrième modèle du compte : elle décrit une
_intention_, pas un état persistant. C'est ce qui permet d'appeler le cas d'usage depuis une
route, une tâche de fond ou une commande en ligne sans changer sa signature.

Le cas d'usage ne reçoit qu'un **port**, jamais une session : depuis BACK-06a, c'est
l'[unité de travail](#unité-de-travail) du module qui entre dans son constructeur, et ses
dépôts n'existent que dans le bloc `async with` qui délimite la transaction.

Deux détails du trajet valent d'être signalés, parce qu'ils illustrent où se rangent les règles :

- la **normalisation** de l'adresse et du téléphone est une politique du domaine
  (`domain/policies.py`), appelée par la fabrique de l'entité. Elle n'est pas dans la route : un
  second point d'entrée l'oublierait, et deux comptes naîtraient pour une seule personne ;
- le choix des champs **exposés** se fait dans `AccountRead`, à la sortie. La minimisation des
  données (BACK-26) se décide là, pas dans l'entité, qui doit rester complète pour le métier.

### L'indépendance des modules

Un module n'importe **jamais** l'intérieur d'un autre : ni son entité, ni son dépôt, ni son
modèle de persistance, ni une jointure sur ses tables. Les échanges passent par les cas d'usage
publics du module cible — c'est-à-dire par la surface qu'il a choisi d'exposer, et qu'il peut
donc tenir dans le temps. Ce que cette étanchéité coûte, et l'entorse assumée de la `Base`
déclarative partagée, sont consignés dans les conséquences de
l'[ADR-0003](../../documentation/docs/adr/0003-monolithe-modulaire.md).

Depuis BACK-04b, la règle n'est plus seulement écrite : le contrat
[`module-independence`](#import-linter) la fait respecter, dans les deux sens et **même
indirectement**.

**Le piège à éviter** : ne pas calquer les modules sur les trois frontends — ce sont des canaux
de livraison, pas des contextes métier. L'alternative est instruite et écartée dans
l'[ADR-0003](../../documentation/docs/adr/0003-monolithe-modulaire.md).

### Les modules prévus

Six modules, chacun répondant à une question. Leur tableau vit dans
l'[ADR-0003](../../documentation/docs/adr/0003-monolithe-modulaire.md) ; la docstring de
[`src/app/modules/__init__.py`](src/app/modules/__init__.py) le porte aussi, au plus près du
code.

### Ce que la structure attend encore

Les dossiers vides ne le sont pas par oubli : chacun porte une docstring qui dit ce qui vient s'y
ranger, et quel ticket l'apporte.

| Emplacement                        | Ce qui manque                                                       | Ticket                    |
| ---------------------------------- | ------------------------------------------------------------------- | ------------------------- |
| `shared/domain/ports/`             | `TokenService`                                                      | BACK-10a                  |
| `shared/domain/exceptions.py`      | la hiérarchie complète et les codes `<module>.<ressource>.<erreur>` | BACK-09                   |
| `shared/infrastructure/db/`        | le filtre de tenance, dans `repositories/`                          | BACK-06b                  |
| `shared/infrastructure/api/`       | handlers d'erreur, intergiciels, identifiant de requête             | BACK-09, BACK-11          |
| `modules/identity/…/api/routes.py` | inscription, connexion, réinitialisation de mot de passe            | BACK-28, BACK-29, BACK-31 |
| `modules/organization/`            | groupes, cliniques, appartenances, affectations                     | BACK-16                   |

### Vérifier que les règles tiennent

Même esprit que la sonde de [Mypy](#mypy) et celles de la
[configuration](#vérifier-que-le-filet-tient). Depuis `backend/api/`.

**Les règles d'architecture** (BACK-04b). Attendu : `Contracts: 5 kept, 0 broken.`

```bash
make imports
```

Ce n'est plus une sonde qu'il faut penser à lancer : `make lint` l'enchaîne après
Ruff, et la [CI backend](../../.github/workflows/ci-backend.yml) la rejoue sur
chaque pull request. Les cinq contrats et la preuve qu'ils mordent : [Import
Linter](#import-linter).

Deux sondes `grep` tenaient ce rôle jusqu'ici. Elles ne manquent pas : une
recherche textuelle lit une ligne à la fois, quand un contrat suit les **chaînes**
d'imports. Un `import sqlalchemy` glissé dans `shared/domain/` ne salit pas que
ce fichier — il salit tout domaine qui en dépend, et le contrat 1 le dit en
affichant la chaîne complète :

```text
app.modules.identity.domain.exceptions -> app.shared.domain.exceptions
app.shared.domain.exceptions -> app.shared.infrastructure.db.base
app.shared.infrastructure.db.base -> sqlalchemy
```

**Le trajet complet des trois modèles.** Le dépôt et l'unité de travail en mémoire sont définis
_dans la sonde_ et non dans `src/` : les doublures de production appartiennent à BACK-06c.

```bash
uv run python - <<'PY'
import asyncio
from uuid import UUID

from app.modules.identity.application.use_cases.create_account import CreateAccount
from app.modules.identity.domain.entities import Account
from app.modules.identity.domain.ports import AccountRepository, IdentityUnitOfWork
from app.modules.identity.infrastructure.api.schemas import AccountCreate, AccountRead
from app.modules.identity.infrastructure.db.repositories import SqlAlchemyAccountRepository


class InMemoryAccountRepository(AccountRepository):
    def __init__(self) -> None:
        self.accounts: dict[UUID, Account] = {}

    async def get(self, account_id: UUID) -> Account:
        return self.accounts[account_id]

    async def find_by_email(self, email: str) -> Account | None:
        return next((a for a in self.accounts.values() if a.email == email), None)

    async def add(self, account: Account) -> None:
        self.accounts[account.id] = account

    async def save(self, account: Account) -> None:
        self.accounts[account.id] = account


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    # Doublure JETABLE : commit et rollback sans effet reel. La doublure de
    # production, ou les deux gestes agissent sur l'etat, appartient a BACK-06c.
    def __init__(self) -> None:
        self._accounts = InMemoryAccountRepository()

    @property
    def accounts(self) -> AccountRepository:
        return self._accounts

    async def __aenter__(self) -> "InMemoryIdentityUnitOfWork":
        return self

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def _release(self) -> None:
        pass


async def walk_through() -> None:
    payload = AccountCreate(
        first_name=" Jean ",
        last_name="Dupont",
        email="  Jean@Exemple.FR ",
        phone="06 12 34 56 78",
        account_type="individual",
    )
    print("1. schema API (Pydantic)  :", payload)

    command = payload.to_command()
    print("2. commande (application) :", command)

    account = await CreateAccount(InMemoryIdentityUnitOfWork()).execute(command)
    print("3. entite (domaine)       :", account)

    # Aucune session n'est necessaire pour le sens entite -> modele : le depot
    # generique ne la touche pas dans `_to_model`.
    model = SqlAlchemyAccountRepository(None)._to_model(account)
    print("4. modele (SQLAlchemy)    :", {c.name: getattr(model, c.name) for c in model.__table__.columns})

    print("5. schema API (reponse)   :", AccountRead.from_entity(account))

    account.verify_email()
    account.suspend()
    print("6. comportements          :", account.status, account.email_verified)
    try:
        account.suspend()
    except Exception as error:
        print("7. invariant tenu         :", type(error).__name__, error)


asyncio.run(walk_through())
PY
```

Attendu : l'adresse arrive ` Jean@Exemple.FR` et ressort `jean@exemple.fr`, le téléphone perd
ses séparateurs, l'identifiant est attribué par le domaine avant tout aller-retour SQL, et la
seconde suspension est refusée par l'entité elle-même — la preuve qu'elle n'est pas anémique.

**L'application démarre et monte le routeur.**

```bash
uv run uvicorn app.main:app
```

Puis, dans un autre terminal :

```bash
curl -s http://localhost:8000/openapi.json | python3 -m json.tool
```

Attendu : `"paths": {}`. Le routeur d'`identity` est bien monté — il ne porte simplement encore
aucune route, et `/docs` reste donc vide.

### Écarts assumés avec le ticket BACK-04

| Écart                                                                  | Raison                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Le routeur d'`identity` est monté mais ne porte aucune route           | Une route de création avait besoin d'une session (BACK-05) et d'une unité de travail (BACK-06a), livrées depuis. Ce qui manque désormais est **métier** — mot de passe (BACK-10b), non-divulgation (BACK-09), vérification (BACK-17) — et les routes viennent en BACK-28 et BACK-29.                                                             |
| `Base` déclarée ici, mais nue                                          | Le ticket la nomme dans sa portée, et le module pilote en a besoin pour déclarer sa table. La convention de nommage des contraintes, les mixins, le moteur et la session restent à BACK-05.                                                                                                                                                      |
| Le cas d'usage reçoit un dépôt et non une unité de travail             | Résorbé depuis : BACK-06a a livré l'[unité de travail](#unité-de-travail), et le cas d'usage la reçoit. Le contrat qui compte n'a jamais cessé d'être tenu : ce qui entre dans un cas d'usage est un **port**, jamais une session.                                                                                                               |
| `create_account` recouvre partiellement BACK-28                        | C'est le seul trajet d'**écriture** démontrable aujourd'hui, et le critère d'acceptation demande le sens schéma → entité → modèle. BACK-28 le reprendra en `register_individual`, avec mot de passe, OTP et non-divulgation.                                                                                                                     |
| `shared/domain/exceptions.py` réduit à `DomainError`                   | La hiérarchie intermédiaire et les codes namespacés sont la portée de BACK-09. Les exceptions d'`identity` héritent donc de la racine en attendant d'être reparentées.                                                                                                                                                                           |
| `shared/domain/ports/` ne contient qu'une docstring                    | `Cache`, `FileStorage` et `TokenService` appartiennent à BACK-14, BACK-13 et BACK-10a. Le paquet existe pour fixer leur place, pas pour les anticiper.                                                                                                                                                                                           |
| `identity/unit_of_work.py` réduit à une docstring                      | Le fichier était nommé par la portée du ticket, son contenu était celui de BACK-06a — qui l'a rempli depuis. Il fixait la place, tenue : à la racine du module, pas dans une couche.                                                                                                                                                             |
| `domain/entities.py` plat, et non un dossier `domain/entities/`        | Le guide de référence montre un dossier ; c'est le ticket lui-même qui l'écarte, et pour une bonne raison — un dossier d'entités partagé est exactement le domaine plat qu'il s'agit d'éviter.                                                                                                                                                   |
| `str` et non `EmailStr` pour l'adresse                                 | `EmailStr` dépend d'`email-validator`, qui n'est pas une dépendance déclarée du projet. La validation de forme relève de BACK-28, l'unicité insensible à la casse d'INFRA-09.                                                                                                                                                                    |
| Type et statut stockés en `String` et non en enum natif                | Ajouter une valeur à un enum PostgreSQL exige une migration, et le mapping explicite vers `AccountType` devient visible plutôt que magique — ce que la règle des 3 modèles demande précisément de montrer.                                                                                                                                       |
| Le contrôle automatique de la checklist historique n'est pas livré ici | Il est **extrait dans BACK-04b**, et livré depuis : cinq contrats [import-linter](#import-linter) déclarés dans [`pyproject.toml`](pyproject.toml), câblés à `make lint` et à la [CI backend](../../.github/workflows/ci-backend.yml). Les deux sondes `grep` qui en tenaient lieu ont été retirées.                                             |
| `alembic.ini` réattribué à BACK-07, et l'entrypoint corrigé            | INFRA-04 écrivait que le fichier arriverait avec BACK-05 ; la carte BACK-07 le porte dans sa propre portée. Trois endroits l'affirmaient à tort — [`entrypoint.sh`](../../docker/api/entrypoint.sh), son message de journal et le [README de la racine](../../README.md#ce-que-fait-lentrypoint) — et rien ne les aurait démentis avant BACK-07. |
| Aucun test automatisé, mais des sondes documentées                     | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02 et BACK-03.                                                                                                                                                                                                                                         |

## Configuration

Toute la configuration du service tient dans un objet unique,
[`Settings`](src/app/core/config.py), typé et validé **au démarrage** : aucun `os.getenv`
n'a sa place ailleurs dans le code. Une variable obligatoire absente arrête le processus en
la nommant, plutôt que de produire une panne au premier appel HTTP.

Les valeurs viennent de deux sources — les variables d'environnement du processus, comme les
recevra le conteneur d'INFRA-04, et le fichier `backend/api/.env` pour un lancement sur le
poste. Ce que signifie chaque variable est écrit dans [`.env.example`](.env.example), son
gabarit ; ce README ne le recopie pas, pour éviter que les deux divergent.

### Les cinq sous-modèles

| Sous-modèle        | Préfixe     | Ce qu'il porte                                    | Consommé par                                 |
| ------------------ | ----------- | ------------------------------------------------- | -------------------------------------------- |
| `AppSettings`      | _aucun_     | environnement, niveau de log, origines CORS       | BACK-08 (environnement), BACK-11 (CORS, log) |
| `DatabaseSettings` | `POSTGRES_` | connexion PostgreSQL                              | BACK-05                                      |
| `RedisSettings`    | `REDIS_`    | connexion Redis, bases de cache et de broker      | BACK-14, BACK-15                             |
| `S3Settings`       | `S3_`       | stockage objet, MinIO en dev et Amazon S3 en prod | BACK-13                                      |
| `JWTSettings`      | `JWT_`      | clé de signature, algorithme, durées de vie       | BACK-10                                      |

Un préfixe par sous-modèle plutôt qu'un délimiteur de nesting : `POSTGRES_USER` et
`MINIO_ROOT_USER` sont imposés par les images Docker, et la traduction n'aurait servi à rien.
L'arbitrage remonte à SETUP-05, il est inscrit au [README de la racine](../../README.md#écarts-assumés-avec-le-ticket-setup-05).

L'accès se fait par sous-modèle : `settings.app.environment`, `settings.db.host`,
`settings.redis.cache_db`, `settings.s3.bucket`, `settings.jwt.algorithm`.

**Sept variables n'ont aucun défaut**, et sont donc obligatoires : `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` et
`JWT_SECRET_KEY`. Elles désignent une base, un bucket ou une clé réels — leur donner un
défaut ne ferait que retarder l'échec jusqu'à la première requête. Toutes les autres portent
une valeur de développement, ce qui rend la copie du gabarit suffisante.

Les secrets sont typés `SecretStr`. Ils n'apparaissent ni dans un `repr`, ni dans
`model_dump(mode="json")` où ils sortent en `'**********'` — leur valeur ne s'obtient que par
un `get_secret_value()` explicite.

### Valeurs dérivées

Les URLs ne se saisissent pas, elles se recomposent à partir de leurs composants. C'est ce
qui évite la seconde source de vérité qu'aurait été un `DATABASE_URL` écrit à la main à côté
d'un `POSTGRES_PASSWORD` : les deux divergeraient au premier changement de mot de passe.

| Propriété                    | Valeur                                  |
| ---------------------------- | --------------------------------------- |
| `settings.db.sqlalchemy_url` | `postgresql+asyncpg://…` — pour BACK-05 |
| `settings.redis.cache_url`   | base `REDIS_CACHE_DB` — pour BACK-14    |
| `settings.redis.broker_url`  | base `REDIS_BROKER_DB` — pour BACK-15   |

Ce sont des **propriétés** et non des champs calculés, à dessein : le mot de passe y figure
en clair, et une propriété n'entre ni dans le `repr` ni dans `model_dump()`. Ne jamais les
journaliser telles quelles.

### Le fichier `.env` est strict

Une clé que ce fichier porte sans qu'aucun champ ne la réclame **empêche le démarrage**, en
la nommant. C'est ce que promet [`.env.example`](.env.example), et c'est ce qui en fait le
miroir exact des champs de `Settings` : une variable qui y figure sans exister dans le code
se signale au premier `uvicorn`, pas six mois plus tard. D'où l'interdiction d'y recopier le
`.env` de la racine — `COMPOSE_PROJECT_NAME` ou `PGADMIN_DEFAULT_EMAIL` suffiraient à bloquer
l'API.

La contrainte est **à sens unique**. Les variables d'environnement du _processus_ sont, elles,
filtrées sur les champs déclarés : le conteneur d'INFRA-04 pourra recevoir tout le `.env` de
la racine, `POSTGRES_HOST_PORT` et `MINIO_API_HOST_PORT` compris, sans que rien ne bronche.

pydantic-settings ne sait pas tenir cette promesse seul : chaque sous-modèle ne voit que son
préfixe, et personne ne surveille le reste du fichier. La source `_OrphanKeyDotEnvSource` de
[`config.py`](src/app/core/config.py) comble ce trou en une douzaine de lignes, et le jeu des
clés admises se calcule par introspection des sous-modèles — il n'y a aucune liste à tenir à
jour à la main.

### Dans le code

`get_settings()` construit `Settings` une seule fois (`@lru_cache`) et s'utilise comme
dépendance FastAPI. L'alias `SettingsDep` évite de répéter l'annotation :

```python
from app.core import SettingsDep


@router.get("/exemple")
def exemple(settings: SettingsDep) -> str:
    return settings.app.environment
```

En test, la dépendance se remplace sans toucher à l'environnement du processus :

```python
app.dependency_overrides[get_settings] = lambda: settings_de_test
```

`get_settings.cache_clear()` remet le cache à zéro entre deux cas.

### Vérifier que le filet tient

Trois sondes, dans le même esprit que celle de [Mypy](#mypy). La première met le `.env` de
côté, puis le remet — le `;` garantit la restauration même en cas d'échec :

```bash
mv .env .env.hors-service ; uv run python -c 'from app.core import get_settings; get_settings()' ; mv .env.hors-service .env
```

Attendu : les sept variables obligatoires listées **d'un seul coup**, chacune sous son nom
d'environnement — et non un `user Field required` qui laisserait deviner le préfixe.

La deuxième ajoute une clé étrangère au fichier, après l'avoir sauvegardé :

```bash
cp .env .env.sonde && echo 'PGADMIN_DEFAULT_EMAIL=dev@example.com' >> .env ; uv run python -c 'from app.core import get_settings; get_settings()' ; mv .env.sonde .env
```

Attendu : `PGADMIN_DEFAULT_EMAIL : cle inconnue -- aucun champ de Settings ne la reclame`.

La troisième montre le masquage des secrets, puis la surcharge de la dépendance :

```bash
uv run python - <<'PY'
import asyncio

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.core import AppSettings, DatabaseSettings, JWTSettings, S3Settings, Settings, SettingsDep, get_settings

print(repr(get_settings().jwt))

application = FastAPI()


@application.get("/sonde")
def sonde(settings: SettingsDep) -> str:
    return settings.s3.bucket


async def appeler() -> str:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://sonde") as client:
        return (await client.get("/sonde")).json()


print("sans surcharge :", asyncio.run(appeler()))

application.dependency_overrides[get_settings] = lambda: Settings(
    app=AppSettings(environment="staging"),
    db=DatabaseSettings(user="u", password=SecretStr("p"), db="d"),
    s3=S3Settings(access_key=SecretStr("a"), secret_key=SecretStr("s"), bucket="bucket-de-test"),
    jwt=JWTSettings(secret_key=SecretStr("k")),
)
print("avec surcharge :", asyncio.run(appeler()))
PY
```

Attendu : `secret_key=SecretStr('**********')`, puis `juui-dev` et `bucket-de-test`.

### Écarts assumés avec le ticket BACK-03

| Écart                                                          | Raison                                                                                                                                                                                                                                  |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `env_prefix` par sous-modèle plutôt que `env_nested_delimiter` | Le ticket prévoit `DB__`, `JWT__`. `POSTGRES_*` et `MINIO_ROOT_*` sont imposés par les images Docker, et les deux gabarits sont écrits ainsi depuis SETUP-05. C'est aussi la seule forme qui permette l'alias de repli S3 ci-dessous.   |
| Une source `.env` maison pour tenir la promesse de strictesse  | Le ticket suppose le comportement natif suffisant. Il ne l'est pas avec des sous-modèles préfixés : chacun ne voit que son préfixe. Sans ces douze lignes, l'en-tête de `.env.example` serait faux.                                     |
| Propriétés plutôt que validateur pour les URLs dérivées        | Le ticket dit « validateur ». Un champ calculé ferait entrer le mot de passe en clair dans le `repr` et dans `model_dump()`, ce que le critère « les secrets n'apparaissent ni dans les logs ni dans les repr » interdit.               |
| `main.py` modifié, hors de la portée déclarée                  | Le ticket limite sa portée à `core/`, mais son critère d'acceptation parle de l'**application** qui refuse de démarrer. Quatre lignes dans le `lifespan`, le point d'accroche que BACK-01 avait laissé vide.                            |
| `AliasChoices` S3 déclaré ici et non en BACK-13                | Le [`.env.example` de la racine](../../.env.example) l'attribue à BACK-13, mais c'est `S3Settings` qui le porte, et cette classe naît ici. Sans lui, le `.env` de la racine — où `S3_ACCESS_KEY` est commentée — ne fonctionnerait pas. |
| `JWT_SECRET_KEY` du gabarit refusée en production              | Hors périmètre littéral. La valeur livrée est un marqueur, pas une clé ; la laisser en place en production est une faille, et c'est le seul endroit du code qui voie à la fois l'environnement et la clé.                               |
| Un `noqa: N804` sur le validateur de modèle                    | BACK-02 apprend à Ruff que `model_validator` produit des méthodes de classe. Ce n'est vrai qu'en mode « before » ; un validateur « after » reçoit `self`, et le renommer casserait l'accès aux sous-modèles.                            |
| `validate_by_name` activé sur `S3Settings`                     | Deux champs obligatoires n'y sont atteignables que par alias, ce que le greffon Mypy de pydantic signale : une surcharge de test devrait écrire `S3Settings(S3_ACCESS_KEY=…)`. La lecture par alias reste active, c'est le défaut.      |
| Aucun test automatisé, mais des sondes documentées             | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02, dont la sonde Mypy a créé le précédent.                                                                                                   |

## Persistance

Le service parle à PostgreSQL avec **SQLAlchemy 2.0 en asynchrone**, sur le pilote
`asyncpg`. Le socle vit dans [`shared/infrastructure/db/`](src/app/shared/infrastructure/db/),
et ce qui l'organise n'est pas la couche mais la **durée de vie** :

| Fichier      | Ce qu'il porte                                                  | Vit le temps |
| ------------ | --------------------------------------------------------------- | ------------ |
| `base.py`    | la `Base` déclarative, la convention de nommage, `check_schema` | de l'import  |
| `mixins.py`  | `UUIDPrimaryKey`, `TimestampMixin`, `TenantMixin`               | de l'import  |
| `engine.py`  | le moteur et son pool de connexions                             | du processus |
| `session.py` | la fabrique de sessions et l'accès aux ressources ouvertes      | du processus |

Rien ne s'ouvre à l'import : c'est le [`lifespan`](#mainpy) qui construit le moteur,
éprouve la connexion, range le tout dans `app.state`, puis referme. La fermeture est dans
un `finally` — un moteur construit avant un `SELECT 1` en échec doit être libéré lui aussi,
faute de quoi une boucle de redémarrage de conteneur fuit un pool à chaque tour.

### Le moteur et son pool

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

### L'API ne démarre plus sans base

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

### La convention de nommage est figée

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
[Migrations](#migrations)).

Le motif `ck_` réclame un `%(constraint_name)s`. **Toute `CheckConstraint` doit donc porter un
`name=`**, ainsi que tout `Enum(...)` construit de valeurs littérales, sinon la construction de
la table lève `InvalidRequestError` et c'est l'import du modèle qui échoue. Un `Mapped[bool]`
n'est pas concerné : PostgreSQL a un booléen natif.

Ces cinq motifs **se figent à la première migration** (BACK-07). En changer un ensuite
donnerait à chaque contrainte déjà créée un nom que les métadonnées ne savent plus reproduire.

### Les trois mixins

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

### La tenance est opt-in, et la garde est mécanique

`TenantMixin` ne se déclare que sur les agrégats **produits par un groupe et conservés sous sa
garde** — les contre-exemples qui valent règle (`Consultation` le porte, `Animal` et le compte
non) et leurs motifs sont consignés dans les ADR
[0004](../../documentation/docs/adr/0004-tenance-par-groupe.md),
[0005](../../documentation/docs/adr/0005-appartenance-datee.md) et
[0006](../../documentation/docs/adr/0006-dossier-medical-animal.md). Le filtre correspondant ne
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
l'[ADR-0004](../../documentation/docs/adr/0004-tenance-par-groupe.md) : BACK-16 posera la
contrainte table par table, quand `groups` existera.

### Ce que la session promet, et ce qu'elle coûte

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

Deux pièges que l'[unité de travail](#unité-de-travail) (BACK-06a) affronte désormais : le
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

### Vérifier que le socle tient

Quatre sondes, dans le même esprit que celles de la
[configuration](#vérifier-que-le-filet-tient). Depuis `backend/api/`, avec la pile levée.

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

### Écarts assumés avec le ticket BACK-05

| Écart                                                              | Raison                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Account.create()` tire un UUID de **version 7**                   | Hors de la portée déclarée, qui s'arrête à `shared/`. Mais le mixin promet une localité d'index que seul le domaine peut tenir : c'est lui qui bat la monnaie, et une v4 rendrait la promesse fausse dès la première table.                                                                      |
| `AccountModel` adopte deux des trois mixins                        | Hors portée également, mais annoncé par la docstring de BACK-04 — « les mixins de BACK-05 remplaceront les déclarations équivalentes ». Gratuit tant qu'aucune migration n'existe, et c'est la seule preuve exécutable que les mixins fonctionnent.                                              |
| Quatre variables `POSTGRES_*` et `docker-compose.yml` modifié      | Le ticket dit « paramétrables » sans nommer les variables. La liste `environment:` du service `api` est explicite : sans ces quatre lignes, les réglages ne seraient atteignables que hors conteneur. Le `:-` leur donne un défaut, un `.env` antérieur suffisant sinon à empêcher le démarrage. |
| `POSTGRES_ECHO` en champ dédié, et non déduit de `LOG_LEVEL`       | `echo` journalise les paramètres liés : adresses aujourd'hui, empreintes de mot de passe en BACK-10b, secret TOTP en BACK-18. Personne ne doit déclencher cela en passant `LOG_LEVEL=DEBUG` pour suivre un problème de routage.                                                                  |
| `group_id` sans clé étrangère vers `groups`                        | Vérifié : la table n'existe pas avant BACK-16, et une `ForeignKey` posée d'avance casse `metadata.sorted_tables`, donc l'autogénération Alembic de tout le projet. Elle rendrait de plus chaque module structurellement dépendant d'`organization`.                                              |
| Une garde mécanique plutôt qu'une consigne pour l'index de tenance | Le ticket demande l'index, pas le mécanisme. Un balayage séquentiel ne plante pas — il ralentit, une fois qu'un client a des données, et c'est trop tard pour le voir en revue.                                                                                                                  |
| `check_schema` et la limite des 63 octets                          | Hors périmètre littéral. SQLAlchemy tronque en silence avec un condensat, Alembic l'ignore, et l'autogénération reproposerait le même index à chaque exécution — un symptôme qui se lit comme un défaut d'Alembic, ce qu'il n'est pas.                                                           |
| Aucune dépendance `get_session()`                                  | Le ticket ne la demandait pas, et BACK-06a interdisait déjà d'exposer la session à la couche application — c'est désormais tenu : l'[unité de travail](#unité-de-travail) consomme la fabrique, et le dépôt reçoit sa session en argument.                                                       |
| `autoflush=False` sur la fabrique                                  | Non demandé. Avec le défaut, une violation d'unicité remonte depuis une **lecture** — au mauvais endroit et sous le mauvais nom.                                                                                                                                                                 |
| `main.py` modifié, hors de la portée déclarée                      | Même arbitrage qu'en BACK-03 : la portée dit `shared/infrastructure/db/`, mais le critère d'acceptation parle du `lifespan` qui ferme le moteur.                                                                                                                                                 |
| `DatabaseUnavailableError` distincte de `ConfigurationError`       | Une base injoignable est une configuration **valide** et une panne d'exécution. Les confondre enverrait l'exploitant relire un fichier correct pendant que le serveur finit de démarrer.                                                                                                         |
| Le premier `[[tool.mypy.overrides]]` du projet                     | `asyncpg` ne livre pas de `py.typed`, et `engine.py` doit nommer ses exceptions : SQLAlchemy n'enveloppe pas les échecs survenus **dans** `asyncpg.connect()`. La dérogation est par module, comme BACK-02 l'avait prévu — il pariait seulement qu'elle n'arriverait jamais.                     |
| Aucun test automatisé, mais des sondes documentées                 | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02, BACK-03 et BACK-04.                                                                                                                                                                                |

## Unité de travail

BACK-06a livre la pièce que tout le socle de persistance annonçait : le **pattern Unit of
Work**, qui donne aux cas d'usage l'atomicité sans leur montrer la session. Un cas d'usage
ouvre un bloc, lit et écrit par ses dépôts, décide du commit — et ne sait toujours pas que
SQLAlchemy existe :

```python
async with uow:
    account = await uow.accounts.get(account_id)
    account.verify_email()
    await uow.accounts.save(account)
    await uow.commit()
```

### Le port, et sa promesse

[`AbstractUnitOfWork`](src/app/shared/domain/ports/unit_of_work.py) est le troisième port
technique du noyau, et sa réponse à la panne complète la série : `Cache` **dégrade**,
`FileStorage` **lève**, l'unité de travail **lève et annule**. Un `commit()` en échec remonte à
l'appelant, et toute sortie de bloc sans commit explicite — exception comprise — n'écrit rien.

Ce rollback automatique n'est pas une consigne : `__aexit__` est la **seule méthode concrète du
port**, une méthode-gabarit qui enchaîne `rollback()` puis la libération des ressources, et que
tous les adaptateurs héritent — celui de SQLAlchemy comme la doublure en mémoire de BACK-06c. La
promesse centrale du pattern est ainsi du code partagé, pas une discipline à reproduire.

Le rollback de sortie est **inconditionnel**, sans drapeau « déjà commité » : après un commit,
la session n'a pas rouvert de transaction et `rollback()` est un geste vide, sans SQL émis. Un
drapeau serait d'ailleurs faux — un bloc peut commiter **puis** continuer à lire ou écrire, et
c'est précisément cette transaction implicite de fin de bloc que le rollback inconditionnel
nettoie.

Trois règles engagent l'appelant, écrites au port et tenues par des gardes :

| Règle                               | Ce qui se passe sinon                                                     |
| ----------------------------------- | ------------------------------------------------------------------------- |
| le commit est **explicite**         | sortir sans `commit()` annule tout — oublier de valider n'écrit jamais    |
| **un seul bloc** à la fois          | rentrer dans une unité déjà ouverte lève `RuntimeError`                   |
| la transaction **vit dans le bloc** | `commit()`, `rollback()` et les dépôts lèvent `RuntimeError` hors du bloc |

Rouvrir la **même** unité après la sortie d'un bloc est en revanche permis : chaque entrée
fabrique une session neuve — c'est la doctrine « une session par bloc » de
[la section Persistance](#ce-que-la-session-promet-et-ce-quelle-coûte), rendue mécanique. La
fermeture est même définitive (`close_resets_only=False`) : un dépôt capturé dans un bloc et
rejoué après la sortie lève une erreur SQLAlchemy au lieu de rouvrir une connexion en douce.

### Une unité de travail par module

Il n'existe **pas** d'unité de travail globale, et c'est une décision d'architecture consignée
dans l'[ADR-0009](../../documentation/docs/adr/0009-unite-de-travail-par-module.md) : chaque
module dérive son port — [`IdentityUnitOfWork`](src/app/modules/identity/domain/ports.py) le
premier — qui n'expose que les dépôts de ce module. Ce qu'on ne peut pas placer dans une seule
transaction devient une frontière **visible** — `identity` et `organization` ne partagent pas
leur atomicité — plutôt qu'une dette invisible que le premier incident révélera.

Le port du module vit dans son **domaine**, et l'implémentation
[`SqlAlchemyIdentityUnitOfWork`](src/app/modules/identity/unit_of_work.py) à la **racine** du
module — la place que BACK-04 avait fixée : le point d'assemblage, ni domaine ni tout à fait
infrastructure. La raison du dédoublement est mécanique autant qu'architecturale : le fichier
racine importe l'infrastructure, et un cas d'usage qui le nommerait créerait la chaîne
`application → infrastructure` que le contrat [`module-layers`](#import-linter) refuse. Le cas
d'usage type donc sur le port, qui ne connaît que le domaine — et c'est ce qui permettra à
BACK-06c de substituer sa doublure sans toucher une signature.

Les dépôts du module sont des **propriétés paresseuses**, pas des attributs posés à l'entrée du
bloc : un attribut survivrait à la sortie, dépôt mort en main, tandis que la propriété repasse
par la garde de l'unité à chaque accès — servir un dépôt hors bloc est donc structurellement
impossible.

### Le dépôt générique

[`SqlAlchemyRepository`](src/app/shared/infrastructure/db/repositories/base.py) porte ce qui se
répétait à l'identique d'un agrégat à l'autre : `get`, `list`, `add`, `save`, `delete`, et la
mécanique du mapping. Un dépôt concret ne déclare plus que ce qui lui appartient :

| Déclaration          | Chez `identity`                                    |
| -------------------- | -------------------------------------------------- |
| `_model_type`        | `AccountModel`                                     |
| `_not_found_error`   | `AccountNotFoundError`                             |
| `_not_found_message` | « Aucun compte ne porte l'identifiant… »           |
| `_to_entity`         | ligne → `Account`, conversions de types visibles   |
| `_apply_to_model`    | `Account` → ligne suivie, sans jamais toucher `id` |

**Deux** fonctions de mapping et non trois : `_to_model`, le sens « entité neuve → ligne à
insérer », est dérivé dans le générique — un modèle neuf reçoit l'identifiant, puis
`_apply_to_model` fait le reste. « L'identifiant n'est jamais reporté » cesse d'être une
consigne : `save` ne passe que par `_apply_to_model`, qui ne le touche pas, structurellement.

Le vocabulaire du protocole [`Repository`](src/app/shared/domain/ports/repository.py) décrit la
surface **complète** de l'infrastructure générique ; le port métier du module, lui, la
**rétrécit**. `AccountRepository` n'expose ni `list` ni `delete` — ses cas d'usage n'en ont pas
le droit — alors que la classe concrète les sait faire : le port ne s'élargit pas parce que la
classe sait faire plus. C'est aussi pourquoi le port métier n'hérite **pas** du protocole : en
hériter ferait entrer les cinq opérations dans son contrat.

Quatre comportements valent d'être nommés, parce qu'ils se décident ici pour tous les agrégats :

- `get`, `save` et `delete` lèvent **l'erreur du module** — l'absence est une erreur quand on
  tient l'identifiant d'un jeton ou d'une URL, la doctrine `get_`/`find_` du port ne change pas ;
- `add` **flushe sa ligne, sans jamais commiter** : l'INSERT part dans la transaction du bloc —
  que le rollback de sortie sait toujours annuler — et l'entité ajoutée est aussitôt visible du
  reste de son bloc, pour `get`, `save`, `delete` comme pour `find_by_email`. Sans ce flush,
  `autoflush=False` la rendrait invisible à son propre bloc — un `delete` après `add` aurait
  même déclaré la ligne inexistante tout en la laissant partir à l'INSERT au commit. Les
  contraintes remontent donc depuis l'écriture qui les viole : la course résiduelle sur
  l'unicité d'une adresse (deux requêtes passant `find_by_email` ensemble) éclate en
  `IntegrityError` au flush du second `add`, que BACK-09/BACK-28 traduiront ;
- `save` modifie la **ligne suivie** (`session.get` puis `_apply_to_model`), jamais un
  `merge()` d'objet reconstruit qui coûterait un SELECT de plus ;
- `list` suit la clé primaire : les identifiants **UUIDv7** étant horodatés, l'ordre est
  chronologique et déterministe sans colonne de tri — et la sortie est **sans borne**, la
  pagination étant une convention de BACK-24, pas un choix à figer ici en douce.

### `get_identity_uow` : une instance par requête

La dépendance FastAPI vit à la racine du module, à côté de l'implémentation qu'elle assemble,
avec son alias [`IdentityUowDep`](src/app/modules/identity/unit_of_work.py) sur le modèle de
`SettingsDep`. Elle livre une unité **fermée** — la session ne s'ouvrira qu'au `async with` du
cas d'usage — ce qui dispense de tout finaliseur `yield` : une requête abandonnée avant le bloc
n'a rien à nettoyer, une requête annulée en plein bloc voit `__aexit__` dérouler rollback et
fermeture au dépilement.

`get_identity_uow` et non `get_uow` : une unité par module, le nom porte la frontière —
`organization` publiera la sienne. Et le type de retour est le **port** : une route ne sait pas
quelle technologie la sert.

### Vérifier que l'unité de travail tient

Quatre sondes, dans le même esprit que celles du [socle](#vérifier-que-le-socle-tient). Depuis
`backend/api/`. La première se joue **sans conteneur** ; les trois suivantes travaillent sur
`app_test`, la base que INFRA-01 crée pour les opérations destructrices — **jamais** sur la
base applicative.

La première éprouve les gardes : hors bloc, et ré-entrée pendant un bloc.

```bash
uv run python - <<'PY'
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.identity.unit_of_work import SqlAlchemyIdentityUnitOfWork


async def main() -> None:
    uow = SqlAlchemyIdentityUnitOfWork(async_sessionmaker())
    try:
        await uow.commit()
    except RuntimeError as error:
        print("hors bloc :", error)
    async with uow:
        try:
            async with uow:
                pass
        except RuntimeError as error:
            print("re-entree :", error)


asyncio.run(main())
PY
```

Attendu : `hors bloc : Aucune transaction en cours : l'unite de travail ne sert que dans son
bloc async with.` puis `re-entree : Cette unite de travail est deja ouverte : un seul bloc a la
fois.`

La deuxième éprouve le cycle transactionnel — commit effectif, rollback sans commit, rollback
sur exception — en relisant chaque fois depuis un bloc **neuf** de la même unité :

```bash
uv run python - <<'PY'
import asyncio

from app.core import get_settings
from app.modules.identity.domain.entities import Account, AccountType
from app.modules.identity.unit_of_work import SqlAlchemyIdentityUnitOfWork
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.engine import build_engine, verify_connectivity
from app.shared.infrastructure.db.session import build_sessionmaker

settings = get_settings()
settings = settings.model_copy(update={"db": settings.db.model_copy(update={"db": "app_test"})})


def make_account(email: str) -> Account:
    return Account.create(
        email=email,
        first_name="Sonde",
        last_name="BACK-06a",
        account_type=AccountType.INDIVIDUAL,
    )


async def main() -> None:
    engine = build_engine(settings)
    try:
        await verify_connectivity(engine, settings)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        uow = SqlAlchemyIdentityUnitOfWork(build_sessionmaker(engine))

        async with uow:
            await uow.accounts.add(make_account("commite@example.com"))
            visible = await uow.accounts.find_by_email("commite@example.com")
            print("0. visible du bloc :", visible.email if visible else None)
            await uow.commit()
        async with uow:
            found = await uow.accounts.find_by_email("commite@example.com")
            print("1. commite       :", found.email if found else None)

        async with uow:
            await uow.accounts.add(make_account("oublie@example.com"))
        async with uow:
            print("2. sans commit   :", await uow.accounts.find_by_email("oublie@example.com"))

        try:
            async with uow:
                await uow.accounts.add(make_account("panne@example.com"))
                raise RuntimeError("panne simulee")
        except RuntimeError:
            pass
        async with uow:
            print("3. sur exception :", await uow.accounts.find_by_email("panne@example.com"))
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


asyncio.run(main())
PY
```

Attendu : `0. visible du bloc : commite@example.com` — l'écriture flushée est relisible par son
propre bloc —, puis `1. commite : commite@example.com`, puis `2. sans commit : None`, puis
`3. sur exception : None` — seule l'écriture validée existe.

La troisième éprouve le dépôt générique, les cinq opérations et le mapping dans les deux sens.
Elle travaille en session directe : c'est une sonde d'**infrastructure**, assumée comme telle —
un cas d'usage, lui, passe par l'unité de travail.

```bash
uv run python - <<'PY'
import asyncio

from app.core import get_settings
from app.modules.identity.domain.entities import Account, AccountType
from app.modules.identity.domain.exceptions import AccountNotFoundError
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
            accounts = SqlAlchemyAccountRepository(session)

            first = Account.create(
                email="premier@example.com",
                first_name="Premier",
                last_name="Sonde",
                account_type=AccountType.INDIVIDUAL,
            )
            await accounts.add(first)
            await session.commit()

            relu = await accounts.get(first.id)
            print("aller-retour :", relu == first)

            relu.verify_email()
            await accounts.save(relu)
            await session.commit()
            print("sauvegarde   :", (await accounts.get(first.id)).email_verified)

            second = Account.create(
                email="second@example.com",
                first_name="Second",
                last_name="Sonde",
                account_type=AccountType.INDIVIDUAL,
            )
            await accounts.add(second)
            await session.commit()
            print("liste        :", [account.email for account in await accounts.list()])

            await accounts.delete(first.id)
            await session.commit()
            try:
                await accounts.get(first.id)
            except AccountNotFoundError as error:
                print("suppression  :", type(error).__name__, "--", error)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


asyncio.run(main())
PY
```

Attendu : `aller-retour : True` — l'égalité de dataclass prouve le mapping dans les deux sens —
puis `sauvegarde : True`, la liste dans l'**ordre de création** `['premier@example.com',
'second@example.com']`, et la suppression suivie d'un `AccountNotFoundError` portant le message
du module.

La quatrième joue le cas d'usage complet à travers une route, et prouve « une instance par
requête ». L'application est définie **dans la sonde** : les vraies routes appartiennent à
BACK-28.

```bash
uv run python - <<'PY'
import asyncio

import httpx
from fastapi import FastAPI

from app.core import get_settings
from app.modules.identity.application.use_cases.create_account import (
    CreateAccount,
    CreateAccountCommand,
)
from app.modules.identity.domain.entities import AccountType
from app.modules.identity.domain.exceptions import EmailAlreadyUsedError
from app.modules.identity.unit_of_work import IdentityUowDep
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.engine import build_engine, verify_connectivity
from app.shared.infrastructure.db.session import STATE_KEY, Database, build_sessionmaker

settings = get_settings()
settings = settings.model_copy(update={"db": settings.db.model_copy(update={"db": "app_test"})})

application = FastAPI()
seen: list[object] = []


@application.post("/sonde")
async def sonde(uow: IdentityUowDep) -> dict[str, str]:
    seen.append(uow)
    command = CreateAccountCommand(
        email="Sonde@Example.COM ",
        first_name="Sonde",
        last_name="BACK-06a",
        account_type=AccountType.INDIVIDUAL,
    )
    try:
        account = await CreateAccount(uow).execute(command)
    except EmailAlreadyUsedError:
        return {"resultat": "refus"}
    return {"resultat": account.email}


async def main() -> None:
    engine = build_engine(settings)
    try:
        await verify_connectivity(engine, settings)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        setattr(
            application.state,
            STATE_KEY,
            Database(engine=engine, sessionmaker=build_sessionmaker(engine)),
        )

        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://sonde") as client:
            print("premier appel :", (await client.post("/sonde")).json()["resultat"])
            print("second appel  :", (await client.post("/sonde")).json()["resultat"])
            print("une instance par requete :", seen[0] is not seen[1])
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


asyncio.run(main())
PY
```

Attendu : `premier appel : sonde@example.com` — l'adresse normalisée par le domaine — puis
`second appel : refus` — le contrôle d'unicité a vu l'écriture commitée de la première requête —
et `une instance par requete : True`.

### Écarts assumés avec le ticket BACK-06a

| Écart                                                             | Raison                                                                                                                                                                                                                                                                                                                                                             |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| L'implémentation s'appelle `SqlAlchemyIdentityUnitOfWork`         | Le ticket écrit « une `IdentityUnitOfWork` » ; ce nom revient au **port**, dans le domaine du module, que les cas d'usage typent. La raison est mécanique : le fichier racine importe l'infrastructure, et le contrat `module-layers` interdit à `application/` de le nommer.                                                                                      |
| `get_identity_uow` et non `get_uow`                               | Une unité de travail par module : le nom porte la frontière, et `organization` publiera la sienne sans collision.                                                                                                                                                                                                                                                  |
| `list` et `delete` absents du port `AccountRepository`            | Le ticket demande le dépôt de base à cinq opérations, et le contrat du port « ne bouge pas ». Les deux tiennent : la classe concrète hérite des cinq, le port n'expose que ce que ses cas d'usage ont le droit de faire.                                                                                                                                           |
| `delete` lève sur l'absent plutôt que rendre un booléen           | Même doctrine que `get` : on supprime par un identifiant qu'on tient, et un second appel signale un rejeu. Le booléen de `Cache.delete` et `FileStorage.delete` porte la sémantique d'un stockage idempotent, qui n'est pas celle d'un agrégat.                                                                                                                    |
| `Identified` fixe l'identifiant à `UUID`                          | Un paramètre de type sans second cas réel serait de la généralité spéculative : `UUIDPrimaryKey` (BACK-05) fait de l'UUIDv7 la convention du socle.                                                                                                                                                                                                                |
| Rollback de sortie inconditionnel, sans drapeau « commité »       | Après un commit, `rollback()` est un geste vide — vérifié dans la source de SQLAlchemy. Un drapeau serait faux : un bloc peut commiter puis continuer, et sa transaction implicite de fin de bloc doit être nettoyée.                                                                                                                                              |
| La course d'unicité `find`/`add` n'est pas traduite ici           | Deux requêtes passant `find_by_email` ensemble se départagent sur la contrainte unique, en `IntegrityError` au flush du second `add`. La traduction en erreur métier est la frontière de BACK-09 et BACK-28 ; le chemin nominal est couvert par le contrôle du cas d'usage.                                                                                        |
| `add` flushe sa ligne, quand BACK-05 renvoyait le flush au commit | La doctrine de BACK-05 vise le flush **implicite** déclenché par une lecture, toujours désactivé (`autoflush=False`). Sans flush explicite, une entité ajoutée serait invisible à son propre bloc — `delete` après `add` aurait déclaré la ligne inexistante tout en la laissant s'insérer au commit. Le flush part de l'écriture, l'erreur remonte de l'écriture. |
| Arguments positionnels (`/`) ajoutés au port `AccountRepository`  | Seule retouche à un contrat existant, et une fermeture de trou : Mypy ne compare pas les noms de paramètres positionnels entre les deux bases de la classe concrète, et un appel par mot-clé (`account_id=`) aurait passé le typage pour casser à l'exécution.                                                                                                     |
| Aucune route ajoutée                                              | La dépendance `IdentityUowDep` est prête, mais les routes portent des règles métier (BACK-10b, BACK-09, BACK-17) qui appartiennent à BACK-28 et BACK-29.                                                                                                                                                                                                           |
| Aucun test automatisé, mais des sondes documentées                | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02, BACK-03, BACK-04, BACK-05, BACK-13 et BACK-14.                                                                                                                                                                                                                       |

## Migrations

Le schéma est sous contrôle de version depuis BACK-07 : Alembic compare `Base.metadata` — le
registre unique que tous les modèles peuplent — à la base réelle, et chaque écart devient un
fichier de migration rejouable et réversible dans [`alembic/versions/`](alembic/versions/).
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

### Toute migration autogénérée se relit avant d'être commitée

L'autogénération est un **brouillon**, pas une vérité : elle déduit un plan de la différence
entre les métadonnées et la base, et se trompe en silence dès que l'un des deux n'est pas ce
qu'on croit — base non vierge, modèle pas encore importé, type qu'elle ne sait pas comparer.
La relecture est donc obligatoire, et elle vérifie au minimum :

- **l'ordre des colonnes** : identité, tenance, colonnes du modèle, horodatage — la silhouette
  imposée par les `sort_order` des [mixins](src/app/shared/infrastructure/db/mixins.py) ;
- **les noms passés par `op.f()`** (`pk_accounts`, `ix_accounts_email`) : c'est la convention
  de nommage figée qui parle, pas une fantaisie du générateur ;
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
[`script.py.mako`](alembic/script.py.mako) fournit docstrings et annotations. Il ne reste à la
relecture que ce qu'aucun outil ne sait juger : le sens.

### L'URL vient de `Settings`, jamais d'`alembic.ini`

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

### Un seul migrateur à la fois

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

### Le mode hors ligne est refusé

`alembic upgrade head --sql` — générer le SQL sans l'exécuter — lève une `CommandError`
explicite : personne ne consomme de script SQL généré, et le verrou ci-dessus ne peut rien
sérialiser sans connexion. Le refus est écrit et motivé dans l'`env.py` ; c'est là qu'il se
rouvre si un besoin réel apparaît.

### Ajouter un module de modèles

`Base.metadata` ne recense que les tables des modèles effectivement **importés**. Tout
nouveau module métier qui gagne un `infrastructure/db/models.py` doit s'ajouter au tuple
`_MODEL_MODULES` de l'`env.py` — même geste que `_MODULE_ROUTERS` dans `main.py` : la liste
des tables sous contrôle de version se lit d'un coup d'œil. L'oubli ne pardonne pas :
l'autogénération proposerait de **supprimer** les tables du module absent. Le filet est
`make migrate-check` (`alembic check`) : sur une base à jour, il échoue dès que modèles et
migrations divergent — il attend son entrée en CI avec QA-01.

### Vérifier que le cycle tient

PostgreSQL démarré (`docker compose --project-directory . -f docker/docker-compose.yml up -d
postgres` depuis la racine), depuis `backend/api/` :

```bash
uv run alembic upgrade head     # applique tout
uv run alembic current          # -> 41e48e9250af (head)
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

Attendu : `"pk_accounts" PRIMARY KEY` et `"ix_accounts_email" UNIQUE`.

### Vérifier que la comparaison voit vraiment quelque chose

Un `alembic check` silencieux ne prouve rien si la comparaison est aveugle. Élargir
temporairement une colonne — `String(30)` → `String(40)` sur `phone` dans le modèle — puis :

```bash
uv run alembic check   # -> FAILED: New upgrade operations detected: [modify_type ...]
```

Attendu : l'échec, grâce à `compare_type` ; puis restaurer le modèle. Pour le verrou : tenir
`SELECT pg_advisory_lock(1786082665);` dans une session `psql`, lancer `make migrate` dans un
autre terminal — il bloque, visible dans `pg_stat_activity` sous `juui-alembic/…` — puis
`SELECT pg_advisory_unlock(1786082665);` le libère et la commande termine.

### Écarts assumés avec le ticket BACK-07

| Écart                                                          | Raison                                                                                                                                                                                                                                                                                         |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Un verrou consultatif dans `env.py`, que le ticket ne cite pas | L'arbitrage était demandé par l'entrypoint d'INFRA-04 : `api` et `worker` le partagent, et le worker est `--scale`-able. Sans sérialisation, deux `alembic upgrade head` simultanés sont une course. Décision consignée dans l'ADR-0010.                                                       |
| Le mode hors ligne (`--sql`) est refusé                        | Aucun consommateur de scripts SQL, et le verrou ne sérialise rien sans connexion. Un chemin de code jamais exercé serait faux le jour où on en aurait besoin ; le refus, lui, est testé.                                                                                                       |
| Pas de déclencheur `BEFORE UPDATE` pour `updated_at`           | La promesse des [mixins](src/app/shared/infrastructure/db/mixins.py) est conditionnelle — « le jour où `updated_at` deviendra porteur ». Ce jour n'est pas arrivé, et l'autogénération ne voyant pas les triggers, l'ajouter plus tard ne créera aucun diff parasite : attendre ne coûte rien. |
| Cibles Makefile, `post_write_hooks` et `timezone = UTC`        | Hors de la lettre du ticket, mais dans son esprit : les commandes portent un nom (`make migration`…), la migration naît conforme à Ruff au lieu de le découvrir en CI, et deux postes dans deux fuseaux nomment leurs fichiers pareil.                                                         |
| `env.py` construit son moteur sans `build_engine`              | `NullPool` refuse les `pool_size`/`max_overflow` que `build_engine` transmet toujours, et une migration doit s'annoncer sous son propre nom dans `pg_stat_activity`. Le paramètre `poolclass` de `build_engine` reste promis aux fixtures de BACK-12.                                          |
| Aucun test automatisé, mais des vérifications documentées      | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02, BACK-03, BACK-04, BACK-05, BACK-06a, BACK-13 et BACK-14. Le cycle complet, la sensibilité de la comparaison et le verrou ont tous été joués avant livraison.                                     |

## Cache

Redis sert de cache applicatif sur la **base 0** ; la base 1 appartient au broker TaskIQ
(BACK-15), et la séparation est une exigence d'INFRA-02 — purger le cache ne doit jamais vider la
file de tâches.

Le domaine ne connaît que le port `Cache`. L'adaptateur Redis, la composition des clés et la
configuration vivent dans `shared/infrastructure/` : le contrat `domain-purity` interdit au domaine
d'importer une dépendance applicative, et il refuse aussi les chaînes **indirectes** — un port ne
peut donc pas même importer `app.core`, qui importe pydantic. C'est cette contrainte, et non un
choix de style, qui explique la forme du port.

### Le port, et ce qu'il promet

Cinq opérations, toutes asynchrones : `get`, `set`, `delete`, `exists`, `invalidate_pattern`. Trois
règles les accompagnent, écrites dans la docstring de `Cache` parce que tout le reste en dépend.

**1. Les clés reçues sont logiques.** L'appelant écrit `dossier:42` ; l'adaptateur, et lui seul, y
appose l'environnement et le périmètre. Un appelant ne _peut_ donc pas oublier le groupe — composer
le segment de tenance n'est pas son travail. C'est ce qui rend le cloisonnement structurel plutôt
que conventionnel.

**2. Toute entrée expire.** `ttl=None` signifie « la durée par défaut configurée »
(`REDIS_CACHE_TTL_SECONDS`, 300 s), jamais « pas d'expiration », et un TTL nul ou négatif lève une
`ValueError`. La raison est écrite dans `docker/redis/redis.conf` : l'instance est partagée avec la
file de tâches, et la seule politique d'éviction acceptable pour elle — `volatile-lru` — ne libère
que les clés portant un TTL. Une entrée éternelle la rendrait inopérante en silence.

**3. Aucune implémentation ne lève quand son stockage est injoignable.** Voir plus bas.

### La clé porte l'environnement et le groupe

```
{environnement}:g-{group_id}:{clé logique}     — CacheScope.TENANT
{environnement}:shared:{clé logique}           — CacheScope.SHARED
```

`ENVIRONMENT=development` donne `dev`, `staging` donne `staging`, `production` donne `prod` : c'est
la promesse que les deux `.env.example` publient depuis SETUP-05, et `_environment_slug` est ce qui
la tient. La traduction passe par un `match` avec `assert_never` — le jour où un quatrième
environnement s'ajoute au `Literal` d'`AppSettings`, **Mypy échoue ici** plutôt que de laisser le
service produire des clés `None:shared:…`.

Le segment de groupe est le cloisonnement de
l'[ADR-0004](../../documentation/docs/adr/0004-tenance-par-groupe.md) appliqué au cache. Le
corollaire vaut pour l'invalidation : `invalidate_pattern("*")` purge le groupe actif et
**lui seul**, et une purge inter-groupes n'est pas exprimable.

Une entrée non tenant porte un `shared` **écrit**, jamais l'absence de segment. Si l'oubli de
périmètre produisait une clé d'apparence normale, il passerait inaperçu ; il produit une clé
visiblement partagée.

### Le contexte de tenance

Le groupe actif est porté par `current_group_id`, dans `shared/infrastructure/tenancy.py`. Trois
choses, et rien de plus : lire, exiger (`require_current_group_id()`), et poser le temps d'un bloc
(`use_group()`).

`require_current_group_id()` **lève** au lieu de dégrader — le motif est consigné dans
l'[ADR-0004](../../documentation/docs/adr/0004-tenance-par-groupe.md). La dégradation gracieuse
porte sur Redis absent, pas sur un appelant qui ignore de quel groupe il parle.

BACK-06b y ajoutera l'intergiciel qui alimente la contextvar depuis l'authentification (BACK-10c),
et le filtre SQLAlchemy dans `db/`. Un piège l'attend, écrit dans la docstring : `BaseHTTPMiddleware`
exécute l'aval de la chaîne dans une **tâche distincte**, donc un `set()` fait dans son `dispatch()`
n'atteindrait pas l'endpoint.

### Ce que la dégradation gracieuse promet — et ce qu'elle ne promet pas

Redis injoignable : `get` rend `MISSING`, `set` et `delete` restent sans effet, `exists` rend
`False`, `invalidate_pattern` rend `0`. Un avertissement part **une seule fois** à la chute, un
autre à la reprise — un avertissement par appel noierait le journal pendant une coupure de dix
minutes, et un journal noyé est un journal que personne ne lit.

L'application **démarre** sans Redis, contrairement à ce qu'elle fait sans PostgreSQL. L'asymétrie
est le sujet, pas un oubli : sans base, aucune route ne peut répondre juste et échouer vite est
correct ; sans cache, toutes répondent, plus lentement. Il n'existe donc ni `verify_connectivity`
bloquant, ni `CacheUnavailableError` — cette classe n'aurait aucun endroit où être levée.
`RedisCache.ping()` sonde quand même au démarrage et journalise, pour que l'exploitant voie la panne
dans la ligne de démarrage plutôt qu'à la première requête.

> **Ce contrat convient à un cache, et à rien d'autre.** Une décision de sécurité lue ici s'ouvrirait
> toute seule le jour où Redis tombe : « ce jeton est-il révoqué ? » (BACK-10d) répondrait « non »,
> « cet OTP a-t-il été consommé ? » (BACK-17) répondrait « non ». Ces deux tickets doivent traiter
> l'indisponibilité explicitement — échouer fermé — et non l'hériter d'ici.

`MISSING` est une sentinelle, distincte de `None`. Sans elle, un cas d'usage qui retourne
légitimement `None` — « ce dossier n'existe pas » — ne serait **jamais** servi depuis le cache : sa
valeur serait relue comme une absence et recalculée à chaque appel. Un défaut de rendement que rien
ne signale.

### Le décorateur `@cached`

À poser sur une méthode de lecture d'un cas d'usage. Jamais sur une écriture : le résultat serait
mémorisé, et l'effet de bord rejoué ou sauté selon l'état du cache.

```python
class LireLeDossier:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    @cached(ttl=60, namespace="medical_records.dossier")
    async def execute(self, animal_id: UUID) -> dict[str, JsonValue]: ...
```

Le cache vient de `self.cache`, jamais d'un registre global : la borne `S: CacheHolder` fait
**échouer le typage à la définition** si la classe décorée n'expose pas de cache. La question « où le
décorateur trouve-t-il son cache, sans requête HTTP ? » est donc tranchée à la compilation, et non
par une convention que quelqu'un oubliera. Décorer une classe qui n'en a pas donne :

```
error: Value of type variable "S" of function cannot be "SansCache"  [type-var]
```

Et le type de retour garde sa précision — `dict[str, JsonValue]` reste `dict[str, JsonValue]`, il
n'est pas élargi à `JsonValue`.

Le groupe n'apparaît pas dans la signature, et c'est voulu : le décorateur vit dans le domaine, la
contextvar dans l'infrastructure, où l'architecture lui interdit d'aller la chercher. C'est
l'adaptateur qui lit le groupe au moment de composer la clé physique — le décorateur ne peut donc pas
se tromper de groupe, puisqu'il n'en manipule aucun.

La clé est `namespace` (ou `module:qualname` à défaut) suivi d'une **empreinte SHA-256** des
arguments. Une empreinte et non les arguments en clair : une clé Redis se lit dans `MONITOR`, dans le
`SLOWLOG` et dans la console d'inspection, et `…:lire_le_dossier:marie.dupont@exemple.fr` y
déverserait une donnée personnelle. Limite à connaître : l'empreinte vaut ce que vaut le `repr` des
arguments — un objet sans `__repr__` propre y met son adresse mémoire, et le cache manquerait alors
systématiquement, en silence.

Ce que le décorateur ne fait pas : il ne protège pas de l'avalanche, et il n'invalide rien.
L'invalidation est du côté écriture, par `invalidate_pattern`.

### Vérifier que le cache tient

Cinq sondes. Les deux premières ne demandent **aucun** conteneur.

**1. Les cinq opérations, le TTL, le décorateur et la bascule de groupe — sans Redis.** La doublure
est définie _dans la sonde_ et non dans `src/` (les doublures de production appartiennent à
BACK-06c), mais elle compose ses clés avec le **vrai** `build_key_builder` : c'est ce qui fait que la
sonde prouve le préfixage de production, et non le sien.

```bash
uv run python - <<'PY'
import asyncio, fnmatch, time
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.cache import MISSING, Cache, CacheScope, JsonValue, Missing, cached
from app.shared.infrastructure.clients.cache_keys import build_key_builder
from app.shared.infrastructure.tenancy import MissingTenantContextError, use_group

A = UUID("01931f2a-0000-7000-8000-00000000000a")
B = UUID("01931f2a-0000-7000-8000-00000000000b")


class InMemoryCache(Cache):
    """Doublure du port, adossee au VRAI compositeur de cles."""

    def __init__(self, settings, default_ttl_seconds=300):
        self._keys = build_key_builder(settings)
        self._default_ttl_seconds = default_ttl_seconds
        self._entries: dict[str, tuple[JsonValue, float]] = {}

    def physical_keys(self):
        maintenant = time.monotonic()
        return sorted(k for k, (_, fin) in self._entries.items() if fin > maintenant)

    async def get(self, key, *, scope=CacheScope.TENANT) -> JsonValue | Missing:
        physique = self._keys.key(key, scope)
        entree = self._entries.get(physique)
        if entree is None:
            return MISSING
        if entree[1] <= time.monotonic():
            del self._entries[physique]
            return MISSING
        return entree[0]

    async def set(self, key, value, *, ttl=None, scope=CacheScope.TENANT) -> None:
        secondes = self._default_ttl_seconds if ttl is None else ttl
        if secondes <= 0:
            raise ValueError("Un TTL de cache doit etre strictement positif.")
        self._entries[self._keys.key(key, scope)] = (value, time.monotonic() + secondes)

    async def delete(self, key, *, scope=CacheScope.TENANT) -> bool:
        return self._entries.pop(self._keys.key(key, scope), None) is not None

    async def exists(self, key, *, scope=CacheScope.TENANT) -> bool:
        return await self.get(key, scope=scope) is not MISSING

    async def invalidate_pattern(self, pattern, *, scope=CacheScope.TENANT) -> int:
        motif = self._keys.pattern(pattern, scope)
        vises = [k for k in self.physical_keys() if fnmatch.fnmatchcase(k, motif)]
        for cle in vises:
            del self._entries[cle]
        return len(vises)


class LireLeDossier:
    def __init__(self, cache):
        self.cache = cache
        self.appels = 0

    @cached(ttl=60, namespace="sonde.dossier")
    async def execute(self, animal_id: str) -> dict[str, JsonValue]:
        self.appels += 1
        return {"animal": animal_id, "appels": self.appels}


async def main() -> None:
    cache = InMemoryCache(get_settings(), default_ttl_seconds=1)

    with use_group(A):
        await cache.set("dossier:42", {"note": "vu par le groupe A"}, ttl=60)
        print("1. set (ttl=60) puis get:", await cache.get("dossier:42"))
        print("2. exists               :", await cache.exists("dossier:42"))
        await cache.set("liste:1", 1, ttl=60)
        await cache.set("liste:2", 2, ttl=60)
        print("3. invalidate_pattern   :", await cache.invalidate_pattern("liste:*"))
        await cache.set("ephemere", "x")
        await asyncio.sleep(1.2)
        print("4. TTL par defaut expire:", await cache.get("ephemere") is MISSING)
        cas = LireLeDossier(cache)
        await cas.execute("rex")
        await cas.execute("rex")
        print("5. @cached, deux appels :", cas.appels, "execution(s) reelle(s)")

    with use_group(B):
        print("6. le groupe B ne lit rien du groupe A :", await cache.get("dossier:42") is MISSING)
        await cache.set("dossier:42", {"note": "vu par le groupe B"}, ttl=60)

    with use_group(A):
        print("7. le groupe A relit la sienne        :", await cache.get("dossier:42"))
        print("8. delete                             :", await cache.delete("dossier:42"))

    await cache.set("otp:0612345678", "123456", ttl=60, scope=CacheScope.SHARED)
    try:
        await cache.set("dossier:1", "x")
    except MissingTenantContextError as erreur:
        print("9. hors contexte de groupe            :", type(erreur).__name__)

    print("10. cles physiques :")
    for cle in cache.physical_keys():
        print("      ", cle)


asyncio.run(main())
PY
```

Attendu — la ligne 6 est le critère de bascule de groupe, la ligne 7 sa contrepartie (l'écriture du
groupe B n'a pas écrasé celle du groupe A) :

```
1. set (ttl=60) puis get: {'note': 'vu par le groupe A'}
2. exists               : True
3. invalidate_pattern   : 2
4. TTL par defaut expire: True
5. @cached, deux appels : 1 execution(s) reelle(s)
6. le groupe B ne lit rien du groupe A : True
7. le groupe A relit la sienne        : {'note': 'vu par le groupe A'}
8. delete                             : True
9. hors contexte de groupe            : MissingTenantContextError
10. cles physiques :
       dev:g-01931f2a-0000-7000-8000-00000000000a:sonde.dossier:0459e6e24fb37678a201e3cbeeacfaa9
       dev:g-01931f2a-0000-7000-8000-00000000000b:dossier:42
       dev:shared:otp:0612345678
```

**2. Le préfixe suit l'environnement.** La même commande, précédée d'une variable — les variables du
processus passent devant le fichier `.env` :

```bash
ENVIRONMENT=staging uv run python - <<'PY'
...  # la meme sonde qu'au point 1
PY
```

Attendu : les trois mêmes clés, préfixées `staging:` au lieu de `dev:`.

**3. Aller-retour réel, expiration réelle, séparation des bases.** Pile levée.

```bash
uv run python - <<'PY'
import asyncio
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.cache import CacheScope
from app.shared.infrastructure.clients.redis_cache import build_cache
from app.shared.infrastructure.tenancy import use_group

A = UUID("01931f2a-0000-7000-8000-00000000000a")
B = UUID("01931f2a-0000-7000-8000-00000000000b")


async def main() -> None:
    settings = get_settings()
    cache = build_cache(settings)
    try:
        print("0. ping                  :", await cache.ping(), "sur", cache.target)
        with use_group(A):
            await cache.set("sonde:dossier", {"valeur": 42}, ttl=60)
            print("1. relu depuis Redis     :", await cache.get("sonde:dossier"))
            await cache.set("sonde:liste:1", 1, ttl=60)
            await cache.set("sonde:liste:2", 2, ttl=60)
            print("2. invalidate_pattern    :", await cache.invalidate_pattern("sonde:liste:*"))
            await cache.set("sonde:ephemere", "x", ttl=2)
            await asyncio.sleep(2.5)
            print("3. TTL expire cote Redis :", await cache.exists("sonde:ephemere") is False)
        with use_group(B):
            await cache.set("sonde:dossier", {"valeur": 99}, ttl=60)
        await cache.set("sonde:partagee", "x", ttl=60, scope=CacheScope.SHARED)
        print("4. bases                 : cache", settings.redis.cache_db,
              "/ broker", settings.redis.broker_db, "(BACK-15)")
    finally:
        await cache.aclose()


asyncio.run(main())
PY
```

Puis, **depuis la racine du dépôt**, la vérification qui compte — chaque entrée porte-t-elle un TTL,
et le cache a-t-il touché la base du broker ?

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  sh -c "redis-cli -n 0 --scan --pattern 'dev:*sonde*' | while read c; do echo \"\$(redis-cli -n 0 ttl \"\$c\")s  \$c\"; done" | sort -k2
```

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  redis-cli -n 1 --scan --pattern 'dev:*' | wc -l
```

Attendu : trois clés, **toutes** porteuses d'un TTL positif — c'est la promesse faite à
`redis.conf` —, la même clé logique déclinée sous deux groupes, et `0` clé de cache en base 1. Le
décompte de secondes ci-dessous dépend évidemment du moment de la lecture ; c'est sa positivité qui
se vérifie, pas sa valeur.

```
51s  dev:g-01931f2a-0000-7000-8000-00000000000a:sonde:dossier
53s  dev:g-01931f2a-0000-7000-8000-00000000000b:sonde:dossier
53s  dev:shared:sonde:partagee
```

Nettoyer ensuite : `redis-cli -n 0 --scan --pattern 'dev:*sonde*' | xargs -r redis-cli -n 0 unlink`.

**4. Redis coupé : un avertissement, puis on continue.** Le port hors service passe par une variable,
comme la sonde de BACK-05 — inutile d'arrêter le conteneur.

```bash
REDIS_PORT=6399 uv run python - <<'PY'
import asyncio

from app.core import get_settings
from app.shared.domain.ports.cache import MISSING, CacheScope, JsonValue, cached
from app.shared.infrastructure.clients.redis_cache import build_cache


class LireLeDossier:
    def __init__(self, cache):
        self.cache = cache
        self.appels = 0

    @cached(ttl=60, namespace="sonde.degradee", scope=CacheScope.SHARED)
    async def execute(self, animal_id: str) -> dict[str, JsonValue]:
        self.appels += 1
        return {"animal": animal_id}


async def main() -> None:
    cache = build_cache(get_settings())
    try:
        print("0. ping             :", await cache.ping())
        print("1. get              :", await cache.get("x", scope=CacheScope.SHARED) is MISSING)
        print("2. set              :", await cache.set("x", 1, scope=CacheScope.SHARED))
        print("3. exists           :", await cache.exists("x", scope=CacheScope.SHARED))
        print("4. invalidate       :", await cache.invalidate_pattern("*", scope=CacheScope.SHARED))
        print("5. delete           :", await cache.delete("x", scope=CacheScope.SHARED))
        cas = LireLeDossier(cache)
        await cas.execute("rex")
        await cas.execute("rex")
        print("6. @cached, 2 appels:", cas.appels, "execution(s) reelle(s), aucune exception")
    finally:
        await cache.aclose()


asyncio.run(main())
PY
echo "code de sortie : $?"
```

Attendu : **un seul** avertissement sur la sortie d'erreur malgré huit opérations, toutes les valeurs
dégradées, et un code de sortie `0`. La queue du message vient de la bibliothèque et dépend de
l'ordre de résolution IPv4/IPv6 du poste — c'est le préfixe qui compte, pas elle.

```
Cache Redis injoignable sur localhost:6399 (base 0) (demarrage) : le service continue SANS cache. Error 61 connecting to localhost:6399. Connection refused.
0. ping             : False
1. get              : True
2. set              : None
3. exists           : False
4. invalidate       : 0
5. delete           : False
6. @cached, 2 appels: 2 execution(s) reelle(s), aucune exception
code de sortie : 0
```

L'avertissement paraît alors qu'**aucune journalisation n'est configurée** : le `lastResort` de la
bibliothèque standard sert les `WARNING` sur `stderr`. BACK-11 n'aura donc rien à défaire ici — mais
c'est aussi pourquoi le message `INFO` de `ping()` réussi reste invisible d'ici là.

**5. L'application démarre et répond sans Redis, et le pool meurt avec le processus.**

```bash
REDIS_PORT=6399 uv run uvicorn app.main:app --port 8001
```

Attendu : l'avertissement, **puis** `Application startup complete.` — à comparer avec
`POSTGRES_PORT=5999`, qui donne `Application startup failed. Exiting.` et un code de sortie 3. Dans
un autre terminal, `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/openapi.json`
rend `200`.

Puis, la pile levée et l'API relancée sans la variable, depuis la racine :

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  redis-cli client list | grep "name=juui-api-cache"
```

Attendu : une ligne portant `name=juui-api-cache/development` et `db=0` — c'est le pendant exact de
la sonde `pg_stat_activity` de BACK-05. Après un `Ctrl-C` sur uvicorn, la même commande ne rend plus
rien : le `finally` du `lifespan` a bien fermé le client **et** le pool.

### Écarts assumés avec le ticket BACK-14

| Écart                                                                                    | Raison                                                                                                                                                                                                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| La contextvar `current_group_id` est créée ici, dans `infrastructure/` et non sous `db/` | Le ticket exige le groupe actif dans la clé, et rien ne le portait — `tenant_context.py` appartient à BACK-06b. La surface livrée est réduite à lire, exiger et poser. Elle est montée d'un cran par rapport à ce que BACK-04 annonçait : le cache n'a aucune raison d'importer le socle de persistance pour nommer une clé. BACK-06b y ajoutera l'intergiciel et gardera le filtre dans `db/`. |
| `InMemoryCache` défini dans la sonde, pas dans `src/`                                    | Le ticket l'attribue explicitement à BACK-06c. Même arbitrage qu'en BACK-04 pour `InMemoryAccountRepository`. La doublure compose ses clés avec le vrai `build_key_builder`, ce qui lui fait prouver le préfixage de production et non le sien.                                                                                                                                                 |
| `logging.getLogger(__name__)` nu, sans BACK-11                                           | L'avertissement de dégradation est un critère d'acceptation ; l'attendre reviendrait à renoncer à le vérifier. Un logger nommé n'a rien à reprendre le jour venu : BACK-11 configurera la racine, ces appels en hériteront. Aucun `basicConfig()` n'est appelé, précisément pour ne pas se battre avec cette future configuration.                                                              |
| Ni `verify_connectivity` bloquant, ni `CacheUnavailableError`                            | Asymétrie délibérée avec BACK-05 : une base injoignable doit arrêter le processus, un cache injoignable ne doit pas — sans quoi le critère « si Redis est arrêté, l'application continue de répondre » serait inatteignable. La classe d'erreur n'aurait aucun endroit où être levée. `ping()` sonde et journalise.                                                                             |
| Les clés sont préfixées par l'adaptateur, jamais par l'appelant                          | La seule forme qui rende la fuite structurellement impossible plutôt que conventionnellement évitée. Corollaire gratuit : aucun motif d'invalidation ne peut viser un autre groupe que le sien.                                                                                                                                                                                                 |
| `MISSING` plutôt que `None` pour l'absence                                               | Sans sentinelle, un cas d'usage qui retourne légitimement `None` ne serait jamais servi depuis le cache : un défaut de rendement invisible, que rien ne signalerait. Le motif enum est celui que Mypy sait affiner.                                                                                                                                                                             |
| `require_current_group_id()` lève au lieu de dégrader                                    | La dégradation porte sur Redis absent, pas sur un appelant qui ignore de quel groupe il parle. Contourner en silence cacherait précisément le défaut que le ticket qualifie de fuite et non de défaut d'affichage.                                                                                                                                                                              |
| `cache_keys.py`, hors de la portée nommée                                                | La convention de nommage est partagée par l'adaptateur Redis et par toute doublure du port. L'enfermer dans `redis_cache.py` obligerait une doublure en mémoire à importer le client Redis pour savoir nommer une clé.                                                                                                                                                                          |
| `retry=Retry(NoBackoff(), retries=0)` épinglé explicitement                              | Vérifié dans redis 8.1 : un pool construit à la main hérite déjà de ce réglage, mais `Redis(host=…)` hérite de dix tentatives avec repli exponentiel — plusieurs secondes par appel pendant une panne. L'épinglage rend le comportement indépendant du constructeur employé.                                                                                                                    |
| `decode_responses=False`, et `SCAN` plutôt que `KEYS`                                    | Le sérialiseur possède l'encodage : décoder côté client réduirait le « point d'extension pour d'autres formats » aux seuls formats texte, or msgpack et le JSON compressé sont les candidats réels. Et Redis est mono-thread : un `KEYS` lancé pour invalider un dossier suspendrait la distribution des tâches de fond, cache et broker partageant le processus.                               |
| Aucun `default=` sur `json.dumps`                                                        | Un `default=str` ferait entrer un `UUID` et ressortir une `str`. L'écart n'apparaîtrait qu'au premier **succès** de cache : en production, sous charge, et jamais dans une sonde. Une valeur non sérialisable échoue donc à l'écriture, là où le défaut se corrige.                                                                                                                             |
| `client_name` posé sur le pool, non demandé                                              | Pendant de l'`application_name` de BACK-05. C'est lui qui rend le critère « pool créé et fermé dans le lifespan » **observable** par un `CLIENT LIST`, au lieu de reposer sur une lecture de code.                                                                                                                                                                                              |
| `REDIS_CACHE_TTL_SECONDS` ajoutée, et `docker-compose.yml` modifié                       | Le ticket demande un TTL par défaut « configurable » sans nommer de variable. La liste `environment:` du service `api` est explicite : sans cette ligne, le réglage serait inatteignable en conteneur. Le `:-` lui donne un défaut, comme les quatre `POSTGRES_*` de BACK-05.                                                                                                                   |
| Délais et tailles de lot en constantes de module, non configurables                      | Même arbitrage que `_CONNECT_TIMEOUT_SECONDS` en BACK-05. Chaque variable coûte deux gabarits, une ligne de compose et une ligne de README ; aucune n'a de consommateur qui demanderait à en changer.                                                                                                                                                                                           |
| Pas de fenêtre de circuit ouvert                                                         | Non demandée, et le drapeau suffit à ne pas noyer le journal. Limite assumée : chaque appel retente sa connexion pendant la panne. Sur un refus l'échec est immédiat ; sur un hôte qui absorbe les paquets, chaque appel paie les deux secondes de `_CONNECT_TIMEOUT_SECONDS`. Le service répond toujours, mais plus lentement.                                                                 |
| `@cached` livré sans consommateur                                                        | Aucun cas d'usage de lecture n'existe avant BACK-19. La sonde 1 en démontre le fonctionnement, bascule de groupe comprise. Le paramètre de projection d'objet (un codec `T ↔ JsonValue`) n'est pas écrit pour la même raison : il doublerait la signature sans appelant.                                                                                                                        |
| `main.py` modifié, hors de la portée déclarée                                            | La portée le nomme (« init lifespan »), et le critère d'acceptation parle du pool créé et fermé dans le `lifespan`. Même arbitrage qu'en BACK-03 et BACK-05.                                                                                                                                                                                                                                    |
| Aucun test automatisé, mais des sondes documentées                                       | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02, BACK-03, BACK-04 et BACK-05. L'expiration se démontre deux fois : par une horloge monotone en mémoire, et par un TTL relu dans Redis.                                                                                                                                                             |

## Stockage objet

Les fichiers — photos d'animaux, comptes rendus, documents de santé — vivent dans un **bucket S3**.
MinIO en tient lieu sur le poste, Amazon S3 en production, et **un seul paramètre les distingue** :
`S3_ENDPOINT_URL`. Rempli, boto3 parle à MinIO ; vide, il retombe sur les endpoints Amazon calculés
depuis la région. Aucune ligne de code ne connaît le mot « MinIO ».

Le domaine ne connaît que le port `FileStorage`. L'adaptateur, la convention de clés et la
construction du client vivent dans `shared/infrastructure/` — même contrainte qu'au
[cache](#cache) : `domain-purity` refuse au domaine `boto3`, `botocore` et les chaînes indirectes,
`app.core` compris.

### Le port, et ce qu'il promet

Cinq opérations : `upload`, `download`, `delete`, `exists`, `generate_presigned_url`. Quatre règles
les accompagnent, écrites dans la docstring de `FileStorage`.

**1. Aucune dégradation, jamais.** C'est le point où ce port s'oppose au précédent, et la
question s'est reposée au suivant — l'[unité de travail](#unité-de-travail) y répond en levant
**et** en annulant. `Cache` rend `MISSING` quand Redis tombe, parce qu'un
cache absent ne change qu'une **latence**. Un stockage absent change un **résultat** :

- un `upload` qui ne lèverait pas serait un fichier **perdu**, alors qu'on vient de répondre
  « enregistré » à l'utilisateur ;
- un `exists` qui rendrait `False` sur panne déclarerait **inexistant** un document de santé qui
  existe.

Aucune des cinq opérations n'a donc de valeur de repli. `exists()` contient le seul `except` du
fichier qui avale une erreur, et il n'avale que `StoredFileNotFoundError` — la panne, elle, continue
de remonter. C'est ce qui sépare « ce document n'existe pas » de « je ne sais pas s'il existe ».

**2. Les clés sont complètes, et validées.** Contrairement aux clés de cache, qui sont _logiques_ et
que l'adaptateur préfixe, une clé de stockage est celle qui sera **persistée en base**.

**3. Le cloisonnement entre groupes n'est pas dans le nommage.** Voir plus bas.

**4. La validation précède le réseau.** `UploadPolicy` — 20 Mio, et `image/jpeg`, `image/png`,
`image/webp`, `application/pdf` — s'applique avant le premier octet émis, et le type est vérifié
**avant** la taille : un fichier de 40 Mo au format refusé doit s'entendre dire que le format est
refusé, pas partir se faire compresser en vain.

La politique vit dans le **port** et non dans l'adaptateur : « quels fichiers ce service
accepte-t-il ? » ne dépend ni de S3, ni du fournisseur suivant. `image/heic` n'y figure pas, et
c'est une lacune **connue** — c'est le format natif des photos d'iPhone, et l'accepter sans
conversion côté serveur produirait des fichiers que ni les navigateurs ni les visionneuses de bureau
n'affichent.

Six exceptions, toutes sous `FileStorageError`, elle-même sous `DomainError` :
`StoredFileNotFoundError`, `FileTooLargeError`, `UnsupportedContentTypeError`,
`InvalidStorageKeyError`, `FileStorageUnavailableError`. **Aucune exception boto3 n'en sort** —
`_call` est le seul endroit du service qui connaisse `ClientError`, et c'est ce qui permet à un cas
d'usage d'attraper `FileStorageError` sans importer la bibliothèque du fournisseur.

> `StoredFileNotFoundError` et non `FileNotFoundError` : la règle Ruff `A` refuse de masquer un
> builtin. L'écart de nom vaut mieux qu'une classe qui, attrapée par mégarde, avalerait aussi les
> erreurs du système de fichiers local.

### La clé, et ce qu'elle ne porte pas

```
{entity_type}/{entity_id}/{nom de fichier assaini}
```

Par exemple `animal-photos/01931f2a-…/radiographie-thoracique.jpg`. Le segment central est un UUID :
deux téléversements du même nom ne peuvent pas se confondre.

`build_storage_key` **compose** une clé conforme ; `validate_storage_key` vérifie qu'une clé est
**sans danger**, sans lui imposer cette forme. La distinction n'est pas théorique : une clé relue
d'une colonne de base a été composée par une version antérieure du service, et la refuser sur un
changement de convention rendrait illisibles des fichiers parfaitement valides. Ce qui est refusé
sans discussion, c'est ce qui **sort de son préfixe** — `..`, barre initiale, segment vide, caractère
de contrôle, clé de plus de 1024 octets.

L'assainissement du nom traite le **radical et l'extension séparément**, et ce n'est pas un
raffinement : assainis ensemble, `上書き.pdf` perdrait son radical _et_ son point, et il resterait
`pdf` — une clé où l'extension a pris la place du nom. Séparés, il reste `fichier.pdf`, où le repli
se voit pour ce qu'il est. Un nom entièrement non latin n'est pas un cas de laboratoire dans un
service ouvert au public.

| Nom fourni                              | Clé produite                            |
| --------------------------------------- | --------------------------------------- |
| `Radiographie Thoracique.JPG`           | `radiographie-thoracique.jpg`           |
| `../../evasion.pdf`                     | `evasion.pdf`                           |
| `C:\Users\moi\échographie (2).png`      | `echographie-2.png`                     |
| `上書き.pdf`                            | `fichier.pdf`                           |
| `rapport.2026.sauvegarde-du-15-janvier` | `rapport.2026.sauvegarde-du-15-janvier` |

Le dernier montre la règle : ce qui suit le dernier point n'est traité comme extension que s'il est
court et purement alphanumérique. Sinon le nom entier est gardé — mieux vaut un nom long et fidèle
qu'un nom tronqué à un endroit choisi au hasard.

**Aucun segment de tenance, et c'est délibéré.** Une clé de cache est volatile ; une clé de stockage
est persistée. La faire dépendre de `current_group_id` la rendrait introuvable dès que le contexte de
lecture diffère de celui de l'écriture — une tâche de fond (BACK-15), un export, ou simplement un
vétérinaire remplaçant qui a changé de structure entre-temps. Le cloisonnement entre groupes
appartient à l'**autorisation** : qui a le droit de demander une URL pré-signée pour cette clé. Il ne
peut pas appartenir au nommage d'une donnée durable.

> Corollaire à ne jamais oublier : **l'opacité d'un UUID n'est pas un contrôle d'accès.** Le bucket
> est privé (INFRA-03 le referme à chaque démarrage), et c'est la route qui émet l'URL pré-signée qui
> devra vérifier le droit d'y accéder.

Pas de préfixe d'environnement non plus, contrairement aux clés de cache : les environnements ont des
**buckets** distincts, la séparation est faite un cran au-dessus.

### Les URLs pré-signées sont la voie principale

Une URL pré-signée porte son autorisation et son expiration dans sa signature : le navigateur parle
**directement** au stockage, et l'octet du fichier ne traverse jamais l'API. Faire transiter les
fichiers par les workers reviendrait à occuper une boucle d'événements entière pendant le
téléversement d'une radiographie.

`generate_presigned_url` est la seule des cinq opérations à être **synchrone**, et c'est ce qui rend
ce chemin gratuit : signer n'appelle personne, botocore calcule une empreinte à partir de la clé
secrète, de la date et du verbe. Elle fonctionne même stockage éteint.

Quinze minutes par défaut, `expires_in` par appel, plafond de sept jours — celui de la signature V4,
au-delà duquel le stockage refuserait l'URL sans en dire la raison.

**Une URL de téléversement exige son type MIME.** Sans lui, le chemin principal échapperait
entièrement à `UploadPolicy` : l'API n'est plus sur le trajet pour regarder ce qui passe. Le type est
donc validé, puis **épinglé dans la signature** — un dépôt qui annonce autre chose est refusé par le
stockage lui-même, avec un `403`. Le rendre facultatif aurait fait de la validation une politesse.

> **Ce qu'une URL de téléversement ne peut toujours pas faire : plafonner la taille.** Un PUT
> pré-signé n'emporte aucune condition sur la longueur du corps, et il n'existe aucun moyen de lui en
> ajouter — seul un **formulaire** pré-signé (POST, avec une condition `content-length-range` dans sa
> policy) l'exprimerait. `max_bytes` ne s'applique donc qu'à `upload`. Le ticket qui exposera la route
> de téléversement direct devra le savoir, et passer au formulaire pré-signé s'il tient à la borne.

**Limite d'exploitation.** L'URL porte l'**hôte** de `endpoint_url`. Dans la pile Docker, c'est
`http://minio:9000`, résolvable depuis `app_network` seulement : une URL émise par l'API en conteneur
n'est pas ouvrable depuis le navigateur du poste. Sans conséquence tant qu'aucune route ne la publie ;
le ticket qui exposera ces URLs au frontend devra distinguer l'endpoint **interne** de l'endpoint
**public** — ce que BACK-13 écarte, ayant posé qu'un seul paramètre sépare MinIO d'Amazon.

### L'asymétrie du service a trois temps, pas deux

C'est la question à se poser en branchant la ressource suivante dans le `lifespan`.

| Ressource      | Au démarrage                     | À l'appel                        | Pourquoi                                            |
| -------------- | -------------------------------- | -------------------------------- | --------------------------------------------------- |
| PostgreSQL     | **lève** (`verify_connectivity`) | lève                             | sans base, aucune route ne répond juste             |
| Redis          | journalise                       | **dégrade** (`MISSING`, `False`) | sans cache, toutes répondent — plus lentement       |
| Stockage objet | journalise                       | **lève**                         | sans bucket, seules les routes de fichiers échouent |

Le stockage est le seul des trois à se comporter différemment au démarrage et à l'appel. Refuser de
partir priverait le service de tout ce qui n'a rien à voir avec les fichiers ; se taire à l'appel
ferait perdre des fichiers en silence. `ping()` journalise, les opérations lèvent — et l'avertissement
part en `WARNING`, donc visible tant que BACK-11 n'a pas configuré la journalisation.

### Vérifier que le stockage tient

Six sondes. La première ne demande **aucun** conteneur.

**1. La convention de clés et la politique d'upload — sans réseau.**

```bash
uv run python - <<'PY'
from uuid import UUID
from app.shared.domain.ports.file_storage import (
    DEFAULT_UPLOAD_POLICY, FileTooLargeError, InvalidStorageKeyError,
    UnsupportedContentTypeError,
)
from app.shared.infrastructure.clients.storage_keys import build_storage_key, validate_storage_key

ANIMAL = UUID("01931f2a-0000-7000-8000-00000000000a")

print("--- composition ---")
for nom in ("Radiographie Thoracique.JPG", "../../evasion.pdf",
            "C:\\Users\\moi\\échographie (2).png", "上書き.pdf", ".ssh"):
    print(f"  {nom!r:44} -> {build_storage_key('animal-photos', ANIMAL, nom).rsplit('/', 1)[-1]}")

print("--- cles refusees ---")
for cle in ("", "/absolu.jpg", "a/../../b.jpg", "a//b.jpg", "a/b\u202e.jpg", "x/" + "a" * 1030):
    try:
        validate_storage_key(cle)
        print(f"  {cle[:28]!r:32} -> ACCEPTEE  <<< PROBLEME")
    except InvalidStorageKeyError as erreur:
        print(f"  {cle[:28]!r:32} -> refusee : {str(erreur)[:56]}")

print("--- politique d'upload ---")
politique = DEFAULT_UPLOAD_POLICY
for octets, type_mime in ((b"x", "image/svg+xml"),
                          (b"x" * (politique.max_bytes + 1), "image/png"),
                          (b"x", "image/png")):
    try:
        politique.validate(octets, type_mime)
        print(f"  {len(octets):>9} o {type_mime:<14} -> accepte")
    except (UnsupportedContentTypeError, FileTooLargeError) as erreur:
        print(f"  {len(octets):>9} o {type_mime:<14} -> {type(erreur).__name__}")
PY
```

Attendu : `../../evasion.pdf` devient `evasion.pdf`, `上書き.pdf` devient `fichier.pdf`, les six clés
sont refusées, et seul le `image/png` d'un octet passe la politique.

Les cinq suivantes demandent la pile (`make up`) et un `.env` local pointant `localhost:9000`.

**2. L'aller-retour complet des cinq opérations.**

```bash
uv run python - <<'PY'
import asyncio, subprocess, time
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.file_storage import PresignedOperation, StoredFileNotFoundError
from app.shared.infrastructure.clients.s3_storage import build_file_storage
from app.shared.infrastructure.clients.storage_keys import build_storage_key

ANIMAL = UUID("01931f2a-0000-7000-8000-00000000000a")


def statut(url: str) -> str:
    """Code HTTP rendu par un GET nu sur l'URL."""
    return subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
        capture_output=True, text=True, check=True,
    ).stdout


async def main() -> None:
    stockage = build_file_storage(get_settings())
    print("cible :", stockage.target, "| ping :", await stockage.ping())

    cle = build_storage_key("animal-photos", ANIMAL, "Radiographie Thoracique.JPG")
    await stockage.upload(cle, b"\xff\xd8\xff-fausse-image", "image/jpeg")
    print("upload   -> exists :", await stockage.exists(cle))
    print("download ->", await stockage.download(cle))

    url = stockage.generate_presigned_url(cle)
    print("presign GET -> curl :", statut(url))

    court = stockage.generate_presigned_url(cle, expires_in=1)
    print("expire=1s : immediat", statut(court), end=" ")
    time.sleep(2)
    print("| apres 2s", statut(court))

    print("delete ->", await stockage.delete(cle), "| re-delete ->", await stockage.delete(cle))
    try:
        await stockage.download(cle)
        print("download apres delete -> AUCUNE ERREUR  <<< PROBLEME")
    except StoredFileNotFoundError:
        print("download apres delete -> StoredFileNotFoundError")
    await stockage.aclose()


asyncio.run(main())
PY
```

Attendu :

```
cible : http://localhost:9000/juui-dev | ping : True
upload   -> exists : True
download -> b'\xff\xd8\xff-fausse-image'
presign GET -> curl : 200
expire=1s : immediat 200 | apres 2s 403
delete -> True | re-delete -> False
download apres delete -> StoredFileNotFoundError
```

Les deux dernières lignes portent trois critères d'acceptation à elles seules : l'aller-retour,
l'expiration réelle de l'URL — `200` puis `403`, pas une lecture de code — et un `delete` dont le
retour ne ment pas.

**3. Le type MIME épinglé dans la signature d'un téléversement.** C'est ce qui empêche le chemin
direct d'échapper à la politique.

```bash
uv run python - <<'PY'
import asyncio, subprocess
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.file_storage import PresignedOperation, UnsupportedContentTypeError
from app.shared.infrastructure.clients.s3_storage import build_file_storage
from app.shared.infrastructure.clients.storage_keys import build_storage_key

ANIMAL = UUID("01931f2a-0000-7000-8000-00000000000b")


def depose(url: str, type_mime: str) -> str:
    """Code HTTP rendu par un PUT annoncant ce type."""
    return subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "PUT",
         "-H", f"Content-Type: {type_mime}", "--data-binary", "%PDF-1.4 faux", url],
        capture_output=True, text=True, check=True,
    ).stdout


async def main() -> None:
    stockage = build_file_storage(get_settings())
    cle = build_storage_key("medical-documents", ANIMAL, "compte rendu.pdf")
    url = stockage.generate_presigned_url(
        cle, operation=PresignedOperation.UPLOAD, content_type="application/pdf"
    )
    print("PUT, bon type     ->", depose(url, "application/pdf"), "| exists :",
          await stockage.exists(cle))
    print("PUT, MAUVAIS type ->", depose(url, "image/png"))
    await stockage.delete(cle)

    try:
        stockage.generate_presigned_url(
            cle, operation=PresignedOperation.UPLOAD, content_type="application/x-msdownload"
        )
        print("type hors politique -> ACCEPTE  <<< PROBLEME")
    except UnsupportedContentTypeError:
        print("type hors politique -> UnsupportedContentTypeError")

    for arguments in ({"operation": PresignedOperation.UPLOAD}, {"expires_in": 0},
                      {"expires_in": 10**7}, {"content_type": "image/png"}):
        try:
            stockage.generate_presigned_url(cle, **arguments)
            print(f"  {arguments} -> ACCEPTE  <<< PROBLEME")
        except ValueError as erreur:
            print(f"  {str(arguments)[:32]:34} -> ValueError : {str(erreur)[:44]}")
    await stockage.aclose()


asyncio.run(main())
PY
```

Attendu : `200` avec le bon type, **`403` avec un autre** — c'est MinIO qui refuse, pas l'API —, puis
quatre `ValueError` : un téléversement sans type, une expiration nulle, une expiration au-delà de sept
jours, et un type MIME donné à un téléchargement.

**4. Le stockage injoignable : le service démarre, les opérations lèvent.**

```bash
S3_ENDPOINT_URL=http://127.0.0.1:9 uv run python - <<'PY'
import asyncio

from app.core import get_settings
from app.shared.domain.ports.file_storage import FileStorageUnavailableError
from app.shared.infrastructure.clients.s3_storage import build_file_storage


async def main() -> None:
    stockage = build_file_storage(get_settings())
    print("ping ->", await stockage.ping(), "(False, SANS lever : le service demarre)")
    for nom, appel in (
        ("upload", stockage.upload("x/y/z.png", b"x", "image/png")),
        ("download", stockage.download("x/y/z.png")),
        ("exists", stockage.exists("x/y/z.png")),
        ("delete", stockage.delete("x/y/z.png")),
    ):
        try:
            await appel
            print(f"  {nom:9} -> AUCUNE ERREUR  <<< PROBLEME")
        except FileStorageUnavailableError:
            print(f"  {nom:9} -> FileStorageUnavailableError")
    print("  presign   ->", stockage.generate_presigned_url("x/y/z.png")[:44], "(hors ligne)")
    await stockage.aclose()


asyncio.run(main())
PY
```

Attendu : un `WARNING` nommant l'endpoint, `ping` à `False`, **quatre** levées — `exists` compris,
qui ne se rabat pas sur `False` — et une URL signée malgré tout, la signature étant un calcul local.
C'est le tableau de l'asymétrie, observé plutôt que lu.

**5. Basculer sur Amazon S3 ne demande qu'une configuration.** Vérifiable sans compte AWS :

```bash
S3_ENDPOINT_URL= uv run python -c "
from app.core import get_settings
from app.shared.infrastructure.clients.s3_storage import build_file_storage
stockage = build_file_storage(get_settings())
print('target :', stockage.target)
print('URL    :', stockage.generate_presigned_url('animal-photos/x/y.jpg').split('?')[0])
"
```

Attendu : `target : Amazon S3/juui-dev` et une URL sur `https://s3.amazonaws.com`. Une variable
vidée, **pas une ligne de code**.

**6. Le cycle de vie, et l'ordre de démarrage de la pile.**

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d api
```

Attendu, dans la sortie : `minio Healthy`, puis `minio-init Started`, puis **`minio-init Exited`**,
et seulement ensuite `api Started`. C'est le `depends_on: service_completed_successfully` qui
l'impose — un bucket dont la création a échoué empêche l'API de partir, au lieu de la laisser
découvrir l'absence au premier téléversement.

### Écarts assumés avec le ticket BACK-13

| Écart                                                                       | Raison                                                                                                                                                                                                                                                                                                                                               |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `boto3` synchrone dans `asyncio.to_thread`, plutôt qu'`aioboto3`            | Le ticket laisse le choix. `generate_presigned_url` — la seule opération sur le chemin des requêtes — ne fait **aucun** I/O et reste synchrone ; les quatre autres transportent des octets. `aioboto3` imposerait `aiobotocore`, qui épingle `botocore` à la version près, et rendrait inutiles les `boto3-stubs[s3]` déjà verrouillés par BACK-01.  |
| Aucune dégradation gracieuse, contrairement au cache                        | Un `upload` silencieux est un fichier perdu, un `exists` à `False` sur panne est un document de santé déclaré inexistant. Le contrat de `Cache` convient à un cache et à rien d'autre — sa propre docstring le dit déjà pour BACK-10d et BACK-17.                                                                                                    |
| `ping()` journalise au lieu de lever, alors que les opérations lèvent       | Troisième temps de l'asymétrie du service. Aucune route ne dépend encore du bucket : refuser de démarrer priverait le service de tout ce qui n'a rien à voir avec les fichiers. La panne se voit dans la ligne de démarrage, en `WARNING`, donc relayée même sans BACK-11.                                                                           |
| Clés sans segment de tenance, contrairement aux clés de cache               | Une clé de stockage est **persistée**, une clé de cache est volatile. La lier à `current_group_id` la rendrait introuvable depuis une tâche de fond, un export, ou après une bascule de structure. Le cloisonnement appartient à l'autorisation, pas au nommage d'une donnée durable.                                                                |
| Clés sans préfixe d'environnement, contrairement aux clés de cache          | Les environnements ont des **buckets** distincts : la séparation est déjà faite un cran au-dessus, et la répéter dans la clé n'ajouterait qu'un segment à taper.                                                                                                                                                                                     |
| `storage_keys.py`, hors de la portée nommée                                 | Même arbitrage que `cache_keys.py` en BACK-14 : l'`InMemoryFileStorage` de BACK-06c devrait sinon importer boto3 pour savoir nommer une clé. Deux fonctions et non une classe — contrairement à `CacheKeyBuilder`, il n'y a aucun état à porter.                                                                                                     |
| `generate_presigned_url` prend `operation` et `content_type`, non prévus    | Le ticket demande des URLs pré-signées « pour l'upload **et** le téléchargement » avec une seule signature. `operation` couvre les deux sans ajouter de sixième opération. `content_type` est **exigé** pour un téléversement : sans lui, le chemin principal du ticket échapperait entièrement à la validation MIME que ce même ticket réclame.     |
| La borne de taille ne couvre pas le téléversement pré-signé                 | Impossible autrement : un PUT pré-signé n'emporte aucune condition sur la longueur du corps. Seul un formulaire pré-signé (POST, `content-length-range`) l'exprimerait, et il n'a aucun appelant avant la route de téléversement. Le trou est nommé ici et dans la docstring du port plutôt que laissé à découvrir.                                  |
| `main.py` modifié, hors de la portée déclarée                               | Sans branchement dans le `lifespan`, l'adaptateur serait invérifiable en conditions réelles et inutilisable par la route qui le consommera. Même arbitrage qu'en BACK-03, BACK-05 et BACK-14.                                                                                                                                                        |
| `docker-compose.yml` modifié, hors de la portée déclarée                    | INFRA-04 y a laissé le `depends_on` de `minio-init` en commentaire, adressé nommément à BACK-13 : « à ajouter quand l'API touchera réellement au bucket ». C'est maintenant le cas.                                                                                                                                                                  |
| `botocore` ajouté aux `forbidden_modules` du contrat `domain-purity`        | L'adaptateur importe `botocore` **directement** — `Config` et les exceptions du client en viennent, pas de `boto3`. Interdire `boto3` sans lui laisserait au domaine un chemin ouvert vers la même technologie. La règle du pyproject s'étend ainsi : tout paquet qu'un adaptateur importe par son nom s'y déclare.                                  |
| Taille, types MIME et expiration en constantes, non configurables           | Même arbitrage que `_CONNECT_TIMEOUT_SECONDS` en BACK-05 et BACK-14 : chaque variable coûte deux gabarits, une ligne de compose et une ligne de README. Le ticket ne demande « configurable » que d'`endpoint_url`, et l'appelant passe déjà `expires_in`. **Aucun `.env.example` n'est donc modifié** — `S3Settings` était complète depuis BACK-03. |
| `retries={"max_attempts": 3}`, à l'inverse du `retries=0` du cache          | Une lecture de cache manquée se recalcule ; une opération de stockage manquée se perd. Le mode `standard` ne rejoue que ce qui est rejouable — 429, 5xx, erreurs de connexion —, jamais un refus d'autorisation.                                                                                                                                     |
| `addressing_style: "path"` et `signature_version: "s3v4"` épinglés          | Le style _virtual-host_ met le bucket dans le nom d'hôte, ce qui donnerait `juui-dev.minio:9000` — un nom qu'`app_network` ne résout pas. `s3v4` est exigé par MinIO et par toute région Amazon ouverte après 2014 ; l'écrire évite de dépendre du défaut de la version de botocore installée.                                                       |
| `mypy_boto3_s3` importé sous `if TYPE_CHECKING:`                            | Le paquet appartient au groupe `dev`, que le build d'INFRA-04 écarte (`--no-dev`). Un import à l'exécution ferait échouer le démarrage du **conteneur seulement** — le genre de panne qui ne se voit qu'en production. Vérifié : l'image reconstruite démarre.                                                                                       |
| `delete()` fait deux allers-retours                                         | S3 répond `204` qu'un objet ait existé ou non. Sans le `head_object` préalable, la méthode ne pourrait rendre que `True` en permanence, ce qui reviendrait à ne rien rendre. Course connue et sans gravité : un objet supprimé entre les deux appels fait rendre `True` à tort — le fichier est parti dans les deux cas.                             |
| Trois codes d'erreur reconnus comme « absent », pas seulement `NoSuchKey`   | `head_object` n'a pas de corps où loger un code : botocore y reporte le statut nu, `404`. S'en tenir à `NoSuchKey` ferait lever `exists()`, dont le travail est précisément de répondre non.                                                                                                                                                         |
| `image/heic` absent des types acceptés                                      | Format natif des photos d'iPhone, donc une lacune réelle — mais l'accepter sans conversion côté serveur produirait des fichiers que ni les navigateurs ni les visionneuses de bureau n'affichent. La question appartient au ticket qui exposera la route : convertir à l'arrivée, ou dans le navigateur.                                             |
| URL pré-signée non ouvrable depuis le poste quand l'API tourne en conteneur | L'URL porte l'hôte de `endpoint_url`, soit `http://minio:9000`, résolvable depuis `app_network` seulement. Y remédier demanderait un **second** endpoint, public — ce que le ticket écarte en posant qu'un seul paramètre sépare MinIO d'Amazon. Sans conséquence tant qu'aucune route ne publie ces URLs ; nommé pour celui qui le fera.            |
| Aucun test automatisé, mais six sondes documentées                          | `tests/` et la configuration de pytest appartiennent à BACK-12, qui nomme aussi le fichier de la portée. Même arbitrage qu'en BACK-02, BACK-03, BACK-04, BACK-05 et BACK-14. Les six sondes ci-dessus ont toutes été jouées avant livraison, l'expiration de l'URL comprise — `200` puis `403`.                                                      |

## Surface HTTP

La surface publique du service, posée par BACK-08 pour ses trois consommateurs **mécaniques** :
le healthcheck du conteneur Docker, la CI, et Orval
([ADR-0007](../../documentation/docs/adr/0007-client-api-genere-orval.md)), qui générera le
client des frontends à partir du schéma OpenAPI (SHARED-03). Les conventions de routage sont
consignées dans
l'[ADR-0011](../../documentation/docs/adr/0011-routage-versionne-par-module.md) ; cette section
dit comment elles se matérialisent ici.

### Le routeur racine `/api/v1`

Toutes les routes **métier** vivent sous `/api/v1`. Le préfixe de version se pose une fois, dans
[`shared/infrastructure/api/router.py`](src/app/shared/infrastructure/api/router.py) — la
**version** est un choix du service, le chemin de la **ressource** (`/auth`, …) reste celui du
module, chacun maître de sa moitié de l'URL. Le routeur racine est une **fonction**
(`build_api_router`) et non un routeur pré-assemblé : `shared` n'a pas le droit d'importer les
modules (contrat d'Import Linter n° 5), c'est donc [`main.py`](src/app/main.py) qui possède la
liste `_MODULE_ROUTERS` et la passe en argument.

### Deux sondes, deux questions

[`shared/infrastructure/api/health.py`](src/app/shared/infrastructure/api/health.py) répond à
deux questions distinctes, et l'URL des deux vit **hors** de `/api/v1` : une sonde est un
contrat d'exploitation — compose, orchestrateur, supervision — qui doit survivre à une v2 sans
reconfiguration.

- **`GET /health/live`** — « le processus répond-il ? ». Aucune dépendance externe : c'est la
  sonde du conteneur, et une base arrêtée ne doit pas faire redémarrer l'API en boucle.
- **`GET /health/ready`** — « le service peut-il servir ? ». PostgreSQL (le `SELECT 1` de
  `verify_connectivity`, BACK-05) et Redis (PING, BACK-14) sont interrogés **en parallèle** ;
  le premier composant défaillant vaut `503`, avec un corps qui le nomme :
  `{"status":"unready","components":{"postgres":"ok","redis":"unreachable"}}`.

Redis est **bloquant ici, et seulement ici** : les routes métier dégradent sans cache
([l'asymétrie du service](#lasymétrie-du-service-a-trois-temps-pas-deux)), mais la sonde de
disponibilité doit dire la vérité d'une panne — retirer l'instance du trafic n'est pas casser le
service. Le stockage objet, lui, n'est **pas** sondé : aucune route n'en dépend (BACK-13), et
ses opérations lèvent d'elles-mêmes.

### Étiquettes, `operation_id` et le client généré

L'étiquette OpenAPI vaut le **nom du module** — une par contexte métier, plus `health`. Orval
découpe le client généré par étiquette (`tags-split`) : le découpage du code frontend coïncide
ainsi avec la carte des modules, gratuitement. Chaque route porte un **`operation_id` explicite,
égal au nom de sa fonction**, en snake_case verbe-objet (`check_liveness`, `check_readiness`) :
Orval en dérive le nom des hooks, et l'égalité rend la convention vérifiable au grep — puis par
un test de BACK-12.

### Métadonnées OpenAPI et la production

`create_app()` pose title, description, version, contact et les descriptions d'étiquettes
(`_OPENAPI_TAGS`). Quand `ENVIRONMENT=production`, la surface de documentation se ferme
**entièrement** : `/docs`, `/redoc` et `/openapi.json` répondent 404. La fermeture se décide à
la **construction** de l'application, d'après `AppSettings` seul — voir les écarts ci-dessous.

### Le périmètre de requête

Le groupe actif voyage dans le **jeton** (claim `active_group_id`), la clinique active dans
l'**en-tête** `X-Clinic-Id`, jamais l'inverse — et l'en-tête n'autorise rien. La convention, ses
alternatives écartées et ce qu'elle coûte sont consignés dans
l'[ADR-0012](../../documentation/docs/adr/0012-perimetre-de-requete.md) ; son application
revient à BACK-10c (dépendance d'authentification) et BACK-10e (bascule de groupe).

### Vérifier que la surface tient

Cinq sondes. Les trois premières se jouent depuis la **racine du monorepo**, pile lancée ; les
deux dernières depuis `backend/api`.

**1. Les deux sondes répondent.**

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d --build api
curl -s http://localhost:8000/health/live
# {"status":"alive"}
curl -s http://localhost:8000/health/ready
# {"status":"ready","components":{"postgres":"ok","redis":"ok"}}
```

**2. La panne se nomme.** Composant par composant, et le code passe à 503.

```bash
docker compose --project-directory . -f docker/docker-compose.yml stop postgres
curl -si http://localhost:8000/health/ready | head -1
# HTTP/1.1 503 Service Unavailable
curl -s http://localhost:8000/health/ready
# {"status":"unready","components":{"postgres":"unreachable","redis":"ok"}}
docker compose --project-directory . -f docker/docker-compose.yml start postgres

docker compose --project-directory . -f docker/docker-compose.yml stop redis
curl -s http://localhost:8000/health/ready
# {"status":"unready","components":{"postgres":"ok","redis":"unreachable"}}
docker compose --project-directory . -f docker/docker-compose.yml start redis
```

**3. Le conteneur se déclare sain** — sa sonde vise désormais `/health/live` (interval 10 s).

```bash
docker compose --project-directory . -f docker/docker-compose.yml ps api
# STATUS ... (healthy)
```

**4. La production ferme la documentation.** Le `JWT_SECRET_KEY` est nécessaire : la
configuration refuse de partir en production avec la clé du gabarit
([BACK-03](#configuration)) — et le `lifespan` exige toujours PostgreSQL, donc la pile reste
lancée.

```bash
uv run uvicorn app.main:app --port 8001 &
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/docs          # 200
kill %1

ENVIRONMENT=production JWT_SECRET_KEY=$(openssl rand -hex 32) \
  uv run uvicorn app.main:app --port 8001 &
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/docs          # 404
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/redoc         # 404
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/openapi.json  # 404
kill %1
```

**5. Le schéma dit qui il est.** Métadonnées, étiquettes et `operation_id` — ce que verra Orval.

```bash
curl -s http://localhost:8000/openapi.json | uv run python -c "
import json, sys
spec = json.load(sys.stdin)
info = spec['info']
print(info['title'], info['version'], info.get('contact'))
print([tag['name'] for tag in spec.get('tags', [])])
for path, ops in spec['paths'].items():
    for method, op in ops.items():
        print(method.upper(), path, '->', op.get('operationId'), op.get('tags'))
"
# Juui API 0.1.0 {'name': 'Equipe Juui', 'url': 'https://github.com/kederiku/juui'}
# ['health', 'identity']
# GET /health/live -> check_liveness ['health']
# GET /health/ready -> check_readiness ['health']
```

### Écarts assumés avec le ticket BACK-08

| Écart                                                                | Raison                                                                                                                                                                                                                                                                                                                                                                      |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sondes montées hors du routeur racine `/api/v1`                      | Le ticket parle d'« un routeur racine unique », mais l'URL d'une sonde est un contrat d'**exploitation** : la versionner casserait l'orchestration à chaque montée de version, et le healthcheck du compose — écrit par INFRA-04 à l'intention de BACK-08 — vise littéralement `/health/live`. La checklist du ticket réserve d'ailleurs `/api/v1` aux « routes métier ».   |
| `/openapi.json` fermé en production, au-delà du ticket               | Le ticket ne nomme que `/docs` et `/redoc`. Mais plus aucun consommateur légitime ne reste : la sonde du conteneur vise `/health/live`, et Orval (SHARED-03) génère depuis un poste de développement. Un plan complet de l'API servi sans authentification est de la reconnaissance offerte.                                                                                |
| `/health/ready` n'interroge pas le stockage objet                    | Le ticket nomme PostgreSQL et Redis, et c'est cohérent : aucune route ne dépend du bucket (BACK-13), et ses opérations **lèvent** — une panne S3 ne justifie pas de retirer du trafic un service qui n'en fait rien. Nommé dans la docstring de `health.py`, à rediscuter au premier module consommateur de fichiers.                                                       |
| `create_app()` lit `AppSettings()` directement, pas `get_settings()` | `app = create_app()` s'exécute à l'**import**, qui doit rester possible sans `.env` complet — la règle posée par le `lifespan`. `AppSettings` n'a que des champs à défaut ; `Settings` réclamerait `POSTGRES_USER` et consorts. Corollaire : la fermeture de `/docs` se surcharge par `create_app(app_settings=...)`, pas par `dependency_overrides`.                       |
| `redis_cache.py` (BACK-14) retouché                                  | `ping()` gagnait un second appelant **périodique** — la sonde de disponibilité — et son INFO de joignabilité partait à chaque succès : une ligne toutes les dix secondes après BACK-11. L'INFO ne part plus qu'au premier succès, la reprise après panne restant annoncée par `_recover`. Le libellé d'échec « demarrage » devient « sonde », les deux appelants confondus. |
| `contact` réduit au nom et au dépôt                                  | Aucune adresse de support n'existe : en inventer une serait pire que ce vide. Le nom et l'URL du dépôt satisfont l'exigence de métadonnées sans mentir — à compléter quand une adresse réelle existera.                                                                                                                                                                     |
| `docker-compose.yml` modifié, hors de la portée déclarée             | INFRA-04 y a laissé sa sonde provisoire avec un commentaire adressé nommément à ce ticket : « À BASCULER SUR /health/live À BACK-08 ». Même arbitrage qu'en BACK-13.                                                                                                                                                                                                        |
| Aucun test automatisé, mais cinq sondes documentées                  | `tests/` et la configuration de pytest appartiennent à BACK-12 — auquel ce ticket lègue aussi un test tout désigné : chaque `APIRoute` porte un `operation_id` explicite égal au nom de sa fonction. Même arbitrage qu'en BACK-02, BACK-03, BACK-04, BACK-05, BACK-06a, BACK-07, BACK-13 et BACK-14. Les cinq sondes ci-dessus ont été jouées avant livraison.              |

## Dépendances

Deux groupes, strictement séparés. Le build Docker d'INFRA-04 installera le
premier seulement (`uv sync --frozen --no-dev`).

### Applicatives

| Paquet                | Rôle                                                                  |
| --------------------- | --------------------------------------------------------------------- |
| `fastapi`             | Framework HTTP et génération du contrat OpenAPI.                      |
| `uvicorn[standard]`   | Serveur ASGI. L'extra apporte uvloop, httptools et le `--reload`.     |
| `pydantic`            | Validation et sérialisation des schémas d'API.                        |
| `pydantic-settings`   | Configuration typée, lue de l'environnement (BACK-03).                |
| `sqlalchemy[asyncio]` | ORM. L'extra tire `greenlet`, sans lequel l'asynchrone ne marche pas. |
| `asyncpg`             | Pilote PostgreSQL asynchrone.                                         |
| `alembic`             | Migrations de schéma — voir [Migrations](#migrations).                |
| `pyjwt`               | Émission et vérification des jetons d'authentification (BACK-10).     |
| `redis`               | Cache applicatif (BACK-14) et, plus tard, broker de TaskIQ.           |
| `taskiq`              | Tâches de fond (BACK-15). Le broker Redis viendra avec ce ticket.     |
| `boto3`               | Stockage objet S3 en production, MinIO en développement (BACK-13).    |

### Développement (`dev`)

| Paquet            | Rôle                                                  |
| ----------------- | ----------------------------------------------------- |
| `ruff`            | Lint et formatage. Épinglé à l'exact — voir plus bas. |
| `mypy`            | Vérification de types en mode strict.                 |
| `import-linter`   | Contrats d'architecture. Épinglé à l'exact lui aussi. |
| `pytest`          | Cadre de test.                                        |
| `pytest-asyncio`  | Support des tests asynchrones.                        |
| `pytest-cov`      | Mesure de couverture.                                 |
| `httpx`           | Client HTTP de test, via `ASGITransport`.             |
| `boto3-stubs[s3]` | Stubs de typage de boto3, limités au service S3.      |

`boto3` est le seul paquet de la liste à ne pas embarquer ses propres
annotations : tous les autres livrent un `py.typed`, et leurs paquets `types-*`
d'antan ont été retirés de PyPI.

**Ruff et Import Linter sont épinglés à la version exacte**, contrairement à
tout le reste. Un outil qui change d'avis tout seul entre deux `uv sync` ferait
échouer la CI sans qu'une ligne de code ait bougé : leur montée de version doit
rester un commit délibéré.

### La version d'`uv`, et la borne du backend de build

Même raisonnement, appliqué à l'outil qui installe tous les autres — mais il a
fallu un incident pour l'y appliquer.

`uv` tourne dans **trois** environnements, et chacun portait sa propre
politique : le [Dockerfile](../../docker/api/Dockerfile) l'épinglait à l'exact
(`ARG UV_VERSION`), la [CI backend](../../.github/workflows/ci-backend.yml) le
laissait flotter, le poste suivait son gestionnaire de paquets. Rien ne les
obligeait à s'accorder. La CI a donc glissé en 0.12.5 pendant que le poste
restait en 0.11.7, et le seul symptôme fut une ligne dans chaque log de CI :

```
warning: `build_system.requires = ["uv-build>=0.11.7,<0.12.0"]` does not contain the current uv version 0.12.5
```

Les trois sont désormais alignés sur **0.12.5**, et `[tool.uv]
required-version` fait de cet accord une **contrainte** plutôt qu'une
convention : un `uv` hors de la plage déclarée s'arrête net —

```
error: Required uv version `>=0.12.5, <0.13` does not match the running version `0.11.7`
```

— au lieu de réussir en le murmurant dans un log. Une plage, et non un `==` :
l'arbitrage est consigné dans
l'[ADR-0002](../../documentation/docs/adr/0002-uv-outillage-python.md).

**La borne haute du backend de build est passée de `<0.12.0` à `<0.13.0`.** Elle
ne venait d'aucune décision : c'était la sortie littérale d'`uv init` sous uv
0.11, jamais commentée. Deux vérifications avant de l'élargir. Les notes de
version d'uv 0.12.0, d'abord, qui sont explicites — « _There are no breaking
changes to the configuration of the uv build backend_ », avec la recommandation
d'ouvrir jusqu'à 0.13. Ce projet ensuite, où `module-name = "app"` et la
disposition `src/` sont ce qui pourrait souffrir : les roues construites sous
0.11.7 et sous 0.12.5 portent 37 fichiers, dont **35 identiques octet pour
octet**. Les deux autres sont la ligne `Generator:` du fichier `WHEEL`, qui
nomme le constructeur, et son empreinte dans `RECORD`. Le paquet `app/` et le
`METADATA` ne bougent pas.

Le plancher reste à `>=0.11.7`, et non au `>=0.11.32` de l'exemple amont : c'est
la version qui a construit ce projet et celle qu'embarquait l'image Docker. Le
relever rendrait la déclaration fausse pour les roues déjà produites.

> **Cette borne ne contraint rien**, et le savoir évite de s'y fier. uv emploie
> son backend intégré dès que la version déclarée tombe dans sa plage connue
> compatible, et ne va chercher le paquet `uv_build` sur PyPI qu'en dehors. La
> CI construisait donc **déjà** avec `uv_build` 0.12.5 quand la borne disait
> `<0.12.0` : l'avertissement signalait une déclaration périmée, pas un
> changement de backend. Ce que la borne déclare, ce sont les versions sous
> lesquelles cette roue est _vérifiée_.

Les deux bornes s'arrêtent à 0.13 — celle d'`uv_build` et celle de
`required-version` — et se rediscutent ensemble, comme le consigne
l'[ADR-0002](../../documentation/docs/adr/0002-uv-outillage-python.md).

`uv.lock` n'entre pas dans l'affaire : uv ne verrouille pas les dépendances de
build, le fichier ne contient aucune entrée `uv-build`, et changer cette borne
ne le désaccorde pas. Aucun `uv lock` n'est à relancer.

## Qualité et typage

Ruff, Mypy et Import Linter sont configurés dans
[`pyproject.toml`](pyproject.toml), chaque réglage accompagné de sa
justification. Quatre vérifications, toutes lançables depuis ce dossier :

| Commande                       | Raccourci           | Rôle                      |
| ------------------------------ | ------------------- | ------------------------- |
| `uv run ruff check .`          | `make lint`         | Lint                      |
| `uv run lint-imports`          | `make imports`      | Contrats d'architecture   |
| `uv run ruff format --check .` | `make format-check` | Formatage (lecture seule) |
| `uv run mypy src`              | `make typecheck`    | Typage strict             |

`make lint` enchaîne les deux premières — Ruff d'abord, la vérification la moins
chère. `make check` enchaîne les quatre **dans l'ordre qu'aura la CI** (QA-01) :
un échec local reproduit donc un échec de CI. `make` seul liste toutes les
cibles.

Deux cibles réécrivent le code : `make format` (`ruff format .`) et `make lint-fix`
(`ruff check --fix .`, corrections sûres uniquement).

Ces deux-là s'appliquent aussi **toutes seules au moment du commit** : le hook de
pre-commit du monorepo (SETUP-04) passe chaque fichier `.py` indexé par
`ruff check --fix` puis `ruff format`, et interrompt le commit sur ce qui reste.
Voir [Hooks de pre-commit](../../README.md#hooks-de-pre-commit). Le typage et
les contrats d'architecture, eux, n'entrent pas dans le hook : lint-staged passe
des **fichiers**, quand Mypy et Import Linter raisonnent sur le **projet
entier**. Ils restent à lancer à la main, et la CI les vérifie.

### Ruff

Lint **et** formatage : `ruff format` remplace Black, il n'y a aucune autre
dépendance de formatage. Ligne à 100 caractères, cible `py314`.

Le jeu de règles : `E`/`F` (socle), `I` (tri des imports), `N` (nommage), `UP`
(modernisation de la syntaxe), `B` (pièges classiques), `A` (masquage des
builtins), `C4`, `SIM`, `RUF`, `ANN` (annotations obligatoires), `S` (sécurité)
et `D` (docstrings).

Dans `tests/` — à venir en BACK-12 — `assert` (S101) et les docstrings (D1xx)
sont relâchés. Les annotations, non : `-> None` sur une fonction de test coûte
huit caractères.

À noter : `ruff format` traite aussi les blocs de code Python **de la
documentation Markdown**, ce qui garde les exemples conformes. Un extrait
volontairement incomplet est ignoré sans erreur, et `ruff check` ne lint jamais
les fichiers Markdown.

### Mypy

Mode `strict`, plugin Pydantic activé, périmètre `src/` (les tests y entreront
avec BACK-12 si ce ticket le décide). `strict` couvre à lui seul
`disallow_untyped_defs`, `warn_return_any` et `warn_unused_ignores`, entre
autres — d'où l'absence de ces clés dans le `pyproject.toml`.

Aucune dépendance ne réclame `ignore_missing_imports` : toutes livrent un
`py.typed`, et `boto3` est couvert par `boto3-stubs[s3]`. Si une librairie sans
stubs entre un jour, la dérogation se déclare **par module** — jamais
globalement, ce qui aveuglerait Mypy sur tout le projet. Le modèle est en
commentaire dans le `pyproject.toml`.

Pour vérifier que le filet tient, une fonction non annotée doit faire échouer
Mypy :

```bash
printf '"""Sonde."""\n\n\ndef f(x):\n    """Doc."""\n    return x\n' > src/app/_sonde.py
uv run mypy src ; uv run ruff check src/app/_sonde.py ; rm src/app/_sonde.py
```

Attendu : `[no-untyped-def]` côté Mypy, `ANN001` et `ANN202` côté Ruff — les deux
barrières répondent.

### Écarts assumés avec le ticket BACK-02

| Écart                                               | Raison                                                                                                                             |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `target-version = "py314"` et non `py312`           | Le projet est verrouillé sur Python 3.14. Cibler py312 ferait réécrire par Ruff du code déjà moderne.                              |
| ANN101/ANN102 ne sont pas ignorées                  | Ruff les a **retirées**. Les nommer dans `ignore` ne produirait qu'un avertissement à chaque exécution et dans chaque log de CI.   |
| `S` et `D` ajoutés au jeu de règles                 | Sans eux, l'assouplissement demandé pour `tests/` (« assert autorisé, docstrings non requises ») n'aurait relâché rien du tout.    |
| Les trois drapeaux Mypy nommés ne sont pas réécrits | `strict = true` les active déjà tous les trois.                                                                                    |
| Aucun `[[tool.mypy.overrides]]` vivant              | Vrai jusqu'à BACK-05, qui en a ajouté un pour `asyncpg` — la seule dépendance sans `py.typed`. Le motif reste documenté sur place. |

### Import Linter

BACK-04 a posé les règles d'architecture ; BACK-04b les rend **mécaniques**.
[Import Linter](https://import-linter.readthedocs.io/) lit le graphe d'imports
réel du paquet `app` et refuse ce qui ne respecte pas les contrats déclarés en
`[tool.importlinter]`. Une violation échoue donc en CI, elle ne se découvre plus
six mois plus tard en revue de code.

| #   | Contrat               | Type           | Ce qu'il tient                                                                                        |
| --- | --------------------- | -------------- | ----------------------------------------------------------------------------------------------------- |
| 1   | `domain-purity`       | `forbidden`    | `modules/*/domain/` et `shared/domain/` n'importent aucun paquet technique — douze sont nommés        |
| 2   | `module-layers`       | `layers`       | dans chaque module : `infrastructure` → `application` → `domain`, jamais l'inverse                    |
| 3   | `module-independence` | `independence` | les modules ne s'importent pas mutuellement, **même indirectement**                                   |
| 4   | `shared-layers`       | `layers`       | dans `shared/` : `infrastructure` → `domain`                                                          |
| 5   | `service-spaces`      | `layers`       | `main` > `modules` > `shared` > `core` — « `shared` est importable par tous, l'inverse est interdit » |

Trois choix de configuration méritent d'être connus avant d'y toucher :

- **Les contrats 2 et 3 visent `app.modules.*`, pas une liste de modules.** Ils
  couvriront `organization` (BACK-16), `medical_records` (BACK-19) et les
  suivants le jour où ceux-ci naîtront — c'est la différence entre un garde-fou
  et une liste qu'on oublie de tenir à jour.
- **Les couches du contrat 2 sont optionnelles** (elles s'écrivent entre
  parenthèses) parce que `modules/organization/` ne porte encore qu'un
  `__init__.py`. Ce que cela relâche, `exhaustive = true` le rattrape : tout
  fichier ou dossier ajouté dans un module, dans `shared/` ou à la racine d'`app`
  fait échouer le contrat tant qu'il n'est pas déclaré comme une couche. Seul
  `unit_of_work` est exempté — BACK-04 le range volontairement à la racine du
  module, parce qu'il compose les trois couches.
- **Le contrat 1 nomme douze paquets, pas les cinq du ticket.**
  `pydantic_settings` est un paquet distinct de `pydantic`, et `jwt` est le nom
  d'import réel de `pyjwt`. Règle à tenir : **toute dépendance applicative
  ajoutée au projet s'ajoute à cette liste, dans la même pull request**.

**Les exceptions.** Aucune n'est nécessaire aujourd'hui. Le jour où l'une le
devient, elle s'écrit dans le `ignore_imports` du contrat concerné — jamais en
désactivant le contrat — et porte son motif et sa date de revue :

```toml
ignore_imports = [
    # MOTIF : <pourquoi cette entorse est tolerable>
    # REVUE : AAAA-MM-JJ  <date a laquelle elle doit etre reexaminee>
    "app.modules.x.domain -> paquet.y",
]
```

Rien n'oblige à tenir la date, mais rien ne laisse non plus l'exception dormir :
`unmatched_ignore_imports_alerting` vaut `"error"` par défaut, si bien qu'une
exception devenue sans objet fait échouer le lint — `No matches for ignored
import …` — au lieu de survivre à l'import qu'elle couvrait.

**Le garde-fou est lui-même vérifié.** Un contrat qu'on n'a jamais vu échouer est
un contrat dont on ne sait rien. Chacun a été cassé volontairement, puis remis en
état ; le tableau se rejoue en quelques minutes le jour où l'on touche à la
configuration.

| Violation introduite                                                     | Contrat qui tombe                               |
| ------------------------------------------------------------------------ | ----------------------------------------------- |
| `import sqlalchemy` dans `modules/identity/domain/policies.py`           | 1                                               |
| `domain/entities.py` importe `application/use_cases/create_account.py`   | 2                                               |
| `modules/organization/__init__.py` importe une entité d'`identity`       | 3                                               |
| `shared/domain/exceptions.py` importe `shared/infrastructure/db/base.py` | 4, **et 1** par la chaîne qui mène à SQLAlchemy |
| `core/config.py` importe `shared/domain/exceptions.py`                   | 5                                               |
| un fichier `modules/identity/services.py`                                | 2, sur l'exhaustivité                           |
| `organization` importe un module de `shared/` qui importe `identity`     | 3, **par un chemin indirect**                   |

Les deux dernières lignes sont celles qui comptent : ni un `grep`, ni une revue
de code pressée n'auraient vu la couche clandestine ni la chaîne à deux sauts.

### Écarts assumés avec le ticket BACK-04b

| Écart                                                             | Raison                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.github/workflows/ci-backend.yml` est **créé ici**, pas en QA-01 | Le ticket met le fichier dans sa portée, et l'objectif — « une violation doit échouer en CI » — ne se tient pas autrement. Le workflow ne porte qu'un job, et son en-tête énumère ce que QA-01 viendra y ajouter : Ruff, Mypy, pytest, les services PostgreSQL et Redis, la couverture et le contrôle des migrations.                                                                                                                                                            |
| Cinq contrats au lieu de trois                                    | Les contrats 4 et 5 sortent de la portée littérale. Sans le 4, `shared/` — la seule couche dont **tous** les modules dépendent — serait la seule que rien ne garde. Sans le 5, la phrase du ticket « `app.shared` est importable par tous, l'inverse est interdit » resterait déclarative, ce qui est précisément ce que le ticket reproche à BACK-04.                                                                                                                           |
| Douze paquets interdits au lieu de cinq                           | `pydantic_settings` et `jwt` ne sont pas couverts par `pydantic` et `pyjwt` : ce sont d'autres noms d'import. S'en tenir à cinq aurait laissé passer les sept autres dépendances déclarées du projet.                                                                                                                                                                                                                                                                            |
| `app.core` **absent** de la liste interdite                       | Un domaine pur ne devrait rien lire de sa configuration, mais l'arbitrage inverse appartient à BACK-04, qui l'a rendu par écrit dans [`core/__init__.py`](src/app/core/__init__.py) — « le domaine ne doit rien y importer d'autre que des réglages ». Le contrat 5 garde le **sens** de cette dépendance ; y revenir serait rouvrir BACK-04.                                                                                                                                    |
| `source_modules` couvre aussi `app.shared.domain`                 | Le ticket ne nomme que `app.modules.*.domain`. La racine des erreurs métier est un domaine comme un autre, et la sonde `grep` de BACK-04 la couvrait déjà : la restreindre aurait été une régression.                                                                                                                                                                                                                                                                            |
| Configuration dans `pyproject.toml`, pas dans un `.importlinter`  | Le ticket offrait les deux. Ruff et Mypy y sont déjà : un seul fichier d'outillage Python, un seul format, et les justifications écrites au même endroit que les leurs.                                                                                                                                                                                                                                                                                                          |
| Rien dans le hook de pre-commit                                   | lint-staged passe des **fichiers**, Import Linter analyse le **projet entier** et construit un graphe incluant les paquets externes. C'est un coût fixe à chaque commit touchant un `.py`, pour un hook dont SETUP-04 a fixé le budget à 10 s. Même arbitrage que Mypy, qui n'y entre pas non plus.                                                                                                                                                                              |
| `uv sync --locked` en CI, là où QA-01 écrit `--frozen`            | Les deux installent les versions du verrou, mais `--frozen` ne le **regarde pas** : un `pyproject.toml` modifié sans `uv lock` passerait en silence, et la CI vérifierait un environnement qui n'est pas celui du dépôt. `--locked` est le pendant exact du `--frozen-lockfile` de pnpm employé par [`documentation.yml`](../../.github/workflows/documentation.yml). La description de `--frozen` en tête de ce README, qui lui prêtait ce contrôle, a été corrigée au passage. |
| Aucun test automatisé, mais un tableau de violations documenté    | `tests/` appartient à BACK-12. Même arbitrage qu'en BACK-02, BACK-03 et BACK-04. Les sept violations ci-dessus ont toutes été jouées avant livraison.                                                                                                                                                                                                                                                                                                                            |

## Ce qui n'est pas encore là

| Sujet                                 | Ticket   |
| ------------------------------------- | -------- |
| Filtrage multi-tenant automatique     | BACK-06b |
| Doublures en mémoire (fakes)          | BACK-06c |
| Traduction des erreurs métier en HTTP | BACK-09  |
| Suite de tests                        | BACK-12  |
| Pipeline CI complet du backend        | QA-01    |

La structure modulaire et hexagonale est posée (BACK-04) et ses règles sont
désormais tenues par [Import Linter](#import-linter) (BACK-04b), le socle de
persistance est en place (BACK-05), l'[unité de travail](#unité-de-travail)
avec son dépôt générique le coiffe (BACK-06a) et le schéma est sous contrôle de
version par les [migrations](#migrations) (BACK-07), quatre des cinq ports
techniques du noyau partagé sont livrés — [cache](#cache) (BACK-14),
[stockage objet](#stockage-objet) (BACK-13), unité de travail et dépôt
générique (BACK-06a), `TokenService` restant à BACK-10a —, la
[surface HTTP](#surface-http) versionnée et ses sondes sont en place (BACK-08),
Ruff et Mypy sont configurés (BACK-02). Les dépendances de test, elles, restent
**déclarées sans être configurées** : c'est volontaire, chaque ticket porte son
propre outil.
