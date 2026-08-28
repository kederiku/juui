---
title: ADR-0031 — L'arbre porte le module, la clôture porte le niveau, la transaction porte l'isolation
description: Le niveau d'un test se déduit de ce qu'il réclame, la base d'intégration reçoit les migrations et annule la transaction de chaque test, et un service absent ne rend jamais la suite verte.
---

# ADR-0031 — L'arbre porte le module, la clôture porte le niveau, la transaction porte l'isolation

| Statut      | Date       | Tickets |
| ----------- | ---------- | ------- |
| **Accepté** | 2026-08-28 | BACK-12 |

## Contexte

Le harnais de tests du service avait été **tiré en avant morceau par morceau** par les tickets qui
en avaient besoin : BACK-06b pour l'isolation de tenance, BACK-06c pour les suites de conformité,
BACK-09 et BACK-11 pour les sondes HTTP. Une vingtaine d'entrées du registre des écarts portaient
le même mot : « appartient à BACK-12 ».

Ce que cet état coûtait, concrètement :

- **Sans PostgreSQL, la session entière s'arrêtait** — `pytest.exit()` dans la fixture `engine` —,
  y compris les moitiés en mémoire des suites de conformité, qui n'ont besoin de rien. On ne
  pouvait pas écrire un test de cas d'usage sur un poste sans Docker.
- **Cinq `conftest.py` de module créaient leurs propres tables.** Le schéma sous test n'était donc
  pas celui que les migrations posent en production.
- **La couche d'un test était portée par le nom du fichier** (`test_ports.py` = infrastructure), pas
  par l'arbre : la frontière de module n'existait que dans `src/`.
- **Aucun moyen de dire « joue ce qui ne demande aucun service »**, les dix marqueurs déclarés étant
  tous thématiques.

Quatre questions liées se posaient donc ensemble, et c'est pourquoi cet ADR est un seul : **où** un
test vit, **comment** on sait ce qu'il coûte, **comment** la base d'intégration s'isole, et **ce
qu'une exécution verte prouve**.

## Décision

### L'arbre porte le module puis la couche, et seulement les couches qui existent

`tests/modules/<module>/{domain,application,infrastructure}/`. Un test vit à côté de ce qu'il
éprouve.

**On ne crée pas une couche que le module n'a pas.** `organization`, `medical_records` et
`scheduling` n'ont pas de couche `application/` dans `src/`, et le contrat n° 2 d'Import Linter met
déjà `(application)` entre parenthèses pour cette raison. Un répertoire de tests naît le jour où la
couche naît.

`tests/core/` et `tests/shared/` **ne sont pas découpés** : le contrat n° 5 dit qu'`app.core` ne
connaît personne et n'a pas de couches, et le contrat n° 4 en déclare exactement **deux** pour
`app.shared`, en écrivant que « le noyau partagé n'orchestre aucun cas d'usage ». Un découpage à
trois y serait faux. Ce qui **aide** à tester sans être un test — sondes HTTP, doublures
d'authentification, fabrique de jetons, stubs de tenance — est sorti dans `tests/support/`, parce
que le laisser sous `tests/shared/` faisait mentir le miroir.

### Le niveau se déduit de la clôture de fixtures, jamais du chemin

`unit`, `integration` et `slow` sont posés par `pytest_collection_modifyitems`, qui lit la clôture
de fixtures — transitive — de chaque test. Un test qui demande `session` tire `engine` et se classe
sans rien déclarer ; un test qui cesse d'avoir besoin d'une base se reclasse tout seul.

`slow` est un **qualificatif orthogonal**, pas un troisième niveau : un test peut être `unit` et
`slow`.

`--strict-markers` est actif, sans quoi la catégorie obligatoire `tenant_isolation` resterait un
vœu qu'une faute de frappe annule en silence.

### La base d'intégration reçoit les migrations, et chaque test annule sa transaction

`engine` applique `alembic upgrade head` à la base de test, une fois par session, sur sa propre
connexion et sous le verrou consultatif d'`env.py` — la même clé, ce qui sérialise la suite avec un
`make migrate` concurrent. Les cinq `conftest.py` de module disparaissent.

`connection` ouvre une transaction **externe** par test ; `bound_sessionmaker` y inscrit les
sessions en `join_transaction_mode="create_savepoint"`. Un `commit()` applicatif relâche alors un
savepoint, et le rollback emporte tout. **Plus aucune purge manuelle.**

### Un service absent ne rend jamais la suite verte, et ne l'arrête plus

`pytest.exit()` disparaît de la fixture `engine`. `require_service` saute **et recense** ; le bloc
de fin de session nomme les services qui ont manqué ; `--require-services` transforme le saut en
échec. C'est ce qui fait d'une CI verte une preuve, là où une exécution locale verte reste un
rapport.

Le seul `pytest.exit` restant est ailleurs, et il le mérite : un validateur refuse que la base de
test soit la base applicative. La surface de dégât est passée de « créer et détruire deux tables de
stub » à « ramener la base à `base` ».

## Alternatives écartées

### Déduire le niveau du chemin

