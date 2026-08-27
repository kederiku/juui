"""Politique de mot de passe du service : l'objet-valeur et ses refus (BACK-10b).

La regle du cahier des charges tient en une phrase -- entre 14 et 128 caracteres,
AUCUNE contrainte de composition -- et c'est deliberement tout. Elle suit les
recommandations du NIST (SP 800-63B) : exiger une majuscule, un chiffre et un
caractere special produit `Motdepasse1!` a la chaine, c'est-a-dire des secrets
plus courts, plus previsibles et moins bien memorises. La longueur, elle, achete
de l'entropie sans rien couter a personne.

POURQUOI CE MODULE VIT DANS `shared/` ET NON DANS `identity/`
Le port `PasswordHasher` vit ici, et il TYPE son argument : `hash(password:
Password)`. Le contrat `service-spaces` interdisant a `app.shared` d'importer un
module, un `Password` range dans `identity` obligerait le port a prendre un `str`
-- et la garantie « on ne hache que ce qui a passe la politique » disparaitrait
avec le type. L'annonce contraire de `identity/domain/policies.py` est corrigee,
et l'ecart est consigne au registre : il contredit la regle d'ADR-0022, qui
reserve `shared/` aux besoins TECHNIQUES atteints par DEUX modules.

ON N'OBTIENT PAS UN `Password` SANS AVOIR DEMANDE LE CONTROLE DE FUITE
`Password(...)` echoue. La seule fabrique est `Password.create(...)`, qui exige un
`BreachChecker` en argument nomme. Ce n'est pas de la coquetterie : le ticket veut
que la regle ne soit pas dupliquee entre inscription, reinitialisation et
changement de mot de passe, et une regle qui ne tient que par une docstring est
une regle qu'un quatrieme parcours oubliera. Ici, l'oubli ne compile pas -- au
sens ou il echoue au premier test. Une doublure reste possible (le semis
d'INFRA-08 en pose une), mais c'est alors un ACTE, visible en diff, et non une
omission.

CE QUE `Password` PROMET, ET CE QU'IL NE PROMET PAS
Il promet que la longueur a ete verifiee et que le controle de fuite a ete
DEMANDE. Il ne promet pas que le mot de passe est absent des fuites : le port
degrade en cas de panne du service tiers, et rend `False` faute de mieux. C'est le
contrat ecrit dans `ports/breach_checker.py`, et le mensonge serait de pretendre
l'inverse dans un type.

LA POLITIQUE NE S'APPLIQUE PAS A LA CONNEXION
On l'applique a l'INSCRIPTION, a la REINITIALISATION et au CHANGEMENT. Jamais a la
verification d'identifiants : refuser un mot de passe existant parce qu'il est
devenu trop court dirait a l'attaquant, avant tout controle, que ce compte-la vaut
la peine -- et interroger le service de fuites a chaque connexion lui enverrait un
prefixe du vrai mot de passe de chaque utilisateur, plusieurs fois par jour.

DEUX BORNES INCLUSES, COMPTEES EN POINTS DE CODE
Le ticket ecrit « strictement comprise entre 14 et 128 ». Lue a la lettre, la
phrase n'admettrait que 15 a 127 : elle refuserait un mot de passe de 128
caracteres sorti d'un gestionnaire, c'est-a-dire l'utilisateur exemplaire, et
refuserait quatorze caracteres a qui vient de lire « quatorze caracteres ». La
checklist du ticket, elle, ecrit « 14-128 ». Retenu : 14 <= n <= 128.

Le comptage est celui de `len()`, donc des POINTS DE CODE -- pas des octets, qui
feraient de quatorze un plancher de cinq ideogrammes, ni des graphemes, qui
demanderaient une dependance pour rien. C'est aussi ce que compte le `min_length`
de Pydantic, si bien que la bordure HTTP et le domaine comptent la meme chose.

AUCUNE NORMALISATION UNICODE, ET C'EST UN CHOIX CONTRE UN « SHOULD » DU NIST
Ni `strip`, ni casse, ni NFKC. Trois raisons. La normalisation de compatibilite
REDUIT l'entropie -- « fi » et « ﬁ » deviennent le meme secret, ce qu'OWASP
proscrit explicitement. Normaliser a l'inscription et l'oublier a la
reinitialisation enferme l'utilisateur dehors, et l'oubli est invisible jusqu'au
jour ou il ne l'est plus. Enfin `FakeBreachChecker` (BACK-06c) l'a deja tranche
pour le port voisin : « la comparaison est faite sur la chaine EXACTE : le port ne
promet aucune normalisation, et un mot de passe ne se normalise pas ». Deux ports
du meme parcours ne peuvent pas repondre differemment a la meme question.
"""

