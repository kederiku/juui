"""Identification du porteur et controle de l'audience de la route (BACK-10c).

BACK-10a savait emettre et verifier un jeton ; rien ne le branchait sur une
requete. C'est ce que ce module fait, et il le fait en quatre gestes ordonnes
dont l'ORDRE EST UNE PROPRIETE DE SECURITE : lire l'audience que la route
declare, extraire le jeton, le decoder, puis seulement alors lire le compte en
base. Un flot de jetons forges coute une comparaison et un HMAC, jamais un
aller-retour PostgreSQL.

UN SEUL 401, SANS DETAIL
Expire, mal signe, illisible, du mauvais type, de la mauvaise audience, ou dont
le sujet ne designe aucun compte : toutes ces causes passent par la meme
fabrique `_unauthenticated()` et produisent une reponse indistinguable.
L'indistinguabilite est ainsi STRUCTURELLE -- elle ne depend pas d'une revue qui
comparerait les chemins un a un. En-tete `WWW-Authenticate: Bearer` nu : pas de
`realm`, qui nommerait la structure, et pas de `error=`, qui dirait a un
attaquant que sa forgerie est cryptographiquement bonne mais perimee. Le contrat
client tient en une phrase : tout 401 declenche un rafraichissement, et son
echec une deconnexion. Le SPA lit `exp` dans son propre jeton, il n'a pas besoin
du serveur pour cela.

L'AUDIENCE EST UNE PROPRIETE DE LA ROUTE
Rien dans une requete ne dit honnetement quelle application appelle. Le claim
`aud` serait tautologique -- on verifierait le jeton contre lui-meme --, et
`audience_for(claims.account_type)` serait pire : le controle deviendrait vrai
pour TOUT jeton authentique, puisque l'emission pose les deux ensemble. Un
en-tete laisserait l'appelant choisir la porte qu'il franchit. L'audience est
donc declaree au montage, par le routeur, et lue dans le `scope` ASGI.

CE QUE `app.shared` N'A PAS LE DROIT DE NOMMER
`Account` vit dans `identity`, que le contrat `service-spaces` rend inaccessible
d'ici. Ce module decrit donc la FORME dont il a besoin -- `AccountRecord` -- et
`identity.Account` la satisfait telle quelle. Chaque membre de ce protocole est
une `@property` LECTURE SEULE, et ce n'est pas un style : un membre declare en
attribut nu est mutable, donc invariant, et `AccountStatus` echouerait face a
`str`. En propriete lecture seule il est covariant, et un `StrEnum` passe.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Protocol
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.correlation import use_account_id
from app.shared.domain.exceptions import (
    NotFoundError,
    SuspendedAccountError,
    UnverifiedEmailError,
)
from app.shared.domain.ports.token_service import (
    TokenClaims,
    TokenError,
    TokenService,
    TokenType,
    UnknownAccountTypeError,
)
from app.shared.infrastructure.tenancy import use_group

__all__ = [
    "ACCOUNT_STATUSES",
    "ACCOUNT_STATUS_ACTIVE",
    "ACCOUNT_STATUS_SUSPENDED",
    "AUTH_STATE_KEY",
    "EXPECTED_AUDIENCE_SCOPE_KEY",
    "AccountRecord",
    "AccountResolver",
    "ActiveAssignment",
    "ActiveAssignmentsResolver",
    "AuthenticatedAccount",
    "Authentication",
    "ClinicGroupResolver",
    "CurrentAccount",
    "CurrentActiveAccount",
    "audience_of",
    "get_authentication",
    "get_current_account",
    "get_current_active_account",
]

# Cle sous laquelle le `lifespan` range le montage d'authentification, meme
# convention que `database`, `cache` et `otp_store`.
AUTH_STATE_KEY: Final = "authentication"

# Cle d'extension ASGI portant le type de compte que la route sert. Prefixe
# `juui.` comme `REQUEST_ID_SCOPE_KEY` : le `scope` est partage avec le serveur
# et toute bibliotheque de la chaine.
EXPECTED_AUDIENCE_SCOPE_KEY: Final = "juui.expected_audience"

# Recopie SURVEILLEE des valeurs d'`AccountStatus`, qui vit dans `identity`. Meme
# parti que les constantes `ACCOUNT_TYPE_*` de `jwt_service.py`, et meme garde :
# un test compare les deux jeux de valeurs a chaque execution.
#
# LA BORDURE DECIDE EN LISTE BLANCHE. Refuser le seul statut « suspendu » serait
# une liste noire d'une valeur : un statut ajoute a l'enumeration -- « clos »,
# « supprime » -- franchirait la bordure par defaut, du seul fait que personne
# n'a pense a l'y ajouter. C'est l'inverse qu'il faut : ce qui n'est pas
# explicitement actif attend que ce module tranche ce qu'il en fait.
ACCOUNT_STATUS_ACTIVE: Final = "active"
ACCOUNT_STATUS_SUSPENDED: Final = "suspended"
ACCOUNT_STATUSES: Final[tuple[str, ...]] = (ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_SUSPENDED)

# Extracteur du jeton. `auto_error=False` : il rend `None` au lieu de lever, ce
# qui laisse ce module tenir SON 401 -- message francais, en-tete choisi, et
# surtout une seule fabrique de refus. Le declarer quand meme, plutot que de
# lire l'en-tete a la main, garde le schema de securite dans l'OpenAPI : c'est
# lui qui donnera le cadenas de /docs et l'en-tete que generera Orval.
_BEARER: Final = HTTPBearer(auto_error=False, scheme_name="bearerAuth")

_BEARER_SCHEME: Final = "bearer"


class AccountRecord(Protocol):
    """Ce qu'un compte doit savoir dire pour franchir la bordure HTTP.

    Voir la docstring de module : propriete lecture seule obligatoire sur chaque
    membre, faute de quoi `identity.Account` cesserait de satisfaire ce
    protocole sous Mypy strict.
    """

    @property
    def id(self) -> UUID:
        """L'identifiant du compte."""

    @property
    def account_type(self) -> str:
        """Le type de compte -- professionnel, particulier ou administrateur."""

    @property
    def status(self) -> str:
        """L'etat du compte : actif ou suspendu."""

    @property
    def email_verified(self) -> bool:
        """Si l'adresse du compte a ete verifiee."""


