---
title: Ce qui est interdit, et ce qui l'attrape
description: La liste des anti-patterns proscrits, ce qui se passe quand on les écrit, l'outil qui les arrête — et comment lire un contrat d'architecture qui casse.
---

# Ce qui est interdit, et ce qui l'attrape

Cette page est une **liste de contrôle**, pas un cours. Chaque ligne dit ce qui est interdit, ce
qui se passe si on l'écrit quand même, et ce qui l'arrête. Le raisonnement derrière chaque règle
est sur la page [Comment écrire un module conforme](./ecrire-un-module-conforme.md) ; les termes
sont définis au [glossaire](./glossaire.md).

La troisième colonne est la plus utile, et elle est honnête : certaines règles sont
**mécaniques** — un outil les fait échouer — et d'autres ne tiennent que par la **revue**. Les
secondes demandent davantage d'attention, précisément parce que rien ne les rattrape.

## Les interdits

| Interdit                                                                                     | Ce qui se passe sinon                                                                                                                                      | Ce qui l'attrape                                                                                                              |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Importer une technologie dans un `domain/` — `sqlalchemy`, `fastapi`, `pydantic`, `redis`…   | Le domaine devient indissociable de la base ou du serveur, et ne se teste plus sans eux.                                                                   | **Mécanique** — contrat 1, chaînes indirectes comprises                                                                       |
| Contourner la règle précédente par `if TYPE_CHECKING:`                                       | Le couplage reste, il ne coûte simplement rien à l'exécution. Ce n'est pas la même chose qu'être absent.                                                   | **Mécanique** — `exclude_type_checking_imports` laissé à `false`                                                              |
| Ajouter une dépendance applicative sans l'ajouter à la liste interdite du contrat 1          | Le domaine garde un chemin ouvert vers une technologie que personne ne surveille. La règle s'étend à tout paquet qu'un adaptateur importe **par son nom**. | **Revue** — dans la même pull request                                                                                         |
| Importer l'intérieur d'un autre module — son entité, son dépôt, son modèle                   | Les frontières se dissolvent, et le monolithe modulaire redevient un monolithe.                                                                            | **Mécanique** — contrat 3, dans les deux sens et même indirectement                                                           |
| Écrire une jointure SQL sur les tables d'un autre module                                     | Même effet, sans même laisser de trace dans le graphe d'imports.                                                                                           | **Revue** — invisible à l'outil                                                                                               |
| Poser une clé étrangère d'un module vers un autre                                            | La contrainte lie physiquement deux modules ; l'un ne peut plus migrer sans l'autre.                                                                       | **Revue** — relecture de migration, [ADR-0015](../adr/0015-cles-etrangeres-frontiere-module.md)                               |
| Faire dépendre `application/` de `infrastructure/`                                           | Le cas d'usage se met à connaître une technologie, et n'est plus testable par doublure.                                                                    | **Mécanique** — contrat 2                                                                                                     |
| Faire dépendre `shared/` d'un module                                                         | Le noyau partagé devient dépendant d'un métier ; tous les autres modules l'importent avec.                                                                 | **Mécanique** — contrat 5                                                                                                     |
| Écrire une entité **anémique** — une dataclass sans méthode, dont les règles vivent ailleurs | La règle se recopie chez chaque appelant, et un appelant l'oublie.                                                                                         | **Revue**                                                                                                                     |
| Injecter une **session** de base de données dans un cas d'usage                              | Le cas d'usage devient inappelable depuis un test ou une tâche de fond sans base réelle.                                                                   | **Revue** — le contrat 2 n'attrape que l'import, pas l'argument                                                               |
| Lever une `HTTPException` depuis le domaine                                                  | Le même code devient inutilisable depuis une tâche de fond, où personne n'attend de code HTTP.                                                             | **Mécanique** — contrat 1 (`fastapi`, `starlette`)                                                                            |
| Élargir un port parce que sa classe concrète sait faire plus                                 | La surface que les cas d'usage peuvent appeler grandit sans que personne l'ait décidé.                                                                     | **Revue**                                                                                                                     |
| Écrire `Entity(**model.__dict__)` au lieu d'un mapping à la main                             | Casse **en silence** au premier champ nommé différemment, en remplissant l'entité de valeurs par défaut.                                                   | **Mécanique** — Mypy, si les types diffèrent ; **revue** sinon                                                                |
| Oublier le filtre de tenance, ou l'ouvrir sans raison                                        | Une requête voit les données d'un autre groupe. L'échappatoire `use_all_groups(reason=…)` exige une raison et n'ouvre que les lectures.                    | **Mécanique** — dépôt tenant, garde d'index armée, [ADR-0013](../adr/0013-filtre-de-tenance-dans-le-depot.md)                 |
| Faire descendre du **vocabulaire métier** dans `shared/`                                     | `shared/` est réservé au besoin **technique**. Un vocabulaire partagé se **recopie**, sous garde de non-dérive.                                            | **Revue** — [ADR-0026](../adr/0026-fiche-technique-praticien.md)                                                              |
| Calquer les modules sur les trois frontends                                                  | Le cœur d'authentification serait triplé à l'identique. Ce sont des canaux de livraison, pas des contextes métier.                                         | **Revue** — [ADR-0003](../adr/0003-monolithe-modulaire.md)                                                                    |
| Éditer le code généré par Orval                                                              | La prochaine régénération efface la correction, et la CI la refuse avant.                                                                                  | **Mécanique** — `make generate-api-check` régénère puis compare (`git diff --exit-code`), rejoué par le workflow `api-client` |
| Écrire une migration sans la relire                                                          | L'autogénération d'Alembic propose des `DROP` qu'on ne veut pas, et le schéma diverge en silence.                                                          | **Revue** — [ADR-0010](../adr/0010-migrations-alembic.md)                                                                     |

