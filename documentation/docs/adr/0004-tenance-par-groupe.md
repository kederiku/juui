---
title: ADR-0004 — Le groupe de cliniques est la frontière de tenance
description: L'isolation entre structures passe par le groupe, avec un filtre applicatif opt-in ; le RLS PostgreSQL est différé, pas écarté.
---

# ADR-0004 — Le groupe de cliniques est la frontière de tenance

| Statut      | Date       | Tickets                              |
| ----------- | ---------- | ------------------------------------ |
| **Accepté** | 2026-08-25 | BACK-05, BACK-06b, BACK-16, INFRA-08 |

## Contexte

Décision rendue par BACK-05, qui pose le socle de persistance, et précisée par BACK-06b et
BACK-16. Le SaaS est multi-tenant et héberge des données médicales de structures potentiellement
concurrentes : une fuite entre tenants n'est pas un bug, c'est une faute. Mais quel est le tenant ?
Un vétérinaire remplaçant travaille dans plusieurs cliniques d'un même groupe au fil de la
journée, et un dossier circule légitimement entre les cliniques d'un groupe. « Quel groupe
regarde-t-on ? » n'est pas une propriété du code appelé — c'est une propriété de l'appel.

## Décision

**Le groupe de cliniques est la frontière d'isolation. La clinique n'est qu'un périmètre de
travail, jamais une frontière de sécurité.** Une clinique qui travaille seule est simplement un
groupe d'une clinique.

Le filtre de tenance est **applicatif et opt-in** : un agrégat déclare `TenantMixin` s'il est
produit par un groupe et conservé sous sa garde — et lui seul sera filtré. Les deux
contre-exemples valent règle : une `Consultation` porte le mixin, un `Animal` non — il est créé à
l'inscription d'un particulier, avant qu'un groupe existe dans sa vie
([ADR-0006](./0006-dossier-medical-animal.md)) ; le compte non plus, son appartenance étant une
relation datée ([ADR-0005](./0005-appartenance-datee.md)). Le mixin est armé : sa garde
`__init_subclass__` refuse à l'import toute table de tenance dépourvue d'index préfixé par
`group_id`.

Le groupe actif du traitement vit dans une variable de contexte, `current_group_id`, lue par la
persistance comme par les clés de cache. L'absence de contexte là où un groupe est requis
**lève** (`MissingTenantContextError`) au lieu de dégrader : se rabattre en silence sur « pas de
groupe » produirait précisément la fuite que le dispositif cherche à rendre impossible.

## Alternatives écartées

### La clinique comme frontière

Le remplaçant et le dossier la traversent légitimement. En faire une frontière de sécurité
obligerait à des mécanismes de partage permanents entre cliniques d'un même groupe — qui la
videraient de sens tout en compliquant chaque requête.

### Une base ou un schéma PostgreSQL par tenant

L'isolation la plus forte sur le papier. Mais chaque migration se rejouerait par groupe, la
création d'un tenant deviendrait une opération d'infrastructure, et l'exploitation — sauvegardes,
métriques, montées de version — serait multipliée d'autant. Disproportionné au stade du projet.

### Le mixin obligatoire sur tous les modèles

Un filtre global appliqué d'office dans le dépôt de base semblerait plus sûr. Il mentirait pour
`Animal` et pour le compte, dont l'appartenance passe par une relation datée et non par une
colonne — et il transformerait chaque cas légitime hors groupe en contournement silencieux, là où
l'opt-in en fait un choix conscient, visible en revue.

### Le RLS PostgreSQL — différé, pas écarté

Une deuxième ceinture au niveau de la base resterait souhaitable : elle protégerait même d'un
bug applicatif. Elle exige de propager le groupe actif jusqu'à la session SQL, et son coût
d'exploitation n'est pas nul. La décision est explicitement **à trancher plus tard** ; si elle
est adoptée, ce sera par un nouvel ADR qui complétera celui-ci sans le remplacer.

## Conséquences

**Ce que cela donne.** Une seule base et un seul schéma à exploiter. Les clés de cache sont
cloisonnées par groupe. Une erreur de câblage éclate bruyamment au lieu de fuiter des données
entre structures — et le cas le plus risqué, le remplaçant porteur d'un jeton du groupe A devant
une ressource du groupe B, devient testable.

**Ce que cela coûte.** Tant que le RLS n'est pas tranché, la sécurité de tenance repose sur la
seule application : c'est une dette explicite. Chaque nouvel agrégat exige un choix conscient —
mixin ou pas — en revue de code. Le filtre SQLAlchemy lui-même a été livré par BACK-06b, avec sa
propre décision ([ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md)) ; reste le piège documenté
dans `tenancy.py` pour BACK-10c : l'intergiciel qui alimente la variable de
contexte ne peut pas être un `BaseHTTPMiddleware`. Enfin, `group_id` ne porte pas encore de clé
étrangère vers la table des groupes — elle n'existera qu'avec BACK-16, qui posera la contrainte
table par table ; en attendant, l'intégrité tient par le filtre, pas par la base.

## Références

- `backend/api/src/app/shared/infrastructure/db/mixins.py` — `TenantMixin`, sa garde et la dette
  de clé étrangère, nommée.
- `backend/api/src/app/shared/infrastructure/tenancy.py` — la variable de contexte, l'erreur qui
  lève, et le piège de l'intergiciel.
- `backend/api/src/app/shared/infrastructure/clients/cache_keys.py` — le groupe actif dans les
  clés de cache.
