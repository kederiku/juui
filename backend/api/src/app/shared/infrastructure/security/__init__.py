"""Adaptateurs de securite : ce qui signe, verifie et protege des secrets.

La place que BACK-04 avait reservee ici, et que la docstring du paquet parent
annoncait. Un sous-paquet distinct de `clients/` parce que ces adaptateurs ne
parlent a AUCUN service externe : ils calculent. Un jeton se signe et se verifie
en memoire, sans socket a ouvrir au demarrage ni a refermer a l'arret -- il n'y
a donc ni ressource dans `app.state`, ni accesseur, et la fabrique suffit.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier          | Port           | Ticket   |
| ---------------- | -------------- | -------- |
| `jwt_service.py` | `TokenService` | BACK-10a |

BACK-10b rejoindra ce paquet avec le hachage des mots de passe, qui a la meme
propriete : du calcul, pas de reseau.
"""
