---
title: ADR-0021 — Un module émet un événement, notifications choisit le canal
description: Le canal n'appartient pas à l'émetteur ; les préférences se règlent par type d'événement, et un message transactionnel ne se désactive pas.
---

# ADR-0021 — Un module émet un événement, notifications choisit le canal

| Statut      | Date       | Tickets                                        |
| ----------- | ---------- | ---------------------------------------------- |
| **Accepté** | 2026-08-26 | BACK-22, BACK-31 (à venir), FRONT-11 (à venir) |

## Contexte

Décision rendue par BACK-22, qui pose le module `notifications`. Le cahier des charges décrit,
dans les trois espaces personnels, un réglage « e-mail, SMS mobile, SMS ou combinaison ». Trois
questions se cachent derrière cette phrase, et chacune avait une réponse « évidente » qui ne
tenait pas à l'examen.

**Qui choisit le canal ?** La lecture naturelle donne un paramètre à l'appel : `envoyer_email(...)`,
`envoyer_sms(...)`. Elle place la décision chez l'émetteur — c'est-à-dire chez cinq modules
différents, dont aucun n'a de raison de connaître les préférences d'un compte. Le premier qui
oublierait de les lire enverrait un e-mail à quelqu'un qui avait demandé un SMS, et personne ne
s'en apercevrait.

**Que règle-t-on, au juste ?** Un booléen « je veux être notifié » se code en dix minutes. Il ne
couvre pas le besoin réel, que la carte du ticket nomme littéralement : « rappels de rendez-vous
par SMS mais actualités par e-mail ». Un interrupteur unique force à choisir entre tout recevoir
sur le mauvais canal et ne rien recevoir du tout.

**Peut-on tout couper ?** Si les préférences valent pour tous les messages, un utilisateur peut
désactiver la réinitialisation de son propre mot de passe — et découvrir, le jour où il l'oublie,
qu'il s'est enfermé dehors. Un rendez-vous annulé sans notification, c'est un client qui se
déplace pour rien.

## Décision

**Un module appelant émet un ÉVÉNEMENT.** L'API du module est un
[`NotificationDispatcher`](../backend/notifications.md) dont la méthode ne porte aucun paramètre de
canal, et n'en portera pas : `dispatch(account_id, event, recipient, recipient_name, payload)`.
Le catalogue d'événements est **fermé** et vit dans le domaine de `notifications`.

**Le canal se décide à la remise, une seule fois, pour tous les modules.** Le cas d'usage
`DeliverNotification` lit les préférences du compte, en déduit les canaux, rend le message depuis
le gabarit de l'événement, et le confie aux adaptateurs concernés. Le port d'envoi est **unique**
(`NotificationSender`), avec une implémentation par canal, chacune annonçant le canal qu'elle
dessert — ce qui remplace la cascade de conditions par une indexation.

**Les préférences se règlent PAR TYPE D'ÉVÉNEMENT**, jamais globalement. L'agrégat ne stocke que
les **écarts** au défaut : un compte neuf n'a aucune ligne, et un événement absent du document
signifie « ce compte n'a rien dit » — distinct d'un ensemble vide, qui signifie « ce compte a
désactivé cet événement ». Les confondre réactiverait en silence ce qu'un utilisateur vient de
couper.

**Un événement TRANSACTIONNEL ignore les préférences.** La classification vit dans le catalogue,
pas dans un réglage : l'agrégat **refuse** qu'on configure un événement transactionnel, et la
résolution des canaux ne regarde même pas ce qui aurait été enregistré pour lui. Sont
transactionnels aujourd'hui la réinitialisation de mot de passe et l'annulation de rendez-vous ;
sont optionnels la confirmation et le rappel de rendez-vous, et les actualités.

**Le destinataire voyage avec l'événement.** `notifications` ne lit pas l'adresse dans `identity` :
le contrat `module-independence` le lui interdit, et une seconde copie des coordonnées serait une
donnée personnelle de plus à tenir à jour. L'émetteur, qui la détient déjà, la fournit.

