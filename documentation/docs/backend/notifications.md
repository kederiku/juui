---
title: Notifications
description: "Un module émet un événement, notifications choisit le canal : préférences par type d'événement, transactionnel non désactivable, envoi toujours en tâche de fond."
---

# Notifications

Le module `notifications` répond à **« qui prévenir, par quel canal »**. Sa règle tient en une
phrase, et c'est elle qui explique tout le reste : **un module appelant émet un événement, il ne
choisit jamais de canal**. Le canal se décide ici, une seule fois pour tous les modules, à partir
des préférences du compte.

Sans cette règle, chaque module réimplémenterait sa propre logique de canal, et les préférences ne
vaudraient que pour celui qui aurait pensé à les lire. L'argumentaire est
l'[ADR-0021](../adr/0021-notification-par-evenement.md).

## Le parcours

```
émetteur (n'importe quel module)             worker TaskIQ
  NotificationDispatcher.dispatch(             notifications.delivery.deliver
      account_id, event,                         └─ DeliverNotification
      recipient, recipient_name,                      1. lit les préférences du compte
      payload, group_id)                              2. resolve_channels(event, choix)
        │                                             3. render(event, payload)
        └──────────── file (base 1) ─────────►        4. NotificationSender par canal
                                                      5. journal d'envoi
```

Aucun paramètre `channel` dans `dispatch`, et il n'y en aura pas. **Tout passe par la tâche de
fond**, jamais par le fil d'une requête HTTP : une session TLS vers un fournisseur de messagerie
prend le temps qu'elle prend, et le geste métier qui a déclenché la notification — prendre un
rendez-vous, l'annuler — ne doit pas en dépendre.

C'est aussi la raison d'être du port `NotificationDispatcher` : sans lui, un émetteur devrait
importer `infrastructure/tasks/`, ce que le contrat `module-layers` refuse — et le premier qui
appellerait l'envoi directement remettrait le SMTP dans le fil d'une requête.

## Le catalogue d'événements

Fermé, et volontairement court : un événement sans émetteur ni gabarit serait du code mort. Chaque
entrée est **transactionnelle** ou **optionnelle**, et cette classification n'est pas un réglage.

| Événement                  | Nature             | Ce qu'il annonce                      |
| -------------------------- | ------------------ | ------------------------------------- |
| `password_reset`           | **transactionnel** | un lien de réinitialisation (BACK-31) |
| `appointment_cancelled`    | **transactionnel** | un rendez-vous annulé                 |
| `appointment_confirmation` | optionnel          | un rendez-vous vient d'être pris      |
| `appointment_reminder`     | optionnel          | rappel à l'approche du rendez-vous    |
| `news`                     | optionnel          | actualités du service                 |

**Un événement transactionnel part toujours.** Sans lui l'utilisateur reste bloqué : il ne peut pas
reprendre la main sur son compte, ou il se présente à un rendez-vous annulé. L'agrégat **refuse**
qu'on le configure, et la résolution des canaux ne regarde même pas ce qui aurait été enregistré
pour lui.

Le refus est explicite plutôt que silencieux : accepter le réglage puis l'ignorer laisserait croire
à l'utilisateur qu'il a coupé un message qu'il continuera de recevoir, ce qui est pire qu'un refus
franc.

:::note Le code de vérification d'adresse n'est pas dans ce catalogue

