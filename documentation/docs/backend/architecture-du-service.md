---
title: Architecture du service
description: Les trois espaces, les trois couches d'un module, la règle des 3 modèles et les commandes qui vérifient que ces règles tiennent.
---

# Architecture du service

Cette page décrit l'architecture **existante** du service — les espaces, les couches et les
modèles tels qu'ils sont posés dans le code aujourd'hui. Le guide normatif — règles à suivre,
carte de contexte — viendra avec DOC-02a dans la section [Architecture](../architecture/index.md).

Hexagonale — ports et adaptateurs — **à l'intérieur de modules métier**, et non un domaine plat :
c'est le **module** qui porte la frontière, la couche ne décrit que le sens des dépendances. Le
pourquoi de ce découpage, et les alternatives écartées, sont consignés dans
l'[ADR-0003](../adr/0003-monolithe-modulaire.md).

Les règles ci-dessous sont **mécaniques** depuis BACK-04b : les contrats
d'[Import Linter](./qualite-et-typage.md#import-linter) font échouer la CI sur toute violation.

## Les trois espaces

| Espace     | Ce qu'il porte                                                                           | Ce qu'il importe   |
| ---------- | ---------------------------------------------------------------------------------------- | ------------------ |
| `core/`    | réglages du **processus** : configuration (BACK-03), journalisation (BACK-11)            | rien du métier     |
| `shared/`  | noyau **partagé** : racine des erreurs, ports techniques, socles de persistance et d'API | `core/`            |
| `modules/` | les **contextes métier**, étanches les uns aux autres                                    | `core/`, `shared/` |

La relation entre les deux derniers est à sens unique : `modules/` → `shared/` est autorisé,
`shared/` → `modules/` ne l'est jamais — c'est le contrat `service-spaces`
d'[Import Linter](./qualite-et-typage.md#import-linter) qui le tient.

`core/` **reste en place** et n'a pas été fondu dans `shared/` : ce qu'il contient règle le
processus, pas l'architecture.

## Un module, trois couches

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

## La règle des 3 modèles

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

## Le trajet, sur le module pilote

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
l'[unité de travail](./unite-de-travail.md) du module qui entre dans son constructeur, et ses
dépôts n'existent que dans le bloc `async with` qui délimite la transaction.

Deux détails du trajet valent d'être signalés, parce qu'ils illustrent où se rangent les règles :

- la **normalisation** de l'adresse et du téléphone est une politique du domaine
  (`domain/policies.py`), appelée par la fabrique de l'entité. Elle n'est pas dans la route : un
  second point d'entrée l'oublierait, et deux comptes naîtraient pour une seule personne ;
- le choix des champs **exposés** se fait dans `AccountRead`, à la sortie. La minimisation des
  données (BACK-26) se décide là, pas dans l'entité, qui doit rester complète pour le métier.

## L'indépendance des modules

Un module n'importe **jamais** l'intérieur d'un autre : ni son entité, ni son dépôt, ni son
modèle de persistance, ni une jointure sur ses tables. Les échanges passent par les cas d'usage
publics du module cible — c'est-à-dire par la surface qu'il a choisi d'exposer, et qu'il peut
donc tenir dans le temps. Ce que cette étanchéité coûte, et l'entorse assumée de la `Base`
déclarative partagée, sont consignés dans les conséquences de
l'[ADR-0003](../adr/0003-monolithe-modulaire.md).

Depuis BACK-04b, la règle n'est plus seulement écrite : le contrat
[`module-independence`](./qualite-et-typage.md#import-linter) la fait respecter, dans les deux
sens et **même indirectement**.

**Le piège à éviter** : ne pas calquer les modules sur les trois frontends — ce sont des canaux
de livraison, pas des contextes métier. L'alternative est instruite et écartée dans
l'[ADR-0003](../adr/0003-monolithe-modulaire.md).

## Les modules prévus

Six modules, chacun répondant à une question. Leur tableau vit dans
l'[ADR-0003](../adr/0003-monolithe-modulaire.md) ; la docstring de
`src/app/modules/__init__.py` le porte aussi, au plus près du code.

## Ce que la structure attend encore

Les dossiers vides ne le sont pas par oubli : chacun porte une docstring qui dit ce qui vient s'y
ranger, et quel ticket l'apporte.

| Emplacement                        | Ce qui manque                                            | Ticket                    |
| ---------------------------------- | -------------------------------------------------------- | ------------------------- |
| `shared/domain/ports/`             | `TokenService`                                           | BACK-10a                  |
| `shared/infrastructure/api/`       | intergiciels, identifiant de requête                     | BACK-11                   |
| `modules/identity/…/api/routes.py` | inscription, connexion, réinitialisation de mot de passe | BACK-28, BACK-29, BACK-31 |
| `modules/organization/`            | cas d'usage, invitations, routes d'administration        | BACK-25                   |

## Vérifier que les règles tiennent

Même esprit que la sonde de [Mypy](./qualite-et-typage.md#mypy) et celles de la
[configuration](./configuration.md#vérifier-que-le-filet-tient). Depuis `backend/api/`.

**Les règles d'architecture** (BACK-04b). Attendu : `Contracts: 5 kept, 0 broken.`

```bash
make imports
```

Ce n'est plus une sonde qu'il faut penser à lancer : `make lint` l'enchaîne après
Ruff, et la CI backend (`.github/workflows/ci-backend.yml`) la rejoue sur
chaque pull request. Les cinq contrats et la preuve qu'ils mordent : [Import
Linter](./qualite-et-typage.md#import-linter).

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

Les écarts assumés avec le ticket BACK-04 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-04).