**Tout passe par une tâche de fond** (BACK-15), jamais par le fil d'une requête HTTP. C'est la
raison d'être du port de dispatch : sans lui, un émetteur devrait importer `infrastructure/tasks/`,
ce que le contrat `module-layers` refuse — et le premier qui appellerait l'envoi directement
remettrait le SMTP dans le fil d'une requête.

## Alternatives écartées

### Un paramètre `channel` à l'appel

C'est la forme que prendrait n'importe quelle bibliothèque d'envoi. Elle place la décision chez
l'émetteur, donc la duplique autant de fois qu'il y a de modules, et rend les préférences
facultatives dans les faits — elles ne s'appliquent qu'à qui pense à les lire. Écartée : c'est
exactement la dette que ce module existe pour éviter.

### Un booléen `notifications_enabled` sur le compte

Une colonne, aucun module, aucune table. Elle ne couvre pas le besoin nommé par le cahier des
charges, et surtout elle ne survit pas au premier ajout : dès qu'un second type de message existe,
il faut ou bien un second booléen — et l'on recommence à chaque événement — ou bien la
modélisation retenue ici.

### Des préférences complètes, une ligne par événement et par compte

Plutôt que les seuls écarts. Elle oblige à semer les lignes à l'inscription — un module qui écrit
dans sa table à chaque création de compte chez un autre module — et fige les défauts : les changer
demanderait une migration de données sur tous les comptes. Écartée : l'écart est plus petit, plus
sûr, et se laisse relire.

### Laisser l'émetteur désactivable pour tout, transactionnel compris

« L'utilisateur est maître de ce qu'il reçoit » se défend. Il l'est pour ce qui est du confort ; il
ne l'est pas pour ce qui conditionne l'usage de son compte. Écartée, avec une nuance qui compte :
le refus est **explicite** plutôt que silencieux — accepter le réglage puis l'ignorer laisserait
croire à l'utilisateur qu'il a coupé un message qu'il continuera de recevoir, ce qui est pire qu'un
refus franc.

### Faire passer le code de vérification d'adresse par ce module

La carte du ticket le cite en exemple de message transactionnel, et BACK-17 annonçait s'y
rebrancher. Impossible : un événement de notification voyage par la file, où tout argument reste
lisible en clair dans un stream sans TTL, et un OTP est un secret engendré dans le worker
([ADR-0020](./0020-otp-hache-et-echec-ferme.md)). Ce que BACK-22 lui a repris est le **transport**
([ADR-0022](./0022-transport-email-partage.md)), pas le parcours. La règle qu'il illustre reste
celle-ci : son expéditeur ne consulte aucune préférence.

## Conséquences

Ce que le service gagne : une seule implémentation de la logique de canal, des préférences qui
s'appliquent partout sans que personne ait à y penser, et l'impossibilité structurelle de couper un
message dont dépend l'usage du compte.

Ce qu'il paie : un port de dispatch de plus, un catalogue fermé qu'il faut étendre en code — une
livraison, pas une migration — et l'obligation, pour chaque émetteur, de fournir le destinataire et
les variables du gabarit. Ce dernier point est vérifié au rendu, qui nomme l'événement et les
variables manquantes plutôt que de laisser filer un `KeyError`.

Ce qui reste ouvert : les canaux SMS et push sont **structurés mais muets** — aucun fournisseur
n'est engagé, la portée du ticket l'écarte. Le jour où l'un remettra vraiment, une notification ne
s'adresse plus à une personne mais à une coordonnée de canal : `NotificationRequest` gagnera de quoi
la porter, et le push demandera en plus un registre de jetons d'appareil. Et l'écriture des
préférences depuis l'espace personnel attend `get_current_active_account` (BACK-10c) et la surface
de composition de BACK-23.