import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from typing import ClassVar, Final, Self

from app.shared.domain.exceptions import ValidationError
from app.shared.domain.ports.breach_checker import BreachChecker

__all__ = [
    "DECOY_PASSWORD",
    "PASSWORD_MAX_LENGTH",
    "PASSWORD_MIN_LENGTH",
    "Password",
    "PasswordBreachedError",
    "PasswordHash",
    "PasswordPolicyError",
    "PasswordTooLongError",
    "PasswordTooShortError",
]

# Les deux bornes du cahier des charges, en points de code, INCLUSES.
#
# Constantes et non reglages : une regle du cahier des charges n'est pas un bouton
# d'exploitation, et le domaine n'a de toute facon pas le droit de lire `app.core`
# (contrat `domain-purity`, meme indirectement). BACK-28 posera son
# `Field(min_length=..., max_length=...)` en important CES noms, ce qui fait de la
# bordure HTTP et du domaine deux gardiens d'une seule constante -- exactement ce
# que `shared/infrastructure/api/pagination.py` fait deja de `MAX_PAGE_SIZE`.
PASSWORD_MIN_LENGTH: Final = 14
PASSWORD_MAX_LENGTH: Final = 128

# Drapeau de fabrique. Python n'a pas de constructeur prive ; ceci en tient lieu.
#
# UNE CONTEXTVAR ET NON UN CHAMP DE LA DATACLASS, et la difference n'est pas
# theorique : un jeton porte par l'instance est recopie par `dataclasses.replace`,
# qui rejoue `__init__` avec les champs existants. Mesure sur la premiere version
# de ce fichier -- `replace(password, value=<mot de passe connu fuite>)` rendait un
# `Password` valide sans un seul appel au controle. Le drapeau vit donc dans le
# CONTEXTE d'appel, que `replace` n'a aucun moyen de reproduire.
#
# Une contextvar et non un booleen de module -- mais pas pour la raison qu'on
# croit, verification faite : `to_thread` et `create_task` COPIENT le contexte, si
# bien qu'une tache fille verrait le drapeau elle aussi. Ce qui protege ici, c'est
# qu'aucun `await` ne separe le `set` du `reset` : la fenetre ne contient qu'un
# appel de constructeur, et rien ne s'y intercale. La contextvar apporte le
# `reset()` exact -- un booleen de module laisserait un drapeau leve derriere une
# exception, et le `finally` d'une contextvar restaure la valeur PRECEDENTE plutot
# que de deviner laquelle remettre.
_UNDER_CONSTRUCTION: Final[ContextVar[bool]] = ContextVar(
    "juui_password_under_construction", default=False
)


def _ensure_length(candidate: str) -> None:
    """Refuse une longueur hors bornes, en points de code.

    Fonction de module et non methode : la fabrique doit pouvoir l'appeler AVANT
    de construire quoi que ce soit, pour qu'une saisie trop courte ne parte jamais
    vers le service de fuites.

    Args:
        candidate: le mot de passe en clair.

    Raises:
        PasswordTooShortError: en deca de `PASSWORD_MIN_LENGTH` points de code.
        PasswordTooLongError: au-dela de `PASSWORD_MAX_LENGTH` points de code.
    """
    bornes: Final[dict[str, object]] = {
        "min_length": PASSWORD_MIN_LENGTH,
        "max_length": PASSWORD_MAX_LENGTH,
    }
    length = len(candidate)
    if length < PASSWORD_MIN_LENGTH:
        raise PasswordTooShortError(
            f"Le mot de passe doit compter au moins {PASSWORD_MIN_LENGTH} caracteres.",
            details=bornes,
        )
    if length > PASSWORD_MAX_LENGTH:
        raise PasswordTooLongError(
            f"Le mot de passe ne peut pas depasser {PASSWORD_MAX_LENGTH} caracteres.",
            details=bornes,
        )


