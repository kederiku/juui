---
title: ADR-0006 — Le dossier médical appartient à l'animal, la détention est datée
description: Le dossier suit l'animal lors d'un changement de détenteur ; chaque acte référence la détention en vigueur au moment des faits.
---

# ADR-0006 — Le dossier médical appartient à l'animal, la détention est datée

| Statut      | Date       | Tickets                   |
| ----------- | ---------- | ------------------------- |
| **Accepté** | 2026-08-25 | BACK-19, BACK-20, BACK-30 |

## Contexte

Décision rendue par BACK-19, qui modélise le module `medical_records` — et prise avant toute
donnée réelle, parce que ces frontières sont très coûteuses à déplacer une fois des dossiers
enregistrés. Un animal change de détenteur : vente, adoption, décès du propriétaire. Son
historique médical — vaccins, allergies, pathologies, chirurgies — doit le suivre pour que les
soins continuent. Mais chaque acte passé a été **demandé par quelqu'un**, et ce quelqu'un, ses
coordonnées et ses décisions sont des données personnelles qui n'appartiennent pas au détenteur
suivant.

## Décision

**L'animal est la racine du dossier. La détention est une relation datée** — animal, compte
particulier, début, fin — **plusieurs dans le temps, une seule active. Chaque acte clinique
référence la détention en vigueur au moment des faits**, jamais le propriétaire courant.

La frontière entre ce qui suit l'animal et ce qui reste à la détention est explicite : les faits
cliniques suivent l'animal ; les coordonnées du détenteur, la facturation et les notes de
contexte restent attachées à la détention qui les a produites. Et l'`Animal` ne porte pas le
mixin de tenance : il est créé à l'inscription d'un particulier, avant qu'un groupe existe dans
sa vie — ce sont les actes cliniques, produits par un groupe, qui le portent
([ADR-0004](./0004-tenance-par-groupe.md)). La clinique reste dépositaire des dossiers qu'elle
produit ; le propriétaire a un droit d'accès et de copie, pas la propriété du fichier.

## Alternatives écartées

### Un `proprietaire_id` que l'on écrase

Le modèle que tout le monde écrirait spontanément, et celui qu'il faut regarder en face : au
transfert, on repointe la colonne, et tout semble fonctionner. Sauf qu'une consultation de 2024 a
été demandée par le détenteur de l'époque — repointer la colonne ferait apparaître chez le
nouveau propriétaire des actes qu'il n'a jamais demandés, avec les notes et les décisions de son
prédécesseur. C'est la livraison des données personnelles d'un tiers, indéfendable au regard du
RGPD, et irréversible une fois l'historique réécrit.

### Le dossier rattaché au client

Le modèle d'un logiciel de gestion : le client paie, le dossier est à lui. Juste pour la
facturation, faux pour la médecine — l'historique vaccinal d'un animal ne repart pas à zéro parce
qu'il change de mains, et un praticien qui ne voit que la période du client courant soigne à
l'aveugle.

### Dupliquer le dossier au transfert

Une copie pour l'ancien détenteur, une pour le nouveau : les deux divergent dès la consultation
suivante, et un rappel de vaccin finit calculé sur la mauvaise copie. La duplication répond au
problème de confidentialité en créant un problème de vérité.

## Conséquences

**Ce que cela donne.** La continuité des soins au transfert, par construction. La minimisation
des données aussi : chaque détenteur ne voit que les actes de sa période, sans logique de
filtrage ad hoc. Et le dossier a un identifiant naturel de réconciliation — le numéro de puce —
qui permettra de détecter les doublons entre la fiche créée par le propriétaire et celle créée à
l'accueil d'une clinique, la fusion restant une décision humaine, jamais automatique.

**Ce que cela coûte.** « Les animaux de ce client » devient une jointure sur la détention en
cours, plus une lecture de colonne. La fin d'une détention, son chevauchement éventuel et le
transfert de dossier entre groupes demandent des règles explicites. Et l'expérience utilisateur
doit assumer qu'un ancien détenteur perd l'accès au dossier vivant — c'est une conséquence de la
confidentialité, pas un oubli.

## Références

- `backend/api/src/app/shared/infrastructure/db/mixins.py` — `Animal` comme contre-exemple fondateur
  de la tenance opt-in.
- `backend/api/src/app/shared/infrastructure/clients/storage_keys.py` — les emplacements
  `animal-photos/` et `medical-documents/`, déjà réservés au dossier de l'animal.
