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

Ajouter `--frozen` pour interdire toute re-résolution : l'installation échoue
alors si [`uv.lock`](uv.lock) ne correspond plus au `pyproject.toml`, au lieu de
mettre le verrou à jour en silence. C'est le mode qu'utiliseront la CI (QA-01) et
le build Docker (INFRA-04).

## Démarrage

Un fichier `.env` est nécessaire depuis BACK-03 : l'API valide sa configuration au
démarrage et refuse de partir sans elle. Les valeurs livrées conviennent telles quelles
sur un poste vierge.

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
    │       ├── db/base.py      `Base` déclarative des modèles de persistance
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
- **`lifespan`** est le point d'accroche des ressources de longue durée : pool
  PostgreSQL (BACK-05), client Redis (BACK-14), broker TaskIQ (BACK-15). Il pose
  la règle que toutes devront suivre : rien ne s'ouvre à l'import du module, tout
  passe par lui. Son seul occupant à ce jour est la validation de la
  configuration (BACK-03), qui précède par construction toute ouverture de
  ressource.

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
| `shared/infrastructure/db/`        | moteur, session, mixins, convention de nommage des contraintes      | BACK-05                              |
| `shared/infrastructure/db/`        | dépôt générique, unité de travail, contexte de tenance              | BACK-06a, BACK-06b                   |
| `shared/infrastructure/api/`       | handlers d'erreur, intergiciels, identifiant de requête             | BACK-09, BACK-11                     |
| `modules/identity/unit_of_work.py` | l'unité de travail du module                                        | BACK-06a                             |
| `modules/identity/…/api/routes.py` | inscription, connexion, réinitialisation de mot de passe            | BACK-28, BACK-29, BACK-31            |
| `modules/organization/`            | groupes, cliniques, appartenances, affectations                     | BACK-16                              |

### Vérifier que les règles tiennent