class ActiveAssignment(Protocol):
    """Ce qu'une affectation active doit savoir dire a la bordure HTTP.

    `start_at` en fait partie : c'est lui qui departage deux affectations
    chevauchantes vers une meme clinique (voir `tenant.get_active_clinic`).
    """

    @property
    def id(self) -> UUID:
        """L'identifiant de l'affectation."""

    @property
    def clinic_id(self) -> UUID:
        """La clinique sur laquelle porte l'affectation."""

    @property
    def role(self) -> str:
        """Le role de perimetre clinique tenu au titre de cette affectation."""

    @property
    def start_at(self) -> datetime:
        """Le debut de la fenetre d'affectation."""


# Trois franchissements de frontiere, trois alias de fonctions -- jamais des
# ports. La signature de la methode du depot les satisfait telle quelle, comme
# `MembershipRepository.find_active_role` satisfait `ActiveGroupRoleResolver`.
type AccountResolver = Callable[[UUID], Awaitable[AccountRecord]]
type ActiveAssignmentsResolver = Callable[[UUID, datetime], Awaitable[Sequence[ActiveAssignment]]]
type ClinicGroupResolver = Callable[[UUID], Awaitable[UUID | None]]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticatedAccount:
    """Ce que la bordure a VERIFIE sur le porteur, fige pour la requete.

    `claims` porte tout ce que le jeton affirmait -- sujet, audience, groupe
    actif, role de groupe, identifiant de jeton. Un seul champ s'y ajoute :
    celui que la bordure est allee chercher en base et dont une dependance
    ULTERIEURE a besoin. Le statut, lui, n'est pas porte : il a ete controle et
    refuse ici meme, rien en aval n'en a l'usage.
    """

    claims: TokenClaims
    email_verified: bool

    @property
    def account_id(self) -> UUID:
        """L'identifiant du compte porteur -- le `sub` du jeton verifie.

        Returns:
            L'identifiant du compte.
        """
        return self.claims.subject


