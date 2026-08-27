"""Adaptateur Have I Been Pwned du port `BreachChecker` (BACK-10b).

Premier client HTTP SORTANT du service. Tout ce que le port refuse de connaitre
vit ici : le SHA-1, la k-anonymity, le format de reponse, et surtout ce qu'il faut
faire quand le service ne repond pas.

LA K-ANONYMITY, ET CE QUI PART REELLEMENT SUR LE FIL
Le mot de passe est condense en SHA-1 ; seuls les CINQ premiers caracteres de
l'empreinte quittent le processus. Le service rend alors tous les suffixes de son
corpus partageant ce prefixe -- de l'ordre d'un millier -- et la comparaison se
fait ICI, en memoire. Ni le mot de passe, ni son empreinte complete, ni meme le
suffixe ne sortent jamais.

CE SHA-1 N'EST PAS UN USAGE DE SECURITE, ET `usedforsecurity=False` LE DIT
On ne s'appuie ni sur la resistance aux collisions -- une collision produirait un
« fuite » CONSERVATEUR -- ni sur la resistance a la preimage, l'empreinte complete
n'etant ni transmise ni conservee. SHA-1 est ici la fonction de casiers du corpus
distant, imposee par son API, exactement comme un CRC de partitionnement. Le
drapeau eteint la regle S324 de Ruff (verifie), et il est vrai au fond : sur un
OpenSSL en mode FIPS, c'est meme lui qui maintient `hashlib.sha1` utilisable, la
ou un `noqa` laisserait le code casse.

`Add-Padding` N'EST PAS UNE OPTION
Sans lui, la TAILLE de la reponse varie avec le nombre de suffixes du seau. Un
observateur du flux -- proxy d'entreprise, journal d'intermediaire, observateur
passif -- correle la longueur du chiffre au seau et resserre considerablement les
vingt bits du prefixe. C'est exactement la fuite que la k-anonymity existe pour
empecher. Le rembourrage a un corollaire qu'il faut connaitre : les entrees
ajoutees portent un COMPTE DE ZERO. « Mon suffixe est-il dans le corps ? » rend
donc un faux positif ; la question juste est « y est-il avec un compte non nul ? ».

LE DELAI D'HTTPX NE BORNE PAS CE QU'ON CROIT -- MESURE, PAS LU
`httpx.Timeout(2.0)` fixe deux secondes PAR PHASE (connexion, lecture, ecriture,
attente de pool), et le delai de lecture SE REARME a chaque fragment recu. Un
serveur qui envoie un octet toutes les 1,5 s tient donc la requete ouverte
indefiniment : mesure sur ce depot, 30,1 s pour un delai annonce a 2 s. L'enveloppe
`asyncio.timeout` est ce qui borne le TOTAL, et sans elle une inscription --
non authentifiee -- devient un amplificateur de deni de service. Le delai d'httpx
est conserve par-dessus : il coupe plus tot les cas ordinaires.

CE QU'IL DETIENT ENTRE DEUX APPELS : RIEN
Meme forme que `smtp_mailer.py`, et pour le motif que ce paquet enonce -- ce qui
varie d'un adaptateur a l'autre n'est pas le style, c'est ce qu'il detient. Le
controle de fuite est consulte a l'inscription, a la reinitialisation et au
changement de mot de passe ; JAMAIS a la connexion. A cette cadence, le pool d'un
client partage serait vide a chaque appel de toute facon, l'intermediaire distant
ayant referme sa connexion depuis longtemps : on paierait la poignee de main TLS
sans rien gagner, plus une cle dans `app.state`, plus un niveau dans le cycle de
vie, plus le meme montage a refaire dans le worker. Rien a ouvrir au demarrage,
rien a refermer a l'arret, et le semis d'INFRA-08 s'en sert sans construire
d'application.

CE QUI NE VA PAS DANS UN JOURNAL, ET C'EST PLUS LARGE QU'ON NE CROIT
Ni le mot de passe, ni l'empreinte, ni LE PREFIXE -- vingt bits de SHA-1 dans un
journal, croises avec le corpus public, reduisent le mot de passe d'un utilisateur
a un millionieme de ce corpus. Ni, surtout, L'EXCEPTION HTTPX ELLE-MEME : une
`HTTPStatusError` cite l'URL complete, donc le prefixe, et le masquage de
`core/logging.py` ne touche pas une URL nue (verifie). On journalise le nom de
classe de l'exception et le statut, rien d'autre. A savoir aussi : `str()` d'un
`ReadTimeout` est VIDE, si bien qu'un « injoignable : %s » sur l'exception rendrait
un avertissement muet sur le cas le plus frequent.
"""