Même esprit que la sonde de [Mypy](#mypy) et celles de la
[configuration](#vérifier-que-le-filet-tient). Depuis `backend/api/`.

**La pureté du domaine.** Attendu : aucune sortie.

```bash
grep -rnE "^(from|import) (fastapi|sqlalchemy|pydantic|redis|boto3)" src/app/modules/*/domain src/app/shared/domain
```

**L'indépendance des modules.** Attendu : aucune sortie.

```bash
grep -rn "app\.modules\." src/app/modules/identity | grep -v "app\.modules\.identity"
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

| Écart                                                              | Raison                                                                                                                                                                                                                             |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Le routeur d'`identity` est monté mais ne porte aucune route       | Une route de création a besoin d'une session (BACK-05) et d'une unité de travail (BACK-06a). L'exposer aujourd'hui supposerait de brancher un dépôt factice dans le code de production. Les routes viennent en BACK-28 et BACK-29. |
| `Base` déclarée ici, mais nue                                      | Le ticket la nomme dans sa portée, et le module pilote en a besoin pour déclarer sa table. La convention de nommage des contraintes, les mixins, le moteur et la session restent à BACK-05.                                        |
| Le cas d'usage reçoit un dépôt et non une unité de travail         | L'unité de travail est livrée par BACK-06a. Le contrat qui compte est déjà tenu : ce qui entre dans un cas d'usage est un **port**, jamais une session.                                                                            |
| `create_account` recouvre partiellement BACK-28                    | C'est le seul trajet d'**écriture** démontrable aujourd'hui, et le critère d'acceptation demande le sens schéma → entité → modèle. BACK-28 le reprendra en `register_individual`, avec mot de passe, OTP et non-divulgation.       |
| `shared/domain/exceptions.py` réduit à `DomainError`               | La hiérarchie intermédiaire et les codes namespacés sont la portée de BACK-09. Les exceptions d'`identity` héritent donc de la racine en attendant d'être reparentées.                                                             |
| `shared/domain/ports/` ne contient qu'une docstring                | `Cache`, `FileStorage` et `TokenService` appartiennent à BACK-14, BACK-13 et BACK-10a. Le paquet existe pour fixer leur place, pas pour les anticiper.                                                                             |
| `identity/unit_of_work.py` réduit à une docstring                  | Le fichier est nommé par la portée du ticket, son contenu est celui de BACK-06a. Il fixe la place — à la racine du module, pas dans une couche.                                                                                    |
| `domain/entities.py` plat, et non un dossier `domain/entities/`    | Le guide de référence montre un dossier ; c'est le ticket lui-même qui l'écarte, et pour une bonne raison — un dossier d'entités partagé est exactement le domaine plat qu'il s'agit d'éviter.                                     |
| `str` et non `EmailStr` pour l'adresse                             | `EmailStr` dépend d'`email-validator`, qui n'est pas une dépendance déclarée du projet. La validation de forme relève de BACK-28, l'unicité insensible à la casse d'INFRA-09.                                                      |
| Type et statut stockés en `String` et non en enum natif            | Ajouter une valeur à un enum PostgreSQL exige une migration, et le mapping explicite vers `AccountType` devient visible plutôt que magique — ce que la règle des 3 modèles demande précisément de montrer.                         |
| Le contrôle automatique de la checklist historique n'est pas livré | Il est **extrait dans BACK-04b** (contrats import-linter, câblés en CI par QA-01). Les quatre sondes ci-dessus en tiennent lieu en attendant.                                                                                      |
| Aucun test automatisé, mais des sondes documentées                 | `tests/` et la configuration de pytest appartiennent à BACK-12. Même arbitrage qu'en BACK-02 et BACK-03.                                                                                                                           |

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
| `pytest`          | Cadre de test.                                        |
| `pytest-asyncio`  | Support des tests asynchrones.                        |
| `pytest-cov`      | Mesure de couverture.                                 |
| `httpx`           | Client HTTP de test, via `ASGITransport`.             |
| `boto3-stubs[s3]` | Stubs de typage de boto3, limités au service S3.      |

`boto3` est le seul paquet de la liste à ne pas embarquer ses propres
annotations : tous les autres livrent un `py.typed`, et leurs paquets `types-*`
d'antan ont été retirés de PyPI.

**Ruff est épinglé à la version exacte**, contrairement à tout le reste. Un
linter qui change d'avis tout seul entre deux `uv sync` ferait échouer la CI sans
qu'une ligne de code ait bougé : sa montée de version doit rester un commit
délibéré.

## Qualité et typage

Ruff et Mypy sont configurés dans [`pyproject.toml`](pyproject.toml), chaque
réglage accompagné de sa justification. Trois vérifications, toutes lançables
depuis ce dossier :

| Commande                       | Raccourci           | Rôle                      |
| ------------------------------ | ------------------- | ------------------------- |
| `uv run ruff check .`          | `make lint`         | Lint                      |
| `uv run ruff format --check .` | `make format-check` | Formatage (lecture seule) |
| `uv run mypy src`              | `make typecheck`    | Typage strict             |

`make check` enchaîne les trois **dans l'ordre qu'aura la CI** (QA-01) : un échec
local reproduit donc un échec de CI. `make` seul liste toutes les cibles.

Deux cibles réécrivent le code : `make format` (`ruff format .`) et `make lint-fix`
(`ruff check --fix .`, corrections sûres uniquement).

Ces deux-là s'appliquent aussi **toutes seules au moment du commit** : le hook de
pre-commit du monorepo (SETUP-04) passe chaque fichier `.py` indexé par
`ruff check --fix` puis `ruff format`, et interrompt le commit sur ce qui reste.
Voir [Hooks de pre-commit](../../README.md#hooks-de-pre-commit). Le typage, lui,
n'entre pas dans le hook — il reste à lancer à la main, et la CI le vérifiera.

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

| Écart                                               | Raison                                                                                                                           |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `target-version = "py314"` et non `py312`           | Le projet est verrouillé sur Python 3.14. Cibler py312 ferait réécrire par Ruff du code déjà moderne.                            |
| ANN101/ANN102 ne sont pas ignorées                  | Ruff les a **retirées**. Les nommer dans `ignore` ne produirait qu'un avertissement à chaque exécution et dans chaque log de CI. |
| `S` et `D` ajoutés au jeu de règles                 | Sans eux, l'assouplissement demandé pour `tests/` (« assert autorisé, docstrings non requises ») n'aurait relâché rien du tout.  |
| Les trois drapeaux Mypy nommés ne sont pas réécrits | `strict = true` les active déjà tous les trois.                                                                                  |
| Aucun `[[tool.mypy.overrides]]` vivant              | Aucune dépendance n'en a besoin ; le motif est documenté en commentaire.                                                         |

## Ce qui n'est pas encore là

| Sujet                                   | Ticket   |
| --------------------------------------- | -------- |
| Moteur SQLAlchemy et session asynchrone | BACK-05  |
| Unité de travail et dépôt générique     | BACK-06a |
| Traduction des erreurs métier en HTTP   | BACK-09  |
| Sonde de santé et métadonnées OpenAPI   | BACK-08  |
| Suite de tests                          | BACK-12  |
| Contrats import-linter                  | BACK-04b |
| `Dockerfile` et `.dockerignore`         | INFRA-04 |
| Intégration continue                    | QA-01    |

La structure modulaire et hexagonale est posée (BACK-04), Ruff et Mypy sont
configurés (BACK-02). Les dépendances de test, elles, restent **déclarées sans
être configurées** : c'est volontaire, chaque ticket porte son propre outil.
