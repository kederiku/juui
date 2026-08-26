---
title: ADR-0018 — Les journaux se formatent avec la bibliothèque standard, deux rendus, un contexte automatique
description: JSON dès que l'environnement n'est pas development, rendu aligné et coloré en développement, contexte de requête lu de contextvars, masquage par nom de clé — structlog et python-json-logger écartés après mesure de ce qu'ils couvrent réellement.
---

# ADR-0018 — Les journaux se formatent avec la bibliothèque standard

| Statut      | Date       | Tickets                             |
| ----------- | ---------- | ----------------------------------- |
| **Accepté** | 2026-08-26 | BACK-11, BACK-15, BACK-27 (à venir) |

## Contexte

Décision rendue par BACK-11, dont le ticket suggérait « structlog ou python-json-logger ».

Le service n'avait aucune configuration de journalisation. Les sept `logging.getLogger(__name__)`
du dépôt écrivaient à travers le `lastResort` de la bibliothèque standard, qui ne relaie que les
`WARNING` et au-delà — au point que la reprise du cache Redis avait dû être écrite en `WARNING`
alors que c'est une bonne nouvelle, faute de quoi la fin d'une panne aurait été invisible. Aucun
`basicConfig()` n'avait été appelé, délibérément, pour ne pas se battre avec cette configuration à
venir.

Le besoin n'est pas seulement d'écrire du JSON. Il en compte quatre, et c'est leur somme qui décide :
un rendu **lisible et coloré** sur le poste de développement ; un rendu **JSON** pour un agrégateur ;
un **contexte de requête automatique** — identifiant de requête, compte, groupe actif, clinique —
lu des contextvars que BACK-15 ([ADR-0008](./0008-taskiq-taches-de-fond.md)) et BACK-14
([ADR-0004](./0004-tenance-par-groupe.md)) ont déjà posées ; et un **masquage** systématique de ce
qui ne doit jamais atteindre un journal. Sans ce contexte dans les lignes, aucun incident
multi-tenant n'est diagnosticable après coup ([ADR-0012](./0012-perimetre-de-requete.md)) — et le
coût d'ajouter les trois identifiants est quasi nul si c'est fait en même temps que l'identifiant
de requête.

## Décision

**Les deux formateurs sont écrits avec la bibliothèque standard, dans `core/logging.py` ; le format
se déduit de `ENVIRONMENT`, le contexte se lit de contextvars, et le masquage porte sur les noms de
clé.** Concrètement :

- **Aucune dépendance de journalisation.** `JsonFormatter` et `ConsoleFormatter` héritent de
  `logging.Formatter` : les sept loggers existants les traversent sans une ligne de changement, et
  le contrat `domain-purity` ne gagne pas de paquet à interdire.
- **JSON dès que l'environnement n'est pas `development`.** Le pré-production suit la production et
  non le développement : il existe pour la **répéter**, et c'est là qu'on valide l'ingestion des
  journaux. La règle ne s'écrit donc pas `is_production` — nuance corrigée dans la docstring de
  `AppSettings.is_production`, qui ne sert plus qu'à fermer `/docs`.
- **Les clés absentes plutôt que nulles**, à l'inverse de `ErrorResponse`
  ([ADR-0014](./0014-traduction-des-erreurs-a-la-bordure.md)). Celui-là est un contrat **client**,
  typé par Orval ([ADR-0007](./0007-client-api-genere-orval.md)), où une clé qui apparaît et
  disparaît casse le typage. Un journal se lit par `grep` et par un agrégateur, où l'absence **est**
  une valeur — et quatre `null` sur chaque ligne d'un worker sont du volume payé pour rien.
- **Le contexte arrive par deux chemins, et il le faut.** L'identifiant de requête, le compte et la
  clinique vivent dans `core/correlation.py` : le formateur les lit directement. Le groupe actif vit
  dans `shared/infrastructure/tenancy.py`, et le contrat `service-spaces` interdit à `core`
  d'importer `shared` : il arrive par `configure_logging(context_providers=...)`, passé par les
  **deux points d'entrée du processus** — le `lifespan` de l'API et `worker_startup()`. Une seule
  source de vérité, aucune copie à tenir synchrone, et tout ce qui pose un groupe apparaît dans les
  journaux sans que personne y pense.
- **Le masquage porte sur les NOMS DE CLÉ**, en sous-chaîne et sans égard à la casse : une
  correspondance exacte laisserait passer `hashed_password`, `access_token` et `otp_code`,
  c'est-à-dire la quasi-totalité des noms réels. Un second mécanisme, par forme, rattrape ce qui est
  déjà interpolé dans une phrase — affectations, identifiants d'URL, jetons porteurs. **C'est un
  filet, pas le mécanisme** : un secret passé en argument positionnel sans nom de clé aux alentours
  passe entre les mailles, et la règle reste de ne pas l'écrire.
- **Le masquage vit dans des fonctions pures appelées par les formateurs**, jamais dans un
  `logging.Filter`. Un filtre devrait _muter_ l'enregistrement, or celui-ci est partagé avec tout
  autre handler présent — celui de `caplog` en test, un handler d'audit demain (BACK-27).
- **`configure_logging()` est impérative, idempotente, et appelée par les deux points d'entrée du
  processus** — jamais à l'import, jamais depuis `create_app()`. Elle reprend au passage la main sur
  les loggers d'uvicorn et éteint `uvicorn.access`, dont notre intergiciel prend la place.

