"""La fabrique de jetons de test, parametrable par audience, groupe et role.

POURQUOI UNE FABRIQUE, ET PAS SEULEMENT UNE FONCTION (BACK-12)
Le ticket la reclame nommement : « sans elle, chaque test de route reecrira sa
propre emission et divergera ». Ce que BACK-10a et BACK-10c avaient ecrit --
`token_service(...)` et `bearer(...)`, plus bas dans `auth.py` -- servait deja,
mais butait sur un point qu'un test de route ne peut pas contourner : la table
des appartenances etait FIGEE a la construction du service. Or le service doit
etre pose sur `app.state` AVANT que le test ne sache quel role il veut. La
fabrique tient donc une table VIVANTE, que le resolveur relit a chaque emission.

LE ROLE N'EST PAS UN ARGUMENT D'EMISSION, ET LA FABRIQUE NE FAIT PAS SEMBLANT
`create_access_token` n'a pas de parametre `group_role` : le role vient d'un
resolveur, parce qu'une appartenance est une relation datee (ADR-0005) et non
une revendication que l'appelant choisit. `group_role=` inscrit donc
l'appartenance dans la table, puis emet -- le meme trajet qu'en production, avec
un dictionnaire a la place du depot d'`organization`. Et `group_role=None`
n'inscrit rien : c'est ainsi qu'on obtient le refus reel
(`InactiveMembershipError`), au lieu de forger une charge utile qui prouverait
autre chose.

CELUI QUI SIGNE EST CELUI QUI VERIFIE
Une fabrique porte UN service pour toute sa vie, et c'est lui qu'on pose dans
`Authentication`. Emettre deux jetons de roles differents ne doit pas produire
deux services, sinon le second refuserait le premier.

Ce module ne commence pas par `test_` : pytest ne le collecte pas.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from app.core.config import JWTSettings
from app.shared.domain.ports.token_service import TokenType
from app.shared.infrastructure.security.jwt_service import (
    ACCOUNT_TYPE_PROFESSIONAL,
    CLOCK_SKEW_LEEWAY_SECONDS,
    JwtTokenService,
    utc_now,
)

SIGNING_KEY: Final = "cle-de-test-assez-longue-pour-hs256-0123456"
OTHER_SIGNING_KEY: Final = "autre-cle-de-test-assez-longue-pour-hs256-9"

AUDIENCE_PRO: Final = "test-pro"
AUDIENCE_INDIVIDUAL: Final = "test-particulier"
AUDIENCE_ADMIN: Final = "test-admin"

# Role de groupe rendu par defaut a l'emission. L'emission REFUSE un jeton dont
# le groupe actif ne correspond a aucune appartenance active (BACK-10a) : sans
# ce defaut, chaque test devrait semer une appartenance pour un sujet qui n'est
# pas le sien. Les tests qui portent sur le role, eux, passent leur propre table.
DEFAULT_GROUP_ROLE: Final = "manager"

ACCOUNT_ID: Final = UUID("0198c0de-0000-7000-8000-00000000a001")
OTHER_ACCOUNT_ID: Final = UUID("0198c0de-0000-7000-8000-00000000a002")
GROUP_ID: Final = UUID("0198c0de-0000-7000-8000-00000000b001")
OTHER_GROUP_ID: Final = UUID("0198c0de-0000-7000-8000-00000000b002")
CLINIC_ID: Final = UUID("0198c0de-0000-7000-8000-00000000c001")
OTHER_CLINIC_ID: Final = UUID("0198c0de-0000-7000-8000-00000000c002")

# Marge ajoutee au recul d'horloge d'un jeton deja expire. Une seconde
# suffirait ; cinq evitent qu'un poste lent entre l'emission et la verification
# rende le test intermittent.
_EXPIRY_MARGIN: Final = timedelta(seconds=5)


def jwt_settings(*, key: str = SIGNING_KEY, access_minutes: int = 15) -> JWTSettings:
    """Compose une configuration de jetons complete, sans lire l'environnement.

    Jamais `get_settings()` : elle est `lru_cache`ee et exigerait un fichier
    `.env`, ce qui ferait dependre les tests de jetons d'un fichier qui ne les
    concerne pas.
    """
    return JWTSettings(
        secret_key=key,
        access_token_expire_minutes=access_minutes,
        refresh_token_expire_days=7,
        audience_professional=AUDIENCE_PRO,
        audience_individual=AUDIENCE_INDIVIDUAL,
        audience_admin=AUDIENCE_ADMIN,
    )


def bearer_header(token: str) -> dict[str, str]:
    """Compose l'en-tete `Authorization` d'un jeton d'acces.

    Une fonction a part, et non le retour de l'emission : un jeton de
    RAFRAICHISSEMENT voyage dans un corps, pas dans cet en-tete, et le lui coller
    d'office ferait ecrire des tests qui prouvent le contraire de ce qu'ils
    croient.
    """
    return {"Authorization": f"Bearer {token}"}


@dataclass(slots=True)
class TokenFactory:
    """Emet les jetons d'un test, et tient la table d'appartenances qu'ils lisent.

    Un appel, un cas de test. Les quatre cas degrades se fabriquent en DEGRADANT
    L'EMISSION, jamais en forgeant une charge utile :

    - jeton de RAFRAICHISSEMENT : `token_type=TokenType.REFRESH`. Meme service,
      meme signature ; seuls la duree et le claim `type` changent. Comme
      `get_current_account` code `expected_type=ACCESS` en dur, il est refuse
      partout sauf sur la route de rafraichissement (BACK-29).
    - jeton EXPIRE : `expired=True`. Un service jetable a l'horloge d'EMISSION
      reculee, aux memes `JWTSettings` -- donc meme secret et memes audiences :
      c'est bien le service du test qui le refusera, sur son expiration et rien
      d'autre. Une CLE etrangere, elle, se demande par
      `token_service(key=OTHER_SIGNING_KEY)` : cette fabrique n'a qu'UN service,
      et c'est ce qui garantit que le signataire est le verificateur.
    - AUDIENCE incorrecte : `audience=AUDIENCE_INDIVIDUAL` sur une route
      professionnelle. Un jeton authentique d'une AUTRE application, ce qui est
      le cas realiste que l'isolation du cahier des charges vise.
    - groupe INACTIF : `group_role=None`. La table reste vide pour cette paire,
      le resolveur rend `None`, et l'emission leve `InactiveMembershipError`. Le
      refus se produit donc A L'EMISSION et non au decodage : un test doit
      l'attendre sous `pytest.raises`, pas chercher un 401.
    """

    key: str = SIGNING_KEY
    at: datetime | None = None
    access_minutes: int = 15

    # `None` signifie « toute appartenance est reputee active », ce qui est le
    # defaut commode. Un dictionnaire, meme VIDE, signifie « voici les seules
    # appartenances actives » -- et le vide est un cas de test a part entiere.
    roles: dict[tuple[UUID, UUID], str] | None = None

    service: JwtTokenService = field(init=False)

    def __post_init__(self) -> None:
        """Construit le service, sur un resolveur qui relit la table VIVANTE."""
        frozen = datetime.now(UTC).replace(microsecond=0) if self.at is None else self.at

        async def resolve_group_role(
            account_id: UUID, group_id: UUID, when: datetime
        ) -> str | None:
            """Repond comme `MembershipRepository.find_active_role` : le role, ou `None`."""
            if self.roles is None:
                return DEFAULT_GROUP_ROLE
            return self.roles.get((account_id, group_id))

        self.service = JwtTokenService(
            settings=jwt_settings(key=self.key, access_minutes=self.access_minutes),
            resolve_group_role=resolve_group_role,
            now=lambda: frozen,
        )

    def grant(
        self,
        *,
        account_id: UUID = ACCOUNT_ID,
        group_id: UUID = GROUP_ID,
        role: str = DEFAULT_GROUP_ROLE,
    ) -> None:
        """Inscrit une appartenance active, sans emettre."""
        if self.roles is None:
            self.roles = {}
        self.roles[(account_id, group_id)] = role

    def revoke(self, *, account_id: UUID = ACCOUNT_ID, group_id: UUID = GROUP_ID) -> None:
        """Retire une appartenance : l'emission la refusera desormais."""
        if self.roles is None:
            self.roles = {}
        self.roles.pop((account_id, group_id), None)

    async def token(
        self,
        *,
        account_id: UUID = ACCOUNT_ID,
        account_type: str = ACCOUNT_TYPE_PROFESSIONAL,
        audience: str | None = None,
        active_group_id: UUID | None = GROUP_ID,
        group_role: str | None = DEFAULT_GROUP_ROLE,
        token_type: TokenType = TokenType.ACCESS,
        expired: bool = False,
    ) -> str:
        """Emet un jeton et rend sa chaine.

        `audience=None` DERIVE l'audience du type de compte, par la table du
        service -- jamais une seconde table ici : `audience_for` est la seule, et
        la paire mal assortie, erreur la plus frequente, devient impossible par
        defaut sans devenir interdite.
        """
        if active_group_id is not None:
            if group_role is None:
                self.revoke(account_id=account_id, group_id=active_group_id)
            else:
                self.grant(account_id=account_id, group_id=active_group_id, role=group_role)

        signer = self._backdated(token_type) if expired else self.service

        target = signer.audience_for(account_type) if audience is None else audience
        issue = (
            signer.create_access_token
            if token_type is TokenType.ACCESS
            else signer.create_refresh_token
        )
        return await issue(
            account_id=account_id,
            account_type=account_type,
            audience=target,
            active_group_id=active_group_id,
        )

    async def bearer(self, **overrides: object) -> dict[str, str]:
        """Emet un jeton d'acces et rend l'en-tete `Authorization`. Forme courante."""
        return bearer_header(await self.token(**overrides))  # type: ignore[arg-type]

    def _backdated(self, token_type: TokenType) -> JwtTokenService:
        """Un service jetable dont l'horloge d'EMISSION est reculee.

        L'HORLOGE NE PILOTE QUE L'EMISSION -- aucun argument ne remplace celle
        que PyJWT emploie pour verifier. Un jeton deja expire ne se fabrique donc
        pas en avancant le temps au decodage : il se fabrique en emettant DANS LE
        PASSE, de sa duree de vie plus la tolerance d'horloge du decodeur plus une
        marge. Le recul est DERIVE de la configuration et du type de jeton, jamais
        ecrit en dur : un `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` releve rendrait une
        constante fausse en silence, et le test passerait au vert sans rien prouver.

        Memes `JWTSettings` que le service du test -- donc meme secret et memes
        audiences : c'est bien lui qui refusera le jeton, sur son expiration et
        rien d'autre. Une CLE etrangere se demande autrement, par
        `token_service(key=OTHER_SIGNING_KEY)` : cette fabrique-ci n'a qu'un
        service, et lui en donner deux la ferait mentir sur sa propre promesse.
        """
        settings = jwt_settings(key=self.key, access_minutes=self.access_minutes)
        lifetime = (
            timedelta(minutes=settings.access_token_expire_minutes)
            if token_type is TokenType.ACCESS
            else timedelta(days=settings.refresh_token_expire_days)
        )
        backdate = lifetime + timedelta(seconds=CLOCK_SKEW_LEEWAY_SECONDS) + _EXPIRY_MARGIN

        async def resolve_group_role(
            account_id: UUID, group_id: UUID, when: datetime
        ) -> str | None:
            """Lit la MEME table que le service du test : le sujet est ailleurs."""
            if self.roles is None:
                return DEFAULT_GROUP_ROLE
            return self.roles.get((account_id, group_id))

        return JwtTokenService(
            settings=settings,
            resolve_group_role=resolve_group_role,
            now=lambda: utc_now() - backdate,
        )
