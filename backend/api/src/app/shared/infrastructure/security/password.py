"""Adaptateur argon2id du port `PasswordHasher` (BACK-10b).

Tout ce que le port refuse de connaitre vit ici : la bibliotheque, la variante,
les couts, le format d'empreinte et la taxonomie d'erreurs d'`argon2-cffi`. Le
port reste importable sans extension C, ce que le contrat `domain-purity` verifie
a chaque `make check`.

POURQUOI argon2id, ET PAS bcrypt QUE LE TICKET AUTORISAIT
bcrypt TRONQUE SILENCIEUSEMENT A 72 OCTETS. Avec une politique qui va jusqu'a 128
caracteres, tout le haut de la plage deviendrait decoratif, et deux mots de passe
longs partageant leurs 72 premiers octets deviendraient interchangeables -- sans
qu'aucune erreur ne se produise nulle part. bcrypt n'est par ailleurs pas dur en
memoire, ce qui le rend amical pour un attaquant equipe de cartes graphiques.
argon2**id** et non argon2i ni argon2d : la variante hybride est celle que le RFC
9106 recommande quand on ne sait pas de quel cote viendra l'attaque.

LES TROIS COUTS SONT EPINGLES, PAS DEDUITS
`Type.ID` est deja le defaut d'argon2-cffi, et il est passe explicitement quand
meme : lequel des trois est le defaut ne doit pas dependre d'une montee de
version. Meme geste que le `retry=Retry(NoBackoff(), retries=0)` de l'adaptateur
Redis. Le parallelisme, lui, vit ici et non dans la configuration -- voir
`PASSWORD_PARALLELISM` dans la docstring de `PasswordSettings`.

LE CALCUL SORT DE LA BOUCLE D'EVENEMENTS, ET CE N'EST PAS FACULTATIF
Un hachage coute une quinzaine de millisecondes de processeur PUR, sans la moindre
attente d'entree-sortie. Le laisser dans la coroutine figerait la boucle du
processus entier -- donc TOUTES les requetes en vol, pas seulement celle qui
hache. Meme raisonnement et meme remede que `smtplib` dans `smtp_mailer.py`, avec
un multiplicateur : la connexion est un chemin chaud, l'envoi de courriel non.

CE QUE COUTE LE VIVIER DE FILS, PUISQUE PERSONNE NE LE COMPTE SPONTANEMENT
`asyncio.to_thread` sert le vivier par defaut, plafonne a `min(32, coeurs + 4)`.
Le pic memoire du service vaut donc ce plafond multiplie par le cout memoire d'un
hachage : dix-huit fils a 19 MiB font 342 MiB. C'est ce calcul, et non un
garde-fou de concurrence maison, qui rend la valeur par defaut tenable sur un
point d'entree non authentifie. Monter `PASSWORD_ARGON2_MEMORY_COST_KIB` deplace
ce plafond, et c'est a peser avant de le faire. La defense de fond contre l'abus
de cadence reste la limitation par adresse et par IP, qui appartient a BACK-29.

CE QUE L'ANNULATION NE REND PAS. Un client qui raccroche pendant une connexion
libere la coroutine, pas le creneau de fil ni les mebioctets qu'il tient : le
calcul va jusqu'au bout dans son fil. Le budget ci-dessus le suppose deja, mais
il faut le savoir avant de compter sur une annulation pour degonfler un pic. La
defense de fond reste la limitation de cadence, qui appartient a BACK-29.

AUCUNE EMPREINTE NE VA DANS UN JOURNAL. Elle embarque le sel et les parametres :
la journaliser rendrait une base volee cassable hors ligne depuis les seuls
journaux. Le clair, evidemment, non plus.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Final

import argon2
from argon2.exceptions import (
    HashingError,
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.core.config import Settings
from app.shared.domain.password import Password, PasswordHash
from app.shared.domain.ports.password_hasher import (
    PasswordHasher,
    PasswordHashingFailedError,
    StoredPasswordHashInvalidError,
    VerificationOutcome,
)

_LOGGER: Final = logging.getLogger(__name__)

# Voies de calcul. Fixe a 1 par les cinq configurations de l'OWASP, et non
# configurable : argon2-cffi calcule ses voies A LA SUITE, si bien qu'un `p` eleve
# decouperait la meme memoire en tranches sans rien acheter au defenseur -- tout
# en offrant a l'attaquant une structure a exploiter.
ARGON2_PARALLELISM: Final = 1

# Longueur du condense et du sel, en octets : 256 et 128 bits, les valeurs du RFC
# 9106. JAMAIS moins de seize pour le sel -- en deca, la borne des anniversaires
# rend deux sels egaux plausible a l'echelle d'une base, et les tables precalculees
# redeviennent rentables.
ARGON2_HASH_BYTES: Final = 32
ARGON2_SALT_BYTES: Final = 16

# Variante hybride. Explicite bien que ce soit le defaut : voir la docstring.
ARGON2_TYPE: Final = argon2.low_level.Type.ID


@dataclass(frozen=True, slots=True)
class Argon2Parameters:
    """Les trois couts d'un hachage, portes comme une valeur.

    Geles : les couts sont fixes pour la duree du processus. Un service qui
    pourrait les corriger en chemin produirait des empreintes de forces
    differentes sans que rien ne le dise.

    Une valeur plutot qu'une lecture de `Settings`, pour la meme raison
    qu'`OtpRules` : un test ecrit ses couts en une ligne au lieu de fabriquer une
    configuration complete -- et il en a besoin, la remise a niveau ne se prouvant
    qu'en confrontant deux jeux de couts.
    """

    time_cost: int
    memory_cost_kib: int
    parallelism: int = ARGON2_PARALLELISM


class Argon2PasswordHasher(PasswordHasher):
    """Hacheur argon2id, echouant ferme et ne detenant aucun etat entre deux appels.

    Deux instances construites des memes parametres sont interchangeables, ce qui
    rend le service utilisable depuis une requete, une tache de fond ou le script
    de semis d'INFRA-08 sans qu'aucun cycle de vie n'ait a etre gere.
    """

    def __init__(self, *, parameters: Argon2Parameters) -> None:
        """Assemble le hacheur a partir de ses couts.

        Args:
            parameters: les trois couts. Ils entrent dans CHAQUE empreinte
                produite, ou ils se relisent -- c'est ce qui permet de dire, des
                annees plus tard, avec quels reglages un compte a ete cree.
        """
        self._parameters = parameters
        # Le nom nu revient au PORT : `argon2.PasswordHasher` est son homonyme, et
        # la convention du depot veut que ce soit la bibliotheque tierce qui prenne
        # la qualification.
        self._hasher = argon2.PasswordHasher(
            time_cost=parameters.time_cost,
            memory_cost=parameters.memory_cost_kib,
            parallelism=parameters.parallelism,
            hash_len=ARGON2_HASH_BYTES,
            salt_len=ARGON2_SALT_BYTES,
            type=ARGON2_TYPE,
        )

    async def hash(self, password: Password) -> PasswordHash:
        """Produit l'empreinte. Voir le port pour le contrat."""
        try:
            encoded = await asyncio.to_thread(self._hasher.hash, password.utf8)
        except HashingError as error:
            # Le cas concret est l'allocation refusee : argon2 reserve son cout
            # memoire d'un bloc. Le message NOMME le cout, sans quoi l'exploitant
            # lit « echec de hachage » sans savoir quel bouton tourner.
            message = (
                "Le hachage a echoue. Cout memoire configure : "
                f"{self._parameters.memory_cost_kib} KiB."
            )
            raise PasswordHashingFailedError(message) from error
        return PasswordHash(encoded)

    async def verify(self, *, stored: PasswordHash, candidate: str) -> VerificationOutcome:
        """Confronte la saisie a l'empreinte. Voir le port pour le contrat."""
        return await asyncio.to_thread(self._verify_and_refresh, stored, candidate)

    def _verify_and_refresh(self, stored: PasswordHash, candidate: str) -> VerificationOutcome:
        """Verifie puis, si les couts ont change, rehache -- le tout dans un fil.

        UN SEUL SAUT DE FIL pour les deux calculs : les separer en ferait deux, et
        surtout obligerait a ressortir le clair du fil pour le rendre a un appelant
        qui le rehacherait. Il ne sort pas d'ici.

        Args:
            stored: l'empreinte conservee.
            candidate: la saisie a verifier.

        Returns:
            Le verdict, et l'empreinte a reecrire s'il y a lieu.

        Raises:
            StoredPasswordHashInvalidError: l'empreinte conservee est illisible.
        """
        try:
            self._hasher.verify(stored.encoded, candidate.encode("utf-8"))
        except UnicodeEncodeError as error:
            # Inatteignable par HTTP -- pydantic refuse un surrogate isole avant le
            # domaine, verifie -- mais atteignable depuis un script, une tache ou le
            # semis. La regle du port est « aucune exception ne franchit ce port » :
            # une chaine que Python ne sait pas encoder est un defaut technique, pas
            # un mot de passe faux.
            message = "Le mot de passe soumis n'est pas encodable en UTF-8."
            raise PasswordHashingFailedError(message) from error
        except VerifyMismatchError:
            # LE CAS NOMINAL d'un formulaire de connexion : quelqu'un s'est trompe.
            # Rien a journaliser ici -- le comptage des echecs appartient a la
            # limitation de cadence, pas au calcul.
            return VerificationOutcome(verified=False)
        except (InvalidHashError, VerificationError) as error:
            # L'ORDRE DE CES DEUX CLAUSES EST LE SUJET, ET IL A ETE MESURE.
            # `VerifyMismatchError` HERITE de `VerificationError` : la clause
            # ci-dessus doit passer en premier, sans quoi un simple mot de passe
            # faux deviendrait une erreur technique. Et une empreinte TRONQUEE mais
            # bien formee leve `VerificationError` sans etre une `InvalidHashError`
            # -- attraper la seule `InvalidHashError` laisserait donc filer un 500.
            message = "L'empreinte conservee pour ce compte est illisible."
            raise StoredPasswordHashInvalidError(message) from error

        return VerificationOutcome(verified=True, refreshed_hash=self._refresh(stored, candidate))

    def _refresh(self, stored: PasswordHash, candidate: str) -> PasswordHash | None:
        """Rehache si les couts ont change depuis la creation de l'empreinte.

        SON ECHEC N'EST JAMAIS PROPAGE. Le mot de passe vient d'etre reconnu :
        perdre une connexion valide parce qu'une remise a niveau n'a pas abouti
        serait un mauvais echange. La tentative se rejouera a la connexion
        suivante, et l'avertissement dit qu'elle a eu lieu.

        Args:
            stored: l'empreinte conservee, dont on relit les couts.
            candidate: la saisie, dont on vient de prouver qu'elle est la bonne.

        Returns:
            La nouvelle empreinte, ou None s'il n'y a rien a reecrire.
        """
        try:
            if not self._hasher.check_needs_rehash(stored.encoded):
                return None
            return PasswordHash(self._hasher.hash(candidate.encode("utf-8")))
        except (InvalidHashError, HashingError) as error:
            # `type(error).__name__` et rien d'autre : le message d'une exception de
            # hachage peut citer l'empreinte, qui n'a rien a faire dans un journal.
            _LOGGER.warning(
                "Remise a niveau de l'empreinte impossible, la connexion reste valide : %s",
                type(error).__name__,
            )
            return None


def build_password_hasher(settings: Settings) -> Argon2PasswordHasher:
    """Fabrique le hacheur a partir de la configuration du service.

    Recoit `Settings` EN ARGUMENT et n'appelle jamais `get_settings()` de
    l'interieur, pour la raison deja ecrite dans `db/engine.py` : la fonction est
    mise en cache, et un constructeur qui l'appellerait ne saurait pas fabriquer un
    hacheur different de celui du processus. Le worker TaskIQ, les tests et le
    script de semis d'INFRA-08 ont besoin du leur.

    Args:
        settings: la configuration complete du service.

    Returns:
        Un hacheur aux couts de la section `PASSWORD_`.
    """
    return Argon2PasswordHasher(
        parameters=Argon2Parameters(
            time_cost=settings.password.argon2_time_cost,
            memory_cost_kib=settings.password.argon2_memory_cost_kib,
        )
    )