## Alternatives écartées

### structlog

Le candidat le plus complet, et celui que le ticket nommait en premier. Deux obstacles, dont le
second est architectural. Les sept `logging.getLogger(__name__)` existants ne deviennent des
événements structurés qu'à travers `ProcessorFormatter` et son `foreign_pre_chain` : une couche
d'intégration d'une quarantaine de lignes que personne dans l'équipe ne relira, pour un résultat qui
reste du formatage de messages `%s`. Et structlog porte **ses propres** contextvars
(`bind_contextvars`), à côté de `core/correlation.py` : il faudrait soit un processeur maison qui
lit les nôtres — auquel cas structlog n'apporte plus que son `JSONRenderer` —, soit migrer
`correlation.py` vers structlog, ce qui casserait le contrat `str` opaque et le label TaskIQ déjà
livrés par BACK-15.

### python-json-logger

Vraiment un `logging.Formatter`, donc natif avec l'existant, et c'est son mérite. Mais il ne fait
que le JSON : le rendu de développement, le masquage et la lecture des contextvars — les trois
quarts du travail — restent entièrement à écrire. Payer une dépendance applicative et une ligne au
contrat `domain-purity` pour économiser trente-cinq lignes de sérialisation est un mauvais change.

### `dictConfig` plutôt qu'une configuration impérative

La forme canonique, et la bonne quand la configuration est une donnée. Ici les formateurs reçoivent
des **objets construits à l'exécution** — les fournisseurs de contexte —, que `dictConfig` ne sait
passer qu'à travers une fabrique désignée par un chemin pointé. Vingt lignes lisibles et typées
valent mieux qu'un dictionnaire indirect.

### Faire confiance au `--log-config` d'uvicorn

Inutile, vérifié : uvicorn configure la journalisation dans `Config.__init__`, donc **avant**
d'importer l'application. Toute configuration posée dans le `lifespan` gagne, sans le moindre
argument de ligne de commande. Le worker TaskIQ, lui, appelle `basicConfig` avant d'importer le
broker : ses deux commandes portent donc `--no-configure-logging`.

### Colorer selon `stream.isatty()`

La convention habituelle, et elle échoue précisément là où le critère s'observe : la sortie d'un
conteneur est un tube, pas un terminal, et `docker compose logs api` sortirait en noir et blanc. La
couleur suit donc l'environnement, avec un paramètre explicite pour les tests. Le prix est qu'une
sortie de développement redirigée vers un fichier y emporte ses séquences ANSI.

## Conséquences

**Ce que cela donne.** Une ligne par requête portant méthode, chemin, statut et durée, et — sur une
requête authentifiée — les quatre identifiants du contexte sans qu'aucun appelant y pense.
L'identifiant de requête ressort dans l'en-tête `X-Request-ID`, exposé au JavaScript des frontends,
et dans le corps de **toutes** les réponses d'erreur, 500 comprises. La ligne d'accès d'uvicorn
disparaît, et avec elle un vecteur de fuite : elle journalisait le chemin **avec** sa chaîne de
requête, donc un `?token=...` en clair. La dette du `lastResort` est soldée. Et le niveau par statut
offre une propriété gratuite : `LOG_LEVEL=WARNING` en production réduit le journal d'accès aux
seules requêtes en échec.

**Ce que cela coûte.** Deux cent trente lignes à maintenir, dont deux expressions régulières de
masquage qu'il faudra relire le jour où un format de secret changera. Le filet par forme a une
limite connue et consignée — un secret nu dans un message d'exception n'est masquable par aucun
mécanisme fondé sur les noms. Les lignes émises **avant** le `lifespan` gardent le format d'uvicorn :
quelques lignes au démarrage, aucune en régime. Une réponse 500 ne porte pas les en-têtes CORS —
`ServerErrorMiddleware` répond avec le `send` d'origine, hors de toute enveloppe de sortie — et
apparaît donc au navigateur comme une erreur CORS, le corps restant lisible dans l'onglet Réseau.
Enfin, chaque nouveau fournisseur de contexte devra être ajouté aux **deux** points d'entrée du
processus, API et worker.

## Références

- `backend/api/src/app/core/logging.py` — les deux formateurs, le masquage, `configure_logging()`.
- `backend/api/src/app/core/correlation.py` — les trois contextvars de portée requête, la clé de
  `scope` et le nom de l'en-tête.
- `backend/api/src/app/shared/infrastructure/api/middlewares.py` — les deux intergiciels ASGI purs,
  la politique CORS et l'ordre de la pile.
- `backend/api/src/app/shared/infrastructure/tenancy.py` — `current_group_label()`, le pont qui
  évite la copie du groupe actif.
- `backend/api/tests/core/` et `backend/api/tests/shared/test_cors.py` — la preuve des huit critères
  du ticket, et le contre-exemple du masquage.
- [Journalisation](../backend/journalisation.md) — le format, le contexte, la pile et les sondes.
- [ADR-0004](./0004-tenance-par-groupe.md) — la contextvar de tenance que les journaux lisent.
- [ADR-0008](./0008-taskiq-taches-de-fond.md) — la propagation de l'identifiant vers le worker.
- [ADR-0012](./0012-perimetre-de-requete.md) — `X-Clinic-Id`, autorisé par le CORS et journalisé.
- [ADR-0014](./0014-traduction-des-erreurs-a-la-bordure.md) — l'enveloppe d'erreur dont le
  `request_id` cesse d'être `null`.