## Quand un contrat casse, lire le message

C'est l'échec le plus fréquent du dépôt, et son message dit **exactement** ce qui ne va pas —
encore faut-il savoir quelle partie lire. Les sorties ci-dessous ont toutes été produites en
cassant réellement le contrat, puis en remettant le code en état.

Toutes se lisent depuis `backend/api/` avec la même commande, celle qui joue les cinq contrats :

```bash
make imports
```

Chaque section dit d'abord ce qui a été écrit pour provoquer l'échec, puis montre ce que la
commande répond.

`lint-imports` affiche d'abord un résumé — une ligne par contrat, `KEPT` ou `BROKEN` — puis une
section « Broken contracts » qui donne le détail. **C'est la seconde qu'il faut lire** : elle
contient la chaîne d'imports fautive.

:::tip Le geste qui corrige
Presque toujours : **déplacer du code**, jamais réécrire l'import. Une violation de frontière
dit qu'un fichier est au mauvais endroit, pas qu'un `import` est mal orthographié. C'est aussi
pour cela que `make imports` n'a pas de variante `--fix`.
:::

### Contrat 1 — le domaine importe une technologie

**Provoqué par** un `import sqlalchemy` ajouté dans `demo/domain/entities.py`.

```text
1. Purete du domaine
--------------------

app.modules.demo.domain is not allowed to import sqlalchemy:

-   app.modules.demo.domain.entities -> sqlalchemy (l.68)
```

Le domaine touche une technologie. **La correction** : ce dont l'entité avait besoin appartient
à un adaptateur, ou à un port si c'est un besoin durable.

### Contrat 2 — une couche remonte

**Provoqué par** un import de `demo/infrastructure/db/models.py` dans le cas d'usage.

```text
2. Sens des couches dans chaque module
--------------------------------------

app.modules.demo.application is not allowed to import
app.modules.demo.infrastructure:

- app.modules.demo.application.use_cases.publish_note ->
app.modules.demo.infrastructure.db.models (l.7)
```

Le cas d'usage nomme l'infrastructure. **La correction** : il doit passer par un **port** du
domaine, et l'assemblage se fait ailleurs — dans la route, ou dans `unit_of_work.py`.

### Contrat 3 — un module en importe un autre

**Provoqué par** un import d'une entité d'`identity` dans `demo/domain/ports.py`.

```text
3. Independance des modules
---------------------------

app.modules.demo is not allowed to import app.modules.identity:

- app.modules.demo.domain.ports -> app.modules.identity.domain.entities (l.67)
```

