---
title: Décisions d'architecture (ADR)
description: Registre des décisions structurantes — gabarit commun, vocabulaire des statuts et règle de remplacement.
---

# Décisions d'architecture (ADR)

Un **ADR** — _Architecture Decision Record_ — consigne une décision structurante : son contexte, ce
qui a été décidé, les alternatives écartées, et les conséquences acceptées.

L'objet n'est pas de documenter pour documenter. C'est d'éviter qu'une décision déjà prise soit
rediscutée par accident à chaque ticket, faute de trace de son motif — et de rendre visible ce
qu'elle coûte.

## Comment lire ce registre

**Un gabarit commun.** Chaque ADR ouvre sur un tableau — statut, date de consignation, tickets qui
appliquent la décision — puis déroule les mêmes sections : _Contexte_, _Décision_, _Alternatives
écartées_ (une sous-section par alternative, avec un motif honnête), _Conséquences_ (ce que cela
donne, puis ce que cela coûte — jamais vide), _Références_ (les fichiers du dépôt qui portent la
décision). Les tickets sont cités par leur code ; le détail des cartes vit sur le tableau de
pilotage du projet, qui n'est pas public.

**Trois statuts.** **Accepté** : la décision s'applique. **Remplacé par ADR-XXXX** : une nouvelle
décision a pris sa place. **Déprécié** : la décision ne s'applique plus, sans remplaçante.

**Une décision revisitée ne s'efface pas.** Elle est remplacée par un nouvel ADR — numéro suivant,
jamais réutilisé — dont le contexte ouvre par « Remplace ADR-XXXX » avec le lien. L'ancien ADR ne
subit qu'une seule modification : son statut devient « Remplacé par », avec le lien inverse. Tout
le reste est gelé — l'historique d'une décision vaut souvent autant que la décision elle-même.

## Le registre

| ADR                                                                 | Décision                                                                                  | Statut  |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------- |
| [ADR-0001](./0001-monorepo.md)                                      | Un monorepo pour tout le produit, deux chaînes d'outils                                   | Accepté |
| [ADR-0002](./0002-uv-outillage-python.md)                           | uv comme outillage Python unique, épinglé partout                                         | Accepté |
| [ADR-0003](./0003-monolithe-modulaire.md)                           | Un monolithe modulaire découpé en modules métier                                          | Accepté |
| [ADR-0004](./0004-tenance-par-groupe.md)                            | Le groupe de cliniques est la frontière de tenance                                        | Accepté |
| [ADR-0005](./0005-appartenance-datee.md)                            | L'appartenance à un groupe est une relation N:M datée                                     | Accepté |
| [ADR-0006](./0006-dossier-medical-animal.md)                        | Le dossier médical appartient à l'animal, la détention est datée                          | Accepté |
| [ADR-0007](./0007-client-api-genere-orval.md)                       | Le client d'API des frontends est généré par Orval                                        | Accepté |
| [ADR-0008](./0008-taskiq-taches-de-fond.md)                         | TaskIQ exécute les tâches de fond                                                         | Accepté |
| [ADR-0009](./0009-unite-de-travail-par-module.md)                   | Une unité de travail par module, jamais globale                                           | Accepté |
| [ADR-0010](./0010-migrations-alembic.md)                            | Migrations Alembic pilotées par Settings, un migrateur à la fois                          | Accepté |
| [ADR-0011](./0011-routage-versionne-par-module.md)                  | Un routeur par module, monté sous /api/v1                                                 | Accepté |
| [ADR-0012](./0012-perimetre-de-requete.md)                          | Le groupe actif vit dans le jeton, la clinique dans X-Clinic-Id                           | Accepté |
| [ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md)               | Le filtre de tenance vit dans le dépôt, l'échappatoire se déclare                         | Accepté |
| [ADR-0014](./0014-traduction-des-erreurs-a-la-bordure.md)           | Les erreurs métier se traduisent en HTTP à la bordure, en un format unique                | Accepté |
| [ADR-0015](./0015-cles-etrangeres-frontiere-module.md)              | Les clés étrangères s'arrêtent à la frontière du module                                   | Accepté |
| [ADR-0016](./0016-unicite-email-insensible-casse.md)                | L'unicité d'e-mail tient par un index unique sur lower(email)                             | Accepté |
| [ADR-0017](./0017-pagination-par-offset.md)                         | Les listes se paginent par offset, dans une enveloppe unique                              | Accepté |
| [ADR-0018](./0018-journalisation-bibliotheque-standard.md)          | Les journaux se formatent avec la bibliothèque standard, deux rendus                      | Accepté |
| [ADR-0019](./0019-contrat-openapi-exporte.md)                       | Le contrat OpenAPI est exporté dans un fichier versionné                                  | Accepté |
| [ADR-0020](./0020-otp-hache-et-echec-ferme.md)                      | Un code OTP se hache et se poivre, son magasin échoue fermé                               | Accepté |
| [ADR-0021](./0021-notification-par-evenement.md)                    | Un module émet un événement, notifications choisit le canal                               | Accepté |
| [ADR-0022](./0022-transport-email-partage.md)                       | Un besoin technique partagé par deux modules descend dans `shared`                        | Accepté |
| [ADR-0023](./0023-doublures-en-memoire-et-conformite.md)            | Les doublures en mémoire vivent dans `src`, tenues par un test de conformité              | Accepté |
| [ADR-0024](./0024-jetons-audience-par-application.md)               | Un jeton vise une seule application, son groupe actif est vérifié à l'émission            | Accepté |
| [ADR-0025](./0025-politique-de-mot-de-passe-et-degradation-hibp.md) | Un mot de passe se juge sur sa seule longueur, un contrôle de fuite muet le laisse passer | Accepté |

Les huit premiers ADR ont été rédigés a posteriori (DOC-02b) : les décisions dataient des tickets
cités dans leur contexte, seule leur consignation date d'août 2026. À partir d'ici, un ADR s'écrit
au moment où la décision se prend — l'[ADR-0009](./0009-unite-de-travail-par-module.md),
consigné par BACK-06a en même temps qu'il livrait l'unité de travail, est le premier à suivre la
règle.

Les règles opérationnelles qui découlent de ces décisions — comment structurer un module, écrire
un cas d'usage, déclarer un agrégat tenant — seront reprises dans
[Architecture](../architecture/index.md) (DOC-02a).
