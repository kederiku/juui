"""Regles metier pures du module identity (BACK-04).

Une politique est une regle qui ne tient DANS AUCUNE ENTITE en particulier :
elle s'exprime sur des valeurs, se teste sans rien construire, et se reutilise
d'un cas d'usage a l'autre. Ce qui n'est vrai que d'un compte donne -- ses
transitions de statut, par exemple -- reste dans `entities.py`, ou c'est
l'entite elle-meme qui le fait respecter.

Ce module n'importe RIEN du reste du module identity, `entities.py` compris.
C'est ce qui permet a l'entite d'appeler ces regles dans sa fabrique sans
creer de cycle d'import, et ce n'est pas un hasard : une politique qui aurait
besoin de connaitre l'entite serait un comportement de l'entite.

CE QUE BACK-17 A AJOUTE ICI
Les primitives du code de verification a usage unique : sa fabrication, son
empreinte et sa comparaison, plus le jeu de regles `OtpRules` qui les parametre.
Elles sont DANS LE DOMAINE et non dans l'adaptateur Redis parce qu'elles portent
une regle metier -- « un OTP est un secret d'authentification, il se traite comme
un mot de passe » -- que TOUTE implementation du magasin doit tenir, la doublure
en memoire des tests comprise. Elles ne dependent que de la bibliotheque
standard, ce qu'exige le contrat `domain-purity`.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
La politique de mot de passe et la verification HIBP arrivent en BACK-10b sous
la forme d'un objet-valeur `Password` ; les regles de canal d'inscription
(« seuls les comptes particuliers s'inscrivent seuls ») viennent avec BACK-28.
"""

import hmac
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import Final
from uuid import UUID

# Longueur du code de verification, en chiffres. Six : ce que le cahier des
# charges annonce, ce qu'une application de messagerie affiche sans coupure, et
# ce qu'un utilisateur recopie sans se tromper. L'espace de 10^6 ne tient pas
# tout seul -- ce sont les trois tentatives et les dix minutes qui le rendent
# suffisant.
OTP_CODE_LENGTH: Final = 6

# Etiquette de SEPARATION DE DOMAINE du poivre. Voir `derive_otp_pepper` dans
# l'adaptateur : la cle de signature des jetons ne doit jamais servir telle
# quelle a une seconde fin.
OTP_PEPPER_LABEL: Final = b"juui/otp/email-verification/v1"


def normalize_email(value: str) -> str:
    """Ramene une adresse e-mail a sa forme canonique.

    Une seule forme est ECRITE en base : minuscules, sans espaces de garde. Sans
    cette regle, « Jean@Exemple.fr » et « jean@exemple.fr » creeraient deux
    comptes pour une seule personne, et la seconde inscription passerait le
    controle d'unicite sans broncher.

    La regle est ici parce qu'elle est METIER : la base la fait respecter de
    son cote avec l'index `ix_accounts_email_lower` (INFRA-09, ADR-0016), mais
    un index refuse, il ne normalise pas -- l'utilisateur recevrait un conflit
    la ou il attend un compte.

    Args:
        value: l'adresse telle que saisie.

    Returns:
        L'adresse en minuscules, debarrassee de ses espaces de garde.
    """
    return value.strip().lower()


def normalize_phone(value: str | None) -> str | None:
    """Ramene un numero de telephone a une forme comparable.

    Volontairement MINIMALE : on retire les espaces, points et tirets de mise en
    forme, on ne reformate pas et on ne valide pas. Un numero se saisit de dix
    facons (« 06 12 34 56 78 », « 06.12.34.56.78 », « +33612345678 ») et aucune
    n'est fausse ; la normalisation E.164, elle, suppose un pays connu, ce que
    l'inscription ne demande pas.

    Args:
        value: le numero tel que saisi, ou None -- le telephone est facultatif.

    Returns:
        Le numero sans separateurs de mise en forme, None si rien n'a ete saisi,
        None egalement si la saisie ne contenait que des separateurs.
    """
    if value is None:
        return None
    compacted = value.translate(str.maketrans("", "", " .-"))
    return compacted or None


