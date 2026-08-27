"""Adaptateur PyJWT du port `TokenService` (BACK-10a).

Tout ce que le port refuse de connaitre vit ici : la bibliotheque de signature,
l'algorithme, le secret, les durees de vie et la table des audiences. Le port
reste importable sans PyJWT, ce que le contrat `domain-purity` verifie a chaque
`make check`.

CE QUE LES DEFAUTS DE PyJWT NE FONT PAS, ET QU'IL A FALLU DEMANDER
Les cinq options ci-dessous ont ete verifiees en executant PyJWT 2.13, pas
lues dans sa documentation. Aucune n'est decorative :

- `require` -- PyJWT garde CHAQUE controle derriere « si le claim est present ».
  Sans cette clause, un jeton depourvu d'`exp` est accepte, et il n'expire
  jamais. C'est le defaut le plus dangereux de la bibliotheque, et le plus
  silencieux : le jeton est valide, signe, et eternel.
- `strict_aud` -- sans lui, un `aud` sous forme de LISTE contenant l'audience
  attendue passe. Un jeton adresse a la fois au professionnel et au particulier
  serait recevable des deux cotes, ce qui vide de son sens la separation que ce
  ticket pose.
- `enforce_minimum_key_length` -- vaut `False` par defaut : une cle de cinq
  octets ne declenche qu'un avertissement, et rien dans ce depot ne transforme
  les avertissements en erreurs. `JWTSettings` borne deja la longueur PAR
  ALGORITHME, si bien que cette option ne devrait jamais mordre : c'est une
  seconde barriere, franchissable seulement par un service construit sans passer
  par la configuration. Elle a servi une fois -- a reveler que la premiere
  barriere comptait des caracteres la ou le RFC compte des octets.
- `algorithms` -- liste FERMEE, derivee du `Literal` de la configuration. C'est
  elle qui refuse un jeton annoncant `alg: none`.
- `leeway` -- voir `CLOCK_SKEW_LEEWAY_SECONDS` plus bas.

L'HORLOGE DE L'EMISSION N'EST PAS CELLE DE LA VERIFICATION
`now` est injectable, et ne pilote QUE l'emission : PyJWT compare `exp` a
l'horloge murale reelle, qu'aucun argument ne remplace. Un test qui croirait
avancer l'horloge pour faire expirer un jeton au decodage ne testerait rien --
il faut emettre avec une horloge reculee, ce que fait la suite de tests.

UN SEUL INSTANT PAR EMISSION
Le meme instant alimente `iat`, `exp` et la date a laquelle l'appartenance est
jugee active. Deux appels a l'horloge suffiraient a produire un jeton disant
« au moment ou je t'ai emis, cette appartenance etait active » alors que la
verification aurait porte sur un autre instant. Le port d'appartenance de
BACK-16 le demande d'ailleurs par ecrit.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid7

import jwt
from jwt.types import Options

from app.core.config import JWTSettings, Settings
from app.shared.domain.ports.token_service import (
    ActiveGroupRoleResolver,
    ExpiredTokenError,
    InactiveMembershipError,
    InvalidAudienceError,
    InvalidSignatureError,
    MalformedTokenError,
    MembershipLookupFailedError,
    NaiveInstantError,
    TokenClaims,
    TokenError,
    TokenIssuanceError,
    TokenNotYetValidError,
    TokenService,
    TokenType,
    UnknownAccountTypeError,
    UnknownAudienceError,
    WrongTokenTypeError,
)

# Les quatre claims propres au service, nommes une fois. Les cinq autres --
# `sub`, `exp`, `iat`, `jti`, `aud` -- sont enregistres par le RFC 7519 et PyJWT
# les traite specialement : ils restent des litteraux, comme dans sa propre API.
_CLAIM_TYPE: Final = "type"
_CLAIM_ACCOUNT_TYPE: Final = "account_type"
_CLAIM_ACTIVE_GROUP_ID: Final = "active_group_id"
_CLAIM_GROUP_ROLE: Final = "group_role"

# Les trois types de compte, tels qu'`identity` les nomme (`AccountType`).
#
# RECOPIES ET NON IMPORTES : le contrat `service-spaces` interdit a `app.shared`
# d'importer un module. La derive est surveillee par un test qui, lui, a le droit
# d'importer les deux cotes et compare les deux jeux de valeurs.
ACCOUNT_TYPE_PROFESSIONAL: Final = "professional"
ACCOUNT_TYPE_INDIVIDUAL: Final = "individual"
ACCOUNT_TYPE_ADMIN: Final = "admin"
ACCOUNT_TYPES: Final = (ACCOUNT_TYPE_PROFESSIONAL, ACCOUNT_TYPE_INDIVIDUAL, ACCOUNT_TYPE_ADMIN)

# Les options de decodage, nommees pour etre RELISIBLES ET TESTABLES. Trois des
# cinq corrections que ce module apporte a PyJWT vivent ici, et deux d'entre
# elles sont invisibles au comportement -- `require` fait double emploi avec la
# reconstruction, `enforce_minimum_key_length` avec la configuration. Les
# laisser en argument litteral les aurait rendues supprimables par megarde sans
# qu'aucun test ne bronche ; une constante se verrouille.
_DECODE_OPTIONS: Final[Options] = {
    # `active_group_id` et `group_role` NE SONT PAS dans `require`, et ce n'est
    # pas un oubli : PyJWT y refuse un claim dont la valeur est `null` autant
    # qu'un claim absent. Les y mettre ferait echouer tous les jetons de comptes
    # particuliers, qui n'appartiennent a aucun groupe -- le cas nominal. Leur
    # absence PURE est rattrapee a la reconstruction, qui les lit sans repli.
    "require": ["exp", "iat", "jti", "sub", "aud", _CLAIM_TYPE, _CLAIM_ACCOUNT_TYPE],
    "strict_aud": True,
    "enforce_minimum_key_length": True,
}

# Tolerance d'horloge, en secondes, appliquee a `exp` comme a `iat`.
#
# CONSTANTE ET NON VARIABLE D'ENVIRONNEMENT. Ce que cette valeur absorbe, c'est
# la derive entre deux instances du meme service derriere un repartiteur : une
# seconde, pas dix minutes. Un reglage inviterait a l'elargir le jour ou un
# jeton expire genera quelqu'un, et une tolerance large prolonge exactement ce
# qu'on cherche a borner. Sans elle, cinq secondes d'avance sur une machine
# suffisent a faire refuser ses jetons par la voisine.
CLOCK_SKEW_LEEWAY_SECONDS: Final = 10


def utc_now() -> datetime:
    """Rend l'instant courant, avec fuseau.

    Returns:
        L'instant courant en UTC. Horloge murale et non monotone : un `exp` est
        une DATE, lisible par un autre processus, pas une duree ecoulee.
    """
    return datetime.now(UTC)


class JwtTokenService(TokenService):
    """Emetteur et verificateur de jetons adosse a PyJWT, echouant ferme.

    Ne detient rien entre deux appels : ni connexion, ni etat. Deux instances
    construites de la meme configuration sont interchangeables, ce qui rend le
    service utilisable depuis une tache de fond comme depuis une requete.
    """

    def __init__(
        self,
        *,
        settings: JWTSettings,
        resolve_group_role: ActiveGroupRoleResolver,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        """Assemble le service a partir de sa configuration et de son resolveur.

        Args:
            settings: la section `JWT_` de la configuration -- secret,
                algorithme, durees et les trois audiences.
            resolve_group_role: la question posee au module `organization` a
                chaque emission portant un groupe actif.
            now: l'horloge de l'EMISSION. Injectable pour les tests ; elle ne
                pilote pas la verification, que PyJWT date lui-meme.
        """
        self._secret = settings.secret_key.get_secret_value()
        self._algorithm = settings.algorithm
        self._access_lifetime = timedelta(minutes=settings.access_token_expire_minutes)
        self._refresh_lifetime = timedelta(days=settings.refresh_token_expire_days)
        self._audience_by_account_type = {
            ACCOUNT_TYPE_PROFESSIONAL: settings.audience_professional,
            ACCOUNT_TYPE_INDIVIDUAL: settings.audience_individual,
            ACCOUNT_TYPE_ADMIN: settings.audience_admin,
        }
        self._declared_audiences = frozenset(self._audience_by_account_type.values())
        self._resolve_group_role = resolve_group_role
        self._now = now
        # Un codec dedie plutot que les fonctions de module : `jwt.encode` n'a
        # pas de parametre `options`, et c'est le seul moyen d'exiger la longueur
        # minimale de cle A LA SIGNATURE et non seulement a la verification.
        self._codec = jwt.PyJWT(options={"enforce_minimum_key_length": True})

    def audience_for(self, account_type: str) -> str:
        """Rend l'audience de l'application qui sert ce type de compte.

        LA TABLE EST ICI, ET NULLE PART AILLEURS. BACK-29 doit confronter
        l'audience demandee au type de compte pour qu'un particulier n'obtienne
        jamais un jeton d'audience professionnelle ; il lit cette methode plutot
        que de recopier la correspondance, faute de quoi deux tables
        divergeraient un jour.

        Args:
            account_type: le type de compte, tel qu'`identity` le nomme.

        Returns:
            L'audience configuree pour ce type de compte.

        Raises:
            UnknownAccountTypeError: si ce type de compte n'a pas d'audience --
                signe que la table a derive de l'enumeration d'`identity`.
        """
        audience = self._audience_by_account_type.get(account_type)
        if audience is None:
            message = f"Aucune audience declaree pour le type de compte {account_type!r}."
            raise UnknownAccountTypeError(message)
        return audience

    async def create_access_token(
        self,
        *,
        account_id: UUID,
        account_type: str,
        audience: str,
        active_group_id: UUID | None = None,
    ) -> str:
        """Emet un jeton d'acces court, apres verification de l'appartenance.

        Args:
            account_id: le compte authentifie.
            account_type: le type de compte, tel qu'`identity` le nomme.
            audience: l'application destinataire.
            active_group_id: le groupe actif, ou `None`.

        Returns:
            Le jeton signe.

        Raises:
            UnknownAudienceError: si l'audience n'est pas declaree.
            InactiveMembershipError: si l'appartenance n'est pas active.
        """
        return await self._issue(
            TokenType.ACCESS,
            account_id=account_id,
            account_type=account_type,
            audience=audience,
            active_group_id=active_group_id,
        )

    async def create_refresh_token(
        self,
        *,
        account_id: UUID,
        account_type: str,
        audience: str,
        active_group_id: UUID | None = None,
    ) -> str:
        """Emet un jeton de rafraichissement long, aux memes verifications.

        Args:
            account_id: le compte authentifie.
            account_type: le type de compte, tel qu'`identity` le nomme.
            audience: l'application destinataire.
            active_group_id: le groupe actif, ou `None`.

        Returns:
            Le jeton signe.

        Raises:
            UnknownAudienceError: si l'audience n'est pas declaree.
            InactiveMembershipError: si l'appartenance n'est pas active.
        """
        return await self._issue(
            TokenType.REFRESH,
            account_id=account_id,
            account_type=account_type,
            audience=audience,
            active_group_id=active_group_id,
        )

    async def decode_token(
        self, token: str, *, expected_audience: str, expected_type: TokenType
    ) -> TokenClaims:
        """Verifie un jeton de bout en bout, puis rend ce qu'il affirme.

        LA RECONSTRUCTION VIT DANS LE MEME BLOC QUE LE DECODAGE, et ce n'est pas
        un raccourci d'ecriture : un `sub` qui n'est pas un identifiant leve une
        `ValueError`, un claim absent une `KeyError`, un `exp` non numerique une
        `TypeError`. Aucune n'est une erreur metier -- laissees dehors, elles
        rendraient 500 avec une trace complete sur un evenement d'authentification
        parfaitement ordinaire.

        Args:
            token: la chaine presentee par l'appelant.
            expected_audience: l'audience de l'application qui recoit la requete.
            expected_type: le type attendu a cet endroit du service.

        Returns:
            Les claims verifies.

        Raises:
            ExpiredTokenError: si le jeton a expire.
            TokenNotYetValidError: si sa date d'emission est dans le futur.
            InvalidSignatureError: si la signature ne correspond pas.
            InvalidAudienceError: si l'audience differe, ou manque.
            WrongTokenTypeError: si le type n'est pas celui attendu.
            MalformedTokenError: si le jeton est illisible ou incomplet.
        """
        try:
            payload = self._codec.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=expected_audience,
                leeway=CLOCK_SKEW_LEEWAY_SECONDS,
                options=_DECODE_OPTIONS,
            )
            _ensure_expected_type(payload, expected_type)
            return _to_claims(payload)
        except jwt.ExpiredSignatureError as error:
            raise ExpiredTokenError("Le jeton a expire.") from error
        except jwt.ImmatureSignatureError as error:
            # `InvalidIssuedAtError` N'EST PAS ici, et c'est delibere : PyJWT la
            # leve pour un `iat` INTYPABLE, pas pour un `iat` futur. La ranger
            # avec la derive d'horloge enverrait chercher un NTP en retard la ou
            # il n'y a qu'un defaut de serialisation. Elle descend
            # d'`InvalidTokenError` et tombe donc sur « malforme », plus bas.
            raise TokenNotYetValidError("Le jeton n'est pas encore valide.") from error
        except jwt.MissingRequiredClaimError as error:
            # L'ordre compte : cette classe est SOEUR de `InvalidAudienceError`
            # et non sa fille. Un jeton depourvu d'audience passerait pour
            # « malforme » alors que c'est le cas d'audience le plus grave --
            # sans `aud`, il serait recevable partout.
            if error.claim == "aud":
                raise InvalidAudienceError("Le jeton ne vise aucune application.") from error
            raise MalformedTokenError("Le jeton est incomplet.") from error
        except jwt.InvalidAudienceError as error:
            raise InvalidAudienceError("Le jeton ne vise pas cette application.") from error
        except jwt.InvalidSignatureError as error:
            raise InvalidSignatureError("La signature du jeton est invalide.") from error
        except (jwt.InvalidTokenError, jwt.InvalidKeyError) as error:
            # `InvalidKeyError` est nommee a part : elle descend de `PyJWTError`
            # mais PAS d'`InvalidTokenError`, et sortirait donc du bloc.
            raise MalformedTokenError("Le jeton est illisible.") from error
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
            # `OverflowError` et `OSError` ne sont pas du zele : un `exp` valant
            # 2**62 fait sortir `datetime.fromtimestamp` de la plage de la
            # plateforme, et ni l'une ni l'autre ne descend de `ValueError`.
            # Sans elles, un jeton signe de la bonne cle rendrait 500, avec une
            # trace complete, sur un evenement d'authentification banal.
            raise MalformedTokenError("Le jeton porte un claim inexploitable.") from error

    async def _issue(
        self,
        token_type: TokenType,
        *,
        account_id: UUID,
        account_type: str,
        audience: str,
        active_group_id: UUID | None,
    ) -> str:
        """Compose et signe un jeton, une fois toutes les verifications faites.

        L'ORDRE DES TROIS GESTES EST DELIBERE : l'audience d'abord, parce qu'elle
        ne coute rien et qu'une audience inconnue est un bug d'appelant ;
        l'instant ensuite, fige pour la suite ; l'appartenance enfin, seule a
        toucher la base.

        Args:
            token_type: le type de jeton a produire.
            account_id: le compte authentifie.
            account_type: le type de compte.
            audience: l'application destinataire.
            active_group_id: le groupe actif, ou `None`.

        Returns:
            Le jeton signe.

        Raises:
            UnknownAudienceError: si l'audience n'est pas declaree.
            InactiveMembershipError: si l'appartenance n'est pas active.
        """
        if account_type not in self._audience_by_account_type:
            # Un `account_type` inconnu produirait un jeton parfaitement signe
            # que ce meme service refuserait ensuite de relire -- et il decide,
            # chez BACK-29, de l'application qui a le droit de servir ce compte.
            message = f"Type de compte inconnu : {account_type!r}."
            raise UnknownAccountTypeError(message)
        if audience not in self._declared_audiences:
            message = f"Audience inconnue : {audience!r}."
            raise UnknownAudienceError(message)
        issued_at = self._instant()
        group_role = await self._resolve_active_role(account_id, active_group_id, issued_at)
        lifetime = (
            self._access_lifetime if token_type is TokenType.ACCESS else self._refresh_lifetime
        )
        payload: dict[str, Any] = {
            "sub": str(account_id),
            "iat": issued_at,
            "exp": issued_at + lifetime,
            # Chaine et non UUID : PyJWT refuse un `jti` qui n'en est pas une, et
            # `json.dumps` ne sait de toute facon pas serialiser un UUID.
            "jti": str(uuid7()),
            "aud": audience,
            _CLAIM_TYPE: token_type.value,
            _CLAIM_ACCOUNT_TYPE: account_type,
            _CLAIM_ACTIVE_GROUP_ID: None if active_group_id is None else str(active_group_id),
            _CLAIM_GROUP_ROLE: group_role,
        }
        try:
            return self._codec.encode(payload, self._secret, algorithm=self._algorithm)
        except Exception as error:
            # La configuration ecarte deja les deux causes connues -- cle trop
            # courte pour l'algorithme, duree assez grande pour faire deborder
            # la date. Ce filet couvre ce qu'elle ne voit pas, et tient la
            # promesse du port : aucune exception de la bibliotheque de
            # signature ne sort d'ici, et aucun jeton ne sort non plus.
            message = "La signature du jeton a echoue : aucun jeton n'est emis."
            raise TokenIssuanceError(message) from error

    def _instant(self) -> datetime:
        """Fige l'instant de l'emission, en refusant une horloge sans fuseau.

        Returns:
            L'instant de l'emission, avec fuseau.

        Raises:
            NaiveInstantError: si l'horloge injectee rend un instant naif.
        """
        instant = self._now()
        if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
            message = "L'horloge du service de jetons doit rendre un instant avec fuseau."
            raise NaiveInstantError(message)
        return instant

    async def _resolve_active_role(
        self, account_id: UUID, active_group_id: UUID | None, at: datetime
    ) -> str | None:
        """Resout le role de groupe, ou refuse d'emettre.

        Args:
            account_id: le compte pour lequel le jeton est emis.
            active_group_id: le groupe demande, ou `None` pour un compte sans
                appartenance -- aucun appel n'est alors fait au resolveur.
            at: l'instant de l'emission, deja fige.

        Returns:
            Le role de perimetre groupe, ou `None` quand aucun groupe n'est
            demande.

        Raises:
            InactiveMembershipError: si aucune appartenance active ne repond.
            MembershipLookupFailedError: si le resolveur echoue.
        """
        if active_group_id is None:
            return None
        try:
            role = await self._resolve_group_role(account_id, active_group_id, at)
        except TokenError:
            # Un resolveur qui REFUSE plutot que de rendre `None` -- une
            # implementation future levant `NotFoundError`, par exemple -- garde
            # son refus et son statut. L'envelopper le transformerait en panne
            # 500, alors que tout le double parentage d'`InactiveMembershipError`
            # vise un 404 non divulguant.
            raise
        except Exception as error:
            message = "La verification de l'appartenance a echoue : aucun jeton n'est emis."
            raise MembershipLookupFailedError(message) from error
        if role is not None and (not isinstance(role, str) or not role):
            # Un role vide ou d'un autre type est un defaut de cablage, pas un
            # refus : il produirait un claim que toute garde `if group_role`
            # laisserait passer pour une absence de role.
            message = f"Le resolveur d'appartenance a rendu un role inexploitable : {role!r}."
            raise MembershipLookupFailedError(message)
        if role is None:
            # MESSAGE UNIQUE POUR TROIS SITUATIONS : appartenance terminee, pas
            # encore commencee, ou groupe auquel ce compte n'a jamais appartenu.
            # Les distinguer dirait a l'appelant si le groupe existe.
            message = "Aucune appartenance active a ce groupe."
            raise InactiveMembershipError(message)
        return role


def _ensure_expected_type(payload: dict[str, Any], expected_type: TokenType) -> None:
    """Refuse un jeton du bon service mais du mauvais type.

    Args:
        payload: la charge utile deja verifiee cryptographiquement.
        expected_type: le type attendu a cet endroit du service.

    Raises:
        WrongTokenTypeError: si le claim `type` n'est pas celui attendu.
    """
    if payload.get(_CLAIM_TYPE) != expected_type.value:
        message = f"Ce jeton n'est pas un jeton de type {expected_type.value!r}."
        raise WrongTokenTypeError(message)


def _to_claims(payload: dict[str, Any]) -> TokenClaims:
    """Retype la charge utile dans le vocabulaire du domaine.

    Args:
        payload: la charge utile verifiee -- chaines et entiers uniquement.

    Returns:
        Les claims, identifiants et instants reconstruits.

    Raises:
        KeyError: si un claim attendu manque.
        ValueError: si un identifiant ou le type de jeton est illisible.
        TypeError: si un instant n'est pas numerique.
    """
    active_group_id = payload[_CLAIM_ACTIVE_GROUP_ID]
    group_role = payload[_CLAIM_GROUP_ROLE]
    if (active_group_id is None) != (group_role is None):
        # L'INVARIANT QUE L'EMISSION TIENT, VERIFIE A LA RELECTURE. Un role sans
        # groupe est precisement la combinaison qu'une garde de role mal ecrite
        # accepterait, alors qu'aucun perimetre ne s'y applique.
        message = "Un jeton porte un role de groupe sans groupe actif, ou l'inverse."
        raise ValueError(message)
    if group_role is not None and not isinstance(group_role, str):
        message = "Le role de groupe n'est pas une chaine."
        raise ValueError(message)
    return TokenClaims(
        subject=UUID(payload["sub"]),
        token_type=TokenType(payload[_CLAIM_TYPE]),
        audience=payload["aud"],
        account_type=payload[_CLAIM_ACCOUNT_TYPE],
        token_id=UUID(payload["jti"]),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        active_group_id=None if active_group_id is None else UUID(active_group_id),
        group_role=group_role,
    )


def build_token_service(
    settings: Settings,
    resolve_group_role: ActiveGroupRoleResolver,
    *,
    now: Callable[[], datetime] = utc_now,
) -> JwtTokenService:
    """Construit le service de jetons, sans ouvrir la moindre connexion.

    Comme `build_email_transport`, et pour une raison plus forte encore : il n'y
    a rien a ouvrir. Le resolveur, lui, est fourni par le point de composition --
    `app.shared` n'a pas le droit d'importer `app.modules`, et seul `main.py`
    peut connaitre deux modules a la fois. C'est BACK-10c qui posera ce montage
    avec ses dependances FastAPI.

    Args:
        settings: la configuration du service.
        resolve_group_role: la question posee au module `organization`.
        now: l'horloge de l'emission.

    Returns:
        Le service, pret a emettre et a verifier.
    """
    return JwtTokenService(settings=settings.jwt, resolve_group_role=resolve_group_role, now=now)