La carte du ticket le cite pourtant en exemple de message transactionnel. Il ne **peut pas** passer
par ce module : un événement de notification voyage par la file, où tout argument reste lisible en
clair dans un stream sans TTL, et un OTP est un secret engendré dans le worker
([ADR-0020](../adr/0020-otp-hache-et-echec-ferme.md)). Voir
[Vérification d'adresse (OTP)](./verification-email-otp.md). La règle qu'il illustre est bien celle
d'ici — son expéditeur ne consulte aucune préférence.

:::

## Les préférences : par type d'événement, jamais un interrupteur

Le besoin réel du cahier des charges est littéralement **« rappels de rendez-vous par SMS mais
actualités par e-mail »**. Un booléen unique ne le couvre pas : il force à choisir entre tout
recevoir sur le mauvais canal et ne rien recevoir du tout.

L'agrégat `NotificationPreferences` ne stocke que les **écarts** au défaut. Trois états, et ils
sont bien trois :

| Ce qui est stocké   | Ce que ça veut dire               | Ce qui part         |
| ------------------- | --------------------------------- | ------------------- |
| rien                | « ce compte n'a rien dit »        | le canal par défaut |
| `{"news": []}`      | « ce compte a désactivé `news` »  | rien                |
| `{"news": ["sms"]}` | « ce compte veut `news` par SMS » | le SMS, et lui seul |

Confondre les deux premiers réactiverait en silence ce qu'un utilisateur vient de couper — d'où
`reset(event)`, qui efface un choix, distinct de `set_channels(event, [])`, qui en pose un vide.

Ne ranger que les écarts a deux vertus : un compte neuf est **gratuit** — aucune ligne à semer à
l'inscription, donc aucun module qui écrirait dans la table d'un autre — et les défauts peuvent
évoluer sans migration de données.

## Un port d'envoi, un adaptateur par canal

| Adaptateur                | Canal   | Remet vraiment |
| ------------------------- | ------- | -------------- |
| `EmailNotificationSender` | `email` | **oui**        |
| `LoggingSmsSender`        | `sms`   | non            |
| `LoggingPushSender`       | `push`  | non            |

Le port `NotificationSender` est **unique** ; chaque implémentation annonce le canal qu'elle
dessert, ce qui remplace la cascade de conditions par une indexation. Ajouter un canal, c'est
ajouter un fichier et une valeur d'enum — le cas d'usage ne bouge pas.

**Deux canaux sur trois ne remettent rien**, et c'est la portée du ticket : un contrat SMS se
signe, se paie et se résilie ; le souscrire pour un socle serait une dépense avant tout usage. Ils
**journalisent** plutôt que de se taire, et c'est tout ce qui les sépare d'une classe vide — une
préférence SMS activée doit laisser une trace lisible, au lieu d'un silence qu'on lirait comme une
panne.

Aucun des deux ne **lève** : l'absence de fournisseur n'est pas une panne de transport, et la faire
remonter déclencherait la politique de reprise de [BACK-15](./taches-de-fond.md) sur une tâche qui
ne réussira jamais.

### Le canal e-mail ne parle pas SMTP

Le dialogue vit dans `shared/infrastructure/clients/smtp_mailer.py`, derrière le port technique
`EmailTransport`. Le motif est que `identity` en a besoin pour son code de vérification et n'a pas
le droit d'importer ce module (contrat `module-independence`) :
[ADR-0022](../adr/0022-transport-email-partage.md).

Auth et TLS restent pilotés par `SmtpSettings` (`SMTP_*` et `MAIL_FROM`, voir
[Configuration](./configuration.md)) : **aucun changement de code** ne sépare Mailpit d'un
fournisseur réel.

## Le journal d'envoi

« Un _je n'ai rien reçu_ doit être diagnosticable. » Chaque canal emprunté produit une ligne, au
format de [BACK-11](./journalisation.md), portant quatre champs :

```json
{
  "message": "Notification sent : appointment_reminder vers jean@exemple.fr.",
  "notification_event": "appointment_reminder",
  "notification_channel": "email",
  "notification_status": "sent",
  "recipient": "jean@exemple.fr",
  "account_id": "0199..."
}
```

Trois statuts, et c'est leur différence qui rend le diagnostic possible : `sent`, `failed` (le
transport a refusé, avec `notification_detail`), et `skipped` (le compte avait désactivé
l'événement, ou le canal n'a pas d'adaptateur). Sans le troisième, un événement désactivé et une
panne de transport se ressembleraient trait pour trait — rien dans la boîte, rien dans les journaux.

**Le destinataire y figure**, là où l'adaptateur SMTP de BACK-17 l'excluait de ses journaux. Le
renversement est assumé : cette ligne-là accompagnait un **secret**, et un journal se recopie ; ici
l'adresse _est_ l'objet du diagnostic, et le message rendu n'y figure pas. Elle n'entre donc pas
dans la liste de masquage de BACK-11 — si une revue de confidentialité en décide autrement, c'est
là qu'elle s'ajoutera, en un seul endroit.

**Un canal en échec n'emporte pas les autres** : chaque remise est isolée, la boucle va au bout, et
la tâche échoue ensuite pour que la reprise ait lieu. Interrompre à la première erreur priverait
l'utilisateur d'un canal qui marchait.

## La table

Une seule, `notification_preferences`, **une ligne par compte** :

| Colonne             | Type    | Ce qu'elle porte                                  |
| ------------------- | ------- | ------------------------------------------------- |
| `account_id`        | `uuid`  | unique, sans clé étrangère (ADR-0015)             |
| `channels_by_event` | `jsonb` | `{"<événement>": ["<canal>", ...]}`, écarts seuls |

L'alternative était une table de jointure `(account_id, événement, canal)`. Elle répond à une
question que personne ne pose — « quels comptes veulent des SMS » — alors que toutes les lectures
réelles sont « les préférences **de ce compte** », c'est-à-dire l'agrégat entier, écrit et relu d'un
bloc. C'est exactement la forme que le [dépôt générique](./unite-de-travail.md) sert, une entité
pour une ligne.

Pas de `TenantMixin` : une préférence appartient à un **compte**, pas à un groupe — elle se lit dans
l'espace personnel d'un particulier, hors de toute structure. Même raison que pour `accounts`.

Les valeurs sont stockées **en texte**, comme tous les enums du dépôt, et le dépôt **lève** sur une
valeur que le catalogue ne connaît plus. L'avaler en silence rendrait au compte le défaut de
l'événement disparu — c'est-à-dire lui enverrait des messages qu'il avait coupés.

## Ce que le module n'expose pas

**Aucune route.** Lire ou écrire ses préférences suppose `get_current_active_account` (BACK-10c),
et l'espace personnel se compose en BACK-23. Prendre l'identifiant de compte dans une URL en
attendant recréerait l'oracle d'existence de compte que BACK-17 a refusé.

**Aucun journal d'envoi persisté.** Le critère demande de journaliser, ce que fait le cas d'usage ;
la table qui l'archiverait — annoncée par la docstring de `TenantMixin` parmi les tables qui ne font
que croître — n'a pas d'émetteur à ce jour.
