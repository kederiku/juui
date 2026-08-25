---
title: Qualité et typage
description: Ruff, Mypy strict et Import Linter — les garde-fous mécaniques du service et leurs contrats.
---

# Qualité et typage

Trois outils gardent le service sans intervention humaine — Ruff pour le lint et
le formatage, Mypy en mode strict pour le typage, Import Linter pour les
contrats d'architecture. Cette page détaille leurs réglages, leurs raisons et la
façon de vérifier que chaque garde-fou tient vraiment.

Ruff, Mypy et Import Linter sont configurés dans
`pyproject.toml`, chaque réglage accompagné de sa
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
Voir [Hooks de pre-commit](../getting-started/conventions-du-depot.md#hooks-de-pre-commit). Le typage et
les contrats d'architecture, eux, n'entrent pas dans le hook : lint-staged passe
des **fichiers**, quand Mypy et Import Linter raisonnent sur le **projet
entier**. Ils restent à lancer à la main, et la CI les vérifie.

## Ruff

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

## Mypy

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

## Import Linter

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

Les écarts assumés avec les tickets BACK-02 et BACK-04b sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-02).