**La correction** dépend de ce qui était partagé, et les deux réponses sont opposées : un besoin
**technique** descend dans `shared/domain/ports/` ; un **vocabulaire métier** se recopie, sous
garde de non-dérive. C'est expliqué sur la
[carte de contexte](./carte-de-contexte.md#ce-qui-ne-passe-pas-par-la-carte).

### Contrat 4 — le domaine partagé remonte vers son infrastructure

**Provoqué par** un import de `shared/infrastructure/tenancy.py` dans `shared/domain/pagination.py`.

```text
4. Sens des couches du noyau partage
------------------------------------

app.shared.domain is not allowed to import app.shared.infrastructure:

- app.shared.domain.pagination -> app.shared.infrastructure.tenancy (l.167)
```

Même faute que le contrat 2, dans le noyau partagé. **La correction** est la même : le besoin
devient un port, l'implémentation reste en infrastructure.

### Contrat 5 — `shared/` regarde vers un module

**Provoqué par** un import d'une entité de `demo` dans `shared/domain/exceptions.py`.

C'est celui qui apprend le plus, parce qu'il ne casse **jamais seul**. Un seul import en casse
**deux**, et le second pour les **cinq** modules à la fois :

```text
1. Purete du domaine KEPT
2. Sens des couches dans chaque module KEPT
3. Independance des modules BROKEN
4. Sens des couches du noyau partage KEPT
5. Sens des dependances entre les espaces du service BROKEN

Contracts: 3 kept, 2 broken.


----------------
Broken contracts
----------------

3. Independance des modules
---------------------------

app.modules.organization is not allowed to import app.modules.demo:

- app.modules.organization.domain.exceptions -> app.shared.domain.exceptions
(l.16)
  app.shared.domain.exceptions -> app.modules.demo.domain.entities (l.184)


app.modules.notifications is not allowed to import app.modules.demo:

- app.modules.notifications.domain.exceptions -> app.shared.domain.exceptions
(l.22)
  app.shared.domain.exceptions -> app.modules.demo.domain.entities (l.184)


[... le meme bloc pour medical_records, identity et scheduling ...]


5. Sens des dependances entre les espaces du service
----------------------------------------------------

app.shared is not allowed to import app.modules:

- app.shared.domain.exceptions -> app.modules.demo.domain.entities (l.184)
```

Un import dans `shared/` ne salit pas que ce fichier : il salit **tout module qui en dépend**.
Les **cinq** modules cassent alors qu'aucun n'a rien fait — leurs `domain/exceptions.py`
importent tous la racine des erreurs partagée. Et le contrat affiche, pour chacun, la **chaîne
à deux sauts** qui l'y mène. C'est très exactement ce qu'une recherche textuelle, qui lit une
ligne à la fois, ne saurait pas voir.

La seule chose élidée ci-dessus est la répétition des trois derniers modules : leur bloc est
identique au mot près, seul le nom change.

**La correction** : `shared/` ne peut pas connaître un module. Ce qui devait circuler passe par
le **point de composition**, qui est le seul endroit autorisé à connaître plusieurs modules.

### L'échec sans faute — un fichier nouveau

**Provoqué par** la création d'un `demo/services.py`.

Celui-ci arrive alors qu'on n'a rien cassé du tout : ajouter un fichier dans un module suffit à
le déclencher.

```text
2. Sens des couches dans chaque module
--------------------------------------

The following modules are not listed as layers:

- app.modules.demo.services

(Since this contract is marked as 'exhaustive', every child of every container
must be declared as a layer.)
```

Le contrat est **exhaustif** : tout ce qui vit dans un module doit être une couche déclarée.
**La correction** n'est presque jamais d'ajouter une couche — c'est de ranger le fichier dans
`domain/`, `application/` ou `infrastructure/`, selon ce qu'il fait.

Un module n'a qu'une seule exemption, `unit_of_work.py`, et elle est déjà écrite.

### L'échec sans faute — une exception devenue inutile

**Provoqué par** une entrée `ignore_imports` restée en place après la correction qu'elle couvrait.

```text
No matches for ignored import app.modules.demo.domain.entities -> sqlalchemy.
```

Une entrée d'`ignore_imports` ne couvre plus rien. C'est délibéré :
`unmatched_ignore_imports_alerting` vaut `"error"`, si bien qu'une exception oubliée fait échouer
le lint au lieu de survivre en silence à l'import qu'elle couvrait.

**La correction** : retirer l'entrée. Le dépôt n'en déclare **aucune** aujourd'hui.

## Deux exceptions vivantes

Ces deux règles ont une entorse assumée, arbitrée et consignée. Les ignorer conduit à rouvrir un
dossier déjà clos.

### `shared/domain/password.py` contredit l'ADR-0022, et c'est voulu

La règle, posée par l'[ADR-0022](../adr/0022-transport-email-partage.md), dit que `shared/` est
réservé au besoin **technique** atteint par deux modules. L'objet-valeur `Password` y vit
pourtant, alors qu'il est du vocabulaire métier d'`identity`.

Le motif est mécanique : le port `PasswordHasher` **type** son argument — `hash(password:
Password)`. Le contrat 5 interdisant à `app.shared` d'importer un module, un `Password` rangé
dans `identity` obligerait le port à prendre un `str`, et la garantie « on ne hache que ce qui a
passé la politique » disparaîtrait avec le type.

L'écart est consigné au [registre](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-10b).

### Les entités sont un fichier plat, pas un dossier

Le guide de référence du projet montre un dossier `domain/entities/`. Le dépôt a retenu un
`domain/entities.py` **plat**, et c'est le ticket fondateur BACK-04 lui-même qui l'a écarté.

Créer `domain/entities/` dans un module nouveau irait donc contre un arbitrage rendu — et ferait
au passage échouer le contrat 2, le dossier n'étant pas une couche déclarée.

Les écarts assumés avec le ticket DOC-02a sont consignés au
[registre des écarts](../ecarts/doc.md#écarts-assumés-avec-le-ticket-doc-02a).
