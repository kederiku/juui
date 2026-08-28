---
title: ADR-0023 — Les doublures en mémoire vivent dans src, tenues par un test de conformité
description: Les fakes du projet sont livrées dans `src/` et non sous `tests/`, et une même suite jouée contre le réel et contre la doublure les empêche de diverger.
---

# ADR-0023 — Les doublures en mémoire vivent dans `src`, tenues par un test de conformité

| Statut      | Date       | Tickets           |
| ----------- | ---------- | ----------------- |
| **Accepté** | 2026-08-26 | BACK-06c, BACK-12 |

## Contexte

Décision rendue par BACK-06c. Le guide DDD du projet privilégie explicitement les **Fakes aux
Mocks**, et BACK-12 attend de ce ticket que les tests d'application tournent sans Docker ni base de
données. Trois tickets antérieurs avaient déjà eu besoin de doublures et les avaient écrites où ils
pouvaient :

- BACK-17 et BACK-22 sous `tests/`, dans un `otp_doubles.py` et un `notification_doubles.py` dont
  les docstrings annonçaient leur propre disparition ;
- BACK-14 et BACK-04 **dans une sonde de documentation**, faute de mieux — avec, pour l'unité de
  travail, un commentaire qui disait tout : « doublure JETABLE : commit et rollback sans effet
  réel ».

Deux questions restaient donc ouvertes, et elles sont liées : **où** ces classes vivent, et **ce qui
garantit** qu'elles disent la vérité.

La seconde est la plus sérieuse. Une doublure dont le `rollback()` ne fait rien valide une
sémantique que la vraie implémentation ne tient pas : elle rend un test **vert** qui affirme quelque
chose de faux. C'est pire que pas de test — un test absent ne trompe personne.

## Décision

**Les doublures sont livrées dans `src/`, à côté des adaptateurs qu'elles doublent.** Les doublures
des ports techniques vont dans `shared/infrastructure/memory/` ; celles des ports **métier** vont
dans l'`infrastructure/memory/` de leur module. La règle tient en quatre mots : **la doublure suit
son port**. Le contrat `service-spaces` la rend d'ailleurs obligatoire — `app.shared` ne peut pas
importer `app.modules`, donc un `FakeOtpSender` rangé avec les doublures techniques ferait échouer
`make lint`.

**Une suite de conformité unique est jouée contre les deux implémentations.** Elle vit dans
`tests/shared/conformance/`, sous la forme d'une classe de base portant les tests et de deux
sous-classes ne fournissant que la fixture du sujet. La classe de base ne s'appelle pas `Test…` :
pytest ne la collecte pas, et **un test ajouté à la base est mécaniquement joué des deux côtés**.
Cinq sujets aujourd'hui : le dépôt et l'unité de travail (PostgreSQL contre dictionnaires), le
cache (Redis contre mémoire), le stockage objet (MinIO contre mémoire), et — parce que le socle ne
dit rien des doublures de module — le dépôt de comptes et le magasin d'OTP d'`identity`.

**Ce qui ne peut pas se comparer reste hors de la suite**, dans `tests/shared/memory/` : la réponse
à la panne — qui se simule d'un côté et demanderait d'arrêter un conteneur de l'autre — et les
inspecteurs propres aux doublures.

## Alternatives écartées

### Laisser les doublures sous `tests/`

C'est où elles étaient, et c'est le réflexe. Écartée pour une raison mécanique : une classe rangée
sous `tests/modules/identity/` n'est importable que par les tests qui la voisinent. Or
`InMemoryCache` sert aux tests d'`identity` comme à ceux de `medical_records`, une sonde de
documentation ne peut rien importer de `tests/` du tout, et BACK-12 devait les câbler dans des
fixtures partagées — ce qu'il a fait, sans avoir à les déplacer. Le rangement par ticket produisait déjà trois copies partielles avant que le
quatrième consommateur existe.

### Un paquet `tests/doubles/` partagé, hors de `src/`

Le compromis apparent : partagé, mais hors de la roue de production. Écarté parce qu'il ne résout
que la moitié du problème et en crée une autre — il place les doublures **loin** des adaptateurs
qu'elles doublent, alors que ce qui les fait diverger est précisément qu'on modifie l'un sans
regarder l'autre. Sous `src/`, `memory/` est le voisin de `clients/` et de `db/` : la revue voit
les deux dans le même diff.

### S'en tenir à des doublures écrites au cas par cas dans chaque test

Aucune infrastructure, aucune décision. Écartée : c'est la situation qui a produit une unité de
travail dont le commit ne commitait pas. Une doublure ad hoc reproduit ce que son auteur croit du
contrat, et l'écart ne se voit jamais.

### Se fier à la relecture plutôt qu'à une suite de conformité

Écartée par ce que la suite a trouvé **le jour de son écriture** : deux divergences réelles, dans
le sens inverse de celui qu'on attendait. Ce n'était pas la doublure qui mentait — c'était
l'adaptateur SQLAlchemy qui laissait survivre, dans son propre bloc, une ligne qu'il venait de
supprimer, et qui ordonnait une page sur l'état d'avant une écriture non flushée. Deux ans de
relecture attentive n'auraient pas montré cela ; une suite jouée deux fois l'a montré en une
exécution. Une revue contradictoire menée dans la foulée en a sorti quatre autres, dans des
recoins qu'aucune suite n'atteignait : la casse de `find_by_email`, l'arrondi du `Retry-After`,
quatre divergences de syntaxe de motifs entre Redis et `fnmatch`, et un dépôt en mémoire qui
restait opérant après la sortie de son bloc. **Le dispositif ne dispense pas de la relecture ; il
en fixe le résultat.**

## Conséquences

Ce que le service gagne : un jeu de doublures unique et importable de partout, deux fichiers de
doublures empruntées retirés de `tests/`, et surtout un mécanisme qui **survit aux tickets
suivants**. La règle qui en découle est simple à tenir : une doublure qui gagne un comportement
gagne sa ligne de conformité dans le même commit.

Ce qu'il paie : ces classes voyagent dans la roue de production et dans l'image Docker. Le coût est
mesuré — seize fichiers, les deux paquets de module compris, aucune dépendance nouvelle — et il
n'est pas que du poids mort :
`InMemoryCache` rend un poste de développement capable de servir toutes les routes sans Redis, la
dépendance `get_cache` portant déjà son `isinstance` sur le **port** et non sur `RedisCache`.

Ce qui reste ouvert : `organization` et `medical_records` n'ont pas encore leurs doublures — aucun
cas d'usage ne les consomme, et leurs _finders_ maison seraient réimplémentés pour personne. Le
socle générique rend leur ajout mécanique le jour où BACK-25 ou BACK-30 en auront besoin. Et la
limite de la conformité est nommée : les contraintes du **stockage** — unicité, clé étrangère,
`NOT NULL`, ordre des `NULL` dans un tri — ne sont pas reproduites, et ne doivent pas l'être. Elles
sont l'objet des tests d'infrastructure sur vraie base, troisième niveau de la stratégie que
BACK-12 a installée ([ADR-0031](./0031-strategie-de-test-a-trois-niveaux.md)).
