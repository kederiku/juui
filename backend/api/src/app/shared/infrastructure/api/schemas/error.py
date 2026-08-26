"""Le format d'erreur unique du service (BACK-09).

TOUTE reponse d'erreur de l'API -- refus metier, validation Pydantic, 404 de
routage, 500 -- porte ces quatre cles, toujours presentes, `null` compris. Un
contrat stable a quatre cles est ce qui permet au client genere par Orval
(SHARED-03) de normaliser les erreurs en un seul endroit, et a un operateur de
grepper `code` en production sans ouvrir le code.

POURQUOI `details` EST UN OBJET, JAMAIS UNE LISTE
Les erreurs de validation Pydantic se rangent sous une cle (`{"errors": [...]}`)
plutot qu'en liste au sommet : un objet s'etend sans casser le contrat -- on
peut ajouter une cle demain -- et Orval le type proprement, la ou une union
objet-ou-liste serait penible des deux cotes.

`request_id` porte l'identifiant de la requete, pose par l'intergiciel de
correlation (BACK-11) et renvoye au client dans l'en-tete `X-Request-ID` : le
corps d'une erreur et les lignes de journal qui la racontent se recoupent. Il ne
vaut `null` que HORS de toute requete HTTP -- une `DomainError` levee depuis une
tache de fond ou un script --, ce qui reste un etat normal.
"""

from pydantic import BaseModel, ConfigDict, JsonValue

__all__ = ["ErrorResponse"]


class ErrorResponse(BaseModel):
    """Corps de toute reponse d'erreur : { code, message, details, request_id }.

    Serialise avec ses quatre cles TOUJOURS presentes -- les handlers passent
    par `model_dump(mode="json")` sans `exclude_none`, et c'est voulu : un
    contrat dont les cles apparaissent et disparaissent n'est pas un contrat.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "identity.account.not_found",
                    "message": "Aucun compte ne porte l'identifiant demande.",
                    "details": None,
                    "request_id": None,
                }
            ]
        }
    )

    code: str
    message: str
    details: dict[str, JsonValue] | None = None
    request_id: str | None = None
