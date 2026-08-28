"""Perimetre de travail et autorisation par role scope (BACK-10c).

`auth.py` repond QUI ; ce module repond OU ET A QUEL TITRE. Le jeton dit « qui
tu es et chez qui » -- le groupe actif voyage dans le claim, signe --, l'en-tete
`X-Clinic-Id` dit « ou tu travailles en ce moment » (ADR-0012). L'en-tete
SELECTIONNE un perimetre parmi ceux deja autorises ; il n'en ouvre aucun, et
c'est tout l'objet des verifications ci-dessous.

LE MOT « ROLE » DESIGNE DEUX CHOSES, D'OU LE PERIMETRE OBLIGATOIRE
Un role de perimetre GROUPE -- gerant, administrateur, superadministrateur --
est porte par le jeton et se lit sans aucune requete. Un role de perimetre
CLINIQUE -- veterinaire, ASV -- ne figure JAMAIS dans un jeton : il se resout a
la requete, sur l'affectation de la clinique active. Une signature
`require_role("admin")` sans perimetre serait ambigue et donnerait une
autorisation fausse ; ici le perimetre est un mot-cle sans defaut, discriminant
de surcharge, et l'omettre est une erreur de typage, pas une surprise a
l'execution.

LE VOCABULAIRE DES ROLES EST RECOPIE, ET SURVEILLE
`GroupRole` et `ClinicRole` vivent dans `organization`, que le contrat
`service-spaces` rend inaccessible d'ici. Des `str` nus rendraient
`require_role("asv", scope="group")` parfaitement valide -- et produiraient une
route que personne au monde ne peut atteindre. Deux `Literal` distincts rendent
l'erreur visible chez Mypy ; un test compare les deux jeux de valeurs a chaque
execution, comme pour les types de compte de `jwt_service.py`.

LES DEUX VERIFICATIONS DE LA CLINIQUE, ET POURQUOI ELLES SONT DEUX
Le compte est-il affecte a cette clinique ? La ligne existe dans la lecture
tenant. La clinique appartient-elle au groupe actif ? Un depot NON TENANT rend
son groupe proprietaire, et la comparaison se fait ici, en clair. La seconde
aurait pu s'appuyer sur le filtre de tenance et la cle etrangere composite des
affectations -- mais elle aurait alors partage son point de defaillance avec la
premiere, et deux controles au meme point de defaillance ne font pas deux
controles.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Final, Literal, get_args, overload
from uuid import UUID

from fastapi import Depends, Header, Request

from app.core.correlation import use_clinic_id
from app.shared.domain.exceptions import (
    ActiveClinicNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.shared.infrastructure.api.dependencies.auth import (
    ActiveAssignment,
    AuthenticatedAccount,
    Authentication,
    CurrentActiveAccount,
    get_authentication,
)
from app.shared.infrastructure.tenancy import require_current_group_id

__all__ = [
    "CLINIC_HEADER",
    "CLINIC_ROLE_NAMES",
    "GROUP_ROLE_NAMES",
    "ActiveClinic",
    "ClinicRoleName",
    "GroupRoleName",
    "RoleGuard",
    "get_active_assignments",
    "get_active_clinic",
    "require_role",
]

# En-tete par lequel le client designe sa clinique de travail (ADR-0012). Deja
# autorise par le CORS de BACK-11 : rien a ajouter de ce cote.
CLINIC_HEADER: Final = "X-Clinic-Id"

# Vocabulaires recopies -- voir la docstring de module.
type GroupRoleName = Literal["manager", "admin", "superadmin"]
type ClinicRoleName = Literal["veterinarian", "asv"]

# DERIVES des `Literal` ci-dessus, jamais recopies une seconde fois. Ce sont les
# `Literal` que Mypy fait respecter dans les surcharges de `require_role` ; une
# liste ecrite a cote d'eux serait une troisieme copie du vocabulaire, et le test
# de derive garderait alors la copie plutot que le garde-fou.
GROUP_ROLE_NAMES: Final[tuple[str, ...]] = get_args(GroupRoleName.__value__)
CLINIC_ROLE_NAMES: Final[tuple[str, ...]] = get_args(ClinicRoleName.__value__)

# Ce que rend `require_role` : une dependance FastAPI dont les parametres sont
# decides par le perimetre, et qui rend le porteur si le role convient.
type RoleGuard = Callable[..., Awaitable[AuthenticatedAccount]]

_CLINIC_REFUSAL: Final = "Aucune clinique active ne correspond a cet en-tete."


async def get_active_assignments(
    account: CurrentActiveAccount,
    authentication: Annotated[Authentication, Depends(get_authentication)],
) -> Sequence[ActiveAssignment]:
    """Lit les affectations actives du compte, dans le groupe actif.

    DEUX GARDES AVANT TOUTE LECTURE, ET DANS CET ORDRE. Un jeton sans groupe
    actif -- un compte particulier, cas nominal -- est refuse en 404 : le depot
    est TENANT et leverait `MissingTenantContextError`, c'est-a-dire un 500 avec
    sa pile au journal, sur un refus parfaitement ordinaire. Puis
    `require_current_group_id()`, qui REFUSE le mode « tous groupes » : sous
    l'echappatoire, le filtre de groupe disparait et la lecture rendrait les
    affectations de tous les groupes.

    UN SEUL INSTANT, UN SEUL SELECT. Cette dependance est un objet de module :
    le cache de FastAPI la partage entre `get_active_clinic` et la garde de
    role, qui voient donc les memes lignes au meme instant -- ni requete en
    double, ni fenetre entre deux lectures.

    Args:
        account: le porteur verifie.
        authentication: le montage ouvert par le `lifespan`.

    Returns:
        Les affectations actives du compte dans le groupe actif.

    Raises:
        ActiveClinicNotFoundError: 404 si le jeton ne porte aucun groupe actif.
        MissingTenantContextError: 500 si le mode « tous groupes » est actif --
            defaut de cablage, jamais un refus a montrer au client.
    """
    if account.claims.active_group_id is None:
        raise ActiveClinicNotFoundError(_CLINIC_REFUSAL)
    require_current_group_id()
    return await authentication.resolve_active_assignments(account.account_id, datetime.now(UTC))


async def get_active_clinic(
    request: Request,
    clinic_id: Annotated[UUID, Header(alias=CLINIC_HEADER)],
    assignments: Annotated[Sequence[ActiveAssignment], Depends(get_active_assignments)],
    authentication: Annotated[Authentication, Depends(get_authentication)],
) -> AsyncIterator[ActiveAssignment]:
    """Resout la clinique active, et rend L'AFFECTATION qui l'autorise.

    RENDRE L'AFFECTATION ET NON L'IDENTIFIANT est ce qui empeche un ASV d'une
    clinique de poser un acte veterinaire dans une autre : le role vient de LA
    LIGNE de la clinique active, jamais d'une agregation sur le compte.

    AFFECTATIONS CHEVAUCHANTES. Rien ne les interdit (ADR-0005), et le depot
    trie du debut le plus ANCIEN. On retient celle au debut le plus RECENT,
    departagee par `id` -- la doctrine deja ecrite pour `find_active_role`, « la
    derniere decision prise l'emporte ». Sans cette regle, une retrogradation
    faite sans fermer l'affectation precedente serait sans effet, pour toujours.

    UN SEUL REFUS POUR CINQ CAUSES : clinique inconnue, clinique d'un autre
    groupe, compte non affecte, affectation close, jeton sans groupe actif. Les
    distinguer ferait de l'API un oracle d'enumeration des cliniques
    concurrentes.

    Args:
        request: la requete en cours, pour compter les en-tetes.
        clinic_id: la clinique demandee, lue dans `X-Clinic-Id`.
        assignments: les affectations actives du compte dans le groupe actif.
        authentication: le montage ouvert par le `lifespan`.

    Yields:
        L'affectation active du compte sur la clinique demandee,
        `current_clinic_id` pose pour la duree du traitement puis retire.

    Raises:
        ValidationError: 422 si l'en-tete est envoye plusieurs fois.
        ActiveClinicNotFoundError: 404 pour les cinq causes ci-dessus.
    """
    if len(request.headers.getlist(CLINIC_HEADER.lower())) != 1:
        # Une valeur cliente ne se rectifie jamais : FastAPI en retiendrait la
        # premiere occurrence en silence, la ou un mandataire ou l'audit de
        # BACK-27 pourraient lire la derniere.
        message = f"L'en-tete `{CLINIC_HEADER}` ne doit etre envoye qu'une fois."
        raise ValidationError(message)

    # VERIFICATION 2 -- independante du filtre de tenance et de la cle etrangere
    # des affectations : on lit le groupe proprietaire de la clinique SANS
    # filtre, et on le compare ici. Faite avant la premiere parce qu'elle ne
    # depend que de l'en-tete : une clinique qui n'est pas du groupe est refusee
    # sans qu'on ait a savoir si le compte y serait affecte.
    owning_group_id = await authentication.resolve_clinic_group(clinic_id)
    if owning_group_id != require_current_group_id():
        raise ActiveClinicNotFoundError(_CLINIC_REFUSAL)

    # VERIFICATION 1 -- le compte y est affecte, a cet instant.
    held = [assignment for assignment in assignments if assignment.clinic_id == clinic_id]
    if not held:
        raise ActiveClinicNotFoundError(_CLINIC_REFUSAL)
    active = max(held, key=lambda assignment: (assignment.start_at, assignment.id))

    with use_clinic_id(clinic_id):
        yield active


@overload
def require_role(
    role: GroupRoleName, /, *more: GroupRoleName, scope: Literal["group"]
) -> RoleGuard: ...


@overload
def require_role(
    role: ClinicRoleName, /, *more: ClinicRoleName, scope: Literal["clinic"]
) -> RoleGuard: ...


def require_role(role: str, /, *more: str, scope: Literal["group", "clinic"]) -> RoleGuard:
    """Fabrique la dependance qui exige un role, dans un perimetre EXPLICITE.

    LES DEUX GARDES DEPENDENT DU COMPTE ACTIF, et ce n'est pas une commodite :
    une garde qui ne lirait que le claim laisserait une route de perimetre
    groupe -- les plus sensibles du service -- servir un compte suspendu ou
    supprime, sans un seul SELECT.

    UN ROLE DE GROUPE N'ACTIVE PAS UNE CLINIQUE. La gerante d'un groupe qui
    n'est affectee a aucune de ses cliniques n'obtient pas de perimetre
    clinique : la seule preuve disponible est l'affectation. Le raccourci
    tentant -- « un gerant peut tout » -- supprimerait la premiere des deux
    verifications ; ses routes a elle sont de perimetre groupe.

    Args:
        role: le premier role admis.
        *more: les autres roles admis, s'il y en a.
        scope: le perimetre ou ce role se lit. `"group"` le prend dans le claim,
            sans aucune requete ; `"clinic"` le resout sur l'affectation de la
            clinique active.

    Returns:
        La dependance a passer a `Depends`.
    """
    allowed = frozenset((role, *more))

    if scope == "group":

        async def guard_group_role(account: CurrentActiveAccount) -> AuthenticatedAccount:
            """Verifie le role de perimetre groupe porte par le jeton.

            Args:
                account: le porteur verifie.

            Returns:
                Le meme porteur, une fois son role admis.

            Raises:
                PermissionDeniedError: 403 si le role n'est pas admis.
            """
            if account.claims.group_role not in allowed:
                message = "Ce role ne permet pas cette action dans ce groupe."
                raise PermissionDeniedError(message)
            return account

        return guard_group_role

    async def guard_clinic_role(
        account: CurrentActiveAccount,
        assignment: Annotated[ActiveAssignment, Depends(get_active_clinic)],
    ) -> AuthenticatedAccount:
        """Verifie le role tenu sur la clinique active, resolu a la requete.

        Args:
            account: le porteur verifie.
            assignment: l'affectation qui autorise la clinique active.

        Returns:
            Le porteur, une fois son role admis sur cette clinique.

        Raises:
            PermissionDeniedError: 403 si le role n'est pas admis.
        """
        if assignment.role not in allowed:
            message = "Ce role ne permet pas cette action dans cette clinique."
            raise PermissionDeniedError(message)
        return account

    return guard_clinic_role


# Alias a annoter les parametres de route : la clinique active, deja verifiee.
ActiveClinic = Annotated[ActiveAssignment, Depends(get_active_clinic)]