@dataclass(frozen=True, slots=True)
class OtpRules:
    """Les bornes du parcours OTP, portees comme une valeur du domaine.

    Gelees : ces bornes sont fixees pour la duree du processus, et un cas d'usage
    qui pourrait les corriger en chemin ne serait plus limite par grand-chose.

    POURQUOI UNE VALEUR PLUTOT QU'UNE LECTURE DE `Settings`
    Le contrat `domain-purity` interdit au domaine d'importer `app.core`, meme
    indirectement. Ce n'est pas un obstacle contourne mais la bonne forme : le cas
    d'usage recoit ses bornes comme il recoit ses ports, et un test les ecrit en
    une ligne au lieu de fabriquer une configuration complete.
    """

    ttl_seconds: int
    max_attempts: int
    resend_min_interval_seconds: int
    resend_window_seconds: int
    resend_max_per_email: int
    resend_max_per_ip: int

    def __post_init__(self) -> None:
        """Refuse un jeu de bornes qui ne limiterait rien.

        Raises:
            ValueError: si une duree ou un plafond n'est pas strictement positif.
                Seul le delai minimal entre deux renvois accepte zero, qui le
                desactive -- les deux plafonds, eux, restent en place.
        """
        positives = {
            "ttl_seconds": self.ttl_seconds,
            "max_attempts": self.max_attempts,
            "resend_window_seconds": self.resend_window_seconds,
            "resend_max_per_email": self.resend_max_per_email,
            "resend_max_per_ip": self.resend_max_per_ip,
        }
        for name, value in positives.items():
            if value <= 0:
                message = f"OtpRules.{name} doit etre strictement positif, recu {value}."
                raise ValueError(message)
        if self.resend_min_interval_seconds < 0:
            message = (
                "OtpRules.resend_min_interval_seconds ne peut pas etre negatif, "
                f"recu {self.resend_min_interval_seconds}."
            )
            raise ValueError(message)


def generate_otp_code() -> str:
    """Tire un code de verification a six chiffres.

    `secrets` ET JAMAIS `random`. Le module `random` sert un Mersenne Twister dont
    l'etat interne se reconstitue a partir de quelques sorties observees : un
    attaquant qui demande des codes pour SON compte predirait ceux des autres.
    `secrets.randbelow` puise dans le generateur du systeme et tire UNIFORMEMENT
    sous la borne -- pas de `% 1_000_000` sur un entier tire plus large, qui
    biaiserait les premieres valeurs.

    Le zero de tete est SIGNIFIANT : « 004271 » est un code a six chiffres, pas le
    nombre 4271. Le code est donc une CHAINE d'un bout a l'autre du parcours,
    jamais un entier -- un aller-retour par `int` mangerait le zero et ferait
    echouer une comparaison pourtant juste.

    Returns:
        Six chiffres, zeros de tete compris.
    """
    return f"{secrets.randbelow(10**OTP_CODE_LENGTH):0{OTP_CODE_LENGTH}d}"


def fingerprint_otp_code(code: str, *, account_id: UUID, pepper: bytes) -> str:
    """Reduit un code a l'empreinte que le magasin a le droit de conserver.

    JAMAIS LE CODE EN CLAIR : un OTP est un secret d'authentification, et ce qui
    est stocke doit rester inutilisable pour qui lit le stockage.

    LE POIVRE N'EST PAS DECORATIF -- C'EST LUI QUI REND LE HACHAGE UTILE
    Un condense nu de six chiffres se casse par force brute exhaustive en une
    fraction de seconde : un million de SHA-256, c'est l'affaire de quelques
    millisecondes. Sans une cle que le stockage NE CONTIENT PAS, hacher ne
    protegerait rien du tout. D'ou le HMAC, dont la cle vit dans la configuration
    du service et non dans Redis.

    L'IDENTIFIANT DE COMPTE ENTRE DANS L'EMPREINTE, et il le faut : sans lui, deux
    comptes ayant recu le meme code -- ce qui arrive une fois sur un million, donc
    souvent a l'echelle d'un service -- porteraient la meme empreinte, et une
    empreinte relue ailleurs vaudrait preuve ici.

    Args:
        code: le code en clair, tel qu'il a ete tire ou saisi.
        account_id: le compte auquel ce code est lie.
        pepper: la cle du HMAC, propre au service.

    Returns:
        L'empreinte hexadecimale, 64 caracteres.

    Raises:
        ValueError: si le poivre est vide -- un HMAC a cle nulle rendrait le
            calcul reproductible par quiconque lit le stockage, c'est-a-dire
            exactement ce que cette fonction existe pour empecher.
    """
    if not pepper:
        message = (
            "Le poivre des empreintes OTP est vide : l'empreinte serait "
            "reproductible par qui lit le stockage."
        )
        raise ValueError(message)
    material = f"{account_id}:{code}".encode()
    return hmac.new(pepper, material, sha256).hexdigest()


def codes_match(candidate_fingerprint: str, stored_fingerprint: str) -> bool:
    """Compare deux empreintes en temps constant.

    `hmac.compare_digest` et JAMAIS `==`. L'egalite de chaines de Python s'arrete
    au premier caractere different : le temps de reponse trahit alors le nombre de
    caracteres corrects, et un attaquant reconstitue l'empreinte position par
    position au lieu de la deviner d'un coup. L'ecart mesure est infime, la fuite
    ne l'est pas.

    La comparaison porte sur les EMPREINTES et non sur les codes : le magasin ne
    detient pas le code en clair, et n'a donc rien a comparer d'autre.

    Args:
        candidate_fingerprint: l'empreinte du code saisi.
        stored_fingerprint: l'empreinte conservee par le magasin.

    Returns:
        Vrai si les deux empreintes sont identiques.
    """
    return hmac.compare_digest(candidate_fingerprint, stored_fingerprint)
