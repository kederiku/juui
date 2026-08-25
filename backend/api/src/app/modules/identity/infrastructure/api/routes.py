"""Routeur HTTP du module identity (BACK-04).

Le routeur existe, il est assemble par `app.main`, et il ne porte ENCORE AUCUNE
ROUTE. Ce n'est plus une question d'outillage : l'unite de travail existe
(BACK-06a), et une route n'aurait qu'a annoter `uow: IdentityUowDep` pour la
recevoir. Ce qui manque est METIER : le parcours d'inscription porte des regles
-- mot de passe hache (BACK-10b), non-divulgation (BACK-09), verification
(BACK-17) -- qu'une route de demonstration contournerait, et qu'il faudrait
documenter comme si elles etaient tenues.

Le trajet complet -- schema, commande, entite, unite de travail, modele -- est
en revanche EXECUTABLE des maintenant : les sondes de la section Backend du
site de documentation le parcourent de bout en bout, route de sonde comprise.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
`POST /auth/register` (BACK-28), `POST /auth/login` et le rafraichissement de
session (BACK-29), la reinitialisation de mot de passe (BACK-31). Les endpoints
d'administration iront dans un `routes_admin.py` voisin (BACK-26), avec leur
propre prefixe et leurs propres dependances d'autorisation.
"""

from fastapi import APIRouter

# Prefixe et etiquette poses des maintenant : ils fixent l'URL publique du
# module et le groupe sous lequel /docs rangera ses routes. Le module possede
# le chemin de sa RESSOURCE (`/auth`) ; la VERSION (`/api/v1`), elle, est un
# choix du service, pose par le routeur racine de BACK-08 -- URL publique
# finale : /api/v1/auth/... L'etiquette vaut le NOM DU MODULE : Orval
# (SHARED-03) decoupe le client genere par etiquette, une par contexte metier.
#
# Convention pour les routes a venir (BACK-28, BACK-29) : chaque route porte un
# `operation_id` explicite, en snake_case verbe-objet, egal au nom de sa
# fonction -- Orval en derive le nom des hooks generes.
router = APIRouter(prefix="/auth", tags=["identity"])
