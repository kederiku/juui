"""Port d'emission et de verification des jetons d'authentification (BACK-10a).

Le contrat, jamais son adaptateur : ce module ne connait ni PyJWT, ni HS256, ni
la configuration. Il ne peut d'ailleurs pas les connaitre -- le contrat
`domain-purity` de BACK-04b nomme `jwt` parmi les paquets interdits au domaine,
et refuse aussi les chaines INDIRECTES, `app.core` compris. Les durees de vie,
le secret et la liste des audiences vivent donc dans l'adaptateur, qui seul lit
`Settings`.

CE QU'IL FAIT DEVANT UNE PANNE : IL LEVE, ET N'EMET RIEN
La question que chaque port du noyau partage doit trancher. `Cache` DEGRADE,
parce qu'un cache absent ne change qu'une latence ; `TokenService` ne degrade
sur rien. Un jeton emis alors que l'appartenance n'a pas pu etre verifiee est
une elevation de privilege qui vivra jusqu'a son expiration -- quinze minutes
pendant lesquelles personne ne saura qu'elle a eu lieu. Emettre moins est
toujours preferable a emettre a l'aveugle.

CE QUI N'EST PAS UN ARGUMENT NE PEUT PAS ETRE MENTI
`group_role` ne figure dans aucune signature d'emission : il se RESOUT aupres du
depot d'appartenances, a l'instant meme de l'emission. Un appelant ne peut donc
pas se declarer gerant, et le cas d'usage qui voudrait tricher n'a pas de
parametre pour le faire. C'est la difference entre une regle ecrite dans une
docstring et une regle que la signature rend inexprimable.

`active_group_id`, lui, EST un argument -- l'appelant dit dans quel groupe il
veut travailler -- mais il n'est pas DECLARATIF : l'implementation le confronte
au depot et refuse si l'appartenance n'est pas active a cet instant.
`audience` est un argument sans confrontation : quelle application a le droit de
recevoir quel type de compte est une regle de PARCOURS, tranchee par BACK-29 au
moment de la connexion, qui lit pour cela la table exposee par l'adaptateur.

CE QUI TRAVERSE LA FRONTIERE VOYAGE EN CHAINE
`account_type` vient d'`identity`, `group_role` d'`organization`, et le contrat
`service-spaces` interdit a `app.shared` d'importer un module. Ces deux valeurs
sont donc typees `str` ici, et non `AccountType` ni `GroupRole`. Ce n'est pas un
appauvrissement : un claim JSON est une chaine de toute facon, et `GroupRole`
est un `StrEnum`, donc EST une chaine -- l'implementation rend ses valeurs sans
la moindre conversion.

LE PORT NE PARLE PAS DE REVOCATION
`jti` est present dans les claims, et c'est tout ce que ce ticket en fait. La
liste de revocation, sa duree de vie et la revocation en masse par `sub` sont
l'objet de BACK-10d ; un jeton decode ici est valide au sens CRYPTOGRAPHIQUE,
jamais au sens « toujours autorise ».
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from app.shared.domain.exceptions import DomainError, NotFoundError


class TokenType(StrEnum):
    """Ce qu'un jeton est autorise a faire, inscrit dans le claim `type`.

    Deux jetons signes de la meme cle ne sont pas interchangeables : un jeton de
    rafraichissement vit sept jours et n'ouvre qu'une route, un jeton d'acces
    vit quinze minutes et ouvre tout le service. Sans ce claim, le premier
    servirait de second pendant une semaine -- c'est pourquoi `decode_token`
    EXIGE le type attendu plutot que de l'offrir en option.
    """

    ACCESS = "access"
    REFRESH = "refresh"

    # POUR BACK-10e : le jeton de portee reduite « selection de groupe » sera un
    # MEMBRE DE CETTE ENUMERATION, jamais un claim `scope` pose a cote. Un claim
    # lateral serait ignore par `decode_token`, et tout appelant attendant un
    # jeton d'acces l'accepterait comme un acces plein -- sans que `TokenClaims`
    # donne le moyen de s'en apercevoir.


# La seule question que l'emission pose au module `organization` : « quel role ce
# compte tient-il dans ce groupe, a cet instant, si son appartenance est
# active ? ». Rend `None` quand aucune appartenance active ne repond.
#
# UN ALIAS DE FONCTION ET NON UN HUITIEME PORT. La signature de
# `MembershipRepository.find_active_role` (BACK-16) la satisfait telle quelle,
# `GroupRole` etant un `StrEnum` : un port intermediaire n'aurait rien a
# convertir, et son adaptateur serait une enveloppe d'une ligne. Meme parti que
# `Clock` dans les doublures -- il n'y a rien a nommer de plus qu'une fonction.
#
# L'INSTANT EST UN ARGUMENT, ET IL PORTE TOUJOURS UN FUSEAU. L'implementation
# fige UN instant pour toute l'emission, de sorte que le `iat` du jeton et la
# date a laquelle l'appartenance a ete jugee active soient le meme instant. Le
# depot de BACK-16 refuse un instant naif.
type ActiveGroupRoleResolver = Callable[[UUID, UUID, datetime], Awaitable[str | None]]


class TokenError(DomainError):
    """Racine des erreurs de ce port -- emission comme verification.

    Toutes les erreurs que ce port laisse sortir descendent d'ici, et AUCUNE
    exception de la bibliotheque de signature n'en sort : c'est la promesse qui
    permet a un cas d'usage d'ecrire `except TokenError` sans jamais importer
    PyJWT.

    AUCUNE DE CES ERREURS NE PORTE DE `details` DERIVE DU JETON. Le journal
    redige les fragments sensibles (BACK-11), la REPONSE HTTP non : un
    `details={"token": ...}` pose par reflexe de debogage renverrait le jeton au
    client, ou il finirait dans ses propres journaux d'acces.

    CE QUE LE CLIENT EN VERRA N'EST PAS DECIDE ICI. Ces classes sont distinctes
    pour que le code appelant sache ce qui s'est passe ; la bordure HTTP
    (BACK-10c) reste libre de les fondre dans un unique 401 sans detail. Le
    ticket demande des erreurs explicites, pas des reponses bavardes.
    """

    code: ClassVar[str] = "shared.token.invalid"


class ExpiredTokenError(TokenError):
    """Le jeton a depasse sa date d'expiration.

    La SEULE de la famille qu'un client a interet a distinguer : elle lui dit de
    rafraichir plutot que de se reconnecter. Les autres ne lui apprendraient
    rien qu'il puisse corriger.
    """

    code: ClassVar[str] = "shared.token.expired"


class TokenNotYetValidError(TokenError):
    """Le jeton est date du futur : les horloges ne sont pas d'accord.

    Distincte de `MalformedTokenError`, et ce n'est pas un luxe de taxonomie :
    deux instances derriere un repartiteur dont l'une derive de quelques
    secondes se refusent mutuellement leurs jetons. Ranger ce cas dans
    « malforme » enverrait chercher un bug de serialisation la ou il n'y a qu'un
    NTP en retard. L'implementation tolere une derive courte avant de lever.
    """

    code: ClassVar[str] = "shared.token.not_yet_valid"


class InvalidSignatureError(TokenError):
    """La signature ne correspond pas a la cle du service.

    Jeton forge, ou cle de signature changee depuis l'emission -- ce qui couvre
    le jeton venu d'un autre environnement, mais par le SECRET seul : les
    audiences, elles, portent les memes valeurs partout, et ne separent pas la
    recette de la production. Nom nu malgre la classe homonyme de PyJWT : la
    convention du depot veut que ce soit la bibliotheque tierce qui prenne
    l'alias.
    """

    code: ClassVar[str] = "shared.token.invalid_signature"


class MalformedTokenError(TokenError):
    """Le jeton est illisible, incomplet, ou porte un claim intypable.

    Fourre-tout ASSUME, et delimite : tout ce qui n'est ni une expiration, ni
    une signature fausse, ni une audience refusee, ni un type inattendu. Un
    jeton auquel il manque `exp`, un `sub` qui n'est pas un identifiant, un
    en-tete annoncant un algorithme hors de la liste fermee tombent ici.
    """

    code: ClassVar[str] = "shared.token.malformed"


class WrongTokenTypeError(TokenError):
    """Le jeton est valide, mais ce n'est pas le type attendu a cet endroit.

    Les deux sens comptent : un jeton de rafraichissement presente a une route
    metier est une session de sept jours au lieu de quinze minutes, et un jeton
    d'acces presente au rafraichissement casse la rotation de BACK-29.
    """

    code: ClassVar[str] = "shared.token.wrong_type"


class InvalidAudienceError(TokenError):
    """Le jeton ne vise pas l'application qui le presente -- ou ne vise personne.

    LA verification qui tient l'isolation des trois applications. Un jeton de
    compte particulier reste techniquement presentable a l'API professionnelle :
    seule cette comparaison l'arrete, et c'est pourquoi elle est faite a chaque
    decodage plutot qu'une fois a l'emission.

    Un jeton DEPOURVU d'audience leve la meme erreur qu'un jeton mal adresse.
    C'est voulu : l'absence est le cas le plus dangereux des deux, puisqu'un
    jeton sans `aud` serait recevable partout.
    """

    code: ClassVar[str] = "shared.token.invalid_audience"


class UnknownAudienceError(TokenError):
    """L'audience demandee a l'emission n'est declaree nulle part.

    Erreur d'APPELANT ou de configuration, jamais de porteur de jeton : elle ne
    peut se produire qu'a l'emission, quand le code demande une audience qui
    n'est aucune des trois du service. Sans elle, une faute de frappe produirait
    des jetons parfaitement signes que plus aucune application n'accepterait.
    """

    code: ClassVar[str] = "shared.token.unknown_audience"


class UnknownAccountTypeError(TokenError):
    """Le type de compte fourni a l'emission n'est pas un type connu du service.

    Erreur d'APPELANT, jamais de porteur de jeton. Elle existe parce que ce
    claim n'est pas decoratif : `account_type` decide de l'application qui doit
    servir ce compte, et un jeton qui en porte un inconnu -- ou nul -- est un
    jeton que le service refusera ensuite de relire. Mieux vaut ne pas l'emettre.
    """

    code: ClassVar[str] = "shared.token.unknown_account_type"


class InactiveMembershipError(TokenError, NotFoundError):
    """Le compte n'a pas d'appartenance active au groupe demande.

    Levee A L'EMISSION : c'est ce refus qui rend `active_group_id` non
    declaratif. Une appartenance arrivee a son terme, une appartenance a venir,
    ou un groupe auquel le compte n'a jamais appartenu donnent tous la meme
    erreur et le meme message.

    DEUX PARENTS, ET CHACUN SERT. `TokenError` d'abord, pour qu'un
    `except TokenError` pose autour de l'emission ne la rate pas. `NotFoundError`
    ensuite, pour la regle de non-divulgation de BACK-09 : un refus de droit
    confirmerait l'existence du groupe chez un concurrent. L'adaptateur d'API
    resout par `isinstance` sur un tuple ordonne ou `NotFoundError` vient en
    tete, la reponse est donc un 404 -- ce qui est l'effet recherche.
    """

    code: ClassVar[str] = "shared.token.membership_not_active"


class TokenIssuanceError(RuntimeError):
    """Panne TECHNIQUE a l'emission : le service n'a pas pu conclure.

    Hors de la hierarchie `DomainError`, et c'est le sujet -- meme parti que
    `EmailDeliveryError`. Une base injoignable ou une horloge mal injectee ne
    sont pas des refus metier : les deguiser en 4xx dirait a l'appelant qu'il a
    fait quelque chose de travers. Elles sortent donc en 500, avec leur trace au
    journal. Le point commun avec un refus, en revanche, est entier : AUCUN
    jeton n'est emis.
    """


class NaiveInstantError(TokenIssuanceError):
    """L'horloge de l'emetteur a rendu un instant sans fuseau.

    Refuse au plus tot. Un instant naif transmis au depot d'appartenances y
    declencherait un refus de VALIDATION -- traduit en 422 -- et une connexion
    repondrait « valeur invalide » a un utilisateur qui n'a rien saisi de faux.
    """


class MembershipLookupFailedError(TokenIssuanceError):
    """La resolution de l'appartenance a echoue -- et aucun jeton n'est sorti.

    Enveloppe ce que le resolveur laisse remonter d'imprevu : panne de base,
    contexte manquant, role illisible. Le port ne connait aucune de ces erreurs
    et n'a pas a les connaitre ; ce qu'il garantit, c'est qu'un echec de lecture
    ne devient jamais un jeton sans role, ni un jeton tout court.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenClaims:
    """Ce qu'un jeton VERIFIE affirme, retype dans le vocabulaire du domaine.

    N'existe qu'en sortie de `decode_token`, jamais en entree : un `TokenClaims`
    construit a la main ne prouve rien, et le port n'offre aucun moyen d'en
    signer un. La charge utile qui voyage, elle, ne porte que des chaines et des
    entiers -- les `UUID` et les `datetime` sont reconstruits ici, apres que la
    signature a ete verifiee.

    Gele : ce que le service a verifie ne se corrige pas apres coup.
    """

    subject: UUID
    token_type: TokenType
    audience: str
    account_type: str
    token_id: UUID
    issued_at: datetime
    expires_at: datetime

    # Nuls ensemble ou renseignes ensemble : un compte particulier n'appartient a
    # aucun groupe, et c'est le cas nominal, pas une anomalie. Un role sans
    # groupe n'aurait aucun perimetre ou s'appliquer.
    active_group_id: UUID | None
    group_role: str | None


