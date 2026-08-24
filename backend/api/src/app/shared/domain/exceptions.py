"""Racine des erreurs metier (BACK-04, completee par BACK-09).

Le domaine leve des exceptions METIER, jamais des erreurs de protocole. Une
`HTTPException` levee depuis une entite ou un cas d'usage lierait le coeur du
service a FastAPI, et rendrait le meme code inutilisable depuis une tache de
fond ou une commande en ligne -- ou personne n'attend de code HTTP.

La traduction en reponse HTTP appartient a un seul endroit, l'adaptateur d'API :
`shared/infrastructure/api/error_handlers.py`, livre par BACK-09.

CE QUE BACK-09 AJOUTERA ICI
La hierarchie intermediaire -- `NotFoundError`, `AlreadyExistsError`,
`ValidationError`, `PermissionDeniedError`, `ConflictError` -- ainsi que les
codes namespaces `<module>.<ressource>.<erreur>` qui permettent de lire
l'origine d'une erreur en production sans ouvrir le code. Les exceptions des
modules, qui heritent aujourd'hui de `DomainError` directement, se rangeront
alors sous la bonne classe intermediaire.
"""


class DomainError(Exception):
    """Erreur metier : une regle du domaine n'est pas respectee.

    Classe de base de TOUTES les erreurs metier du service, celles des modules
    comprises. C'est elle que l'adaptateur d'API sait traduire ; une exception
    qui ne descend pas d'ici remontera en 500, ce qui est le comportement
    attendu pour un defaut technique, pas pour un refus metier.
    """
