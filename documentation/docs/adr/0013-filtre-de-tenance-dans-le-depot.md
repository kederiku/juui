---
title: ADR-0013 — Le filtre de tenance vit dans le dépôt, l'échappatoire se déclare
description: Un dépôt dédié aux agrégats tenant charge puis vérifie le groupe en Python ; le mode « tous groupes » est un geste nommé, porteur de sa raison — et lire partout n'autorise pas à écrire n'importe où.
---

# ADR-0013 — Le filtre de tenance vit dans le dépôt, l'échappatoire se déclare

| Statut      | Date       | Tickets                                                             |
| ----------- | ---------- | ------------------------------------------------------------------- |
| **Accepté** | 2026-08-25 | BACK-06b, BACK-06c (à venir), BACK-25 (à venir), INFRA-08 (à venir) |

## Contexte

Décision rendue par BACK-06b, qui livre le filtre que l'[ADR-0004](./0004-tenance-par-groupe.md)
promettait. Le cadre était posé — filtre applicatif, opt-in par `TenantMixin`, absence de contexte
qui lève — mais trois questions d'implémentation restaient ouvertes, et chacune pouvait défaire la
promesse d'isolation. **Où** le filtre s'applique-t-il, sachant que `session.get()` sert depuis
l'identity map sans émettre de SQL — un `WHERE` n'atteint donc pas toutes les lectures ? **Comment**
les requêtes écrites à la main dans les dépôts concrets — les finders comme `find_by_email` —
restent-elles filtrées ? Et **quelle forme** donner à l'échappatoire légitime — CLI superadmin,
jeu de démonstration (INFRA-08), endpoints d'administration — sans
qu'elle soit déclenchable par accident ou par oubli ?

## Décision

**Le filtre vit dans un dépôt dédié, `TenantSqlAlchemyRepository`, qui charge puis vérifie le
groupe en Python ; l'échappatoire est un bloc `use_all_groups(reason=...)`, porteur d'une raison
obligatoire, qui ouvre les lectures sans jamais autoriser une écriture.**

Concrètement :

- le dépôt d'un agrégat déclarant `TenantMixin` hérite de `TenantSqlAlchemyRepository` ; le dépôt
  générique de BACK-06a reste vierge de tenance, et un dépôt non tenant n'en porte rien —
  l'opt-in de l'ADR-0004 se lit dans la classe mère choisie ;
- les lectures par identifiant **chargent puis vérifient** `group_id` en Python : c'est le seul
  chemin qui couvre l'identity map, et la ligne d'un autre groupe lève l'erreur d'**absence** du
  module — indistincte d'un identifiant inexistant, un 404 et jamais un 403 qui confirmerait que
  la ressource existe ;
- toute requête SELECT d'un dépôt part de `self._select()`, la couture que le dépôt tenant
  surcharge pour poser le `WHERE group_id` — un `from sqlalchemy import select` dans un dépôt
  devient un signal de revue ;
- l'insertion est estampillée par le socle (`require_current_group_id()`), jamais par le mapping
  du module — une garde refuse un `_apply_to_model` qui toucherait `group_id` ;
- le mode « tous groupes » est une valeur explicite (`AllGroups(reason)`) dans la **même**
  contextvar que le groupe actif ; sous ce mode, les lectures voient tout, mais tout geste qui
  exige UN groupe — estampiller une insertion, composer une clé de cache tenant — continue de
  lever : écrire se fait dans un bloc `use_group(group_id)` imbriqué, le patron du seed.

## Alternatives écartées

### Le filtre en événement ORM global (`with_loader_criteria` sur la session)

L'événement `do_orm_execute` aurait ajouté le critère à chaque SELECT, finders compris. Mais il ne
couvre pas l'identity map de `session.get()` — aucun SQL émis, aucun critère appliqué — donc le
chargé-vérifié resterait nécessaire : deux mécanismes au lieu d'un. Il ignore l'erreur d'absence
propre à chaque module, que seul le dépôt connaît. Il serait invisible des doublures en mémoire de
BACK-06c, dont le test de conformité doit reproduire la même tenance. Et il déplacerait le filtre
hors du code que la revue lit — à rebours du choix conscient et visible voulu par l'ADR-0004.

### Le filtre dans la classe de base, conditionné au mixin

Un `if issubclass(..., TenantMixin)` dans le dépôt générique aurait évité la seconde classe. Mais
la tenance aurait alors traversé chaque opération d'un dépôt qui n'en a rien à faire, et le choix
d'un agrégat — tenant ou non — serait devenu invisible : c'est la classe mère qui le dit, en une
ligne, au même endroit que le mixin.

### Un second drapeau de contexte pour l'échappatoire

Une contextvar `bypass_tenant_filter` posée à côté du groupe actif. Deux variables se
désynchronisent : un `use_group` imbriqué devrait savoir éteindre le drapeau, et chaque lecteur
combiner deux états. Une seule valeur à trois formes — `UUID`, `AllGroups`, `None` — rend
l'imbrication correcte par construction (`reset(token)`) et le `match` exhaustif chez tous les
lecteurs.

### `use_group(None)` comme échappatoire

La forme existait déjà, et elle était tentante. Mais `None` est l'état **normal** d'un traitement
non tenant — une inscription, une sonde de santé : en faire aussi le mode « tous groupes »
transformerait chaque oubli de contexte en accès global silencieux, précisément la fuite que le
dispositif rend impossible. Hors contexte, un accès tenant lève ; voir tous les groupes se
déclare, avec sa raison — le pendant du segment `shared` écrit des clés de cache.

## Conséquences

**Ce que cela donne.** L'isolation ne repose plus sur la discipline : hériter du dépôt tenant
suffit, et les cinq opérations comme les finders maison sont filtrés. Le cas le plus risqué — le
remplaçant porteur d'un jeton du groupe A devant une ressource du groupe B — est prouvé par les
tests `tenant_isolation`, écriture croisée comprise. L'échappatoire se voit en revue — un appel,
une raison écrite — et le seed comme les futurs endpoints d'administration ont leur patron : lire
partout sous `use_all_groups`, écrire groupe par groupe sous `use_group`.

**Ce que cela coûte.** Une classe mère de plus à choisir en écrivant un dépôt — se tromper dans
le sens sûr : un modèle sans mixin sous le dépôt tenant échoue au premier usage. La convention
`self._select()` n'est tenue mécaniquement que pour les cinq opérations héritées ; pour un finder
maison, elle repose sur la revue — le filet de fond reste le RLS PostgreSQL, différé par
l'ADR-0004. Et la vérification en Python charge la ligne étrangère avant de la refuser : une
lecture croisée coûte un SELECT, ce qui est le prix de la couverture de l'identity map.

## Références

- `backend/api/src/app/shared/infrastructure/db/repositories/tenant.py` — le dépôt tenant : les
  trois surcharges, et la position ferme sur `with_loader_criteria`.
- `backend/api/src/app/shared/infrastructure/tenancy.py` — `AllGroups`, `use_all_groups` et la
  contextvar à trois états.
- `backend/api/tests/shared/test_tenant_isolation.py` — la preuve : quatorze tests
  `tenant_isolation`, dont le cas du remplaçant.
- [ADR-0004](./0004-tenance-par-groupe.md) — la frontière de tenance et l'opt-in que ce filtre
  applique.
- [ADR-0009](./0009-unite-de-travail-par-module.md) — le dépôt générique que la variante tenant
  complète.
