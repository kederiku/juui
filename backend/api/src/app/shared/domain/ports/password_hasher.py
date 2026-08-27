"""Port du hachage de mot de passe (BACK-10b).

Le contrat, jamais son adaptateur : ce module ne connait ni argon2, ni bcrypt, ni
le format PHC. Il dit ce que le service a besoin de faire d'un mot de passe --
en produire une empreinte, et confronter une saisie a une empreinte conservee --
et laisse a `shared/infrastructure/security/` le soin de choisir avec quoi.

CE QU'IL FAIT DEVANT UNE PANNE : IL LEVE, ET IL N'ECRIT RIEN
Huitieme port du noyau partage, huitieme reponse. `Cache` DEGRADE parce qu'un
cache absent ne change qu'une latence ; `BreachChecker` DEGRADE pour un motif
different, un service tiers muet coutant moins cher qu'une inscription
impossible ; `FileStorage`, `EmailTransport` et `TokenService` LEVENT. Celui-ci
leve aussi, et pour le motif le plus simple : une empreinte qu'on ne sait pas
produire n'a pas de valeur de repli, et un verdict d'authentification non plus.
Rendre « vrai » par defaut authentifierait tout le monde ; rendre « faux »
enfermerait tout le monde dehors. Il n'y a pas de troisieme option raisonnable.

A NE PAS CONFONDRE AVEC LE PORT VOISIN. `BreachChecker` et `PasswordHasher` sont
livres par le meme ticket, servent le meme parcours, et repondent a l'INVERSE
l'un de l'autre. Ce qui decide n'est pas la famille du port mais ce que la
reponse par defaut AUTORISE : « ce mot de passe a-t-il fuite ? » repondu « non »
laisse passer un secret que l'utilisateur a lui-meme choisi ; « ce mot de passe
est-il le bon ? » repondu « oui » ouvre le compte de quelqu'un d'autre.

DEUX METHODES, ET PAS DE `needs_rehash` PUBLIC
La remise a niveau vit DANS `verify`, qui rend un `VerificationOutcome`. Un
`needs_rehash()` separe obligerait l'appelant a rehacher lui-meme, donc a
fabriquer un `Password` a partir de la saisie de connexion -- sur un chemin ou la
politique ne s'applique PAS. Le jour ou la borne basse passerait de 14 a 16, tout
compte cree avec quatorze caracteres verrait sa connexion echouer en 422 au
moment du rehachage, et seulement ceux dont l'empreinte est perimee, c'est-a-dire
exactement ceux que la remise a niveau devait servir. L'adaptateur, lui, detient
deja les octets verifies : il rehache sans repasser par la politique.

CE QUE CE PORT NE FAIT PAS, ET QUE BACK-29 DOIT FAIRE

1. LA VERIFICATION FACTICE SUR COMPTE INCONNU. Mesure sur ce depot : un `verify`
   coute une quinzaine de millisecondes, une recherche infructueuse en base moins
   d'une. Repondre « identifiants invalides » tout de suite pour une adresse
   inconnue et quinze millisecondes plus tard pour une adresse connue fait du
   formulaire de connexion un enumerateur de comptes -- et defait d'un coup la
   non-divulgation que le service tient partout ailleurs (404 jamais 403,
   inscription indiscernable, refus d'OTP unique). Le remede tient en une ligne
   sur le chemin du compte inconnu : `await hasher.hash(DECOY_PASSWORD)`, en
   jetant le resultat. La constante vit dans `shared/domain/password.py` et
   existe pour cela -- la premiere redaction de ce paragraphe disait « une
   ligne » sans qu'aucune ligne ne soit ecrivable, `Password.create` etant
   asynchrone et exigeant un controle de fuite qui n'a aucun sens sur une valeur
   jetee.
2. PERSISTER `refreshed_hash`, ET HORS DU CHEMIN QUI DECIDE DE LA CONNEXION. Une
   ecriture en echec ne doit jamais faire echouer une authentification par
   ailleurs valide : la remise a niveau se retentera a la connexion suivante.
3. LA COLONNE. Aucun compte ne porte encore d'empreinte ; c'est BACK-28 qui pose
   le champ, la colonne et la migration, dans le commit qui les remplit. La forme
   attendue est dans la docstring de `PasswordHash`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.shared.domain.password import Password, PasswordHash

__all__ = [
    "PasswordHasher",
    "PasswordHashingError",
    "PasswordHashingFailedError",
    "StoredPasswordHashInvalidError",
    "VerificationOutcome",
]


class PasswordHashingError(RuntimeError):
    """Panne TECHNIQUE du hachage : aucune empreinte, aucun verdict.

    UN `RuntimeError` ET NON UNE `DomainError`, comme `EmailDeliveryError` et
    `TokenIssuanceError` avant elle. Une extension cryptographique absente ou une
    allocation memoire refusee ne sont pas des refus metier : les traduire en 4xx
    dirait a l'appelant qu'il a fait quelque chose de travers, alors que le
    service est en panne. Elles sortent donc en 500, avec leur trace.

    Le refus METIER, lui, est `PasswordPolicyError` et ses filles, dans
    `shared/domain/password.py`.
    """


class StoredPasswordHashInvalidError(PasswordHashingError):
    """L'empreinte conservee est illisible : ce n'est PAS un mot de passe faux.

    LA DISTINCTION EST LE SUJET. Rendre « non verifie » sur une colonne tronquee
    ou corrompue transformerait « notre base est abimee » en « tous ces gens se
    trompent de mot de passe » : une panne totale, diagnostiquee comme une erreur
    d'utilisateur, et decouverte par le service client. Elle leve, donc elle se
    voit.
    """


class PasswordHashingFailedError(PasswordHashingError):
    """Le calcul lui-meme n'a pas abouti.

    Le cas concret est l'allocation : argon2 reserve son cout memoire d'un bloc,
    et un conteneur trop serre le lui refuse. Le message doit donc nommer le cout
    configure, faute de quoi l'exploitant lit « echec de hachage » sans savoir
    quel bouton tourner.
    """


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """Verdict d'une verification, et l'empreinte a reecrire s'il y a lieu.

    Un objet plutot qu'un `bool`, parce que la remise a niveau n'a de sens qu'ici :
    c'est le seul instant ou le service detient a la fois le mot de passe en clair
    et la preuve qu'il est le bon. Voir la docstring de module pour ce qui arrive
    quand on separe les deux.
    """

    verified: bool
    """Vrai si la saisie correspond a l'empreinte conservee."""

    refreshed_hash: PasswordHash | None = None
    """Empreinte recalculee aux parametres COURANTS, a persister telle quelle.

    `None` dans trois situations qu'il ne faut pas confondre : la verification a
    echoue (on ne rehache pas ce dont on vient de prouver qu'on ne le connait
    pas), l'empreinte etait deja aux bons parametres, ou le rehachage a echoue --
    ce dernier cas etant journalise par l'adaptateur, jamais propage : une
    connexion valide ne se perd pas pour une remise a niveau.
    """