Plus simple, et **faux dès le premier jour** : `notifications/infrastructure/test_channel_adapters.py`
est en couche infrastructure et ne touche aucun service ; il en va de même de tous les tests des
doublures en mémoire. Une règle `infrastructure/ → integration` aurait classé faux une bonne moitié
des fichiers, et le critère « les tests d'application tournent sans Docker » serait devenu
invérifiable.

### Répéter `pytestmark` dans chaque fichier

Cinquante lignes à écrire, cinquante à tenir vraies, et un oubli **silencieux** : le test tourne
quand même, il devient seulement invisible aux filtres. Surtout, un fichier déplacé garde un
marqueur devenu faux. Le ticket fonde toute sa réorganisation sur l'idée que l'arbre porte
l'information ; la répéter dans chaque fichier créerait une seconde source de vérité qui
divergerait.

### Ne pas appliquer les migrations, et construire le schéma par `create_all`

L'option la plus économique, et elle a un argument sérieux : c'est le passage par
`Base.metadata.create_all` qui **obligeait** un index comme `ix_accounts_email_lower` à vivre dans
le modèle et pas seulement dans sa migration. Elle a été écartée parce que cette pression se rachète
autrement, et mieux : `tests/shared/db/test_schema_matches_models.py` compare le schéma appliqué à
`Base.metadata`, avec `compare_type` et `compare_server_default`, et échoue donc **dans les deux
sens**. Le ticket demandait par ailleurs les migrations en toutes lettres, et tester un schéma qui
n'est pas celui de la production est précisément ce qu'on cherchait à corriger.

### Piloter Alembic par un sous-processus, ou par une surcharge de `POSTGRES_DB`

La surcharge d'environnement est **impossible** : `alembic/env.py` se termine par `asyncio.run`, qui
lève depuis la boucle d'une fixture. Le sous-processus fonctionnerait, mais il coupe de la stratégie
de transaction — il ne peut pas partager la connexion —, transforme un échec de migration en bloc de
`stderr` capturé plutôt qu'en traceback, et crée une **seconde source de vérité** sur la base que
les tests utilisent. La voie retenue est celle qu'Alembic documente pour ce cas : `env.py` honore
`config.attributes["connection"]`, en six lignes, et la voie de production ne change pas d'un octet
— rien ne pose l'attribut en ligne de commande.

### `testcontainers`

Une dépendance de plus, un démon Docker obligatoire là où `make dev` suffit, et surtout : il
faudrait **réimplémenter INFRA-01** — la création de la base de test et ses extensions `pg_trgm` et
`unaccent`. Deux définitions du même environnement. À réexaminer le jour où la CI devrait tourner
sans la pile compose ; c'est le seul motif qui la ferait gagner.

### Conserver la purge manuelle plutôt que le savepoint

L'objection était sérieuse et mérite d'être écrite : sous `create_savepoint`, le `commit()` du code
testé relâche un savepoint, et la suite de conformité ne prouve donc plus la durabilité **entre
connexions** — la propriété même pour laquelle sa moitié réelle existe.

Elle a été écartée pour deux raisons. D'abord, le patron est ce qui permet à une route atteinte par
le client HTTP de voir le semis non commité du test : sans lui, chaque test de route devrait
commiter puis purger. Ensuite, la propriété perdue est **rendue ailleurs**, explicitement — un test
sort du patron, commite sur le moteur, relit depuis une connexion distincte et purge lui-même. Ce
qui reste à la charge du lecteur est nommé dans la docstring de `bound_sessionmaker` : deux sessions
entrelacées sur une même connexion cassent le relâchement des savepoints, qui se fait en pile.

### Un méta-test qui vérifie qu'un test `tenant_isolation` existe

Séduisant, et **faux dès le premier `pytest -k`** : la collecte ne voit que la sélection courante,
et une telle garde passerait au vert précisément quand elle devrait mordre. La forme retenue prend
le problème par l'autre bout — elle vérifie que la **liste** des modules tenant est à jour, dans les
deux sens.

## Conséquences

**Ce que cela donne.** Les tests unitaires tournent sans aucun conteneur, en quelques secondes. Le
schéma sous test est celui de la production. Aucune purge n'est plus à écrire. Une exécution verte
dit ce qu'elle n'a pas prouvé. Une vingtaine d'entrées du registre des écarts se soldent.

**Ce que cela coûte, et qu'il faut savoir.**

- La moitié réelle des suites de conformité **commite dans un savepoint** et non jusqu'au disque.
  Un seul test sort du patron pour garder la propriété.
- Deux sessions **entrelacées** sur la connexion du test cassent. Le chemin nominal est en pile ;
  un test de concurrence prend `engine_sessionmaker` et se nettoie.
- `alembic check` ne doit **jamais** être lancé en processus depuis pytest : `Base.metadata` porte
  alors les deux tables de stub, et l'autogénération proposerait de les supprimer. `make
migrate-check` reste un sous-processus visant la base applicative.
- `alembic/env.py` a une branche de plus. Elle n'est empruntée que si un appelant dépose une
  connexion dans `config.attributes` — ce que la ligne de commande ne fait pas.

**Ce que cela ne décide pas.** L'entrée de `tests/` dans le périmètre de Mypy reste refusée, et
c'est un écart chiffré au registre, non une décision d'architecture. Le câblage de la suite en CI
appartient à QA-01, à qui BACK-12 livre les cibles et le drapeau `--require-services`.
