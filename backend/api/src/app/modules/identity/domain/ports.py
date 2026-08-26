"""Ports metier du module identity (BACK-04, unite de travail en BACK-06a, OTP en BACK-17).

Un port est un BESOIN exprime par le domaine, jamais une technologie. Celui-ci
dit « je dois pouvoir retrouver et enregistrer un compte » ; il ne dit ni
PostgreSQL, ni SQLAlchemy, ni meme « base de donnees ». L'adaptateur qui le
remplit vit dans `infrastructure/db/repositories.py`, et un second adaptateur en
memoire lui repondra pour les tests (BACK-06c) sans qu'une ligne de metier
change.

POURQUOI CES PORTS-LA SONT DANS LE DOMAINE DU MODULE
`AccountRepository` et `IdentityUnitOfWork` parlent de comptes : ce sont des
ports METIER, ils appartiennent a `identity`. Les ports TECHNIQUES -- cache,
stockage de fichiers, jetons -- vivent dans `shared/domain/ports/`, sans quoi le
premier module a en avoir besoin deviendrait une dependance de tous les autres.
Les trois ports d'OTP restent ici pour la meme raison : un magasin de codes de
verification d'adresse ne sert qu'a `identity`, et le jour ou un second module en
voudrait un, ce serait le signe qu'il parle d'identite.

POURQUOI TROIS PORTS D'OTP ET NON DEUX (BACK-17)
La carte en annonce deux, `OtpSender` et `OtpStore` ; il en faut un troisieme, et
c'est la securite qui l'impose. Un argument de tache TRANSITE EN CLAIR par le
stream Redis, qui n'a pas de TTL : y faire passer le code reviendrait a deposer
le secret a cote de son propre condense. Le code est donc engendre DANS le
worker, et le cas d'usage qui repond en HTTP ne fait que demander un envoi --
c'est ce que dit `OtpDispatcher`. Sans lui, un cas d'usage devrait importer
`infrastructure/tasks/`, ce que le contrat `module-layers` refuse.

CE QUE BACK-06A A CHANGE ICI
Le cas d'usage recoit desormais `IdentityUnitOfWork` -- le port d'unite de
travail du module -- plutot qu'un depot nu, et l'implementation du depot herite
du depot generique de `shared/`. Le contrat d'`AccountRepository`, lui, n'a pas
bouge : c'est precisement ce qu'un port doit permettre. Seule retouche de
forme : les arguments de `get`, `add` et `save` sont devenus positionnels
(`/`), pour que le vocabulaire du port (`account_id`) et celui du generique
(`entity_id`) ne puissent jamais diverger dans un appel par mot-cle que Mypy
ne verifie pas. `find_by_email`, propre au module, garde sa forme.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.identity.domain.entities import Account
from app.modules.identity.domain.policies import OtpRules
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork


class AccountRepository(ABC):
    """Acces aux comptes, exprime en entites du domaine.

    Toutes les methodes echangent des `Account` -- jamais un modele SQLAlchemy,
    jamais un dictionnaire. C'est la frontiere ou le mapping s'applique, et
    c'est ce qui permet au cas d'usage d'ignorer jusqu'a l'existence d'un ORM.

    Le port n'expose QUE ce que les cas d'usage du module ont le droit de
    faire. L'implementation, qui herite du depot generique de `shared/`, sait
    aussi lister et supprimer : le port ne s'elargit pas parce que la classe
    sait faire plus.
    """

    @abstractmethod
    async def get(self, account_id: UUID, /) -> Account:
        """Retourne le compte portant cet identifiant.

        Args:
            account_id: l'identifiant du compte.

        Returns:
            Le compte reconstitue.

        Raises:
            AccountNotFoundError: si aucun compte ne porte cet identifiant. Une
                absence est ici une ERREUR : l'appelant tient l'identifiant d'un
                jeton ou d'une URL, il attend le compte, pas un `None` a tester.
        """

    @abstractmethod
    async def find_by_email(self, email: str) -> Account | None:
        """Cherche un compte par son adresse, sans erreur si rien ne correspond.

        `find_` et non `get_` : ici l'absence est un RESULTAT ATTENDU -- c'est ce
        qu'interroge un controle d'unicite avant creation.

        Args:
            email: l'adresse, deja normalisee par le domaine.

        Returns:
            Le compte, ou None si l'adresse est libre.
        """

    @abstractmethod
    async def add(self, account: Account, /) -> None:
        """Enregistre un compte qui n'existait pas.

        Args:
            account: le compte a creer.
        """

    @abstractmethod
    async def save(self, account: Account, /) -> None:
        """Reporte sur la persistance l'etat d'un compte deja connu.

        Args:
            account: le compte modifie.
        """


class IdentityUnitOfWork(AbstractUnitOfWork):
    """Unite de travail du module : sa transaction, ses depots, rien d'autre.

    UNE UNITE DE TRAVAIL PAR MODULE, et jamais une unite globale. Ce qu'on ne
    peut pas placer dans une seule transaction devient alors une frontiere
    VISIBLE -- `identity` et `organization` ne partagent pas leur atomicite --
    plutot qu'une dette invisible que le premier incident revelera.

    C'est CE type que recoivent les cas d'usage, et la raison est mecanique
    autant qu'architecturale : l'implementation vit a la racine du module et
    importe l'infrastructure ; un cas d'usage qui la nommerait creerait la
    chaine `application -> infrastructure` que le contrat `module-layers` de
    BACK-04b refuse. Le port, lui, ne connait que le domaine.

    LES DEPOTS SONT DES PROPRIETES, PAS DES ATTRIBUTS. Un attribut pose a
    l'entree du bloc survivrait a sa sortie, depot mort en main ; une propriete
    repasse par la garde de l'unite a chaque acces, et lever hors bloc reste
    ainsi la regle 3 du port, partout.
    """

    @property
    @abstractmethod
    def accounts(self) -> AccountRepository:
        """Le depot de comptes, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """


class OtpStoreUnavailableError(RuntimeError):
    """Le magasin de codes ne repond pas : aucune reponse ne peut etre donnee.

    UN `RuntimeError` ET NON UNE `DomainError`, ET C'EST LE COEUR DU CONTRAT.
    Une `DomainError` sortirait en 4xx, c'est-a-dire en refus metier ; ici rien
    n'est refuse, on ne SAIT PAS. Elle tombe donc sur le chemin 500 generique,
    comme `MissingTenantContextError` et pour la meme raison : c'est une panne.

    Le port `Cache` (BACK-14) annonce l'inverse -- il degrade en silence -- et sa
    docstring nomme deja ce ticket pour dire pourquoi la regle ne s'y applique
    pas : « cet OTP a-t-il ete consomme ? » repondu « non » par defaut ouvre la
    porte au lieu de la fermer. Un magasin de securite echoue FERME.
    """


class OtpDeliveryError(RuntimeError):
    """Le code n'a pas pu etre remis a son destinataire.

    Egalement technique, et egalement non metier : le compte est bon, l'adresse
    est bonne, c'est le transport qui a echoue. Levee depuis la tache de fond,
    elle y declenche la politique de reprise de BACK-15 -- reessais avec repli
    exponentiel, puis file de rejets. Un utilisateur qui ne recoit rien redemande
    un code, ce que les quotas de renvoi autorisent.
    """


class OtpConsumption(StrEnum):
    """Ce qu'une tentative de verification a produit.

    Un verdict RENDU par le magasin, et non une exception levee par lui : c'est le
    cas d'usage qui decide de la traduction en refus metier, et lui seul connait
    la regle de non-divulgation qui confond `REJECTED` et l'absence de code.
    """

    ACCEPTED = "accepted"
    """Le code correspond. Il est detruit dans le meme geste : usage unique."""

    REJECTED = "rejected"
    """Code faux, expire, ou aucun code en cours -- indistinctement, a dessein."""

    EXHAUSTED = "exhausted"
    """Le quota de tentatives est epuise : le code est detruit, il en faut un neuf."""


@dataclass(frozen=True, slots=True)
class ResendVerdict:
    """Reponse du magasin a une demande d'envoi : passe, ou repasse plus tard.

    Attributes:
        allowed: vrai si la demande peut partir. Quand il vaut vrai, les compteurs
            ont DEJA ete consommes -- le verdict n'est pas une consultation, c'est
            un passage de tourniquet.
        retry_after_seconds: delai avant nouvelle tentative, quand il est refuse.
            `None` si la demande passe.
    """

    allowed: bool
    retry_after_seconds: int | None = None


class OtpStore(ABC):
    """Magasin des codes de verification d'adresse, et des quotas qui les bornent.

    TROIS REGLES QUI ENGAGENT TOUTE IMPLEMENTATION

    1. LE CODE EN CLAIR N'EST JAMAIS CONSERVE. Le magasin recoit un code, il en
       range l'EMPREINTE (`fingerprint_otp_code`) et oublie le reste. Ce que
       quelqu'un lirait du stockage ne doit pas lui permettre de se verifier.

    2. TOUT ECHEC EST FERME. Stockage injoignable, reponse illisible : lever
       `OtpStoreUnavailableError`, jamais rendre un verdict par defaut. C'est
       l'exact contraire du port `Cache`, dont la docstring designe deja ce
       ticket. Le seul verdict qu'une panne peut produire est « je ne sais pas ».

    3. LA CONSOMMATION EST ATOMIQUE. `consume` decremente le quota de tentatives
       ET rend l'empreinte conservee dans une seule operation indivisible. Deux
       requetes concurrentes ne doivent pas pouvoir depenser la meme tentative --
       sinon trois tentatives en deviennent trente, lancees en parallele.
    """

    @abstractmethod
    async def issue(self, *, account_id: UUID, code: str, rules: OtpRules) -> None:
        """Range un code neuf pour ce compte, et arme son quota de tentatives.

        ECRASEMENT ABSOLU : un code emis remplace le precedent, qui devient
        invalide a l'instant meme. C'est ce qui rend la tache d'envoi rejouable
        sans effet cumulatif -- il n'y a jamais qu'un seul code valide par compte.

        Args:
            account_id: le compte destinataire.
            code: le code en clair. Il ne doit pas survivre a cet appel autrement
                que sous forme d'empreinte.
            rules: les bornes -- duree de validite et nombre de tentatives.

        Raises:
            OtpStoreUnavailableError: si le stockage ne repond pas.
        """

    @abstractmethod
    async def consume(self, *, account_id: UUID, code: str) -> OtpConsumption:
        """Depense une tentative et dit ce que le code presente vaut.

        Le code est detruit dans TROIS cas : il correspond (usage unique), le
        quota de tentatives tombe a zero, ou sa duree de vie s'acheve d'elle-meme.

        Args:
            account_id: le compte dont on verifie l'adresse.
            code: le code saisi par l'utilisateur.

        Returns:
            Le verdict. La comparaison se fait en TEMPS CONSTANT
            (`codes_match`) : une egalite qui s'arrete au premier caractere
            different laisse reconstituer l'empreinte position par position.

        Raises:
            OtpStoreUnavailableError: si le stockage ne repond pas.
        """

    @abstractmethod
    async def register_resend(
        self, *, account_id: UUID, client_ip: str | None, rules: OtpRules
    ) -> ResendVerdict:
        """Passe le tourniquet des envois : delai minimal et deux plafonds.

        LES TROIS CONTROLES SONT INDIVISIBLES et ne consomment RIEN quand l'un
        d'eux refuse. Sans cela, un double-clic ferait passer le delai minimal
        puis brulerait quand meme une unite du plafond horaire.

        Args:
            account_id: le compte demandeur -- il tient lieu d'adresse, la relation
                etant de un a un, et evite de faire entrer une donnee personnelle
                dans une cle de stockage.
            client_ip: l'adresse IP reelle de l'appelant (INFRA-04 la reecrit
                depuis `X-Forwarded-For`), ou `None` quand la demande ne vient pas
                d'une requete HTTP -- le plafond par IP est alors sans objet.
            rules: les bornes des trois controles.

        Returns:
            Le verdict, avec le delai avant nouvelle tentative s'il est refuse.

        Raises:
            OtpStoreUnavailableError: si le stockage ne repond pas. Un quota qu'on
                ne peut pas verifier bloque l'envoi -- c'est la regle 2, et c'est
                aussi ce qui empeche de contourner la limite en faisant tomber
                Redis.
        """


class OtpSender(ABC):
    """Remise du code a son destinataire. Un TRANSPORT, et rien d'autre.

    Le port ne sait ni engendrer un code, ni decider s'il faut l'envoyer : on lui
    donne une adresse et six chiffres, il les fait parvenir. C'est ce qui rend la
    doublure des tests triviale -- elle retient le dernier code emis -- et ce qui
    a permis a BACK-22 de deplacer le dialogue SMTP hors du module sans qu'une
    ligne de metier bouge : le port n'a pas change, seule son implementation
    delegue desormais au port technique `EmailTransport` de `shared/`.

    CE PORT SURVIT A BACK-22, IL N'EST PAS REMPLACE PAR LUI. Le module
    `notifications` recoit ses evenements PAR LA FILE, ou tout argument voyage en
    clair dans un stream sans TTL ; un code de verification est un secret et ne
    traverse rien (ADR-0020). Il est engendre dans le worker et remis depuis le
    worker.

    UN OTP PART TOUJOURS, quelles que soient les preferences de notification : ce
    n'est pas un message de confort mais un message TRANSACTIONNEL, sans lequel le
    compte reste inutilisable. La distinction est posee par BACK-22 ; elle se
    traduit ici par le fait que cet appel ne consulte aucune preference.
    """

    @abstractmethod
    async def send_verification_code(
        self, *, recipient: str, recipient_name: str, code: str, ttl_seconds: int
    ) -> None:
        """Fait parvenir un code de verification a une adresse.

        Args:
            recipient: l'adresse e-mail, deja normalisee.
            recipient_name: le nom affiche du destinataire, pour l'en-tete `To` et
                la formule d'appel.
            code: les six chiffres, tels que l'utilisateur devra les saisir.
            ttl_seconds: la duree de validite, a annoncer dans le message -- un
                code sans peremption affichee se recopie une heure plus tard.

        Raises:
            OtpDeliveryError: si la remise echoue. La tache de fond en fait une
                reprise ; un appelant synchrone n'en attend pas.
        """


class OtpDispatcher(ABC):
    """Declenchement d'un envoi de code, hors du fil de la requete.

    LA REQUETE HTTP N'ATTEND PAS LE SMTP : une session TLS vers un fournisseur de
    messagerie prend le temps qu'elle prend, et l'inscription ne doit pas en
    dependre. L'implementation met une tache en file (BACK-15) ; le code lui-meme
    est engendre de l'autre cote, dans le worker.

    LA TACHE NE TRANSPORTE QU'UN IDENTIFIANT DE COMPTE. Ni le code -- il n'existe
    pas encore --, ni l'adresse, ni l'IP : le worker recharge ce dont il a besoin.
    C'est la regle des taches de BACK-15, et ici c'est aussi une regle de secret.
    """

    @abstractmethod
    async def dispatch_verification(self, *, account_id: UUID) -> None:
        """Demande qu'un code de verification parte vers ce compte.

        L'appel rend la main des que la demande est ACCEPTEE, pas quand le message
        est remis : ce qui suit -- generation, rangement, envoi -- se passe
        ailleurs. Un appelant ne peut donc pas conclure de son retour que
        l'utilisateur a recu quelque chose.

        Args:
            account_id: le compte dont l'adresse est a verifier.

        Raises:
            OtpDeliveryError: si la demande n'a meme pas pu etre mise en file.
        """
