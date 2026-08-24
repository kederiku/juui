"""Routeur HTTP du module identity (BACK-04).

Le routeur existe, il est assemble par `app.main`, et il ne porte ENCORE AUCUNE
ROUTE. Ce n'est pas un oubli : une route de creation de compte a besoin d'une
session de base de donnees (BACK-05) et d'une unite de travail (BACK-06a), qui
n'existent pas. L'exposer aujourd'hui supposerait de brancher un depot factice
dans le code de production, c'est-a-dire d'ecrire du code jetable et de le
documenter comme s'il etait vrai.

Le trajet complet -- schema, commande, entite, modele -- est en revanche
EXECUTABLE des maintenant : la sonde du README le parcourt de bout en bout.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
`POST /auth/register` (BACK-28), `POST /auth/login` et le rafraichissement de
session (BACK-29), la reinitialisation de mot de passe (BACK-31). Les endpoints
d'administration iront dans un `routes_admin.py` voisin (BACK-26), avec leur
propre prefixe et leurs propres dependances d'autorisation.
"""

from fastapi import APIRouter

# Prefixe et etiquette poses des maintenant : ils fixent l'URL publique du
# module et le groupe sous lequel /docs rangera ses routes. Le prefixe vit ICI,
# et non dans `app.main`, pour que le module reste maitre de sa propre surface.
router = APIRouter(prefix="/auth", tags=["identity"])
