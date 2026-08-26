"""Adaptateurs de canal du module notifications (BACK-22).

UN FICHIER PAR CANAL, TOUS DERRIERE LE MEME PORT. C'est la forme que le ticket
demande -- « port `NotificationSender` unique, adaptateurs par canal » -- et c'est
ce qui permet au cas d'usage d'indexer les expediteurs par `channel` au lieu
d'enchainer des `if`. Ajouter un canal, c'est ajouter un fichier ici, une valeur
a `NotificationChannel`, et rien d'autre.

| Fichier            | Canal   | Remet vraiment |
| ------------------ | ------- | -------------- |
| `email_sender.py`  | `EMAIL` | oui            |
| `sms_sender.py`    | `SMS`   | non            |
| `push_sender.py`   | `PUSH`  | non            |

DEUX CANAUX SUR TROIS NE REMETTENT RIEN, ET C'EST LA PORTEE DU TICKET
« Pas de fournisseur SMS ni push reel a ce stade : adaptateur e-mail seul, les
autres canaux en implementation vide et journalisee, pour que la structure existe
sans engager de cout. » Un contrat SMS se signe, se paie et se resilie ; le
souscrire pour un socle serait une depense avant tout usage. Ce que ces deux
fichiers garantissent, c'est qu'aucune ligne du cas d'usage ne changera le jour
ou ils remettront pour de bon.

ILS JOURNALISENT PLUTOT QUE DE SE TAIRE, et la nuance est tout ce qui les separe
d'une classe vide : une preference SMS activee doit laisser une trace lisible, au
lieu d'un silence qu'on lira comme une panne.
"""
