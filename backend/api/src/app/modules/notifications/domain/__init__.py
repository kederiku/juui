"""Coeur metier du module notifications : les regles, et rien de technique.

Quatre fichiers, comme dans les trois modules qui precedent :

- `policies.py`  -- le catalogue des evenements et des canaux, leur
                    classification transactionnel/optionnel, la regle des canaux
                    et les gabarits. La FEUILLE : elle n'importe rien du module
                    hormis `exceptions.py` ;
- `entities.py`  -- l'agregat `NotificationPreferences` et la valeur
                    `NotificationRequest` ;
- `ports.py`     -- les contrats que l'infrastructure devra remplir ;
- `exceptions.py`-- les refus metier, traduits en HTTP ailleurs.

POURQUOI LE VOCABULAIRE EST DANS `policies.py` ET NON DANS `entities.py`
`AccountType` est l'etat d'un compte : il vit avec lui, chez identity. Le
catalogue d'evenements et la liste des canaux, eux, ne sont l'etat de personne --
l'agregat, les ports, les trois adaptateurs de canal et la tache les parlent
tous. Une regle qui ne tient dans aucune entite en particulier est une politique,
et c'est exactement la definition que le depot lui donne.

Ce paquet n'importe ni fastapi, ni sqlalchemy, ni pydantic -- pas plus qu'il
n'importe `app.core` ou un autre module. Il ne connait que la bibliotheque
standard et `app.shared.domain`.
"""
