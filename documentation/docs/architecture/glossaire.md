---
title: Le vocabulaire du projet, terme par terme
description: Chaque mot d'architecture et de métier employé dans le dépôt — sa définition, le fichier qui l'incarne, et les confusions qui coûtent cher.
---

# Le vocabulaire du projet, terme par terme

Cette page définit les mots employés partout ailleurs. Elle existe pour une raison précise : le
reste de la documentation les emploie sans les redéfinir, et un terme mal compris se paie en
code à réécrire — un agrégat pris pour une table, une clinique prise pour une frontière de
sécurité.

Chaque entrée donne une définition, puis **le fichier du dépôt qui l'incarne**. Le fichier fait
foi : quand cette page et le code divergent, c'est le code qui a raison, et cette page qui est à
corriger.

:::info Comment lire ce tableau
La colonne « Où le voir » donne, quand c'est un fichier, un chemin depuis
`backend/api/src/app/` — ouvrir ce fichier est le plus court chemin vers la compréhension,
chacun portant une docstring qui explique pourquoi il existe. Quand la meilleure source est une
page ou un ADR, la colonne y renvoie directement.
:::

## Le vocabulaire de l'architecture

| Terme                       | Ce que c'est                                                                                                                                                                                                                                                                                          | Où le voir                                                   |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| **Architecture hexagonale** | Un style où le métier ne connaît aucune technologie : il déclare des **ports**, et des **adaptateurs** les remplissent. Ici, l'hexagone est **à l'intérieur** de chaque module, pas à l'échelle du service.                                                                                           | [ADR-0003](../adr/0003-monolithe-modulaire.md)               |
| **Workspace**               | Un sous-projet du monorepo géré par pnpm — une application, un package partagé, le site de documentation. `pnpm --filter <nom>` cible l'un d'eux.                                                                                                                                                     | `pnpm-workspace.yaml`                                        |
| **Monolithe modulaire**     | Un seul service déployé, découpé à l'intérieur en modules métier étanches. Ni microservices — dont les frontières deviendraient des frontières réseau — ni domaine plat.                                                                                                                              | [ADR-0003](../adr/0003-monolithe-modulaire.md)               |
| **Espace**                  | L'un des trois territoires qui portent le code — `modules/`, `shared/`, `core/` — auxquels s'ajoute `main.py`. Le contrat 5 ordonne les quatre, et il est `exhaustive` : un cinquième fait échouer le lint tant que sa place n'est pas écrite.                                                        | `__init__.py`                                                |
| **Couche**                  | L'un des trois étages d'un module : `domain/`, `application/`, `infrastructure/`. La couche dit le **sens des dépendances** ; elle ne porte aucune frontière métier.                                                                                                                                  | `modules/identity/`                                          |
| **Module**                  | Un contexte métier étanche, qui répond à **une** question du produit. C'est lui qui porte la frontière.                                                                                                                                                                                               | `modules/__init__.py`                                        |
| **Port**                    | Une classe abstraite qui exprime un **besoin** du métier, écrite en bibliothèque standard seule. Elle dit aussi ce qui se passe quand le service masqué ne répond plus.                                                                                                                               | `shared/domain/ports/__init__.py`                            |
| **Adaptateur**              | L'implémentation concrète d'un port, qui a le droit de connaître une technologie. Un port a en général plusieurs adaptateurs.                                                                                                                                                                         | `shared/infrastructure/clients/redis_cache.py`               |
| **Doublure**                | Un adaptateur en mémoire, écrit pour les tests, qui reproduit **tout le comportement observable** du vrai. Le projet dit « doublure », pas « mock ».                                                                                                                                                  | `shared/infrastructure/memory/`                              |
| **Entité**                  | Un objet du domaine identifié par un identifiant stable, qui **porte ses propres règles**. Une dataclass sans méthode n'est pas une entité, c'est un anti-patron.                                                                                                                                     | `modules/identity/domain/entities.py`                        |
| **Agrégat**                 | Une entité **racine** — celle qui donne son nom à l'ensemble — et tout ce qui n'existe que par elle, modifiés d'un seul tenant. C'est l'unité de cohérence, et l'unité de tenance.                                                                                                                    | `modules/scheduling/domain/entities.py`                      |
| **Schéma d'API**            | Le PREMIER des trois modèles : un objet Pydantic qui valide l'entrée, met en forme la sortie et documente OpenAPI. Il ne porte aucune règle métier.                                                                                                                                                   | `modules/identity/infrastructure/api/schemas.py`             |
| **Modèle de persistance**   | Le TROISIÈME des trois modèles : une classe SQLAlchemy qui décrit des colonnes, des types et des contraintes. Une méthode métier n'y a jamais sa place.                                                                                                                                               | `modules/identity/infrastructure/db/models.py`               |
| **Mixin**                   | Une classe sans existence propre, dont un modèle de persistance hérite pour gagner des colonnes toutes faites — identité, horodatage, tenance.                                                                                                                                                        | `shared/infrastructure/db/mixins.py`                         |
| **Invariant**               | Une propriété qu'un objet du domaine doit vérifier **en permanence** — un compte suspendu ne se suspend pas deux fois. C'est l'objet lui-même qui la fait respecter, jamais son appelant.                                                                                                             | `modules/identity/domain/entities.py`                        |
| **Entité anémique**         | Une entité **sans méthode**, réduite à des champs, dont les règles vivent chez ses appelants. C'est l'anti-patron que tout ce découpage cherche à éviter.                                                                                                                                             | [Ce qui est interdit](./anti-patterns.md)                    |
| **Objet-valeur**            | Un objet du domaine sans identité, défini par sa seule valeur, et **valide par construction**.                                                                                                                                                                                                        | `shared/domain/password.py`                                  |
| **Politique**               | Une règle du domaine extraite en fonction, appelée par l'entité — normaliser une adresse, borner un horaire.                                                                                                                                                                                          | `modules/identity/domain/policies.py`                        |
| **Cas d'usage**             | Une intention du produit, un fichier, une classe, une méthode `execute()`. Il reçoit un **port**, jamais une session de base de données.                                                                                                                                                              | `modules/identity/application/use_cases/create_account.py`   |
| **Commande**                | Ce dont un cas d'usage a besoin, exprimé sans vocabulaire HTTP. Gelée : une commande transmise ne se corrige pas en chemin.                                                                                                                                                                           | `…/use_cases/create_account.py`                              |
| **Fabrique**                | Une fonction qui construit un objet complet et valide — `Account.create()` dans le domaine, `build_cache(settings)` pour un adaptateur. Elle existe pour qu'on ne puisse pas obtenir un objet à moitié construit.                                                                                     | `modules/identity/domain/entities.py`                        |
| **Erreur métier**           | Une exception qui décrit un **refus du domaine**. Elle descend de `DomainError`, porte un code `<module>.<ressource>.<erreur>`, et se traduit en HTTP à la bordure. Quelques pannes techniques en descendent aussi, quand le contrat d'un port l'exige : le traducteur les re-lève alors vers le 500. | `shared/domain/exceptions.py`                                |
| **Dépôt**                   | Le port par lequel un module lit et écrit ses entités. Il échange des **entités**, jamais des lignes de table.                                                                                                                                                                                        | `modules/identity/domain/ports.py`                           |
| **Unité de travail**        | L'objet qui délimite une transaction et sert les dépôts du module pendant sa durée. Une par module, jamais globale.                                                                                                                                                                                   | `modules/identity/unit_of_work.py`                           |
| **Transaction**             | L'intervalle pendant lequel les écritures sont retenues et prennent effet **ensemble**, ou pas du tout. Ici, elle est délimitée par le bloc `async with` d'une unité de travail.                                                                                                                      | `shared/domain/ports/unit_of_work.py`                        |
| **Commit**                  | Le geste **explicite** qui valide une transaction. Sortir du bloc sans l'appeler n'écrit rien : ce n'est pas un oubli rattrapé, c'est la règle.                                                                                                                                                       | `shared/domain/ports/unit_of_work.py`                        |
| **Rollback**                | L'annulation de tout ce que la transaction avait écrit. Il est **structurel** : la sortie du bloc l'exécute d'office, y compris sur les doublures.                                                                                                                                                    | `shared/domain/ports/unit_of_work.py`                        |
| **Point de composition**    | Le **seul** fichier autorisé à connaître plusieurs modules à la fois : `main.py`. Côté worker, `lifecycle.py` ne le peut pas — il vit dans `shared/`, que le contrat 5 rend aveugle aux modules — et chaque module y construit donc sa propre ressource.                                              | `main.py`                                                    |
| **Surface publique**        | Ce qu'un module exporte depuis son `__init__.py`, et rien d'autre. Le reste lui appartient.                                                                                                                                                                                                           | `modules/organization/__init__.py`                           |
| **ASGI**                    | L'interface entre un serveur web Python et une application **asynchrone**. `uvicorn app.main:app` sert l'objet ASGI que `main.py` expose.                                                                                                                                                             | `main.py`                                                    |
| **Tâche de fond**           | Un traitement sorti du cycle de la requête HTTP et confié à un **worker**, un second processus qui consomme une file. L'utilisateur n'attend pas.                                                                                                                                                     | `shared/infrastructure/tasks/demo.py`                        |
| **Sonde**                   | Deux sens, tous deux courants ici. Une **sonde de santé** est une route que l'infrastructure interroge pour savoir si le service répond (`/health/live`, `/health/ready`). Une **sonde de documentation** est une commande donnée par une page pour vérifier soi-même qu'une règle tient encore.      | `shared/infrastructure/api/health.py`                        |
| **Garde de non-dérive**     | Un test dont le seul rôle est d'empêcher deux copies de diverger — le catalogue d'espèces recopié entre deux modules, par exemple.                                                                                                                                                                    | `tests/modules/scheduling/domain/test_species_vocabulary.py` |
| **Contrat d'architecture**  | Une règle vérifiée par Import Linter, qui fait échouer la CI quand elle est violée. Il y en a cinq.                                                                                                                                                                                                   | `pyproject.toml`, à la racine de `backend/api/`              |
| **ADR**                     | _Architecture Decision Record_ — une décision structurante, son motif et les alternatives écartées. Une décision revisitée n'est pas effacée : elle est remplacée.                                                                                                                                    | [Le registre des ADR](../adr/index.md)                       |
| **Écart assumé**            | Un ticket livré autrement que sa lettre, délibérément, avec la raison de l'arbitrage. C'est un ADR en miniature.                                                                                                                                                                                      | [Le registre des écarts](../ecarts/index.md)                 |