class PasswordPolicyError(ValidationError):
    """Le mot de passe propose ne respecte pas la politique du service.

    Racine des quatre refus, pour qu'un appelant puisse tous les attraper d'un
    coup -- une route d'inscription les traite de la meme facon. Traduite en 422
    comme toute `ValidationError` : c'est bien une regle METIER qui refuse la
    valeur, et `shared/domain/exceptions.py` nomme d'ailleurs ce cas-ci en exemple.

    AUCUN DE CES REFUS NE PORTE LA SAISIE. `details` sort tel quel dans le corps de
    la reponse HTTP, et de la dans les journaux de tous les clients : il ne porte
    que les BORNES, jamais une mesure du mot de passe soumis.
    """

    code: ClassVar[str] = "shared.password.invalid"


class PasswordTooShortError(PasswordPolicyError):
    """Moins de `PASSWORD_MIN_LENGTH` points de code.

    Le message ENONCE la borne. La taire produit l'utilisateur qui essaie huit
    caracteres, puis dix, puis douze : la regle est publique de toute facon, elle
    figure dans le contrat OpenAPI et sur le formulaire.
    """

    code: ClassVar[str] = "shared.password.too_short"


class PasswordTooLongError(PasswordPolicyError):
    """Plus de `PASSWORD_MAX_LENGTH` points de code.

    La borne haute n'est pas une contrainte de securite mais une borne d'entree :
    elle existe pour qu'aucune saisie demesuree n'atteigne le hachage.
    """

    code: ClassVar[str] = "shared.password.too_long"


class PasswordBreachedError(PasswordPolicyError):
    """Le mot de passe figure dans une fuite publique connue.

    C'EST LE CODE DEDIE QU'ATTEND FRONT-13. Il est distinct des refus de longueur
    pour que l'interface puisse expliquer la bonne chose : ce mot de passe n'est
    pas « trop faible », il CIRCULE. La nuance change ce que l'utilisateur
    comprend, et donc ce qu'il fait ensuite.

    LE MESSAGE NE DIT JAMAIS COMBIEN DE FOIS. Le service interroge rend un nombre
    d'occurrences ; le repeter au client ferait de notre formulaire un oracle
    gratuit sur ce service, et confirmerait a qui soumet un candidat quelle entree
    exacte du corpus il vient de toucher. La signature du port (`-> bool`)
    l'interdit deja : c'est un bon port.
    """

    code: ClassVar[str] = "shared.password.breached"


