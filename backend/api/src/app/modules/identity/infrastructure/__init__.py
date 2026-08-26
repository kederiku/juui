"""Couche exterieure du module identity : les details remplacables.

Elle DEPEND du domaine, jamais l'inverse. Quatre familles d'adaptateurs y
vivent :

- `db/` -- la table `accounts` et le depot qui traduit une ligne en entite ;
- `api/` -- les schemas HTTP et le routeur ;
- `clients/` -- ce que le module APPELLE : le magasin d'OTP et l'envoi de
  courriel (BACK-17) ;
- `tasks/` -- ce que le module differe : l'emission d'un code (BACK-17), que le
  worker decouvre au demarrage.

Rien de ce qui est ici n'a le droit d'entrer dans `domain/` ou `application/` :
c'est la seule direction que l'architecture hexagonale interdit, et celle que
les contrats import-linter de BACK-04b verifieront.
"""