## L'outillage cité partout

Ces noms reviennent dans presque toutes les pages du site. Aucun n'est un concept du projet : ce
sont les outils qui le tiennent debout, et savoir lequel fait quoi évite de chercher au mauvais
endroit quand quelque chose échoue.

| Outil             | Ce qu'il fait ici                                                                                                                                  | Où lire la suite                                                   |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| **uv**            | Gère l'interpréteur Python, l'environnement, les dépendances et le verrou. Toutes les commandes du backend passent par lui.                        | [Dépendances](../backend/dependances.md)                           |
| **Ruff**          | Lint et formatage Python. Il exige entre autres une docstring sur chaque module et chaque fonction publique.                                       | [Qualité et typage](../backend/qualite-et-typage.md)               |
| **Mypy**          | Vérificateur de types, en mode **strict** : une fonction non annotée est refusée.                                                                  | [Qualité et typage](../backend/qualite-et-typage.md)               |
| **Import Linter** | Fait respecter les cinq contrats d'architecture en suivant les **chaînes** d'imports. C'est lui qui échoue quand une frontière est franchie.       | [Qualité et typage](../backend/qualite-et-typage.md#import-linter) |
| **SQLAlchemy**    | La bibliothèque qui parle à PostgreSQL. Elle n'apparaît **que** dans `infrastructure/db/`.                                                         | [Persistance](../backend/persistance.md)                           |
| **Alembic**       | Met le schéma de la base sous contrôle de version : chaque changement de table est un fichier de migration, relu à la main.                        | [Migrations](../backend/migrations.md)                             |
| **Pydantic**      | Valide ce qui entre et sort de l'API, et la configuration au démarrage.                                                                            | [Configuration](../backend/configuration.md)                       |
| **FastAPI**       | Le cadre HTTP : routes, injection de dépendances, génération du contrat OpenAPI.                                                                   | [Surface HTTP](../backend/surface-http.md)                         |
| **TaskIQ**        | Le mécanisme de tâches de fond : un broker Redis, un worker, une politique de reprise.                                                             | [Tâches de fond](../backend/taches-de-fond.md)                     |
| **Orval**         | Génère le client d'API des frontends **depuis** le contrat OpenAPI — types, hooks et schémas. Sa sortie est versionnée et **interdite d'édition**. | [Client d'API généré](../frontend/client-api-genere.md)            |
| **pytest**        | Le lanceur de tests. Une _fixture_ y est un morceau de contexte préparé d'avance pour un test : une base, un client HTTP, une horloge figée.       | [Doublures en mémoire](../backend/doublures-en-memoire.md)         |

## Le vocabulaire métier

| Terme                            | Ce que c'est                                                                                                                                                                                             | Où le voir                                                 |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| **Groupe**                       | Le groupe de cliniques. C'est **la** frontière d'isolation du produit : deux groupes ne voient jamais les données l'un de l'autre.                                                                       | `modules/organization/domain/entities.py`                  |
| **Clinique**                     | Un lieu de travail à l'intérieur d'un groupe. Un **périmètre**, jamais une frontière de sécurité.                                                                                                        | `modules/organization/domain/entities.py`                  |
| **Tenance**                      | Le fait, pour une donnée, d'appartenir à un groupe et d'être filtrée sur lui automatiquement. Le mixin qui la porte est **opt-in**.                                                                      | `shared/infrastructure/db/mixins.py`                       |
| **Appartenance**                 | Le lien **daté** entre un compte et un groupe. Un compte n'a pas un groupe, il a des appartenances — un vétérinaire remplaçant en a plusieurs.                                                           | `modules/organization/domain/entities.py`                  |
| **Affectation**                  | Le lien **daté** entre un compte et une clinique, à l'intérieur d'une appartenance. Elle dit où l'on travaille, pas qui l'on est.                                                                        | `modules/organization/domain/entities.py`                  |
| **Détention**                    | Le lien **daté** entre un animal et son détenteur. Le dossier suit l'animal, pas le propriétaire du moment.                                                                                              | `modules/medical_records/domain/entities.py`               |
| **Dossier**                      | L'ensemble de ce qui est consigné sur un animal. Il appartient à l'**animal**, et lui survit à chaque changement de détenteur.                                                                           | [ADR-0006](../adr/0006-dossier-medical-animal.md)          |
| **Fiche technique du praticien** | Les horaires d'intervention et les espèces prises en charge d'un vétérinaire, portés par la **clinique** où il exerce.                                                                                   | `modules/scheduling/domain/entities.py`                    |
| **Événement de notification**    | Ce qu'un module **émet** quand quelque chose s'est produit. L'émetteur ne choisit jamais le canal.                                                                                                       | `modules/notifications/domain/policies.py`                 |
| **Canal**                        | Le moyen de remise d'une notification — e-mail, SMS, push. Choisi une seule fois, à la remise, d'après les préférences du compte.                                                                        | `modules/notifications/infrastructure/clients/`            |
| **Claim**                        | Un champ signé à l'intérieur d'un jeton — qui il désigne, pour quelle application, jusqu'à quand. Signé, donc infalsifiable, mais **lisible** par tous : jamais de secret dedans.                        | [Jetons](../backend/jetons.md)                             |
| **Périmètre de requête**         | Le couple « groupe actif, clinique active » sous lequel une requête s'exécute.                                                                                                                           | [ADR-0012](../adr/0012-perimetre-de-requete.md)            |
| **Mutator**                      | La fonction que le client d'API généré appelle pour **chaque** requête. C'est le seul endroit où l'on ajoute l'URL de base, les en-têtes et la gestion d'erreur — le code généré, lui, ne se touche pas. | [Client d'API généré](../frontend/client-api-genere.md)    |
| **Audience d'un jeton**          | L'application à laquelle un jeton est destiné. C'est elle qui sépare les trois frontends, pas un module par frontend.                                                                                    | [ADR-0024](../adr/0024-jetons-audience-par-application.md) |

