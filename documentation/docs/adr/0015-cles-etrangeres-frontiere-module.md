---
title: ADR-0015 — Les clés étrangères s'arrêtent à la frontière du module
description: FK obligatoires à l'intérieur d'un module, posées par consentement sur la colonne de tenance, jamais d'un module vers un autre.
---

# ADR-0015 — Les clés étrangères s'arrêtent à la frontière du module

| Statut      | Date       | Tickets |
| ----------- | ---------- | ------- |
| **Accepté** | 2026-08-25 | BACK-16 |

## Contexte

Décision rendue par BACK-16, le premier ticket à faire coexister plusieurs modules avec des tables
dans la même base. Trois questions se posaient d'un coup : `TenantMixin` portait une dette nommée —
« pas de clé étrangère vers `groups` tant que la table n'existe pas » — qu'il fallait lever ;
l'invariant du ticket — une affectation ne vise que les cliniques de son groupe — pouvait tenir par
la base ou par le seul code ; et les tables d'`organization` référencent des comptes, qui
appartiennent au module `identity`. Or [ADR-0003](./0003-monolithe-modulaire.md) pose que les
modules ne partagent ni leurs tables ni leur intérieur : restait à dire ce que cette frontière
signifie pour le **schéma**, là où les contrats import-linter ne voient rien — une `ForeignKey`
se déclare par une chaîne de caractères, pas par un import.

## Décision

**À l'intérieur d'un module, les clés étrangères sont obligatoires.** `clinics.group_id` et
`memberships.group_id` référencent `groups.id` ; une table qui référence une autre table de son
propre module le déclare, toujours.

**La colonne de tenance obtient sa clé par consentement, table par table.** `TenantMixin` ne
portera jamais de `ForeignKey` : une contrainte partant de `shared/` vers une table
d'`organization` rendrait tous les modules structurellement dépendants de celui-là. Chaque modèle
adoptant le mixin déclare — ou non — la contrainte dans son propre `__table_args__` :

```python
__table_args__ = (ForeignKeyConstraint(["group_id"], ["groups.id"]), ...)
```

**Un invariant inter-tables du même module peut monter d'un cran, en clé composite.**
`assignments (clinic_id, group_id)` référence `clinics (id, group_id)`, adossée à une contrainte
d'unicité redondante avec la clé primaire (`uq_clinics_id_group_id`) qui n'existe que pour cela.
Une affectation dont la clinique n'appartient pas à son groupe est ainsi **impossible à insérer** —
la moitié structurelle de la règle du ticket tient par la base, sa moitié temporelle (appartenance
_active_) restant au domaine, seule à savoir lire une fenêtre de dates.

**Jamais de clé étrangère d'un module vers un autre.** `memberships.account_id` et
`assignments.account_id` restent des UUID nus : la table `accounts` appartient à `identity`.
L'intégrité est applicative — les identifiants de compte arrivent par les jetons et les cas
d'usage d'`identity`, jamais d'une saisie libre.

## Alternatives écartées

### La clé étrangère vers `groups` dans `TenantMixin`

Une ligne dans `shared/`, et tous les agrégats tenant couverts d'un coup. Mais déclarée avant que
`groups` existe, elle cassait `metadata.sorted_tables` — donc l'autogénération Alembic de tout le
projet — et surtout elle inverserait le sens des dépendances : le socle partagé exigerait une table
d'un module métier, et aucun module ne pourrait plus exister sans `organization`. Le mixin reste
neutre ; le consentement se lit table par table, en revue.

### Une clé étrangère vers `accounts`

Elle offrirait la garantie référentielle complète, et PostgreSQL sait la faire. Mais elle
soude les schémas des deux modules : `identity` ne pourrait plus toucher sa table sans l'accord
d'`organization`, une extraction future du module deviendrait une migration de données au lieu
d'un déplacement de code, et les tests de l'un devraient créer les tables de l'autre. C'est le
`JOIN` inter-modules d'ADR-0003, en version DDL.

### Aucune clé étrangère du tout, l'intégrité par le code seul

La cohérence viendrait des dépôts et des règles de domaine, comme la tenance vient du filtre.
Mais le filtre de tenance a une seconde ceinture prévue (RLS, différée par
[ADR-0004](./0004-tenance-par-groupe.md)) ; une référence pendante n'en aurait aucune, et un seed,
une migration de données ou une session `psql` peuvent contourner tous les dépôts du monde. À
l'intérieur d'un module, la base est le seul acteur qui voie toutes les écritures.

## Conséquences

**Ce que cela donne.** L'invariant central de BACK-16 est physiquement inviolable, prouvé par un
test d'`IntegrityError`. La frontière des modules se lit dans le schéma comme dans les imports :
une clé étrangère qui traverse est un signal de revue immédiat. Et chaque module reste extractible —
ses tables ne retiennent personne.

**Ce que cela coûte.** Des orphelins inter-modules sont possibles : un compte supprimé ne
cascaderait pas sur ses appartenances — la suppression de comptes, quand elle existera, devra
orchestrer les deux modules par leurs cas d'usage. La contrainte d'unicité `uq_clinics_id_group_id`
est un index de plus, entretenu à chaque écriture de `clinics`, qui n'existe que pour porter la clé
composite. Et le consentement table par table est une décision répétée : chaque nouvel agrégat
tenant devra choisir, et dire pourquoi.

## Références

- `backend/api/src/app/modules/organization/infrastructure/db/models.py` — les quatre tables, la
  clé composite et les identifiants de compte nus, avec leurs motifs sur place.
- `backend/api/src/app/shared/infrastructure/db/mixins.py` — le mixin définitivement sans clé
  étrangère, et le geste de consentement documenté.
- `backend/api/tests/modules/organization/test_ports.py` — la preuve par `IntegrityError` que la
  clinique hors groupe ne s'insère pas.