class TokenService(ABC):
    """Emission et verification des jetons, derriere un contrat stable.

    TROIS REGLES QUI ENGAGENT L'APPELANT

    1. AUCUNE OPERATION NE DEGRADE. Un depot injoignable, une cle trop courte,
       un algorithme indisponible : rien de tout cela ne produit un jeton par
       defaut. Relire la docstring de module avant d'ecrire un
       `except TokenError: pass`.

    2. LE ROLE VIENT DU DEPOT, JAMAIS DE L'APPELANT. Il est resolu a l'instant
       de l'emission et fige pour la duree du jeton -- le ticket budgete jusqu'a
       quinze minutes de latence sur une retrogradation, et BACK-10d couvre
       l'urgence par la revocation. Les roles de perimetre CLINIQUE, eux, ne
       sont jamais dans un jeton : ils se resolvent a la requete (BACK-10c).

    3. LES CLAIMS D'UN JETON DE RAFRAICHISSEMENT NE FONT PAS AUTORITE. Ils
       disent ce qui etait vrai il y a jusqu'a sept jours. Tout renouvellement
       repasse par `create_access_token`, donc par la verification
       d'appartenance ; recopier les claims d'un rafraichissement dans un jeton
       d'acces figerait un role une semaine et viderait la regle 2 de son sens.
    """

    @abstractmethod
    def audience_for(self, account_type: str) -> str:
        """Rend l'audience de l'application qui sert ce type de compte.

        SUR LE PORT, ET NON SUR L'ADAPTATEUR. BACK-29 doit confronter l'audience
        demandee au type de compte -- « un particulier n'obtient jamais un jeton
        d'audience professionnelle » -- et il le fera en recevant un
        `TokenService`. Ranger cette table sur l'implementation concrete
        l'obligerait a en dependre, c'est-a-dire a defaire ce que le port existe
        pour tenir.

        Args:
            account_type: le type de compte, tel qu'`identity` le nomme.

        Returns:
            L'audience configuree pour ce type de compte.

        Raises:
            UnknownAccountTypeError: si ce type de compte n'a pas d'audience.
        """

    @abstractmethod
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
            account_id: le compte authentifie -- il devient le claim `sub`.
            account_type: `professional`, `individual` ou `admin`, tel
                qu'`identity` le nomme. Chaine et non enumeration : le noyau
                partage n'a pas le droit d'importer un module.
            audience: l'application a laquelle ce jeton est destine. Doit etre
                l'une des audiences declarees du service.
            active_group_id: le groupe dans lequel le porteur veut travailler,
                ou `None` pour un compte sans appartenance -- le cas nominal
                d'un particulier.

        Returns:
            Le jeton signe, pret a etre presente en en-tete `Authorization`.

        Raises:
            UnknownAudienceError: si l'audience demandee n'est pas declaree.
            UnknownAccountTypeError: si le type de compte n'est pas connu.
            InactiveMembershipError: si `active_group_id` est fourni sans
                appartenance active a cet instant. Aucun jeton n'est emis.
            TokenIssuanceError: si la verification n'a pas pu aboutir. Aucun
                jeton n'est emis non plus.
        """

    @abstractmethod
    async def create_refresh_token(
        self,
        *,
        account_id: UUID,
        account_type: str,
        audience: str,
        active_group_id: UUID | None = None,
    ) -> str:
        """Emet un jeton de rafraichissement long, aux memes verifications.

        Meme signature que l'acces, et meme controle d'appartenance : un jeton de
        sept jours emis sans preuve serait le plus durable des deux.

        Args:
            account_id: le compte authentifie.
            account_type: le type de compte, tel qu'`identity` le nomme.
            audience: l'application a laquelle ce jeton est destine.
            active_group_id: le groupe actif, ou `None`.

        Returns:
            Le jeton signe, destine au cookie httpOnly que posera BACK-29.

        Raises:
            UnknownAudienceError: si l'audience demandee n'est pas declaree.
            UnknownAccountTypeError: si le type de compte n'est pas connu.
            InactiveMembershipError: si `active_group_id` est fourni sans
                appartenance active a cet instant. Aucun jeton n'est emis.
            TokenIssuanceError: si la verification n'a pas pu aboutir. Aucun
                jeton n'est emis non plus.
        """

    @abstractmethod
    async def decode_token(
        self, token: str, *, expected_audience: str, expected_type: TokenType
    ) -> TokenClaims:
        """Verifie un jeton de bout en bout, puis rend ce qu'il affirme.

        Verifie la signature, l'expiration, la date d'emission, la presence de
        TOUS les claims attendus, l'audience et le type. Aucune de ces
        verifications n'est optionnelle : un parametre qui permettrait d'en
        desactiver une finirait par etre passe.

        Args:
            token: la chaine presentee par l'appelant.
            expected_audience: l'audience de l'application qui recoit la
                requete. OBLIGATOIRE : sans elle, un jeton d'une autre
                application serait accepte.
            expected_type: le type attendu a cet endroit du service.

        Returns:
            Les claims verifies.

        Raises:
            ExpiredTokenError: si le jeton a expire.
            TokenNotYetValidError: si sa date d'emission est dans le futur.
            InvalidSignatureError: si la signature ne correspond pas.
            InvalidAudienceError: si l'audience differe, ou manque.
            WrongTokenTypeError: si le type n'est pas celui attendu.
            MalformedTokenError: si le jeton est illisible, incomplet, ou porte
                un claim intypable.
        """
