---
title: Tests
description: Lancer la suite pytest du service, lire ses marqueurs et ses skip, et écrire les trois formes de test du dépôt — domaine, cas d'usage sur doublure, conformité.
---

# Tests

`backend/api/tests/` porte la suite du service. Elle est aujourd'hui **le seul endroit du dépôt où
le comportement du backend est vérifié** : la CI ne la joue pas encore, et le
[hook de pre-commit](../getting-started/conventions-du-depot.md#hooks-de-pre-commit) ne lance ni
Mypy ni pytest. Ce qui n'est pas écrit ici n'est rattrapé par personne.

D'où la règle, et elle n'a pas d'exception : **un ticket qui livre du comportement livre ses tests
dans le même commit.** Une pull request qui ajoute un cas d'usage sans test est incomplète, et se
fait renvoyer en revue.

Cette page dit comment lancer la suite, comment lire ce qu'elle rend, et comment écrire les trois
formes de test que le service emploie.

:::note Un harnais intermédiaire, et il faut le savoir

Le harnais complet appartient à **BACK-12** : arborescence par couche, marqueurs de _niveau_,
migrations appliquées à la base de test, fabrique de jetons, fixture `client`, seuil de couverture.
Ce qui existe aujourd'hui a été **tiré en avant** par BACK-06b (isolation), BACK-06c (conformité)
et BACK-11 (observabilité), chaque emprunt étant consigné au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-06b). La dernière
section de cette page dit ce que BACK-12 changera ; le reste décrit ce qui tourne.

:::

## Lancer la suite

Deux `make test` existent, et ils ne couvrent pas la même chose :

| Commande                          | Ce qu'elle lance                                        |
| --------------------------------- | ------------------------------------------------------- |
| `make test` à la racine           | `make test-back` **puis** `make test-front`             |
| `make test-back` à la racine      | délègue à `backend/api/Makefile`                        |
| `make test` depuis `backend/api/` | `uv run pytest` — la suite Python, et rien d'autre      |
| `make test-front` à la racine     | `pnpm test`, qui exécute les trois programmes de preuve |

Autrement dit : **`make test` à la racine enchaîne la suite Python et les trois programmes de preuve
des workspaces pnpm** — la portée des clés de cache (FRONT-04), la traduction des erreurs (FRONT-10)
et les frontières entre features (FRONT-09). Aucun n'est une suite de tests au sens de QA-02 : ce sont des programmes Node hors
ligne, branchés sur le script `test` de leur package en attendant Vitest (FRONT-06). Les deux formes se valent ;
celle de `backend/api/` est celle qu'on garde sous la main, parce qu'elle accepte les arguments de
pytest.

### Ce qu'il faut avant de la lancer

