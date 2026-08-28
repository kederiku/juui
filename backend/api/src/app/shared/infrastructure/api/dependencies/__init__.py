"""Dependances FastAPI que les routes declarent pour etre protegees (BACK-10c).

Le socle HTTP d'a cote repond « comment le service parle » -- erreurs, journal,
pagination. Ce paquet-ci repond « au nom de qui, et a quel titre », et c'est le
point ou l'isolation multi-tenant cesse d'etre une convention ecrite (ADR-0004,
ADR-0012) pour devenir du code execute a chaque requete.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier      | Contenu                                                  | Ticket  |
| ------------ | -------------------------------------------------------- | ------- |
| `auth.py`    | qui : jeton, audience de la route, etat du compte         | BACK-10c |
| `tenant.py`  | ou et a quel titre : clinique active, role scope          | BACK-10c |
| `audit.py`   | tracage des acces aux donnees personnelles                | BACK-27 |

LE SENS EST `auth -> tenant`, JAMAIS L'INVERSE
`require_role(scope="clinic")` a besoin de `get_active_clinic`, et
`get_active_clinic` a besoin du compte porteur. Loger `require_role` dans
`auth.py` produirait donc `auth -> tenant` ET `tenant -> auth` : un cycle
d'import. La coupure retenue tient en une phrase -- `auth.py` repond QUI,
`tenant.py` repond OU ET A QUEL TITRE --, et le titre du ticket range
l'autorisation « scopee » du cote du perimetre.

CE QUI N'EST PAS ICI, ET NE PEUT PAS Y ETRE
Le MONTAGE. Ces dependances ont besoin des comptes d'`identity` et des
affectations d'`organization`, et le contrat `service-spaces` interdit a
`app.shared` d'importer un module. Elles ne connaissent donc que des formes --
`Protocol` et alias de fonctions --, que les entites des deux modules
satisfont telles quelles. C'est `main.py`, seul espace autorise a connaitre
deux modules a la fois, qui lie les deux bouts dans son `lifespan` et range le
resultat dans `app.state`. Meme patron que `ActiveGroupRoleResolver`
(BACK-10a), et meme motif que l'ouverture du magasin d'OTP.

Les routeurs de modules importent ces dependances DEPUIS ICI, jamais depuis
`main` -- qui leur est interdit par le meme contrat.
"""
