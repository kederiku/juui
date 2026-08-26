---
title: ADR-0022 — Un besoin technique partagé par deux modules descend dans shared
description: Le dialogue SMTP devient un port technique de `shared/`, parce que `identity` et `notifications` en ont besoin sans avoir le droit de se connaître.
---

# ADR-0022 — Un besoin technique partagé par deux modules descend dans `shared`

| Statut      | Date       | Tickets                             |
| ----------- | ---------- | ----------------------------------- |
| **Accepté** | 2026-08-26 | BACK-22, BACK-17, BACK-31 (à venir) |

## Contexte

Décision rendue par BACK-22. Sa carte revendique explicitement le code SMTP — « le code de
l'adaptateur SMTP appartient à CE ticket », par opposition à INFRA-07 qui ne fournit que le service
Mailpit. BACK-17 avait écrit cet adaptateur **à titre provisoire** dans `identity`, en le déclarant
dans sa docstring, dans sa page de documentation et au registre des écarts : « à reprendre, le
dialogue SMTP lui-même, qui n'a rien à faire dans identity ».

La reprise s'est heurtée à un mur, et c'est le premier ticket à le rencontrer pour de bon.

**`identity` ne peut pas appeler `notifications`.** Le contrat `module-independence` (BACK-04b)
interdit toute chaîne d'imports entre modules, directe ou indirecte. Or `identity` a besoin
d'envoyer un courriel — le code de vérification d'adresse — et il ne peut pas passer par
`notifications` : un événement de notification voyage par la file, où tout argument reste lisible en
clair dans un stream sans TTL, et un OTP est un secret engendré dans le worker
([ADR-0020](./0020-otp-hache-et-echec-ferme.md)).

Deux modules avaient donc besoin du même dialogue SMTP, et aucun des deux ne pouvait l'emprunter à
l'autre.

## Décision

**Le transport de courriel devient un port technique de `shared/`.** `EmailTransport` vit dans
`shared/domain/ports/email.py`, à côté de `Cache` et de `FileStorage` ; son adaptateur
`SmtpEmailTransport` vit dans `shared/infrastructure/clients/smtp_mailer.py`, à côté de
`RedisCache` et de `S3FileStorage`. Il dit « faire parvenir un texte à une adresse », et rien
d'autre.

**Ce qui reste dans chaque module, c'est la COMPOSITION du message.** `notifications` garde son
adaptateur de canal (`EmailNotificationSender`), ses gabarits et le choix du canal ;
`identity` garde la composition du message de vérification. Aucun des deux ne parle SMTP.

**La règle générale que cette décision énonce** : un besoin **technique** dont deux modules ont
besoin descend dans `shared/domain/ports/`. L'inverse — le laisser chez le premier arrivé — ferait
de lui une dépendance de tous les suivants, ce que la docstring de `shared/domain/ports/` interdit
depuis BACK-04 dans les mêmes termes, pour `Cache`. Ce qui distingue un besoin technique d'un besoin
métier est la question à laquelle il répond : « faire parvenir un texte » est technique, « qui
prévenir, par quel canal » est métier et reste dans `notifications`.

**Auth et TLS restent pilotés par `SmtpSettings`** (`SMTP_*` et `MAIL_FROM`), inchangés depuis
INFRA-07 : aucun changement de code ne sépare Mailpit d'un fournisseur réel.

## Alternatives écartées

### Laisser le dialogue SMTP dans `notifications`, comme la carte le place

C'est la lecture littérale du ticket. Elle oblige `identity` à conserver sa propre copie de
`smtplib` — deux dialogues à maintenir, deux endroits où corriger un défaut de STARTTLS, et l'écart
de BACK-17 qui ne se lève jamais. Écartée : la carte tranche la frontière avec **INFRA-07**, pas
celle avec `identity`, qu'elle n'avait pas de raison d'anticiper.

### Ouvrir une exception `ignore_imports` au contrat d'indépendance

Le `pyproject.toml` prévoit la forme, motif et date de revue compris. Elle rendrait le
rebranchement littéral possible — `identity` appellerait le cas d'usage public de `notifications`.
Écartée pour deux raisons : elle ne résout même pas le problème, l'OTP ne pouvant de toute façon
pas traverser la file ; et elle percerait le contrat qui protège les frontières de modules pour un
besoin qui a une réponse propre.

### Dupliquer le dialogue dans les deux modules

Quarante lignes recopiées, aucune décision à prendre. Écartée : `starttls`, l'authentification
conditionnelle, l'encodage de l'en-tête `To` et le passage par `asyncio.to_thread` sont autant de
détails qui se corrigent une fois ou deux fois.

### Un service `mailer` à part entière, sixième espace du service

Plutôt qu'un port dans `shared/`. Le contrat `service-spaces` est déclaré `exhaustive` : un
cinquième espace à la racine d'`app` doit déclarer sa place dans la hiérarchie. Écartée pour
disproportion — un port et un adaptateur ne sont pas un espace, et `shared/` existe exactement pour
ça.

## Conséquences

Ce que le service gagne : un seul dialogue SMTP, atteignable par les deux modules qui en ont besoin
sans qu'aucun dépende de l'autre ; l'écart de BACK-17 levé ; et une règle écrite pour le prochain
besoin technique partagé — il y en aura d'autres, la génération de PDF en tête.

Ce qu'il paie : le port de `notifications` n'est pas celui que la carte décrivait, et il faut lire
cet ADR pour comprendre pourquoi. Le fichier `smtp_otp_sender.py` d'`identity` a été renommé
`email_otp_sender.py`, puisqu'il ne parle plus SMTP ; `build_otp_sender` garde en revanche son nom
et sa signature — un rebranchement interne n'a pas à se voir de l'extérieur.

Ce qui reste ouvert : la limite de cette décision est le mot **technique**. Un besoin partagé qui
répondrait à une question métier ne descend pas dans `shared/` : il passe par les cas d'usage
publics du module qui le porte, et c'est l'arbitrage déjà rendu pour le compteur d'animaux de
BACK-26. Le jour où deux modules voudront partager autre chose, c'est cette distinction qu'il
faudra trancher, pas la place du fichier.
