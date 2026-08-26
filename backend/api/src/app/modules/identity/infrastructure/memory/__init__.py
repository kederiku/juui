"""Doublures en memoire du module identity (BACK-06c).

Le pendant, pour les ports METIER d'`identity`, de ce que
`shared/infrastructure/memory/` fournit pour les ports techniques : un depot de
comptes, une unite de travail, un magasin d'OTP, un expediteur et un declencheur.
Elles sont completes -- le magasin tient reellement le TTL, le compteur de
tentatives et les trois quotas, et appelle les MEMES fonctions du domaine que
l'adaptateur Redis, meme empreinte et meme comparaison en temps constant. C'est
ce qui rend les tests de cas d'usage significatifs : ils eprouvent la regle, pas
la doublure.

POURQUOI ELLES SONT ICI ET NON DANS `shared/infrastructure/memory/`
La portee du ticket range `FakeOtpSender` avec les autres doublures. C'est
impossible, et pas par gout du rangement : `OtpSender`, `OtpStore`,
`OtpDispatcher` et `AccountRepository` sont des ports METIER, definis dans le
domaine d'`identity`. Le contrat `service-spaces` interdit a `app.shared`
d'importer `app.modules` -- une doublure posee la-bas ferait echouer
`make lint`. La regle qui en sort est simple et vaut pour les modules suivants :
LA DOUBLURE SUIT SON PORT.

CE FICHIER REMPLACE `tests/modules/identity/otp_doubles.py`, ecrit en avance sur
ce ticket par BACK-17 et dont la docstring promettait sa propre disparition. Ce
qui restait specifiquement de TEST -- les bornes par defaut, la fabrique de
compte, la lecture de l'etat valide -- est reste sous `tests/`, dans
`helpers.py` : une doublure repond a un port, une aide de test ne repond a
personne.
"""