class PasswordHasher(ABC):
    """Produit et verifie les empreintes de mot de passe.

    TROIS REGLES QUI ENGAGENT TOUTE IMPLEMENTATION

    1. LE CLAIR NE SORT PAS, ET L'EMPREINTE NON PLUS. Aucune implementation ne
       journalise le mot de passe ; aucune ne journalise l'empreinte, qui embarque
       le sel et les parametres et rendrait une base volee cassable hors ligne
       depuis les seuls journaux.
    2. AUCUNE EXCEPTION DE LA BIBLIOTHEQUE DE HACHAGE NE FRANCHIT CE PORT. Ce qui
       en sort est `False` (mauvais mot de passe) ou l'une des trois erreurs
       ci-dessus. C'est ce qui evite a chaque appelant de connaitre la taxonomie
       d'une bibliotheque tierce pour distinguer un refus d'une panne.
    3. `hash` PREND UN `Password`, PAS UNE CHAINE. Le type est ce qui garantit
       qu'on ne hache jamais un secret dont la politique n'a pas ete appliquee --
       et `Password` ne se construit qu'en demandant le controle de fuite. Un port
       qui prendrait un `str` rendrait cette garantie facultative.
    """

    @abstractmethod
    async def hash(self, password: Password) -> PasswordHash:
        """Produit l'empreinte d'un mot de passe, aux parametres courants.

        Asynchrone parce que le calcul est LONG et delibere : quelques dizaines de
        millisecondes de processeur, mobilisant plusieurs mebioctets. Le tenir dans
        la boucle d'evenements figerait toutes les requetes en vol, pas seulement
        celle-ci.

        Args:
            password: le mot de passe accepte par la politique.

        Returns:
            L'empreinte, prete a etre conservee.

        Raises:
            PasswordHashingFailedError: le calcul n'a pas abouti.
        """

    @abstractmethod
    async def verify(self, *, stored: PasswordHash, candidate: str) -> VerificationOutcome:
        """Confronte une saisie a une empreinte conservee.

        Arguments NOMMES, et types distincts : intervertir l'empreinte et la saisie
        est l'erreur classique de cette famille d'API, et elle ne se voit pas en
        relecture. Ici elle ne passe ni le mot-cle, ni Mypy.

        `candidate` est une CHAINE et non un `Password` : la politique ne s'applique
        pas a la connexion (voir `shared/domain/password.py`). Un mot de passe
        devenu trop court parce que la borne a bouge reste un mot de passe valide
        pour son proprietaire.

        Args:
            stored: l'empreinte conservee pour ce compte.
            candidate: la saisie a verifier, telle quelle.

        Returns:
            Le verdict, accompagne de l'empreinte a reecrire si les parametres de
            cout ont change depuis. Un mot de passe faux rend `verified=False` et
            ne leve pas : c'est le cas nominal d'un formulaire de connexion.

        Raises:
            StoredPasswordHashInvalidError: l'empreinte conservee est illisible.
                A NE PAS traduire en refus d'authentification -- relire la docstring
                de la classe avant d'en faire un `except` qui rend `False`.
        """
