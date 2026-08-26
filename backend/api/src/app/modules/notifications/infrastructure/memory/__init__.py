"""Doublures en memoire du module notifications (BACK-06c).

Le depot des preferences, l'unite de travail et l'expediteur de canal -- les
doublures des ports METIER du module qui ont un consommateur. Celle de
`NotificationDispatcher` n'est pas livree, faute d'emetteur : `senders.py` dit
comment l'ecrire le jour venu. Le transport de courriel
n'est PAS ici : `EmailTransport` est un port technique de `shared/` (ADR-0022),
et sa doublure `FakeEmailTransport` vit avec lui sous
`shared/infrastructure/memory/`. La regle est celle des autres modules : la
doublure suit son port, jamais son consommateur.

CE FICHIER REMPLACE `tests/modules/notifications/notification_doubles.py`, ecrit
en avance sur ce ticket par BACK-22 et dont la docstring promettait sa propre
disparition.
"""
