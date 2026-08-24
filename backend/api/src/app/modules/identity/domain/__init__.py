"""Coeur metier du module identity : les regles, et rien de technique.

Quatre fichiers, tels que les nomme BACK-04 :

- `entities.py`  -- l'agregat `Account` et ses comportements ;
- `policies.py`  -- les regles pures qui ne tiennent dans aucune entite ;
- `ports.py`     -- les contrats que l'infrastructure devra remplir ;
- `exceptions.py`-- les refus metier, traduits en HTTP ailleurs.

Des FICHIERS et non des dossiers : un `domain/entities/` finit par empiler
quarante entites sans qu'aucune frontiere ne dise laquelle repond a quelle
question. C'est le module qui porte la frontiere, pas la couche.

Ce paquet n'importe ni fastapi, ni sqlalchemy, ni pydantic -- pas plus qu'il
n'importe `app.core` ou un autre module. Il ne connait que la bibliotheque
standard et `app.shared.domain`.
"""
