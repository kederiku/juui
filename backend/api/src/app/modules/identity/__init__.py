"""Module identity : « peux-tu prouver qui tu es ».

MODULE PILOTE de BACK-04. Il est le premier complet, et sert de reference de
structure aux suivants -- `organization` (BACK-16), `medical_records` (BACK-19),
`scheduling` (BACK-21), `notifications` (BACK-22), `profile` (BACK-32).

Son perimetre est l'IDENTITE et l'AUTHENTIFICATION : le compte, son adresse, son
type, son statut, et plus tard le mot de passe (BACK-28), l'OTP (BACK-17), la
double authentification (BACK-18) et les sessions (BACK-29). La question « dans
quelle structure ce compte travaille-t-il » appartient a `organization`.

SURFACE PUBLIQUE
Ce paquet n'exporte que le routeur, ce dont le point d'assemblage a besoin. Un
autre module qui aurait affaire aux comptes passera par les cas d'usage publics
d'`identity`, jamais par ses entites, ses depots ni ses tables.

Le re-export est EXPLICITE parce que Mypy tourne avec `no_implicit_reexport`
(implique par `strict`) : un simple import ne suffirait pas a rendre le nom
importable depuis `app.modules.identity`.
"""

from app.modules.identity.infrastructure.api.routes import router

__all__ = ["router"]
