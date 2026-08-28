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

## Lancer la suite

Deux `make test` existent, et ils ne couvrent pas la même chose :

| Commande                          | Ce qu'elle lance                                        |
| --------------------------------- | ------------------------------------------------------- |
| `make test` à la racine           | `make test-back` **puis** `make test-front`             |
| `make test-back` à la racine      | délègue à `backend/api/Makefile`                        |
| `make test` depuis `backend/api/` | `uv run pytest` — la suite Python, et rien d'autre      |
| `make test-front` à la racine     | `pnpm test`, qui exécute les trois programmes de preuve |

Depuis `backend/api/`, quatre cibles découpent la suite. **L'axe qui les sépare est le service,
pas la couche** — c'est ce qui rend la première utilisable sans rien démarrer :

| Cible              | Ce qu'elle joue                                                                                     | Docker ?   |
| ------------------ | --------------------------------------------------------------------------------------------------- | ---------- |
| `test`             | Tout                                                                                                | Pile       |
| `test-unit`        | `-m unit` — rien qui touche un service                                                              | **Aucun**  |
| `test-integration` | `-m integration`, `--require-services`                                                              | Pile       |
| `test-tenancy`     | `-m tenant_isolation`, `--require-services` — la [catégorie obligatoire](#la-catégorie-obligatoire) | PostgreSQL |
| `test-cov`         | Tout, plus la couverture et son seuil bloquant                                                      | Pile       |

À la racine, `make test-back-unit` et `make test-back-cov` délèguent aux deux qui servent le plus
souvent. Les autres se lancent depuis `backend/api/`, qui est aussi la voie pour passer des
arguments à pytest (`-k`, `-m`, un chemin).

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
- **La pile docker**, par `make dev` (ou `make up`) à la racine — pour la suite **complète**
  seulement. La base de test s'appelle `app_test` ; elle naît au premier démarrage du volume
  `postgres` (INFRA-01), et la suite y applique elle-même les migrations. Redis, MinIO et Mailpit
  ne sont pas obligatoires — la section suivante dit ce qu'il en coûte.

La suite entière, depuis `backend/api/` :

```bash
uv run pytest
```

Attendu : la ligne de résumé de pytest, `… passed` — et, si un service ne répond pas, autant de
`skipped` que de moitiés réelles injoignables, précédés du bloc `services absents` qui les
recense.

**Sans aucun service, la moitié unitaire tourne quand même**, et c'est le sens de la cible dédiée :

```bash
make test-unit
```

Attendu : le domaine, les cas d'usage sur doublures et les moitiés en mémoire des suites de
conformité, tous au vert, en quelques secondes, sans qu'un conteneur soit démarré. Aucun de ces
tests ne demande la fixture `engine`, donc aucun ne cherche à joindre PostgreSQL.

C'était l'arbitrage que BACK-06c avait laissé ouvert : la fixture `engine` appelait alors
`pytest.exit()`, et l'arrêt emportait aussi les moitiés **en mémoire**, qui n'ont pourtant besoin
d'aucun conteneur. Il n'en reste qu'un `pytest.exit`, et il est ailleurs — voir
[la garde sur la base de test](#la-base-dintégration).

## Les skip, et comment savoir ce qu'une exécution a vraiment prouvé

Les moitiés qui parlent à un vrai service se **sautent** quand ce service ne répond pas. Elles
n'échouent pas : une exécution verte sur un poste sans Redis ressemblerait donc, trait pour trait,
à une exécution verte sur un poste complet.

**Deux pièces referment ce piège**, et la seconde est celle qui prouve :

| Pièce                      | Ce qu'elle fait                                                                                 |
| -------------------------- | ----------------------------------------------------------------------------------------------- |
| Le bloc `services absents` | Nomme les services qui ont manqué, en dernier avant le décompte final                           |
| `--require-services`       | Transforme chaque saut en **échec** — posé sur `test-integration`, `test-tenancy` et `test-cov` |

Il y en avait trois : `-rs` était dans les `addopts`. Il en a été retiré, et le mesurer explique
pourquoi — **tous** les sauts de cette suite viennent du même helper, donc `-rs` répétait le même
motif 146 fois quand PostgreSQL manquait, et pytest écrit ce bloc **après** tous les
`pytest_terminal_summary`, `trylast` compris. Le recensement, qui dit la même chose en trois lignes,
se retrouvait poussé hors de l'écran par ce qu'il existe pour remplacer. `-rs` reste disponible à la
demande.

| Service manquant | Ce qui se passe                                          |
| ---------------- | -------------------------------------------------------- |
| **PostgreSQL**   | Les tests d'intégration sautent ; les unitaires tournent |
| **Redis**        | Les moitiés Redis du cache et du magasin d'OTP sautent   |
| **MinIO**        | La moitié S3 du stockage objet saute                     |
| **Mailpit**      | Les tests de remise réelle de courriel sautent           |

Le geste qui lève tout doute, avant d'ouvrir une pull request qui touche une doublure ou un
adaptateur :

```bash
uv run pytest -m conformance --require-services
```

Attendu : `… passed`, **et pas un seul `skipped`**. C'est la seule preuve que les deux moitiés de
chaque suite ont réellement tourné. Sur un poste incomplet, le même geste produit des ERREURS de
mise en place nommant le service manquant — jamais un vert trompeur. C'est le drapeau que QA-01
posera en CI.

## Les marqueurs

Treize marqueurs sont déclarés dans `[tool.pytest.ini_options]` de
`backend/api/pyproject.toml`, sur **deux axes qui ne répondent pas à la même question**.

### Le niveau : ce qu'un test coûte

`unit`, `integration` et `slow` répondent à « puis-je le lancer sans Docker, et va-t-il me rendre
la main ? ».

**Personne ne les pose à la main.** Le hook `pytest_collection_modifyitems` du conftest racine lit
la **clôture de fixtures** de chaque test — celle que pytest calcule à la collecte, et qui est
transitive — et pose `integration` dès qu'elle atteint une fixture de service, `unit` sinon. Un
test qui demande `session` tire `engine` et se classe sans rien déclarer ; un test qui cesse
d'avoir besoin d'une base se reclasse tout seul.

Déduire le niveau du **chemin** aurait été plus simple et faux dès le premier jour :
`notifications/infrastructure/test_channel_adapters.py` est en couche infrastructure et ne touche
aucun service. Ce qu'un test _réclame_ est la seule chose qui ne puisse pas mentir.

Quatre endroits portent le marqueur à la main, et un seul motif les explique : la moitié réelle et
la doublure y demandent une fixture du **même nom** (`cache`, `storage`, `store`), qu'aucune
règle ne peut départager. Il est alors posé **sur la classe, jamais sur le module** — un
`pytestmark` de module marquerait aussi la moitié en mémoire, que `-m "not integration"` cesserait
de jouer.

`slow` est un **qualificatif**, pas un troisième niveau : un test peut être `unit` et `slow`.
Traités comme exclusifs, les tests unitaires lents sortiraient de `-m unit` sans que rien ne le
dise. `make test-unit` joue donc `-m unit` tout court : la forme `-m "unit and not slow"` a été
essayée et retirée, parce qu'elle laissait le seul test des deux catégories hors des **deux**
cibles de niveau — exactement l'accident que ce marqueur existe pour éviter.

### Le sujet : quel comportement un test garde

Les dix autres répondent à « qu'est-ce que BACK-17 a livré ? ». Ils se posent à la main, par le
ticket qui livre le comportement, et se **cumulent** avec le niveau — `-m "otp and not
integration"` est une sélection légitime.

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

Attendu : les treize marqueurs, chacun avec sa description et le ticket qui l'a introduit, parmi
les marqueurs internes de pytest.

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
- **En revanche, `--strict-markers` est actif.** Un marqueur mal orthographié fait désormais
  échouer la **collecte**, au lieu de produire un `PytestUnknownMarkWarning` que rien ne lisait.
  C'est ce qui fait de la catégorie obligatoire autre chose qu'un vœu : une faute de frappe sur
  `tenant_isolation` casse bruyamment, elle ne vide plus la sélection en silence.

:::

## L'organisation de `tests/`

**L'arbre des tests recopie celui de `src/app/`, module d'abord puis couche.** Un test vit à côté
de ce qu'il éprouve ; sans cela, la frontière de module n'existerait que dans `src/`.

```text
tests/
  conftest.py                 <- niveaux, base d'integration, gardes autouse
  test_context_guards.py      <- les gardes du harnais, testees elles-memes
  test_harness.py             <- le harnais lui-meme : client, jetons, transaction
  support/                    <- ce qui AIDE a tester, et n'est pas un test
    api.py                    <- asgi_client, l'application reelle
    auth.py                   <- doublures d'authentification, routes de sonde
    tokens.py                 <- TokenFactory, cles, audiences, identifiants figes
    tenancy_stubs.py          <- la paire d'agregats stubs
    logs.py                   <- sondes de journalisation
  core/                       <- app.core n'a pas de couches, ses tests non plus
  shared/                     <- miroir de src/app/shared/
    conformance/              <- depot, cache, stockage : reel ET doublure
    db/                       <- schema, isolation transactionnelle, tenance
    memory/  security/
  modules/
    identity/
      helpers.py              <- fabriques du module, a la RACINE : les trois
                                 couches les consomment
      domain/  application/  infrastructure/
      conformance/            <- un contrat joue sur deux implementations
    organization/  medical_records/  scheduling/
      domain/  infrastructure/          <- pas d'application/ : il n'y en a pas
    notifications/                         dans src/ non plus
      domain/  application/  infrastructure/
```

Quatre conventions se lisent sur cet arbre :

- **On ne crée que les couches qui existent dans `src/`.** `organization`, `medical_records` et
  `scheduling` n'ont pas de couche `application/`, et le
  [contrat n° 2 d'Import Linter](./qualite-et-typage.md#import-linter) met déjà `(application)`
  entre parenthèses pour cette raison. Un répertoire de tests naît le jour où la couche naît.
- **`tests/support/` n'est pas `tests/shared/`.** Le second miroite `src/app/shared/` : ce qu'on y
  trouve **teste** le noyau partagé. Le premier ne teste rien — il sert à tester autre chose.
  Aucun de ses modules ne porte de préfixe `test_`, donc pytest ne les collecte pas.
- **Une doublure ne vit jamais sous `tests/`.** Elle répond à un port, donc sa place est dans
  `src/` à côté des autres implémentations de ce port —
  [ADR-0023](../adr/0023-doublures-en-memoire-et-conformite.md). Ce qui reste sous `tests/` est ce
  qui ne répond à personne.
- **`conformance/` est un sous-paquet, pas une couche.** Un contrat joué sur deux implémentations
  n'en est pas une : il reste frère des trois, et `-m conformance` reste lisible à l'œil sur
  l'arbre.

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

Mypy, lui, ne regarde pas `tests/` : son périmètre est `src`, `alembic` et `scripts`. **BACK-12 a
rendu cet arbitrage, et il le laisse dehors** : la mesure en donne des dizaines d'erreurs, dont la
majorité n'est pas corrigeable proprement — le splat de mots-clés Pydantic, un `str` que Pydantic
convertit en `SecretStr`, et surtout des tests **dont le sujet EST le mauvais type**, qu'on ne peut
faire taire qu'en annotant le mensonge qu'ils dénoncent. `ANN` reste actif, ce qui capte l'essentiel
du bénéfice à coût nul : toute signature de test est annotée. La mesure est reproductible par
`uv run mypy --cache-dir=/dev/null tests`, et l'écart est
[consigné](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-12).

## Le `conftest.py`

**Il n'en reste qu'un, et c'est un résultat du ticket.** Il y en avait sept : un par module pour
créer ses tables, plus un ré-export en tire-bouchon. `tests/conftest.py` porte désormais quatre
choses — la déduction du niveau, la base d'intégration, le harnais HTTP, et les garde-fous.

#### La base d'intégration

| Fixture               | Portée  | Ce qu'elle donne                                                       |
| --------------------- | ------- | ---------------------------------------------------------------------- |
| `engine`              | session | Le moteur vers la base de test, `NullPool`, **schéma migré**           |
| `connection`          | test    | Une connexion sous transaction **externe**, annulée en sortie          |
| `bound_sessionmaker`  | test    | Une fabrique de sessions inscrite dans cette transaction               |
| `session`             | test    | Une session issue de cette fabrique                                    |
| `database`            | test    | Le `Database` que le `lifespan` poserait, fabrique liée                |
| `engine_sessionmaker` | test    | Une fabrique **non liée**, pour les deux cas que le patron ne sert pas |
| `group_a`, `group_b`  | test    | Deux identifiants de groupe, pour éprouver le cloisonnement            |

**Le schéma vient des migrations.** `engine` prend le verrou consultatif d'`alembic/env.py` — la
même clé, ce qui sérialise la suite avec un `make migrate` concurrent —, commite, puis applique
`alembic upgrade head`. Les cinq `conftest.py` de module qui créaient leurs tables à la main ont
disparu avec elle, ainsi que le ré-export en tire-bouchon de `shared/security/`.

`upgrade head` est **idempotent** : la base survit d'une exécution à l'autre, et le plan est alors
vide. `--db-reset` défait tout d'abord (`alembic downgrade base`), pour le jour où un changement de
branche a fait diverger le schéma. Il n'y a **jamais** de `DROP SCHEMA public CASCADE` : il
emporterait `pg_trgm` et `unaccent`, posées une seule fois à la création du volume par un script
d'initialisation qui ne rejoue pas.

Le nom de la base vient du champ `POSTGRES_TEST_DB` de `DatabaseSettings`, et un validateur
**refuse qu'il vaille la base applicative**. Le refus tombe à la configuration, avant toute
collecte : la suite sait désormais appliquer et défaire des migrations, ce qui n'est pas une chose
à pointer par erreur sur une base de travail.

#### L'isolation : une transaction par test

`connection` ouvre une transaction **externe** ; `bound_sessionmaker` y inscrit les sessions en
`join_transaction_mode="create_savepoint"`. Un `commit()` applicatif **relâche alors un savepoint**
— visible de la suite du test, invisible de toute autre connexion — et le rollback de `connection`
emporte l'ensemble, y compris après un test interrompu.

**Il n'y a donc plus aucune purge manuelle**, et c'est ce que le patron achète. Ce qu'il coûte est
écrit noir sur blanc : `commit()` ne franchit plus la frontière de la connexion. La propriété
« une écriture validée survit à la connexion qui l'a faite » est prouvée par un test qui sort
exprès du patron, et les tests de concurrence prennent `engine_sessionmaker` — deux sessions
entrelacées sur une même connexion cassent le relâchement des savepoints, qui se fait en pile.

Ce que le patron achète surtout : **une route atteinte par le client HTTP voit le semis non
commité du test**. Avant, les résolveurs d'authentification devaient être câblés à la main sur la
session du test, parce qu'« une autre connexion ne verrait rien du semis ». Le contournement a
disparu, et le point de composition testé est redevenu celui qui tourne.

#### Le client HTTP et la fabrique de jetons

| Fixture          | Ce qu'elle donne                                                               |
| ---------------- | ------------------------------------------------------------------------------ |
| `tokens`         | La `TokenFactory` du test — celui qui signe **est** celui qui vérifie          |
| `probe_client`   | Un client sur l'application de sonde : les dépendances transverses, sans base  |
| `application`    | L'application **réelle**, `app.state` monté, prête à recevoir des surcharges   |
| `api_client`     | Un client sur cette application                                                |
| `authentication` | Le montage réel, dont seul le service de jetons vient du harnais               |
| `mounted_cache`  | Un cache en mémoire sur l'application, **à la demande** — pour `/health/ready` |

**L'application et le client sont deux fixtures, et c'est ce qui rend les surcharges possibles.**
Une fixture qui ne rendrait que l'`AsyncClient` n'exposerait aucun objet portant
`dependency_overrides` : ni les réglages, ni le compte courant ne seraient surchargeables. Les deux
coûtent trois lignes et se demandent ensemble quand il le faut.

`api_client` monte `app.state` **à la main** et n'exécute pas le `lifespan` : celui-ci appelle
`get_settings()` en direct, reconfigure la journalisation — ce que la garde `_ensure_pristine_logging`
refuse —, ouvre Redis, S3, le magasin d'OTP et le broker, et construit un moteur poolé là où tout
le harnais tient par `NullPool`. Poser le bon `Database` suffit : `get_identity_uow` et
`get_organization_uow` en dérivent, donc les routes ouvrent leurs sessions dans la transaction du
test **sans une seule surcharge de dépendance**.

La fabrique est paramétrable par audience, groupe actif et rôle — alors que `create_access_token`
n'a **pas** de paramètre `group_role`, parce qu'une appartenance est une relation datée et non une
revendication de l'appelant. `group_role=` inscrit donc l'appartenance dans la table du résolveur
puis émet : le même trajet qu'en production, un dictionnaire à la place du dépôt. Les cas de refus
se fabriquent en **dégradant l'émission**, jamais en forgeant une charge utile :

```python
await tokens.bearer()                                    # le cas nominal
await tokens.bearer(group_role="admin")                  # un autre role de groupe
await tokens.bearer(audience=AUDIENCE_INDIVIDUAL)        # un jeton d'une autre application
await tokens.bearer(expired=True)                        # emis dans le passe, donc perime
await tokens.token(group_role=None)                      # leve : appartenance inactive
```

Le dernier mérite d'être connu : le refus tombe **à l'émission**, pas au décodage. Un test qui
chercherait un 401 se tromperait d'endroit — le jeton n'existe jamais.

#### Les garde-fous

Quatre gardes sont `autouse` : elles s'appliquent à **tous** les tests, sans être demandées.

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

## La catégorie obligatoire

**Tout module portant un agrégat tenant doit avoir des tests marqués `tenant_isolation`.** Ce n'est
pas une catégorie de confort : c'est la seule preuve que l'isolation entre groupes tient.

```bash
make test-tenancy
```

Deux modules sont concernés aujourd'hui — `organization` (cliniques, affectations) et `scheduling`
(fiches praticien) — et c'est mécanique, pas déclaratif :
`tests/shared/db/test_tenant_coverage.py` parcourt `app.modules`, importe le `models.py` de chacun,
et compare la liste de ceux qui portent `TenantMixin` à celle qui est déclarée. Un agrégat qui gagne
le mixin fait échouer tant que personne ne l'a inscrit — et l'inscrire est le moment où la question
« où sont ses tests d'isolation ? » se pose.

Il vérifie les **deux sens** : une déclaration qui ne désigne plus aucun agrégat tenant doit
disparaître, parce qu'un marqueur qui ne désigne rien est un marqueur qu'on cessera de croire.

Ce qu'il ne peut pas faire, et il faut le savoir : vérifier qu'un test marqué **existe**. La
collecte pytest ne voit que la sélection courante, et une telle garde passerait au vert sous le
premier `pytest -k`. Elle rendrait donc exactement le service qu'on n'attend pas d'elle.

## La couverture

```bash
make test-cov
```

Attendu : deux rapports. Le premier couvre le **service entier** et ne juge rien — il est là pour
être lu. Le second garde `domain/` et `application/`, et **échoue** sous le seuil.

Le seuil ne porte que sur ces deux couches, et c'est délibéré : ce sont celles dont le
_comportement_ est le sujet des tests. L'infrastructure est couverte par les tests d'intégration,
dont le taux dépend des services joignables sur le poste — un seuil qui bougerait selon que Redis
tourne ou non ne serait pas un seuil.

**`--cov` n'est pas dans les `addopts`**, et c'est le réglage qui décide si un seuil survit. Il y
rendrait `pytest tests/modules/identity/domain` mesurable à quelques pour cent du service, donc en
échec — et un seuil qui mord sur chaque exécution ciblée, celle qu'on lance quarante fois par heure,
finit désactivé. Il vit dans `make test-cov`, et là seulement.

La couverture de **branches** est active : un `if` dont un seul côté est joué est un `if` à moitié
testé, et c'est précisément la moitié qui casse.

## Ce que la CI ne fait pas encore

`.github/workflows/ci-backend.yml` ne rejoue **que les contrats d'architecture**
([Import Linter](./qualite-et-typage.md#import-linter)). Ni Ruff, ni Mypy, ni pytest : ils
entreront avec QA-01, à qui ce fichier appartient et qui déclarera les services du job.

BACK-12 lui livre de quoi le faire sans rien inventer : les cibles `test-unit`,
`test-integration`, `test-tenancy` et `test-cov`, et le drapeau `--require-services` qui fait d'une
exécution verte une preuve plutôt qu'un rapport.

Conséquence pratique, et elle n'est pas théorique : **une suite cassée arrive telle quelle sur
`main`** si personne ne l'a lancée. Avant d'ouvrir une pull request qui touche `backend/api/`,
l'enchaînement minimal est celui-ci, depuis `backend/api/` :

```bash
make check && make test-cov
```

Attendu : Ruff, les contrats d'architecture, le formatage puis Mypy au vert — c'est l'ordre
qu'enchaîne `make check`, et [celui qu'aura la CI](./qualite-et-typage.md) — suivis du résumé de
pytest sans échec et des deux rapports de couverture.

Les écarts assumés avec le ticket BACK-12 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-12).
