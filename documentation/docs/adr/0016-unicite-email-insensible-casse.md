---
title: ADR-0016 — L'unicité d'e-mail tient par un index unique sur lower(email)
description: Colonne texte inchangée, index fonctionnel unique sur lower(email) posé par migration, normalisation applicative conservée — citext écarté.
---

# ADR-0016 — L'unicité d'e-mail tient par un index unique sur lower(email)

| Statut      | Date       | Tickets  |
| ----------- | ---------- | -------- |
| **Accepté** | 2026-08-26 | INFRA-09 |

## Contexte

La règle « un même e-mail ne peut pas créer deux comptes » doit tenir même quand `Veto@x.fr` et
`veto@x.fr` se présentent comme deux adresses. Or l'index unique posé par BACK-04 sur la colonne
`email` est sensible à la casse : il laisse passer ce doublon sans rien signaler. La normalisation
du domaine (`normalize_email`, appelée par la fabrique de l'entité) tenait la promesse seule —
mais une règle que seul le code applique cède devant tout chemin qui le contourne : une session
`psql`, un seed (INFRA-08), une migration de données. Le rattrapage après coup imposerait un
dédoublonnage manuel avec arbitrage humain sur chaque paire. INFRA-09 demandait de trancher entre
les deux façons de rendre la garantie physique : le type `citext` ou un index fonctionnel sur
`lower(email)`.

## Décision

**La colonne reste un `String(320)` ordinaire ; l'unicité est portée par un index unique sur
l'expression `lower(email)`.** L'index `ix_accounts_email_lower` remplace `ix_accounts_email` —
le garder aurait entretenu deux index sur la même colonne pour une garantie que le nouveau
subsume : tout doublon exact est aussi un doublon de casse.

**L'index vit dans le modèle ET dans une migration du module identity, jamais dans le script
d'init.** C'est une règle applicative, pas une propriété de l'instance PostgreSQL. La déclaration
dans `__table_args__` n'est pas une redondance : les tests d'intégration créent leurs tables par
`Base.metadata.create_all` (BACK-06b), et un index absent du modèle serait invisible de la seule
suite qui prouve la contrainte. Son nom est écrit à la main — la seule entorse à la convention de
nommage figée, qui compose les noms à partir de colonnes et ne sait rien nommer d'une expression.

**La normalisation applicative demeure, et reste première.** Un index refuse, il ne normalise
pas : l'utilisateur qui saisit `Jean@Exemple.fr` attend un compte, pas un conflit. Le domaine
continue d'écrire la forme canonique (`normalize_email`), la base ne fait que rendre le doublon
impossible pour les chemins qui ne passent pas par lui.

**Toute égalité sur l'adresse s'écrit désormais `lower(email)`.** `find_by_email` compare
`lower(email) = :adresse` : c'est la seule forme que l'index fonctionnel sait servir — une
égalité sur la colonne nue repartirait en parcours de table depuis la suppression de l'ancien
index.

## Alternatives écartées

### Le type `citext`

Une colonne `citext` rend toutes les comparaisons insensibles à la casse sans réécrire une seule
requête. Mais elle exige une extension — donc une dépendance d'instance pour une règle de
module — et son comportement est un implicite que chaque pilote, chaque outil d'inspection et
chaque lecteur de schéma doit connaître pour prédire un `WHERE`. Surtout, `citext` _masque_ la
casse au lieu d'imposer une forme canonique : la base stockerait `Veto@x.fr` tel quel et
comparerait en douce, là où le domaine normalise déjà à l'écriture — la base n'a qu'à refuser ce
qui lui échappe. Le typage de longueur y passait aussi : `citext` ne porte pas de borne, et le
`String(320)` de la RFC 5321 aurait dû renaître en contrainte `CHECK`.

### Le statu quo : la normalisation applicative seule

Zéro migration, zéro index de plus. Mais c'est précisément la situation que le ticket corrige :
une invariante que seul le code tient n'existe pas pour les écritures qui le contournent, et le
module identity n'a pas de seconde ceinture — là où la tenance, elle, attend la RLS
(ADR-0004). À l'intérieur d'un module, la base est le seul acteur qui voie toutes les écritures
(ADR-0015) ; c'est à elle de porter l'invariant.

### Une colonne générée `email_lower`

Une colonne `GENERATED ALWAYS AS (lower(email)) STORED` avec un index unique classique dessus —
lisible, et la convention de nommage aurait su la nommer. Mais elle double le stockage de chaque
adresse, apparaît dans tout `SELECT *` et dans chaque mapping, et n'apporte rien que l'index
fonctionnel n'offre déjà : PostgreSQL sait indexer une expression nativement.

## Conséquences

**Ce que cela donne.** Le critère du ticket est physiquement inviolable, prouvé par un test
d'`IntegrityError` — même patron que la détention unique de BACK-19. Aucune extension requise :
`lower()` est natif, l'index fonctionne sur n'importe quel PostgreSQL. La forme stockée reste la
forme canonique du domaine : ce qu'on lit en base est ce que le domaine a écrit, sans comparaison
implicite.

**Ce que cela coûte.** Un nom d'index à la main, que la relecture de migration doit vérifier sans
le secours d'`op.f()`. Toute future requête d'égalité sur l'adresse doit s'écrire `lower(email)`
pour rester indexée — une convention à connaître, consignée ici et dans le dépôt. Et la migration
touche un index existant : le `downgrade` restaure l'ancien, mais pas les casses que l'`UPDATE`
défensif de l'`upgrade` aurait aplaties.

## Références

- `backend/api/src/app/modules/identity/infrastructure/db/models.py` — l'index dans
  `__table_args__`, avec le motif du nom manuel sur place.
- `backend/api/alembic/versions/20260826_91eefe8e775b_unicite_email_insensible_a_la_casse.py` —
  le remplacement d'index et la normalisation défensive des lignes préexistantes.
- `backend/api/src/app/modules/identity/infrastructure/db/repositories.py` — `find_by_email`
  aligné sur la forme indexée.
- `backend/api/src/app/modules/identity/domain/policies.py` — `normalize_email`, la moitié
  applicative de la garantie.
- `backend/api/tests/modules/identity/infrastructure/test_ports.py` — la preuve par `IntegrityError` que le
  doublon de casse ne s'insère pas.
- `docker/postgres/init/02-enable-extensions.sh` — les extensions du même ticket (`pg_trgm`,
  `unaccent`), qui n'interviennent pas dans cette décision : `lower()` est natif.
