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

> L'API ne sert **aucune route** pour l'instant : `/docs` s'affiche donc vide.
> C'est attendu — le routeur du module `identity` est bien monté (BACK-04), mais
> ses routes relèvent de BACK-28 et BACK-29, et la sonde de santé de BACK-08.

## Structure

```
backend/api/
├── pyproject.toml     dépendances, métadonnées, configuration des outils
├── uv.lock            versions résolues — versionné, jamais édité à la main
├── .python-version    interpréteur du projet (3.14)
├── .env.example       gabarit d'environnement — miroir des champs de `Settings`
├── Makefile           raccourcis de lint, formatage et typage
└── src/app/
    ├── main.py             assemblage de l'application et des routeurs
    ├── core/               réglages du processus, ni domaine ni infrastructure
    │   └── config.py       configuration typée (BACK-03)
    ├── shared/             noyau partagé — pas un module métier
    │   ├── domain/
    │   │   ├── exceptions.py   `DomainError`, racine des erreurs métier
    │   │   └── ports/          ports techniques : cache, stockage, jetons
    │   └── infrastructure/
    │       ├── db/             socle de persistance (BACK-05)
    │       │   ├── base.py         `Base`, convention de nommage, `check_schema`
    │       │   ├── mixins.py       identité, horodatage, tenance opt-in
    │       │   ├── engine.py       moteur asyncpg et pool de connexions
    │       │   └── session.py      fabrique de sessions et accès à `app.state`
    │       └── api/            socle HTTP : handlers d'erreur, intergiciels
    └── modules/            contextes métier, étanches les uns aux autres
        ├── identity/       module pilote — le seul complet à ce stade
        │   ├── domain/         entities, policies, ports, exceptions
        │   ├── application/    use_cases/
        │   ├── infrastructure/ db/ (modèle, dépôt), api/ (schémas, routeur)
        │   └── unit_of_work.py
        └── organization/   groupes et appartenances (BACK-16)
```

Le paquet s'appelle `app` alors que le projet se nomme `juui-api` : la
correspondance est déclarée par `[tool.uv.build-backend] module-name`.

Le détail de ce découpage — ce que chaque espace a le droit d'importer, et
pourquoi — est l'objet de la section [Architecture](#architecture).

### `main.py`

Le module d'assemblage, et rien d'autre : aucune logique métier n'y a sa place.

- **`create_app()`** construit une instance neuve de l'application. Les tests
  (BACK-12) en dépendront pour repartir d'une application propre à chaque cas.
- **`app = create_app()`** est le point d'entrée ASGI, celui que désigne
  `uvicorn app.main:app`. Un serveur ASGI attend un objet, pas une fonction.
- **`_MODULE_ROUTERS`** est la liste des routeurs montés. Un tuple plutôt
  qu'une suite d'appels : la liste des contextes servis par l'API se lit d'un
  coup d'œil, et chaque module reste maître de son préfixe. C'est le seul
  endroit du service autorisé à connaître plusieurs modules à la fois.