Trois prérequis, tous posés par
[l'installation du poste](../getting-started/installation.md) et
[le démarrage de la pile](../getting-started/demarrage.md) :

- **`uv` et l'environnement du service**, par `uv sync` dans `backend/api/`.
- **`backend/api/.env`**, copié de son gabarit. Les tests construisent de **vrais** `Settings`,
  et quatre champs n'ont pas de valeur par défaut — `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `POSTGRES_DB` et `JWT_SECRET_KEY`. Sans ce fichier, la suite ne compose même pas sa
  configuration.
- **PostgreSQL démarré**, par `make dev` (ou `make up`) à la racine. La base de test s'appelle
  `app_test` ; elle naît au premier démarrage du volume `postgres` (INFRA-01). Redis, MinIO et
  Mailpit ne sont pas obligatoires — la section suivante dit ce qu'il en coûte.

La suite entière, depuis `backend/api/` :

```bash
uv run pytest
```

Attendu : la ligne de résumé de pytest, `… passed` — et, si Redis, MinIO ou Mailpit ne tournent
pas, autant de `skipped` qu'il y a de moitiés réelles injoignables.

**Sans PostgreSQL, la suite ne se saute pas : elle s'arrête.** La fixture `engine` du conftest
racine appelle `pytest.exit()`, pour que la preuve d'isolation ne puisse pas disparaître en
silence :

```bash
make down && uv run pytest ; make dev
```

Attendu : aucun test joué, et le message qui nomme le remède — `Connexion a la base de test
impossible : …`, suivi de `PostgreSQL docker doit tourner (make dev a la racine)` ; le `make dev`
final remet la pile debout. La décision est de BACK-06b, sa conséquence
[consignée par BACK-06c](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-06c) : l'arrêt
emporte aussi les moitiés **en mémoire**, qui n'ont pourtant besoin d'aucun conteneur.

Un fichier seul, en revanche, tourne sans rien démarrer du tout — dès lors qu'il ne demande pas la
base :

```bash
uv run pytest tests/modules/identity/test_verify_otp.py -v
```

Attendu : tous les tests du fichier au vert, sans Docker. C'est la promesse des
[doublures en mémoire](./doublures-en-memoire.md), et le sens de la
[fixture de tables non `autouse`](#ceux-des-modules) décrite plus bas.

## Les skip, et pourquoi une suite verte ne prouve rien

**C'est le piège de cette suite, et le seul qu'il faut connaître avant tout le reste.** Les
moitiés qui parlent à un vrai service se **sautent** quand ce service ne répond pas, avec le
message qui dit quoi lancer. Elles n'échouent pas — donc une suite verte n'est pas la preuve que
la conformité a tourné.

| Service manquant | Ce qui se passe                                            |
| ---------------- | ---------------------------------------------------------- |
| **PostgreSQL**   | La session **s'arrête** — `pytest.exit()`, rien n'est joué |
| **Redis**        | Les moitiés Redis du cache et du magasin d'OTP sont `skip` |
| **MinIO**        | La moitié S3 du stockage objet est `skip`                  |
| **Mailpit**      | Les tests de remise réelle de courriel sont `skip`         |

Le geste qui lève le doute est `-rs`, qui affiche la **raison** de chaque saut :

```bash
uv run pytest -m conformance -rs
```

Attendu : la liste des tests joués, puis un bloc `short test summary info` où chaque `SKIPPED`
porte son motif — `Redis n'est pas joignable : make up a la racine (INFRA-02).` ou
`MinIO n'est pas joignable : make up a la racine (INFRA-03).` **L'absence de ce bloc** est la
seule preuve que les deux moitiés ont réellement tourné.

**Avant d'ouvrir une pull request qui touche une doublure ou un adaptateur, lancer la suite avec
la pile complète démarrée**, et vérifier que ce bloc est vide.

## Les marqueurs

Dix marqueurs sont déclarés dans `[tool.pytest.ini_options]` de
`backend/api/pyproject.toml`. Ils nomment un **sujet**, jamais un niveau de test :

| Marqueur           | Ce qu'il rassemble                                              | Ticket   |
| ------------------ | --------------------------------------------------------------- | -------- |
| `tenant_isolation` | L'isolation multi-tenant, au dépôt et à la bordure HTTP         | BACK-06b |
| `pagination`       | La convention de pagination des listes                          | BACK-24  |
| `observability`    | La journalisation, le CORS et les deux intergiciels HTTP        | BACK-11  |
| `conformance`      | Les suites jouées contre le réel **et** contre la doublure      | BACK-06c |
| `tokens`           | L'émission et la vérification des jetons, et leur configuration | BACK-10a |
| `passwords`        | La politique de mot de passe, argon2id et le contrôle de fuite  | BACK-10b |
| `authorization`    | Les dépendances d'authentification et d'autorisation scopée     | BACK-10c |
| `otp`              | La vérification d'adresse par code, **côté services réels**     | BACK-17  |
| `notifications`    | Les préférences, la résolution des canaux et la remise          | BACK-22  |
| `scheduling`       | Le socle de la fiche technique du praticien                     | BACK-21  |

Pour lire la liste depuis le dépôt plutôt que depuis cette page :

```bash
uv run pytest --markers
```

Attendu : les dix marqueurs ci-dessus, chacun avec sa description et le ticket qui l'a introduit,
parmi les marqueurs internes de pytest.

La sélection se fait par `-m`, qui accepte les expressions booléennes :

```bash
uv run pytest -m "conformance and not tenant_isolation" --collect-only -q
```

Attendu : la liste des identifiants sélectionnés, une par ligne, close par le décompte des tests
collectés et des tests désélectionnés.

:::warning Un marqueur ne sélectionne pas tout son sujet

**Ils servent à jouer un sous-ensemble, jamais à prouver une couverture.** Trois faits qu'il vaut
mieux tenir de cette page que de découvrir sur un rapport :

- **`-m otp` ne joue pas tous les tests d'OTP.** Les tests de politique, de demande et de
  vérification — le cœur de BACK-17, sur doublure — ne portent aucun marqueur ; seuls le magasin
  Redis et la remise Mailpit en portent un. En pratique, `otp` désigne ce qui a besoin d'un
  service réel.
- **`organization` et `medical_records` n'ont aucun marqueur**, et les tests propres aux
  doublures non plus. Pour ces derniers c'est délibéré (BACK-06c) : `tests/shared/memory/` ne
  compare rien, et les faire entrer dans `-m conformance` annoncerait une comparaison qui n'a pas
  lieu.
- **`--strict-markers` n'est pas activé.** Un marqueur mal orthographié ne fait donc pas échouer
  la collecte : il produit un `PytestUnknownMarkWarning` que rien ne lit. Recopier le nom depuis
  le `pyproject.toml`, et l'y déclarer avant de l'employer.

:::

## L'organisation de `tests/`

**L'arbre des tests recopie celui de `src/app/`.** Un test vit à côté de ce qu'il éprouve ; sans
cela, la frontière de module n'existerait que dans `src/`.

```text
tests/
  conftest.py                 <- moteur, session, gardes autouse (voir plus bas)
  test_context_guards.py      <- les gardes du harnais, testees elles-memes
  core/
    logging_probes.py         <- sondes, PAS collecte (pas de prefixe test_)
    test_config_jwt.py  test_logging.py  ...
  shared/
    api_probes.py             <- application reelle + client ASGI, PAS collecte
    tenancy_stubs.py          <- la paire d'agregats stubs, PAS collectee
    conformance/              <- depot, cache, stockage : reel ET doublure
    memory/                   <- ce qui n'est vrai que de la doublure
    security/                 <- jetons et hachage
    test_pagination.py  test_error_handlers.py  ...
  modules/
    identity/
      conftest.py             <- cree la table du module dans app_test
      helpers.py              <- fabriques de donnees, PAS collectees
      conformance/            <- les finders maison du module
      test_request_otp.py  test_verify_otp.py  ...
    organization/  medical_records/  notifications/  scheduling/
```

Trois conventions se lisent sur cet arbre :

- **Un module sans préfixe `test_` n'est pas collecté par pytest.** C'est ce qui range les
  fabriques (`helpers.py`), les stubs (`tenancy_stubs.py`) et les sondes (`api_probes.py`,
  `logging_probes.py`) à côté des tests sans qu'ils en deviennent.
- **Une doublure, elle, ne vit jamais sous `tests/`.** Elle répond à un port, donc sa place est
  dans `src/` à côté des autres implémentations de ce port — le raisonnement complet est dans
  l'[ADR-0023](../adr/0023-doublures-en-memoire-et-conformite.md). Ce qui reste sous `tests/` est
  ce qui ne répond à personne.
- **`conformance/` est un sous-paquet, pas un suffixe de fichier.** Il sépare ce qui se compare de
  ce qui ne se compare pas, et rend `-m conformance` lisible à l'œil sur l'arbre.

### Comment se nomme un test

Les [conventions de langue du dépôt](../getting-started/conventions-du-depot.md#langue-du-code)
s'appliquent telles quelles : **identifiants en anglais, docstring en français**. Le nom d'un test
est une phrase qui énonce la règle, pas un numéro — `test_a_used_code_cannot_serve_twice`, jamais
`test_otp_2`. Sur un rapport d'échec, c'est cette phrase qu'on lit en premier.

Deux règles Ruff sont relâchées dans `tests/`, et deux seulement :

| Règle  | Dans `tests/`                                             |
| ------ | --------------------------------------------------------- |
| `S101` | Relâchée — `assert` est la façon normale d'écrire un test |
| `D1xx` | Relâchée — un test se nomme, il ne se documente pas       |
| `ANN`  | **Active** — `-> None` sur chaque fonction de test        |

Mypy, lui, ne regarde pas `tests/` : son périmètre est `src`, `alembic` et `scripts`. L'y faire
entrer est une décision de BACK-12.

## Les `conftest.py`

### Celui de la racine

`tests/conftest.py` porte deux choses : les fixtures de base de données, et quatre **garde-fous**
qui refusent qu'un test laisse un état de processus derrière lui.

| Fixture              | Portée  | Ce qu'elle donne                                              |
| -------------------- | ------- | ------------------------------------------------------------- |
| `engine`             | session | Le moteur vers `app_test`, en `NullPool`, tables stubs créées |
| `session`            | test    | Une session neuve, **annulée** puis fermée en sortie          |
| `group_a`, `group_b` | test    | Deux identifiants de groupe, pour éprouver le cloisonnement   |

L'URL de la base de test dérive de la configuration réelle en remplaçant le nom de la base par
`POSTGRES_TEST_DB` — défaut `app_test`, lu dans l'**environnement** et non dans les `Settings`.
Rien n'est à décommenter dans `backend/api/.env` pour lancer la suite. Et si cette base était la
base applicative, la session s'arrête avant d'avoir créé quoi que ce soit : les tests créent et
détruisent des tables, ils ne tournent jamais contre la base de travail.

L'isolation entre tests se fait **par rollback** : rien n'est commité, et le teardown de `session`
annule ce que le test a écrit. Ni savepoints, ni `TRUNCATE` — cette machinerie appartient à
BACK-12. La seule exception est la [suite de conformité](#écrire-une-suite-de-conformité), qui
commite pour de bon et purge ses deux tables stubs elle-même.

Les quatre gardes sont `autouse` : elles s'appliquent à **tous** les tests, sans être demandées.

| Garde                           | Ce qu'elle refuse                                                       |
| ------------------------------- | ----------------------------------------------------------------------- |
| `_ensure_clean_tenant_context`  | Un contexte de groupe qui fuirait d'un test au suivant                  |
| `_ensure_clean_request_context` | Une contextvar de requête laissée posée (identifiant, compte, clinique) |
| `_ensure_pristine_logging`      | Une configuration de journalisation laissée sur la racine `logging`     |
| `_forbid_outbound_http`         | Toute requête `httpx` vers un hôte **tiers**                            |

La dernière est celle qui surprend le plus, et elle mérite d'être connue avant d'écrire un test
d'adaptateur sortant : **un test ne joint jamais un service tiers.** Le garde-fou mord sur les
deux transports HTTPX qui ouvrent une socket, laisse passer la pile locale — `localhost`,
`127.0.0.1`, `::1`, `mailpit` — et ne touche pas à `httpx.ASGITransport`, qui sert le trafic
entrant des tests d'API. Un test qui sort quand même reçoit un `RuntimeError` qui nomme le
remède : passer `transport=httpx.MockTransport(...)` à l'adaptateur, ou employer sa doublure.

Les trois premières gardes ne voient que les tests **synchrones** : un test asynchrone tourne dans
une `asyncio.Task`, qui reçoit une **copie** du contexte. Le pendant asynchrone est un hook
`pytest_runtest_setup` qui enveloppe le test pour vérifier **dans** sa tâche — et
`test_context_guards.py` éprouve cette enveloppe, parce qu'une garde qui n'est pas testée n'est
pas une garde.

### Ceux des modules

Chaque module porte un `conftest.py` qui crée **ses** tables dans la base de test, puis les
détruit. Toujours avec une liste de tables nommées : jamais un `create_all` sans cible, qui
toucherait aux tables sous migrations.

Ces fixtures ne sont **pas `autouse`**, et c'est ce qui permet aux tests de domaine et de cas
d'usage de tourner sans Docker. Un test d'infrastructure, lui, demande la sienne en toutes
lettres :

```python
pytestmark = pytest.mark.usefixtures("_identity_tables")
```

Elles disparaîtront toutes le jour où BACK-12 appliquera les migrations à la base de test ;
l'emprunt est consigné au registre.

## Écrire un test de cas d'usage sur doublure

**C'est la forme la plus fréquente, et celle par laquelle commencer.** Le dépôt privilégie
explicitement les _fakes_ aux _mocks_ : on monte de vraies implémentations en mémoire, on exécute
le cas d'usage réel, et on interroge l'état **validé**. Aucun conteneur, aucun réseau, aucun
`unittest.mock`.

Le patron tient en quatre temps :

```python
async def test_the_right_code_verifies_the_address() -> None:
    """Chemin nominal : l'adresse bascule, et la bascule est VALIDEE."""
    # 1. Monter les doublures, semees avec l'etat de depart.
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()
    code = await _issued(store, uow, account.id)

    # 2. Construire le cas d'usage REEL, avec les doublures pour dependances.
    use_case = VerifyEmailOtp(uow=uow, otp_store=store)

    # 3. Executer.
    verified = await use_case.execute(VerifyEmailCommand(account_id=account.id, code=code))

    # 4. Asserter sur l'etat VALIDE, pas sur celui que le bloc tenait en main.
    assert verified.email_verified
    assert stored_account(uow, account.id).email_verified
    assert uow.commits == 1
```

Quatre points de ce patron valent d'être retenus :

**On assert sur l'état commité.** `stored_account(uow, account.id)` relit le magasin **hors de
tout bloc** — la forme générique est `uow.<magasin>_store.committed_entity(id)`. Lire l'entité que
le cas d'usage vient de rendre prouve seulement qu'un objet a changé en mémoire ; la relecture de
l'état validé est la seule qui prouve le **commit**. `uow.commits` compte les commits réussis, et
dit qu'il y en a eu un, pas trois.

**Le cas d'usage est le vrai.** On n'appelle jamais `store.issue()` à la main pour se donner un
code : on passe par `IssueEmailVerificationOtp`, c'est-à-dire par le parcours de production, seul
endroit où le code émis et l'empreinte rangée sont garantis d'être les mêmes.

**L'entité passe par son comportement.** `an_account(verified=True)` appelle `Account.create()`
puis `verify_email()`. Construire la dataclass avec `email_verified=True` contournerait
l'invariant, et un test qui contourne l'invariant n'éprouve plus le même objet que la production.

**Le temps s'injecte.** `FakeClock` fait expirer un code de dix minutes en zéro seconde de test.
Aucun `sleep` dans un test de cas d'usage : le seul du dépôt vit dans la conformité du cache, où
c'est Redis qui tient l'horloge.

Les fabriques communes — `an_account()`, `otp_rules()`, `a_client_ip()`, `stored_account()` —
vivent dans le `helpers.py` du module. Un besoin qui se répète y entre ; un besoin unique reste
dans son fichier de test.

**Où trouver la doublure d'un port** : la page
[Doublures en mémoire](./doublures-en-memoire.md#où-elles-vivent) porte le tableau complet, port
par port, avec la réponse de chacune à la panne — `unavailable=True` pour un cache qui dégrade,
`UnavailableOtpStore` pour un magasin qui échoue fermé. C'est ce qui rend testable la moitié du
contrat qu'on oublie de vérifier.

## Écrire une suite de conformité

Une doublure est fidèle le jour où elle est écrite. Ce qui la fait diverger, c'est le ticket
**suivant** : une règle ajoutée à l'adaptateur réel et oubliée dans la doublure, ou l'inverse.
Rien, dans du code, ne l'empêche — seule une suite **jouée deux fois** le peut.

La forme est toujours la même : **une classe de base qui porte les tests et ne fournit rien, deux
sous-classes qui ne fournissent que la fixture du sujet.**

```python
pytestmark = pytest.mark.conformance


class CacheConformance:
    """La suite commune. Les sous-classes ne fournissent que la fixture `cache`."""

    @pytest.fixture
    def cache(self) -> Cache:
        """Le sujet sous test -- fourni par la sous-classe."""
        raise NotImplementedError

    async def test_a_cached_none_is_distinct_from_an_absence(self, cache: Cache) -> None:
        ...


class TestRedisCacheConformance(CacheConformance):
    """La suite, jouee contre le Redis du poste."""

    @pytest_asyncio.fixture
    async def cache(self) -> AsyncIterator[Cache]:
        opened = build_cache(get_settings())
        if not await opened.ping():
            await opened.aclose()
            pytest.skip("Redis n'est pas joignable : `make up` a la racine (INFRA-02).")
        yield opened
        await opened.aclose()


class TestInMemoryCacheConformance(CacheConformance):
    """La MEME suite, jouee contre `InMemoryCache`."""

    @pytest.fixture
    def cache(self) -> Iterator[Cache]:
        yield build_in_memory_cache(get_settings())
```

Cinq règles gouvernent cette forme, et chacune répond à un accident possible :

- **La base ne s'appelle pas `Test…`**, donc pytest ne la collecte pas. C'est tout le mécanisme :
  un test ajouté à la base est **mécaniquement** joué des deux côtés, et on ne peut pas en ajouter
  un à une seule moitié sans le voir.
- **Une sous-classe ne fournit qu'une fixture.** Si elle redéfinit un test, elle admet une
  divergence sans la nommer — c'est exactement ce que la suite existe pour interdire.
- **La doublure se construit comme la production** : `build_in_memory_cache(get_settings())`, et
  non un constructeur nu. Les deux moitiés comparent ainsi la même convention de clés et le même
  TTL par défaut, pas deux configurations différentes.
- **La moitié réelle se saute quand son service ne répond pas**, avec le message qui dit quoi
  lancer. Elle n'échoue pas : un poste sans Redis doit pouvoir jouer le reste.
- **Le marqueur `conformance` est posé au niveau du module**, par `pytestmark`, et jamais sur les
  tests qui ne comparent rien.

Les suites existantes en donnent cinq exemples : dépôt et unité de travail, cache, stockage objet
dans `tests/shared/conformance/`, plus le dépôt de comptes et le magasin d'OTP dans
`tests/modules/identity/conformance/`. Ce qu'elles ont trouvé le jour de leur écriture — deux
divergences **du côté réel**, quatre autres en revue — est raconté sur la page
[Doublures en mémoire](./doublures-en-memoire.md#la-suite-de-conformité).

:::tip La règle à tenir

**Une doublure qui gagne un comportement gagne sa ligne de conformité dans le même commit.**

:::

## Ce que la CI ne fait pas encore

`.github/workflows/ci-backend.yml` ne rejoue **que les contrats d'architecture**
([Import Linter](./qualite-et-typage.md#import-linter)). Ni Ruff, ni Mypy, ni pytest : ils
entreront avec QA-01, qui déclarera aussi les services PostgreSQL et Redis du job et le seuil de
couverture.

Conséquence pratique, et elle n'est pas théorique : **une suite cassée arrive telle quelle sur
`main`** si personne ne l'a lancée. Avant d'ouvrir une pull request qui touche `backend/api/`,
l'enchaînement minimal est celui-ci, depuis `backend/api/` :

```bash
make check && make test
```

Attendu : Ruff, les contrats d'architecture, le formatage puis Mypy au vert — c'est l'ordre
qu'enchaîne `make check`, et [celui qu'aura la CI](./qualite-et-typage.md) — suivis du résumé de
pytest sans échec.

## Ce que BACK-12 changera

La page sera à relire ce jour-là. Ce qui est aujourd'hui provisoire, et connu comme tel :

| Aujourd'hui                                                                 | Avec BACK-12                                   |
| --------------------------------------------------------------------------- | ---------------------------------------------- |
| Chaque module crée ses tables dans un `conftest.py`                         | Les migrations sont appliquées à `app_test`    |
| Sans PostgreSQL, la session **s'arrête** — moitiés mémoire incluses         | L'arbitrage est repris                         |
| Des marqueurs de **sujet** seulement                                        | `unit`, `integration`, `slow` s'y ajoutent     |
| Aucun seuil de couverture, bien que `pytest-cov` soit installé              | Un seuil sur `domain/` et `application/`       |
| Les sondes HTTP ne sont partagées qu'à moitié — deux fichiers les recopient | Une fixture `client` et une fabrique de jetons |
| `tests/` hors du périmètre de Mypy                                          | Décision à prendre                             |
| Arborescence par module                                                     | Par module **puis par couche**                 |

Les écarts assumés avec le ticket DOC-02d sont consignés au
[registre des écarts](../ecarts/doc.md#écarts-assumés-avec-le-ticket-doc-02d).