import asyncio
import hashlib
import hmac
import logging
from typing import Final
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.shared.domain.ports.breach_checker import BreachChecker

_LOGGER: Final = logging.getLogger(__name__)

# Longueur du prefixe d'empreinte transmis. PUBLIQUE : la suite de tests la lit
# pour prouver que CINQ caracteres partent, et pas six -- recopiee dans le test,
# elle aurait derive au premier ajustement.
HIBP_PREFIX_LENGTH: Final = 5

# Longueur du suffixe rendu par le service : les trente-cinq caracteres restants
# du SHA-1. Elle sert a reconnaitre une ligne EXPLOITABLE -- voir `_contains`.
_SUFFIX_LENGTH: Final = 35
_HEX_DIGITS: Final = frozenset("0123456789ABCDEF")

# Budget d'octets de la reponse.
#
# LE PREMIER CHIFFRE ETAIT FAUX, ET LE DEFAUT ETAIT SILENCIEUX. 64 KiB avait ete
# pose sur « un seau fait mille lignes de quarante octets, c'est dix fois large » :
# c'etait 1,46 fois, pas dix. Et le rembourrage ajoute ses entrees PAR-DESSUS les
# vraies, ce qui porte un seau reel entre 1500 et 1800 lignes. Mesure : a 1800
# entrees (68,6 KiB) la reponse etait coupee, donc le mot de passe ACCEPTE, pour
# tous les mots de passe de ce prefixe et de facon permanente -- le controle de
# fuite s'eteignait par seaux entiers sans que rien n'echoue.
#
# 512 KiB, soit environ dix fois un seau rembourre, cette fois pour de bon. Le
# plafond garde sa raison d'etre : `HIBP_API_URL` est REGLABLE, l'hote au bout
# n'est donc pas de confiance par construction, et l'enveloppe de temps seule
# laisserait passer tout ce qu'un lien rapide sait envoyer en deux secondes.
_MAX_RESPONSE_BYTES: Final = 512 * 1024

# Ce qu'il faut attraper pour dire « le service est injoignable ».
#
# `httpx.TransportError` couvre les delais, les erreurs reseau, les erreurs de
# protocole et de mandataire. `httpx.DecodingError` N'EN FAIT PAS PARTIE (verifie)
# et doit etre nommee : un intermediaire qui annonce `gzip` sur un corps abime la
# leverait, et un 500 sur une inscription serait exactement le contraire de la
# degradation que le port promet. `OSError` couvre l'enveloppe `asyncio.timeout`,
# dont le `TimeoutError` en herite, ainsi que les echecs de resolution que la
# bibliotheque n'enveloppe pas toujours -- meme raisonnement mesure que le
# `_UNREACHABLE` de `redis_cache.py`.
_UNREACHABLE: Final = (OSError, httpx.TransportError, httpx.DecodingError)

# En-tetes de chaque appel.
#
# `User-Agent` : le service distant exige un agent qui l'identifie et repond 403 a
# un client anonyme. Sans cet en-tete, notre propre degradation avalerait ce 403 en
# silence, et le controle de fuite serait desactive pour toujours sans que personne
# l'apprenne.
# `Accept-Encoding: identity` N'EST PAS UNE PREFERENCE, C'EST LE PLAFOND D'OCTETS
# QUI EN DEPEND. Sans lui, httpx annonce `gzip, deflate`, et `aiter_bytes()` rend
# des octets DEJA DECOMPRESSES : un corps de 199 KiB qui se detend en 200 MiB est
# entierement materialise avant que la moindre comparaison de budget s'execute --
# mesure, 437 MiB de pic. Le corps est du texte court, que TLS comprime de toute
# facon au niveau du transport.
_HEADERS: Final = {
    "Accept": "text/plain",
    "Accept-Encoding": "identity",
    "Add-Padding": "true",
    "User-Agent": "juui-api",
}


