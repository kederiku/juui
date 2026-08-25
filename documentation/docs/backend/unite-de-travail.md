---
title: Unité de travail
description: Le port UnitOfWork, la règle d'une unité par module, le dépôt générique et l'injection par requête.
---

# Unité de travail

L'atomicité promise par le socle de persistance devient ici un contrat exécutable — le pattern
Unit of Work, livré par BACK-06a. Le port et sa promesse de rollback, la règle d'une unité par
module, le dépôt générique et l'injection d'une instance par requête.

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

## Le port, et sa promesse

`AbstractUnitOfWork` est le troisième port
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
[la section Persistance](./persistance.md#ce-que-la-session-promet-et-ce-quelle-coûte), rendue mécanique. La
fermeture est même définitive (`close_resets_only=False`) : un dépôt capturé dans un bloc et
rejoué après la sortie lève une erreur SQLAlchemy au lieu de rouvrir une connexion en douce.

## Une unité de travail par module

Il n'existe **pas** d'unité de travail globale, et c'est une décision d'architecture consignée
dans l'[ADR-0009](../adr/0009-unite-de-travail-par-module.md) : chaque
module dérive son port — `IdentityUnitOfWork` le
premier — qui n'expose que les dépôts de ce module. Ce qu'on ne peut pas placer dans une seule
transaction devient une frontière **visible** — `identity` et `organization` ne partagent pas
leur atomicité — plutôt qu'une dette invisible que le premier incident révélera.

Le port du module vit dans son **domaine**, et l'implémentation
`SqlAlchemyIdentityUnitOfWork` à la **racine** du
module — la place que BACK-04 avait fixée : le point d'assemblage, ni domaine ni tout à fait
infrastructure. La raison du dédoublement est mécanique autant qu'architecturale : le fichier
racine importe l'infrastructure, et un cas d'usage qui le nommerait créerait la chaîne
`application → infrastructure` que le contrat [`module-layers`](./qualite-et-typage.md#import-linter) refuse. Le cas
d'usage type donc sur le port, qui ne connaît que le domaine — et c'est ce qui permettra à
BACK-06c de substituer sa doublure sans toucher une signature.

Les dépôts du module sont des **propriétés paresseuses**, pas des attributs posés à l'entrée du
bloc : un attribut survivrait à la sortie, dépôt mort en main, tandis que la propriété repasse
par la garde de l'unité à chaque accès — servir un dépôt hors bloc est donc structurellement
impossible.

## Le dépôt générique

`SqlAlchemyRepository` porte ce qui se
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

Le vocabulaire du protocole `Repository` décrit la
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

## La variante tenant : deux coutures, une classe mère

Depuis BACK-06b, le dépôt générique expose deux points d'extension que toutes ses opérations
empruntent : `_select()`, point de départ de **toute** requête SELECT — `list` comme les finders
maison, `find_by_email` en tête —, et `_load()`, le chargement par identifiant que `get`, `save`
et `delete` partagent. Dans la classe de base, les deux sont neutres : elle reste **vierge de
tenance**.

`TenantSqlAlchemyRepository` les surcharge, et c'est tout ce qu'elle fait : le dépôt d'un agrégat
déclarant `TenantMixin` en hérite, et ses cinq opérations comme ses finders sont restreints au
groupe actif — une ligne d'un autre groupe répond par l'erreur d'**absence** du module,
indistincte d'un identifiant inexistant. L'insertion est estampillée par le socle, jamais par le
mapping du module, et une garde le vérifie. Le choix tenant ou non se lit donc en une ligne : la
classe mère du dépôt. Mécanique, alternatives écartées et échappatoire `use_all_groups` sont
consignées dans l'[ADR-0013](../adr/0013-filtre-de-tenance-dans-le-depot.md) ; la convention qui
en découle pour tout dépôt, tenant ou non : un finder part de `self._select()`, jamais d'un
`select(...)` importé.

## `get_identity_uow` : une instance par requête

La dépendance FastAPI vit à la racine du module, à côté de l'implémentation qu'elle assemble,
avec son alias `IdentityUowDep` sur le modèle de
`SettingsDep`. Elle livre une unité **fermée** — la session ne s'ouvrira qu'au `async with` du
cas d'usage — ce qui dispense de tout finaliseur `yield` : une requête abandonnée avant le bloc
n'a rien à nettoyer, une requête annulée en plein bloc voit `__aexit__` dérouler rollback et
fermeture au dépilement.

`get_identity_uow` et non `get_uow` : une unité par module, le nom porte la frontière —
`organization` publiera la sienne. Et le type de retour est le **port** : une route ne sait pas
quelle technologie la sert.

## Vérifier que l'unité de travail tient

Quatre sondes, dans le même esprit que celles du [socle](./persistance.md#vérifier-que-le-socle-tient). Depuis
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

Les écarts assumés avec le ticket BACK-06a sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-06a).