## Les confusions qui coûtent cher

Quatre distinctions valent d'être apprises avant d'écrire une ligne. Chacune a déjà produit une
décision consignée, ce qui est le signe qu'elle n'est pas évidente.

### Groupe et clinique ne sont pas interchangeables

Le **groupe** isole ; la **clinique** est un périmètre de travail. Une donnée se filtre sur le
groupe, jamais sur la clinique. Choisir la clinique comme frontière ferait d'un cabinet à deux
sites deux clients distincts, incapables de se relire.

C'est la décision de l'[ADR-0004](../adr/0004-tenance-par-groupe.md), et le code en donne la
paire d'exemples : une **affectation** porte le mixin de tenance (`AssignmentModel`), un
**animal** ne le porte pas (`AnimalModel`).

### Appartenance et affectation ne répondent pas à la même question

L'**appartenance** dit « ce compte travaille dans ce groupe, entre ces deux dates ».
L'**affectation** dit « à l'intérieur de ce groupe, ce compte intervient dans cette clinique ».

Les fondre reviendrait à coller au compte un `group_id` immuable, ce qu'un vétérinaire
remplaçant contredit dès son premier jour. Voir l'[ADR-0005](../adr/0005-appartenance-datee.md).

### Une doublure n'est pas un mock

Un **mock** vérifie qu'un appel a eu lieu. Une **doublure** se comporte comme la vraie chose :
elle garde ses écritures en attente jusqu'au commit, applique le filtre de tenance, et lève les
mêmes erreurs d'absence.

La conséquence — pourquoi une doublure complaisante est pire que pas de test, et ce qu'elle ne
doit surtout **pas** reproduire — est traitée sur
[Comment écrire un module conforme](./ecrire-un-module-conforme.md#des-doublures-pas-des-mocks).
Les doublures réellement livrées sont décrites sur
[Doublures en mémoire](../backend/doublures-en-memoire.md), et le motif dans
l'[ADR-0023](../adr/0023-doublures-en-memoire-et-conformite.md).

### Un port n'est pas une interface technique

Un **port** exprime un besoin **du métier**, dans son vocabulaire à lui. `FileStorage` ne parle
ni de bucket ni de clé S3 ; il parle de ranger et de relire un fichier.

Une interface qui recopie l'API d'une bibliothèque n'est pas un port : c'est la même dépendance
avec une couche de peinture, et elle empêchera de changer de technologie exactement comme
l'import direct l'aurait fait.

Les écarts assumés avec le ticket DOC-02a sont consignés au
[registre des écarts](../ecarts/doc.md#écarts-assumés-avec-le-ticket-doc-02a).