- **`lifespan`** est le point d'accroche des ressources de longue durée. Il pose
  la règle que toutes devront suivre : rien ne s'ouvre à l'import du module, tout
  passe par lui, et l'ordre de fermeture est l'inverse exact de l'ordre
  d'ouverture. Deux occupants à ce jour — la validation de la configuration
  (BACK-03), qui précède par construction toute ouverture de ressource, puis le
  [moteur PostgreSQL](#persistance) (BACK-05). Le client Redis (BACK-14) et le
  broker TaskIQ (BACK-15) suivront.

## Architecture

Hexagonale — ports et adaptateurs — **à l'intérieur de modules métier**, et non un domaine plat.
Le découpage par couche seule finit par produire un `domain/entities/` où quarante entités
s'empilent sans qu'aucune frontière ne dise laquelle répond à quelle question. Ici, c'est le
**module** qui porte la frontière ; la couche ne décrit que le sens des dépendances.

Les règles ci-dessous deviendront **mécaniques** avec les contrats import-linter de BACK-04b :
une violation échouera en CI plutôt que de se découvrir six mois plus tard en revue de code. En
attendant, [quatre sondes](#vérifier-que-les-règles-tiennent) en tiennent lieu.

### Les trois espaces

| Espace     | Ce qu'il porte                                                                           | Ce qu'il importe   |
| ---------- | ---------------------------------------------------------------------------------------- | ------------------ |
| `core/`    | réglages du **processus** : configuration (BACK-03), journalisation (BACK-11)            | rien du métier     |
| `shared/`  | noyau **partagé** : racine des erreurs, ports techniques, socles de persistance et d'API | `core/`            |
| `modules/` | les **contextes métier**, étanches les uns aux autres                                    | `core/`, `shared/` |

La relation entre les deux derniers est à sens unique : `modules/` → `shared/` est autorisé,
`shared/` → `modules/` ne l'est jamais. Un noyau partagé qui connaîtrait un contexte métier en
connaîtrait bientôt un deuxième, et deviendrait le fourre-tout dont plus personne ne peut rien
retirer.

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

| #   | Étape                                                                        | Fichier                                   |
| --- | ---------------------------------------------------------------------------- | ----------------------------------------- |
| 1   | `AccountCreate` valide le JSON reçu                                          | `infrastructure/api/schemas.py`           |
| 2   | `.to_command()` en fait une `CreateAccountCommand`, sans vocabulaire HTTP    | `infrastructure/api/schemas.py`           |
| 3   | `CreateAccount.execute()` normalise, contrôle l'unicité, appelle la fabrique | `application/use_cases/create_account.py` |
| 4   | `Account.create()` applique les règles et attribue l'identifiant             | `domain/entities.py`                      |
| 5   | `AccountRepository.add()` reçoit **l'entité**, jamais un modèle              | `domain/ports.py`                         |
| 6   | `_to_model()` traduit l'entité en ligne de la table `accounts`               | `infrastructure/db/repositories.py`       |
| 7   | `AccountRead.from_entity()` remonte l'entité en réponse JSON                 | `infrastructure/api/schemas.py`           |

La commande de l'étape 2 n'est **pas** un quatrième modèle du compte : elle décrit une
_intention_, pas un état persistant. C'est ce qui permet d'appeler le cas d'usage depuis une
route, une tâche de fond ou une commande en ligne sans changer sa signature.

Le cas d'usage ne reçoit qu'un **port**, jamais une session : celui-ci lui sera fourni par
l'unité de travail à partir de BACK-06a, et la règle qui compte est déjà tenue aujourd'hui.

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
donc tenir dans le temps.

L'arbitrage est déjà pris ailleurs sur le board : la liste d'administration des comptes
particuliers (BACK-26) affiche un nombre d'animaux, et ce compteur vient du cas d'usage public de
`medical_records` (BACK-30), jamais d'un `JOIN` sur ses tables.

Depuis BACK-04b, la règle n'est plus seulement écrite : le contrat
[`module-independence`](#import-linter) la fait respecter, dans les deux sens et **même
indirectement**.

Une seule chose est partagée entre modules côté persistance : la `Base` déclarative. Ce n'est pas
une entorse — les modules ne s'importent pas, mais ils écrivent dans la **même base**, donc dans
le même registre de métadonnées. Deux `Base` distinctes donneraient deux jeux de métadonnées, et
Alembic (BACK-07) n'en verrait qu'un à la fois.

**Le piège à éviter** : ne pas calquer les modules sur les trois frontends.
`frontend-professional`, `frontend-individual` et `frontend-admin` sont des canaux de livraison,
pas des contextes métier — le cœur d'authentification (hachage, OTP, 2FA, session, révocation) y
est identique, et serait triplé à l'identique. Le type de compte est une _propriété_ portée par
`identity` ; c'est l'audience du jeton (BACK-10a) qui sépare les trois applications.

### Les modules prévus

| Module            | Question à laquelle il répond                   | Ticket  |
| ----------------- | ----------------------------------------------- | ------- |
| `identity`        | peux-tu prouver qui tu es                       | BACK-04 |
| `organization`    | dans quelle structure travailles-tu, affecté où | BACK-16 |
| `medical_records` | de quels animaux s'agit-il                      | BACK-19 |
| `scheduling`      | quand, avec qui, pour quel acte                 | BACK-21 |
| `notifications`   | qui prévenir, par quel canal                    | BACK-22 |
| `profile`         | où habite ce particulier                        | BACK-32 |

### Ce que la structure attend encore

Les dossiers vides ne le sont pas par oubli : chacun porte une docstring qui dit ce qui vient s'y
ranger, et quel ticket l'apporte.

| Emplacement                        | Ce qui manque                                                       | Ticket                               |
| ---------------------------------- | ------------------------------------------------------------------- | ------------------------------------ |
| `shared/domain/ports/`             | `Cache`, `FileStorage`, `TokenService`, l'unité de travail          | BACK-14, BACK-13, BACK-10a, BACK-06a |
| `shared/domain/exceptions.py`      | la hiérarchie complète et les codes `<module>.<ressource>.<erreur>` | BACK-09                              |
| `shared/infrastructure/db/`        | dépôt générique, unité de travail, contexte de tenance              | BACK-06a, BACK-06b                   |
| `shared/infrastructure/api/`       | handlers d'erreur, intergiciels, identifiant de requête             | BACK-09, BACK-11                     |
| `modules/identity/unit_of_work.py` | l'unité de travail du module                                        | BACK-06a                             |
| `modules/identity/…/api/routes.py` | inscription, connexion, réinitialisation de mot de passe            | BACK-28, BACK-29, BACK-31            |
| `modules/organization/`            | groupes, cliniques, appartenances, affectations                     | BACK-16                              |

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

**Le trajet complet des trois modèles.** Le dépôt en mémoire est défini _dans la sonde_ et non
dans `src/` : les doublures de production appartiennent à BACK-06c.

```bash
uv run python - <<'PY'
import asyncio
from uuid import UUID

from app.modules.identity.application.use_cases.create_account import CreateAccount
from app.modules.identity.domain.entities import Account
from app.modules.identity.domain.ports import AccountRepository
from app.modules.identity.infrastructure.api.schemas import AccountCreate, AccountRead

# Le depot du module reclame une session (BACK-05) : on emprunte ici sa seule
# fonction de mapping, et on branche un depot en memoire jetable.
from app.modules.identity.infrastructure.db.repositories import _to_model


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

    account = await CreateAccount(InMemoryAccountRepository()).execute(command)
    print("3. entite (domaine)       :", account)

    model = _to_model(account)
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
| Le routeur d'`identity` est monté mais ne porte aucune route           | Une route de création a besoin d'une session (BACK-05) et d'une unité de travail (BACK-06a). L'exposer aujourd'hui supposerait de brancher un dépôt factice dans le code de production. Les routes viennent en BACK-28 et BACK-29.                                                                                                               |
| `Base` déclarée ici, mais nue                                          | Le ticket la nomme dans sa portée, et le module pilote en a besoin pour déclarer sa table. La convention de nommage des contraintes, les mixins, le moteur et la session restent à BACK-05.                                                                                                                                                      |
| Le cas d'usage reçoit un dépôt et non une unité de travail             | L'unité de travail est livrée par BACK-06a. Le contrat qui compte est déjà tenu : ce qui entre dans un cas d'usage est un **port**, jamais une session.                                                                                                                                                                                          |
| `create_account` recouvre partiellement BACK-28                        | C'est le seul trajet d'**écriture** démontrable aujourd'hui, et le critère d'acceptation demande le sens schéma → entité → modèle. BACK-28 le reprendra en `register_individual`, avec mot de passe, OTP et non-divulgation.                                                                                                                     |
| `shared/domain/exceptions.py` réduit à `DomainError`                   | La hiérarchie intermédiaire et les codes namespacés sont la portée de BACK-09. Les exceptions d'`identity` héritent donc de la racine en attendant d'être reparentées.                                                                                                                                                                           |
| `shared/domain/ports/` ne contient qu'une docstring                    | `Cache`, `FileStorage` et `TokenService` appartiennent à BACK-14, BACK-13 et BACK-10a. Le paquet existe pour fixer leur place, pas pour les anticiper.                                                                                                                                                                                           |
| `identity/unit_of_work.py` réduit à une docstring                      | Le fichier est nommé par la portée du ticket, son contenu est celui de BACK-06a. Il fixe la place — à la racine du module, pas dans une couche.                                                                                                                                                                                                  |
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

| Sous-modèle        | Préfixe     | Ce qu'il porte                                    | Consommé par     |
| ------------------ | ----------- | ------------------------------------------------- | ---------------- |
| `AppSettings`      | _aucun_     | environnement, niveau de log, origines CORS       | BACK-08, BACK-11 |
| `DatabaseSettings` | `POSTGRES_` | connexion PostgreSQL                              | BACK-05          |
| `RedisSettings`    | `REDIS_`    | connexion Redis, bases de cache et de broker      | BACK-14, BACK-15 |
| `S3Settings`       | `S3_`       | stockage objet, MinIO en dev et Amazon S3 en prod | BACK-13          |
| `JWTSettings`      | `JWT_`      | clé de signature, algorithme, durées de vie       | BACK-10          |

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
refuse le schéma avant d'en arriver là ; BACK-07 l'appellera aussi depuis son `env.py`.

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
Aucune migration n'existe encore : c'est gratuit aujourd'hui et coûteux demain.

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
garde**. Les deux contre-exemples valent règle : une `Consultation` le porte, un `Animal` non —
l'animal est créé à l'inscription d'un particulier, avant qu'un groupe existe dans sa vie. Un
compte non plus : l'appartenance à un groupe est une relation N:M **datée**, portée par le
module `organization` (BACK-16), parce qu'un vétérinaire remplaçant intervient dans plusieurs
groupes avec un seul compte. Le filtre correspondant ne sera **jamais** appliqué globalement
dans le dépôt de base : c'est BACK-06b qui l'appliquera, aux seuls agrégats déclarant le mixin.

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
S'y ajoute une raison d'architecture : une clé étrangère partant de `shared/` vers une table
d'`organization` rendrait tous les modules structurellement dépendants de celui-là. La dette est
assumée et nommée : BACK-16 posera la contrainte table par table, quand `groups` existera.

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

Deux pièges à connaître avant BACK-06a : `rollback()` périme les instances **quoi qu'il
arrive** — journaliser `account.email` après l'annulation lève `MissingGreenlet` au lieu de
rendre une valeur périmée, donc capturer ce qu'on veut tracer avant. Et une session réutilisée
d'un bloc `async with` à l'autre ressert son identity map sans relire la base.

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
| Aucune dépendance `get_session()`                                  | Le ticket ne la demande pas, et BACK-06a interdit d'exposer la session à la couche application. Rien n'en a besoin d'ici là : le dépôt reçoit sa session en argument.                                                                                                                            |
| `autoflush=False` sur la fabrique                                  | Non demandé. Avec le défaut, une violation d'unicité remonte depuis une **lecture** — au mauvais endroit et sous le mauvais nom.                                                                                                                                                                 |
| `main.py` modifié, hors de la portée déclarée                      | Même arbitrage qu'en BACK-03 : la portée dit `shared/infrastructure/db/`, mais le critère d'acceptation parle du `lifespan` qui ferme le moteur.                                                                                                                                                 |
| `DatabaseUnavailableError` distincte de `ConfigurationError`       | Une base injoignable est une configuration **valide** et une panne d'exécution. Les confondre enverrait l'exploitant relire un fichier correct pendant que le serveur finit de démarrer.                                                                                                         |
| Le premier `[[tool.mypy.overrides]]` du projet                     | `asyncpg` ne livre pas de `py.typed`, et `engine.py` doit nommer ses exceptions : SQLAlchemy n'enveloppe pas les échecs survenus **dans** `asyncpg.connect()`. La dérogation est par module, comme BACK-02 l'avait prévu — il pariait seulement qu'elle n'arriverait jamais.                     |
| Aucun test automatisé, mais des sondes documentées                 | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02, BACK-03 et BACK-04.                                                                                                                                                                                |

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
| `alembic`             | Migrations de schéma (BACK-07).                                       |
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

— au lieu de réussir en le murmurant dans un log. Une plage, et non un `==`,
pour qu'une montée de patch côté Homebrew n'arrête pas le poste : ce qui doit
se voir, c'est le saut de mineur. C'est le même arbitrage que les contrats
d'[Import Linter](#import-linter) — une règle qu'aucun mécanisme ne tient
n'est pas une règle.

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
`required-version`. C'est délibéré : uv monte son numéro mineur pour ses
ruptures, et les deux doivent donc être rediscutées ensemble, une fois, plutôt
que de céder l'une après l'autre.

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
| Unité de travail et dépôt générique   | BACK-06a |
| Traduction des erreurs métier en HTTP | BACK-09  |
| Sonde de santé et métadonnées OpenAPI | BACK-08  |
| Migrations Alembic                    | BACK-07  |
| Suite de tests                        | BACK-12  |
| Pipeline CI complet du backend        | QA-01    |

La structure modulaire et hexagonale est posée (BACK-04) et ses règles sont
désormais tenues par [Import Linter](#import-linter) (BACK-04b), le socle de
persistance est en place (BACK-05), Ruff et Mypy sont configurés (BACK-02). Les
dépendances de test, elles, restent **déclarées sans être configurées** : c'est
volontaire, chaque ticket porte son propre outil.