class HibpBreachChecker(BreachChecker):
    """Interroge Have I Been Pwned en k-anonymity, et degrade en silence... bruyant.

    « Degrade » veut dire : rend `False` -- donc accepte le mot de passe -- des que
    le verdict ne peut pas etre obtenu, ET le journalise. Voir le port pour le
    motif : refuser une inscription parce qu'un service tiers est muet coute plus
    cher que le risque couvert. C'est la SEULE degradation permissive du service, et
    elle ne se generalise pas.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        """Assemble le verificateur.

        Args:
            base_url: la racine du service, sans le segment `/range/`.
            timeout_seconds: le budget TOTAL d'un appel, enveloppe comprise.
            transport: le transport HTTP. SANS VALEUR PAR DEFAUT, et c'est
                deliberement penible : l'omettre est une erreur de typage, jamais un
                appel reseau involontaire. La production passe `None`, qui laisse
                httpx choisir ; un test passe un transport de doublure. C'est ce qui
                rend mecanique le critere « aucun test n'appelle le vrai service ».
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport
        # L'hote seul, pour les journaux : il identifie la panne sans porter le
        # chemin, donc sans porter le prefixe.
        #
        # `hostname` ET NON `netloc` : celui-ci conserve les identifiants. Un
        # miroir interne derriere une authentification basique -- le cas d'usage
        # meme pour lequel `HIBP_API_URL` est reglable -- deposerait son mot de
        # passe dans les journaux a chaque degradation, depuis une methode dont la
        # docstring promet « ni mot de passe, ni empreinte, ni prefixe ».
        self._host = urlsplit(self._base_url).hostname or self._base_url

    async def is_breached(self, password: str) -> bool:
        """Dit si ce mot de passe est connu des fuites. Voir le port pour le contrat."""
        digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:HIBP_PREFIX_LENGTH], digest[HIBP_PREFIX_LENGTH:]

        body = await self._fetch(prefix)
        if body is None:
            return False
        return self._contains(body, suffix)

    async def _fetch(self, prefix: str) -> str | None:
        """Rapporte le corps du seau, ou None si le verdict est hors de portee.

        LE BLOC `try` N'ENVELOPPE QUE L'ECHANGE RESEAU, et l'analyse vit dehors.
        C'est structurel et non declaratif : quelle que soit la clause, un defaut
        d'analyse ne peut pas etre avale par la degradation et remonter en 500 comme
        il le doit.

        Args:
            prefix: les cinq caracteres d'empreinte, en majuscules.

        Returns:
            Le corps de la reponse, ou None -- auquel cas l'avertissement a deja ete
            emis.
        """
        url = f"{self._base_url}/range/{prefix}"
        try:
            # L'enveloppe borne le TOTAL ; le delai d'httpx borne chaque phase.
            async with (
                asyncio.timeout(self._timeout),
                httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                    follow_redirects=False,
                ) as client,
                client.stream("GET", url, headers=_HEADERS) as response,
            ):
                if response.status_code != httpx.codes.OK:
                    self._degrade(f"statut {response.status_code}", response=response)
                    return None
                payload = await self._read_capped(response)
        except _UNREACHABLE as error:
            self._degrade(type(error).__name__)
            return None

        if payload is None:
            return None
        return payload.decode("ascii", errors="ignore")

    async def _read_capped(self, response: httpx.Response) -> bytes | None:
        """Lit le corps sans depasser le budget d'octets.

        Args:
            response: la reponse ouverte en flux.

        Returns:
            Les octets lus, ou None si le budget a ete depasse -- l'avertissement a
            alors deja ete emis.
        """
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                self._degrade(f"reponse au-dela de {_MAX_RESPONSE_BYTES} octets")
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    def _contains(self, body: str, suffix: str) -> bool:
        """Cherche le suffixe dans le seau, sans jamais s'arreter en chemin.

        AUCUN `break`, ET UNE COMPARAISON EN TEMPS CONSTANT. Le corpus est public et
        le verdict est de toute facon annonce a l'utilisateur ; ce qui ne doit pas
        fuir, c'est la POSITION du suffixe dans le seau, qui donnerait quelques bits
        gratuits sur l'empreinte d'un mot de passe reel a qui sait chronometrer. Le
        depot applique deja cette regle a l'OTP (`codes_match`) : deux endroits qui
        compareraient des secrets de deux facons enseigneraient deux regles.

        Args:
            body: le corps de la reponse, une entree `SUFFIXE:COMPTE` par ligne.
            suffix: les trente-cinq caracteres restants de l'empreinte.

        Returns:
            Vrai si le suffixe figure au corpus avec un compte non nul.
        """
        wanted = suffix.encode("ascii")
        found = False
        usable = 0

        for raw_line in body.splitlines():
            candidate, separator, count = raw_line.strip().partition(":")
            if not separator or not count.isdigit():
                continue
            # LA FORME DU SUFFIXE EST EXIGEE, ET PAS SEULEMENT LA PRESENCE D'UN
            # DEUX-POINTS. Sans ce controle, une page d'erreur contenant
            # « Retry:30 » ou « upstream:8080 » comptait pour une ligne
            # exploitable : le garde de silence plus bas ne se declenchait pas, et
            # la degradation devenait muette -- exactement ce que le port interdit
            # nommement. Mesure : deux corps HTML sur trois passaient sans un mot.
            candidate = candidate.upper()
            if len(candidate) != _SUFFIX_LENGTH or not _HEX_DIGITS.issuperset(candidate):
                continue
            usable += 1
            if int(count) <= 0:
                # Entree de rembourrage : presente pour egaliser la taille de la
                # reponse, absente du corpus reel.
                continue
            found |= hmac.compare_digest(candidate.encode("ascii"), wanted)

        if usable == 0:
            # Un 200 sans une seule ligne exploitable est une anomalie -- une page
            # d'erreur en HTML, un intermediaire bavard. Rendre `False` sans le dire
            # serait la degradation silencieuse que le port interdit nommement.
            self._degrade("aucune ligne exploitable dans la reponse")
            return False
        return found

    def _degrade(self, reason: str, *, response: httpx.Response | None = None) -> None:
        """Journalise la degradation. Ni mot de passe, ni empreinte, ni prefixe.

        Args:
            reason: la cause, deja debarrassee de tout secret par l'appelant.
            response: la reponse, quand il y en a une -- seul son `Retry-After` est
                relu, parce que c'est la seule information qu'un exploitant puisse
                utiliser.
        """
        retry_after = response.headers.get("retry-after") if response is not None else None
        _LOGGER.warning(
            "Controle de fuite indisponible sur %s (%s)%s : le mot de passe est accepte.",
            self._host,
            reason,
            f", nouvelle tentative possible dans {retry_after} s" if retry_after else "",
        )


def build_breach_checker(settings: Settings) -> HibpBreachChecker:
    """Fabrique le verificateur a partir de la configuration du service.

    Recoit `Settings` en argument et n'appelle jamais `get_settings()` de
    l'interieur : meme motif que les autres fabriques du paquet -- la fonction est
    mise en cache, et le worker comme le semis ont besoin du leur.

    Args:
        settings: la configuration complete du service.

    Returns:
        Un verificateur pointe sur la section `HIBP_`, parlant au vrai reseau.
    """
    return HibpBreachChecker(
        base_url=settings.hibp.api_url,
        timeout_seconds=settings.hibp.timeout_seconds,
        transport=None,
    )