@dataclass(frozen=True, slots=True, repr=False, eq=False)
class Password:
    """Un mot de passe en clair dont la politique a ete appliquee.

    Detenir un `Password` prouve deux choses et seulement deux : sa longueur tient
    dans les bornes, et le controle de fuite a ete demande. Voir la docstring de
    module pour ce que cela ne prouve pas.

    TROIS REGLAGES DE DATACLASS QUI NE SONT PAS COSMETIQUES

    - `repr=False` avec un `__repr__` ecrit a la main. Le `repr` engendre imprime
      TOUS les champs : une trace, un diff d'assertion pytest ou un `%r` de
      journalisation recracherait le secret en clair. Comme `__str__` retombe sur
      `__repr__` quand il n'est pas defini, les deux sont couverts d'un coup.
    - `eq=False`. Le `__eq__` engendre comparerait deux clairs caractere par
      caractere, donc en temps non constant, et ferait porter le hachage de
      l'objet sur sa VALEUR. Avec `eq=False`, l'objet reste hachable -- par son
      identite, comme n'importe quel objet Python : ce qu'on gagne n'est pas
      l'impossibilite d'en faire une cle, c'est qu'aucune table ne la derive du
      secret. Aucun appel du service ne compare deux `Password` de toute facon :
      la confirmation de saisie se compare AVANT, sur les chaines, a la bordure.
    - `frozen=True`. Une valeur deja validee ne se corrige pas en chemin.
    """

    value: str

    def __post_init__(self) -> None:
        """Refuse une construction hors fabrique, puis une longueur hors bornes.

        L'ordre compte : la fabrique d'abord, la longueur ensuite. Un appelant qui
        la contourne doit l'apprendre meme si son mot de passe est bon, sans quoi
        la faute ne se verrait qu'un jour de mauvaise saisie.

        Raises:
            TypeError: hors de la fabrique -- c'est un defaut de PROGRAMME et non
                une saisie invalide, d'ou une erreur qui sort en 500 plutot qu'en
                422 : personne n'a rien fait de travers cote utilisateur.
            PasswordTooShortError: en deca de `PASSWORD_MIN_LENGTH` points de code.
            PasswordTooLongError: au-dela de `PASSWORD_MAX_LENGTH` points de code.
        """
        if not _UNDER_CONSTRUCTION.get():
            message = (
                "Un Password ne se construit pas directement : passer par "
                "`await Password.create(candidat, breach_checker=...)`, qui applique "
                "la politique ET le controle de fuite."
            )
            raise TypeError(message)
        _ensure_length(self.value)

    @classmethod
    async def create(cls, candidate: str, *, breach_checker: BreachChecker) -> Self:
        """Applique la politique complete et rend le mot de passe accepte.

        LA LONGUEUR EST VERIFIEE AVANT L'APPEL AU PORT, et ce n'est pas une
        optimisation : une saisie de trois caracteres n'a aucune raison de partir,
        meme condensee et tronquee, vers un service tiers. Un test l'epingle en
        assurant que le compteur d'appels de la doublure vaut zero.

        Args:
            candidate: le mot de passe en clair, tel que l'utilisateur l'a saisi.
                Il n'est ni elague, ni normalise, ni recase.
            breach_checker: le controle de fuite. ARGUMENT OBLIGATOIRE : c'est ce
                qui empeche un parcours de l'oublier. Une doublure explicite est le
                seul moyen de s'en passer, et elle se voit en revue.

        Returns:
            Le mot de passe accepte.

        Raises:
            PasswordTooShortError: longueur en deca de la borne basse.
            PasswordTooLongError: longueur au-dela de la borne haute.
            PasswordBreachedError: le mot de passe figure dans les fuites connues.
                PAS levee quand le service est injoignable -- il degrade et accepte,
                en le journalisant (voir le port).
        """
        _ensure_length(candidate)
        if await breach_checker.is_breached(candidate):
            raise PasswordBreachedError(
                "Ce mot de passe figure dans une fuite de donnees publique. "
                "Merci d'en choisir un autre."
            )
        jeton = _UNDER_CONSTRUCTION.set(True)
        try:
            return cls(candidate)
        finally:
            _UNDER_CONSTRUCTION.reset(jeton)

    def __repr__(self) -> str:
        """Rend une representation qui ne contient PAS le mot de passe.

        Returns:
            La chaine constante `Password(***)`. Elle sert aussi de `__str__`, que
            `dataclass` n'engendre pas et qui retombe donc ici -- une f-string ou un
            `%s` sont couverts par la meme ligne.
        """
        return "Password(***)"

    def __copy__(self) -> Self:
        """Refuse la copie superficielle.

        `copy`, `deepcopy` et `pickle` reconstruisent un objet SANS passer par
        `__init__` : ils sauteraient donc la garde de `__post_init__`, et un
        `Password` naitrait sans que la politique ait ete appliquee. Les trois
        sont fermees plutot que laissees ouvertes -- un objet-valeur gele n'a de
        toute facon aucune raison d'etre copie, et un secret n'a aucune raison
        d'etre serialise.

        Raises:
            TypeError: toujours.
        """
        message = "Un Password ne se copie pas : le passer, ou en refabriquer un."
        raise TypeError(message)

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Refuse la copie profonde. Voir `__copy__`.

        Args:
            memo: la table des objets deja copies, ignoree.

        Raises:
            TypeError: toujours.
        """
        return self.__copy__()

    def __reduce__(self) -> str | tuple[object, ...]:
        """Refuse la serialisation. Voir `__copy__`.

        Raises:
            TypeError: toujours.
        """
        message = "Un Password ne se serialise pas : un secret ne quitte pas le processus."
        raise TypeError(message)

    @property
    def utf8(self) -> bytes:
        """Rend les octets du mot de passe, en UTF-8.

        L'encodage est nomme ici POUR LE HACHAGE, et c'est tout ce que cette
        propriete promet. Le port `BreachChecker` prend un `str` -- il refait donc
        le sien, dans son adaptateur -- et il faut le savoir plutot que de croire a
        une source unique qui n'existe pas. Les deux encodent en UTF-8, ce qui est
        la seule chose qui compte : le condense envoye au service de fuites porte
        bien sur les octets que le hachage verra.

        Returns:
            La representation UTF-8 du mot de passe.
        """
        return self.value.encode("utf-8")


def _forge(value: str) -> Password:
    """Construit un `Password` en levant le drapeau de fabrique, sans controle.

    RESERVE AUX VALEURS QUI NE SONT PAS DES MOTS DE PASSE D'UTILISATEUR. Privee au
    module, et le seul appelant est `DECOY_PASSWORD` ci-dessous.

    Args:
        value: la valeur a porter.

    Returns:
        Le `Password` correspondant.
    """
    jeton = _UNDER_CONSTRUCTION.set(True)
    try:
        return Password(value)
    finally:
        _UNDER_CONSTRUCTION.reset(jeton)


# Mot de passe LEURRE, tire au demarrage du processus, qui n'appartient a personne
# et n'est jamais conserve.
#
# CE QU'IL SERT A FAIRE, ET POURQUOI IL EST ICI. Le port `PasswordHasher` demande a
# BACK-29 de depenser le meme temps de calcul sur un compte inconnu que sur un
# compte reel : sans cela, la reponse part en une milliseconde d'un cote et en
# quinze de l'autre, et le formulaire de connexion devient un enumerateur de
# comptes. La docstring du port promettait que le remede tenait « en une ligne » --
# il n'en tenait pas, `Password.create` etant asynchrone et exigeant un controle de
# fuite qui n'a aucun sens sur une valeur jetee. Cette constante rend la promesse
# vraie : `await hasher.hash(DECOY_PASSWORD)`.
#
# Tire au hasard plutot que fige en dur : rien ne l'exige, mais une constante
# litterale dans un depot public finit toujours par etre recopiee ailleurs, ou elle
# comptera pour un secret.
DECOY_PASSWORD: Final[Password] = _forge(secrets.token_urlsafe(32)[:PASSWORD_MAX_LENGTH])


@dataclass(frozen=True, slots=True, repr=False)
class PasswordHash:
    """Empreinte d'un mot de passe, au format PHC (`$argon2id$v=19$m=...`).

    Un TYPE et non une `str`, pour une raison qui vaut a elle seule les quinze
    lignes : `verify(stored, candidate)` avec deux chaines est l'erreur la plus
    couteuse de cette famille d'API -- inverser les deux verifie une empreinte
    contre une empreinte, ou stocke un clair. Ici, l'inversion ne passe pas Mypy.

    LA COLONNE QUI L'ACCUEILLERA (BACK-28) : `String(255)` ou `Text`, surtout pas
    `String(97)`. Une empreinte aux parametres par defaut du service fait
    exactement 97 caracteres ; dimensionner dessus transformerait la premiere
    montee de cout en troncature silencieuse ou en insertion refusee.
    """

    encoded: str

    def __post_init__(self) -> None:
        """Refuse une empreinte vide.

        Raises:
            ValueError: si la chaine est vide. C'est un defaut de programme, pas un
                refus metier : personne ne SAISIT une empreinte.
        """
        if not self.encoded:
            message = "Une empreinte de mot de passe ne peut pas etre vide."
            raise ValueError(message)

    def __repr__(self) -> str:
        """Rend les parametres de l'empreinte, sans le sel ni le condense.

        Les parametres ne sont pas secrets -- ils voyagent en clair dans l'empreinte
        et se lisent dans la configuration -- et ce sont eux qu'on veut voir en
        diagnostiquant une remise a niveau. Le sel et le condense, eux, sont ce
        qu'une base volee contient : les laisser fuir par un journal rendrait ce vol
        exploitable hors ligne depuis les seuls journaux.

        LE DECOUPAGE SE FAIT PAR LA FIN, ET C'EST UNE CORRECTION. Compter quatre
        champs depuis le debut supposait le segment de version : une empreinte a
        CINQ champs -- argon2 sans `v=`, `$scrypt$`, `$pbkdf2-sha256$` -- voyait
        alors son SEL passer pour un parametre et sortir en clair. Retirer les deux
        derniers champs, quel qu'en soit le nombre total, ne se trompe jamais : le
        format PHC finit toujours par `$<sel>$<condense>`.

        Returns:
            Par exemple `PasswordHash($argon2id$v=19$m=19456,t=2,p=1$***)`.
        """
        prefix, separator, _ = self.encoded.rpartition("$")
        prefix, _, _ = prefix.rpartition("$")
        return f"PasswordHash({prefix}$***)" if separator and prefix else "PasswordHash(***)"
