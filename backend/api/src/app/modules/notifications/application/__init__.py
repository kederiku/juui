"""Couche d'orchestration du module notifications.

Elle ne contient AUCUNE regle metier -- celles-ci vivent dans `domain/` -- et
aucun detail technique : ni session, ni client SMTP, ni broker. Son travail tient
en une phrase : enchainer des appels aux ports et aux entites pour realiser un
cas d'usage.

PARTICULARITE DE CE MODULE : ses cas d'usage ne s'executent JAMAIS dans le fil
d'une requete HTTP. Ils tournent dans le worker, appeles par une tache (BACK-15)
que l'emetteur a mise en file via `NotificationDispatcher`. C'est ce qui rend le
port de dispatch indispensable, et c'est aussi ce qui rend cette couche testable
sur des doublures en memoire, sans broker ni serveur SMTP.
"""