@dataclass(frozen=True, slots=True)
class Authentication:
    """Le service de jetons et ses resolveurs, lies par le point de composition.

    Un objet unique plutot que quatre attributs poses cote a cote sur
    `app.state` : ils naissent ensemble, et un seul acces suffit alors a savoir
    si le `lifespan` a bien tourne. Meme forme que `Database`.
    """

    tokens: TokenService
    resolve_account: AccountResolver
    resolve_active_assignments: ActiveAssignmentsResolver
    resolve_clinic_group: ClinicGroupResolver


def get_authentication(request: Request) -> Authentication:
    """Retourne le montage d'authentification ouvert par le `lifespan`.

    ECHEC FERME, ET LA NUANCE COMPTE. Une application montee sans son `lifespan`
    -- ce que fait tout test qui l'oublie -- doit repondre 500, jamais 401 : un
    401 se lirait comme « ce jeton est mauvais » alors que le service est
    incapable d'en juger, et un tel defaut de cablage passerait pour un refus
    ordinaire dans les journaux.

    Args:
        request: la requete en cours, d'ou l'on remonte a `app.state`.

    Returns:
        Le montage d'authentification du processus.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne, ou si `app.state` porte
            autre chose sous cette cle.
    """
    authentication = getattr(request.app.state, AUTH_STATE_KEY, None)
    if not isinstance(authentication, Authentication):
        message = (
            "Aucun montage d'authentification dans `app.state` : le `lifespan` "
            "n'a pas tourne. Les routes protegees ne peuvent pas repondre."
        )
        raise RuntimeError(message)
    return authentication


def audience_of(account_type: str) -> Callable[[Request], Awaitable[None]]:
    """Fabrique la dependance qui declare l'audience servie par un routeur.

    A poser sur `include_router(..., dependencies=[...])`, et non route par
    route : l'audience est une propriete de la ROUTE, et la declarer au routeur
    est ce qui empeche qu'on l'oublie sur la trente-huitieme. Voir la docstring
    de module pour les sources ecartees.

    UNE SECONDE ECRITURE DIVERGENTE EST REFUSEE. Sans cette garde, un routeur
    imbrique sous un autre ferait decider la frontiere entre les trois
    applications par l'ordre de montage, en silence. Re-declarer la MEME
    audience reste permis : c'est une redondance, pas une ambiguite.

    Args:
        account_type: le type de compte que ce routeur sert, d'ou l'audience
            attendue se deduit par la table du port.

    Returns:
        La dependance a passer a `Depends`.
    """

    async def declare_audience(request: Request) -> None:
        """Inscrit l'audience attendue dans le `scope` de la requete.

        Args:
            request: la requete en cours.

        Raises:
            RuntimeError: si une audience differente a deja ete declaree.
        """
        already = request.scope.get(EXPECTED_AUDIENCE_SCOPE_KEY)
        if already is not None and already != account_type:
            message = (
                f"Deux audiences declarees sur la meme route : `{already}` puis "
                f"`{account_type}`. La frontiere entre les applications ne peut "
                "pas dependre de l'ordre de montage des routeurs."
            )
            raise RuntimeError(message)
        request.scope[EXPECTED_AUDIENCE_SCOPE_KEY] = account_type

    return declare_audience


