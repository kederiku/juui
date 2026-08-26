---
title: ADR-0012 — Le groupe actif vit dans le jeton, la clinique active dans l'en-tête
description: Le claim active_group_id porte la frontière d'isolation, signée et révocable ; X-Clinic-Id ne désigne qu'un périmètre de travail par requête — jamais une autorisation.
---

# ADR-0012 — Le groupe actif vit dans le jeton, la clinique active dans l'en-tête

| Statut      | Date       | Tickets                                                             |
| ----------- | ---------- | ------------------------------------------------------------------- |
| **Accepté** | 2026-08-25 | BACK-08, BACK-10c (à venir), BACK-10e (à venir), FRONT-08 (à venir) |

## Contexte

Décision rendue par BACK-08, avant qu'aucune route authentifiée n'existe — comme
l'[ADR-0007](./0007-client-api-genere-orval.md) avait consigné le choix d'Orval avant SHARED-03 :
la convention précède son code, parce que BACK-10c, BACK-10e et FRONT-08 vont construire dessus
et qu'un désaccord découvert là se paierait en refonte d'authentification.

L'[ADR-0004](./0004-tenance-par-groupe.md) sépare deux notions emboîtées : le **groupe** de
cliniques est la frontière d'isolation — ce qu'un utilisateur ne doit jamais traverser —, la
**clinique** n'est qu'un périmètre de travail à l'intérieur d'un tenant déjà autorisé. Restait à
fixer **où chacune voyage dans une requête HTTP** : dans le jeton, dans un en-tête, dans l'URL ?
La question est structurante parce que les deux réponses symétriques sont toutes deux fausses,
et chacune d'une façon différente.

## Décision

**Le groupe actif est un claim du jeton (`active_group_id`) ; la clinique active est un en-tête
de requête (`X-Clinic-Id`), et l'en-tête n'autorise rien.**

Concrètement :

- le claim `active_group_id` est posé à l'émission du jeton, signé, révocable, revérifié côté
  serveur ; **changer de groupe est une réémission de jeton**
  ([ADR-0005](./0005-appartenance-datee.md), BACK-10e), jamais un état côté client — c'est le
  geste de sécurité qui accompagne le franchissement de la frontière d'isolation ;
- la clinique active se transmet **par requête**, dans l'en-tête `X-Clinic-Id` ; le serveur
  vérifie qu'elle appartient au groupe du jeton (la dépendance de BACK-10c) — l'en-tête
  sélectionne un périmètre de travail parmi ceux déjà autorisés, il n'ouvre aucun droit ;
- jusqu'à BACK-10c, ni le claim ni l'en-tête n'existent dans le code : le présent ADR est la
  convention que ces tickets appliqueront, et c'est la revue qui la tient d'ici là.

## Alternatives écartées

### La clinique dans le jeton

Un vétérinaire passe d'une clinique à l'autre de son groupe plusieurs fois par jour. Chaque
bascule exigerait une réémission de jeton — le geste que l'[ADR-0005](./0005-appartenance-datee.md)
réserve au franchissement de la frontière d'isolation, appliqué à un simple changement de
périmètre de travail. Et un jeton mono-clinique interdirait deux onglets ouverts sur deux
cliniques du même groupe, cas quotidien d'un gérant.

### Le groupe dans un en-tête

L'erreur symétrique : la frontière d'isolation reposerait sur une valeur que le client écrit à
chaque requête. La signature du jeton est précisément ce qui rend le claim de groupe digne de
confiance — un en-tête n'est qu'une déclaration, et une déclaration ne délimite pas un tenant.

### La clinique dans l'URL

`/api/v1/clinics/{clinic_id}/...` tresserait le périmètre de travail dans chaque chemin — donc
dans tout le client généré ([ADR-0011](./0011-routage-versionne-par-module.md)) — et les
ressources de niveau groupe n'entreraient pas dans la hiérarchie. Un périmètre transversal
voyage en en-tête ; une URL désigne une ressource.

### La clinique « courante » stockée en base

Le motif déjà retenu contre le « groupe courant » dans l'[ADR-0005](./0005-appartenance-datee.md) :
de l'état de session déguisé en donnée. Deux appareils ouverts divergeraient silencieusement —
la consultation saisie sur l'un s'enregistrerait dans la clinique choisie sur l'autre.

## Conséquences

**Ce que cela donne.** La bascule de clinique est instantanée et locale au client : aucun
aller-retour d'authentification, deux onglets sur deux cliniques fonctionnent. La frontière
d'isolation reste unique, signée, testable en un point — la dépendance d'authentification de
BACK-10c. Et la règle se dit en une phrase : le jeton dit **qui tu es et chez qui**, l'en-tête
dit **où tu travailles en ce moment**.

**Ce que cela coûte.** Chaque route à périmètre clinique devra lire l'en-tête et vérifier son
appartenance au groupe du jeton — un oubli de vérification ferait de `X-Clinic-Id` une
autorisation de fait, c'est LE point de vigilance de BACK-10c. L'intercepteur HTTP des frontends
devra propager l'en-tête (SHARED-03, FRONT-08) ; le CORS l'autorise et les journaux portent
`clinic_id` depuis BACK-11. Enfin, tant que BACK-10c n'est pas livré, la convention n'est
tenue que par ce document.

## Références

- `backend/api/src/app/shared/infrastructure/tenancy.py` — la contextvar du groupe actif, que le
  claim alimentera.
- `backend/api/src/app/shared/infrastructure/api/__init__.py` — le socle HTTP, qui renvoie déjà
  le contexte de tenance à BACK-10c.
- [ADR-0004](./0004-tenance-par-groupe.md) — la frontière que le claim transporte.
- [ADR-0005](./0005-appartenance-datee.md) — la bascule de groupe comme réémission de jeton.
