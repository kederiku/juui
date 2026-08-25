---
title: ADR-0005 — L'appartenance à un groupe est une relation N:M datée
description: Un compte n'a pas de groupe ; il a des appartenances datées — le cas du vétérinaire remplaçant l'impose dès le premier jour.
---

# ADR-0005 — L'appartenance à un groupe est une relation N:M datée

| Statut      | Date       | Tickets                     |
| ----------- | ---------- | --------------------------- |
| **Accepté** | 2026-08-25 | BACK-16, BACK-10e, FRONT-08 |

## Contexte

Décision rendue par BACK-16, qui modélise le module `organization`. Le cas métier central est le
**vétérinaire remplaçant** : une personne, un compte, plusieurs groupes au fil des mois — parfois
le même deux fois. Et la question d'audit est temporelle : « où travaillait-il au moment des
faits ? », pas seulement « où travaille-t-il aujourd'hui ? ». Un modèle qui attache le compte à
une structure interdit ce métier dès le premier jour.

## Décision

**L'appartenance d'un compte à un groupe est une relation N:M datée** — compte, groupe, rôle de
périmètre groupe, début, fin — **et le compte ne porte aucun `group_id`.** Une seconde relation
datée, l'affectation, rattache le compte aux cliniques d'un groupe où il a une appartenance
active ; elle relève du périmètre de travail, pas de la sécurité
([ADR-0004](./0004-tenance-par-groupe.md)).

Le **groupe actif** d'une session n'est pas un état stocké : c'est un claim du jeton. Basculer de
groupe est une **réémission de jeton** — vérification de l'appartenance active, révocation de
l'ancien jeton, émission du nouveau — jamais un simple changement d'état côté client. Un compte
mono-appartenance, le cas de l'immense majorité des utilisateurs, reçoit son jeton complet
directement, sans écran de sélection.

## Alternatives écartées

### Un `group_id` immuable sur le compte

Le modèle par défaut de la plupart des SaaS B2B, et le plus simple à écrire. Il imposerait au
remplaçant un compte par structure — mots de passe et double authentification dupliqués — et
fusionner des comptes a posteriori est un chantier connu pour mal finir. Le contre-exemple est
gravé dans le socle de persistance : c'est l'une des deux exceptions qui justifient le filtre de
tenance opt-in.

### Une relation N:M sans dates

Elle répond à « où travaille-t-il », jamais à « où travaillait-il » : supprimer la ligne au
départ du vétérinaire efface l'historique dont l'audit a besoin. Dater la relation permet de la
clore sans la détruire — le même motif que la détention de
[l'ADR-0006](./0006-dossier-medical-animal.md).

### Le groupe « courant » stocké en base

De l'état de session déguisé en donnée : incohérent entre deux appareils ouverts en même temps,
et une écriture par bascule. Le jeton porte déjà un contexte signé, daté et révocable — c'est
exactement sa fonction.

## Conséquences

**Ce que cela donne.** Le remplacement est modélisé nativement, sans cas particulier. L'audit
temporel est une requête, pas une archéologie. Et l'isolation devient testable sur le cas le plus
risqué : un compte ayant deux appartenances légitimes, un jeton émis pour le groupe A, une
ressource du groupe B — réponse 404.

**Ce que cela coûte.** Tout contrôle d'accès vérifie l'appartenance **active à la date**, pas la
seule existence d'une ligne. La bascule impose une réémission de jeton et, côté client, un vidage
complet du cache de requêtes — une invalidation partielle laisserait passer des données de
l'ancien groupe. Enfin, des appartenances qui se chevauchent sont possibles par construction :
c'est voulu, mais chaque requête doit le savoir.

## Références

- `backend/api/src/app/modules/identity/domain/entities.py` — le compte sans `group_id`, et le
  motif écrit sur place.
- `backend/api/src/app/modules/organization/__init__.py` — les entités et les trois ports annoncés
  du module.
- `backend/api/src/app/shared/infrastructure/db/mixins.py` — le contre-exemple du compte dans la
  règle d'opt-in.