def _unauthenticated() -> HTTPException:
    """Fabrique LE refus d'authentification -- le seul de ce module.

    Toutes les causes y passent : c'est ce qui rend l'indistinguabilite
    structurelle plutot que verifiable a la relecture.

    Returns:
        Le 401, avec son defi `Bearer` nu.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentification requise.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _expected_account_type(request: Request) -> str:
    """Lit le type de compte que la route declare servir.

    Args:
        request: la requete en cours.

    Returns:
        Le type de compte declare par le routeur.

    Raises:
        RuntimeError: si la route ne declare aucune audience -- defaut de
            cablage, 500, jamais un refus deguise ni un acces accorde.
    """
    declared = request.scope.get(EXPECTED_AUDIENCE_SCOPE_KEY)
    if not isinstance(declared, str):
        message = (
            "Cette route ne declare aucune audience : monter son routeur avec "
            "`dependencies=[Depends(audience_of(...))]`. Sans elle, un jeton de "
            "n'importe quelle application ouvrirait la route."
        )
        raise RuntimeError(message)
    return declared


def _expected_audience(authentication: Authentication, account_type: str) -> str:
    """Traduit le type de compte declare par la route en audience attendue.

    RESOLUE AVANT MEME DE LIRE L'EN-TETE, et c'est ce qui rend la route mal
    cablee reconnaissable : un marqueur mal orthographie repond 500 que
    l'appelant presente un jeton ou non. Laisser `UnknownAccountTypeError`
    s'echapper la ferait sortir en 400 -- une `DomainError` sans categorie,
    c'est-a-dire un refus METIER, pour ce qui est un defaut de cablage.

    Args:
        authentication: le montage ouvert par le `lifespan`.
        account_type: le type de compte declare par le routeur.

    Returns:
        L'audience que le jeton devra viser.

    Raises:
        RuntimeError: si la route declare un type de compte que le service de
            jetons ne connait pas.
    """
    try:
        return authentication.tokens.audience_for(account_type)
    except UnknownAccountTypeError as error:
        message = (
            f"Cette route declare l'audience {account_type!r}, que le service de "
            "jetons ne connait pas : c'est un defaut de cablage du routeur, pas "
            "un refus a servir au client."
        )
        raise RuntimeError(message) from error


def _bearer_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    """Extrait le jeton de l'en-tete `Authorization`, ou refuse.

    UNE VALEUR CLIENTE NE SE RECTIFIE JAMAIS, doctrine deja tenue par
    l'identifiant de requete : deux en-tetes `Authorization` sont un refus, pas
    une occasion de choisir le premier. `Headers.__getitem__` retient le premier
    en silence la ou un mandataire ou l'audit de BACK-27 pourraient lire l'autre.

    Args:
        request: la requete en cours, pour compter les en-tetes.
        credentials: ce que l'extracteur `HTTPBearer` a su lire, ou `None`.

    Returns:
        Le jeton brut, non decode.

    Raises:
        HTTPException: 401 opaque, quelle que soit la cause.
    """
    if len(request.headers.getlist("authorization")) != 1:
        raise _unauthenticated()
    if credentials is None or not credentials.credentials:
        raise _unauthenticated()
    if credentials.scheme.casefold() != _BEARER_SCHEME:
        raise _unauthenticated()
    return credentials.credentials


async def get_current_account(
    request: Request,
    authentication: Annotated[Authentication, Depends(get_authentication)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> AsyncIterator[AuthenticatedAccount]:
    """Identifie le porteur, pose son contexte, et le retire a coup sur.

    LE COMPTE SUSPENDU EST REFUSE ICI, a l'etage bas et non a l'etage au-dessus.
    Les routes de verification d'adresse (BACK-17) dependront de cette
    dependance-ci, parce qu'elles admettent deliberement un compte non verifie ;
    un refus de suspension place seulement plus haut les laisserait admettre un
    compte suspendu par omission, et un suspendu ferait partir des courriels en
    son nom.

    `expected_type` EST CODE EN DUR a `ACCESS`, jamais un parametre : un jeton
    de rafraichissement vit sept jours et ne fait autorite sur rien (regle 3 du
    port). Il n'est lu que par la route de rafraichissement (BACK-29).

    Args:
        request: la requete en cours.
        authentication: le montage ouvert par le `lifespan`.
        credentials: le porteur declare dans l'en-tete `Authorization`.

    Yields:
        Le porteur verifie, `current_account_id` et `current_group_id` poses
        ENSEMBLE pour la duree du traitement, puis retires.

    Raises:
        HTTPException: 401 opaque si le jeton manque, ne se verifie pas, vise
            une autre application, ou designe un compte inconnu.
        SuspendedAccountError: 403 si le compte est suspendu.
    """
    expected_account_type = _expected_account_type(request)
    expected_audience = _expected_audience(authentication, expected_account_type)
    token = _bearer_token(request, credentials)
    try:
        claims = await authentication.tokens.decode_token(
            token, expected_audience=expected_audience, expected_type=TokenType.ACCESS
        )
    except TokenError as error:
        raise _unauthenticated() from error

    # Le jeton porte SON type de compte, et l'emission le pose en meme temps que
    # l'audience -- les deux devraient donc toujours concorder. On le verifie
    # quand meme : le jour ou une emission poserait les deux de travers, ce
    # controle est ce qui empeche un jeton AUTHENTIQUE de particulier d'ouvrir
    # une route professionnelle. Une comparaison de chaines, jamais une
    # deduction depuis le jeton -- ce serait la tautologie que ce module refuse.
    if claims.account_type != expected_account_type:
        raise _unauthenticated()

    # POINT D'ACCROCHE DE BACK-10d : la verification de revocation vient ICI,
    # sur `claims.token_id`, apres le decodage et AVANT la lecture du compte.
    # Rien n'est cable en attendant : une couture neutre testee contre sa propre
    # doublure ne prouverait rien, et `claims` porte deja le `jti` necessaire.

    try:
        account = await authentication.resolve_account(claims.subject)
    except NotFoundError as error:
        # Un jeton parfaitement signe dont le sujet ne designe aucun compte
        # sortirait sinon en 404 `identity.account.not_found` : un oracle sur la
        # cle de signature, et la divulgation du decoupage en modules.
        raise _unauthenticated() from error

    if account.status != ACCOUNT_STATUS_ACTIVE:
        message = "Ce compte est suspendu."
        raise SuspendedAccountError(message)

    with use_account_id(account.id), use_group(claims.active_group_id):
        yield AuthenticatedAccount(claims=claims, email_verified=account.email_verified)


async def get_current_active_account(
    account: Annotated[AuthenticatedAccount, Depends(get_current_account)],
) -> AuthenticatedAccount:
    """Refuse en outre un compte dont l'adresse n'est pas verifiee.

    Le compte reste AUTHENTIFIE -- c'est la regle de BACK-17, et c'est elle qui
    lui permet de demander un nouveau code. La suspension, elle, a deja ete
    refusee un etage plus bas : voir `get_current_account`.

    Args:
        account: le porteur verifie par la dependance basse.

    Returns:
        Le meme porteur, une fois son adresse verifiee.

    Raises:
        UnverifiedEmailError: 403 si l'adresse n'est pas verifiee.
    """
    if not account.email_verified:
        message = "L'adresse de ce compte n'a pas encore ete verifiee."
        raise UnverifiedEmailError(message)
    return account


# Alias a annoter les parametres de route. `CurrentActiveAccount` est le defaut
# a employer ; `CurrentAccount` est reserve aux parcours qui doivent servir un
# compte non verifie -- la verification d'adresse, et elle seule.
CurrentAccount = Annotated[AuthenticatedAccount, Depends(get_current_account)]
CurrentActiveAccount = Annotated[AuthenticatedAccount, Depends(get_current_active_account)]
