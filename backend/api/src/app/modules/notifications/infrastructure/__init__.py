"""Couche exterieure du module notifications : les details remplacables.

Elle DEPEND du domaine, jamais l'inverse. Trois familles d'adaptateurs y vivent :

- `db/` -- la table `notification_preferences` et le depot qui traduit une ligne
  en entite ;
- `clients/` -- UN ADAPTATEUR PAR CANAL, tous derriere le meme port
  `NotificationSender` : courriel, SMS, push ;
- `tasks/` -- ce que le module differe, c'est-a-dire TOUT ce qu'il fait : la
  remise elle-meme, que le worker decouvre au demarrage.

PAS DE `api/` : le module n'expose aucune route a ce stade. Lire ou ecrire ses
preferences suppose `get_current_active_account` (BACK-10c), et la surface de
composition de l'espace personnel appartient a BACK-23.

Rien de ce qui est ici n'a le droit d'entrer dans `domain/` ou `application/` :
c'est la seule direction que l'architecture hexagonale interdit, et le contrat
`module-layers` de BACK-04b la verifie.
"""
