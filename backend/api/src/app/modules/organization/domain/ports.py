"""Ports metier du module organization (BACK-16).

Un port est un BESOIN exprime par le domaine, jamais une technologie. Ceux-ci
disent « je dois pouvoir repondre aux trois questions de l'authentification » ;
ils ne disent ni PostgreSQL, ni SQLAlchemy. L'adaptateur qui les remplit vit
dans `infrastructure/db/repositories.py`.

LES TROIS REQUETES DU TICKET, ET RIEN D'AUTRE
Elles sont la SEULE surface publique du module -- aucun autre module n'accede
a ses tables :

1. les appartenances actives d'un compte -- consommee a l'emission du jeton
   (BACK-10a), donc AVANT tout groupe actif : `MembershipRepository` n'est pas
   un depot tenant, et cette requete fonctionne hors de tout contexte ;
2. le role d'un compte dans un groupe donne -- meme depot, meme absence de
   contexte requis ;
3. les affectations d'un compte dans le groupe actif -- consommee par
   `require_role(scope="clinic")` (BACK-10c) : `AssignmentRepository` EST un
   depot tenant, la requete exige un perimetre pose et herite du filtre.

Le ticket dit « trois ports » ; ils prennent ici la forme du pattern etabli --
deux ports de depot et l'unite de travail du module (ADR-0009) -- trois
methodes, une par question. C'est d'ailleurs ainsi que les tickets
consommateurs en parlent : le « port d'appartenance » de BACK-10a, le « port
d'affectation » de BACK-10c. Ecart de lettre consigne au registre.

`at` EST FOURNI PAR L'APPELANT, ET TOUJOURS AVEC FUSEAU
« Active » ne veut rien dire sans instant. BACK-10a fige UN instant pour toute
l'emission -- coherence entre le `iat` du jeton et la verification
d'appartenance -- et une question d'audit (ADR-0005) est la meme requete avec
un autre `at`. Aucune horloge cachee dans l'adaptateur : le port se teste sans
injection de temps. Un instant NAIF est refuse (`InvalidWindowError`, garde
`ensure_aware_instant`) : lie tel quel a un `timestamptz`, PostgreSQL
l'interpreterait dans le fuseau de la session, en silence -- la meme regle que
les bornes des fenetres.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.organization.domain.entities import Assignment, GroupRole, Membership
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork


class MembershipRepository(ABC):
    """Acces aux appartenances, exprime en entites du domaine.

    Le port n'expose QUE les deux questions que l'authentification pose.
    L'implementation, qui herite du depot generique de `shared/`, sait aussi
    ajouter, lister et supprimer : le port ne s'elargit pas parce que la
    classe sait faire plus -- BACK-25 elargira le sien quand ses cas d'usage
    existeront.
    """

    @abstractmethod
    async def list_active_for_account(self, account_id: UUID, at: datetime) -> Sequence[Membership]:
        """Rend les appartenances d'un compte actives a l'instant donne.

        La requete de l'EMISSION DE JETON (BACK-10a) : elle tourne avant tout
        groupe actif, donc hors de tout contexte de tenance -- c'est la raison
        pour laquelle ce depot n'est pas tenant.

        Args:
            account_id: le compte dont on cherche les appartenances.
            at: l'instant de reference -- celui de l'emission.

        Returns:
            Les appartenances actives, du debut le plus ancien au plus recent.
            Vide si le compte n'appartient a aucun groupe : pour un compte
            particulier, c'est le cas nominal, pas une erreur.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """

    @abstractmethod
    async def find_active_role(
        self, account_id: UUID, group_id: UUID, at: datetime
    ) -> GroupRole | None:
        """Cherche le role d'un compte dans un groupe donne, a l'instant donne.

        `find_` et non `get_` : ici l'absence est un RESULTAT ATTENDU -- c'est
        `require_role` qui decidera du refus, pas le depot. Si plusieurs
        appartenances au meme groupe se chevauchent (possible par
        construction, ADR-0005), le role rendu est celui de l'appartenance au
        debut le plus recent : la derniere decision prise l'emporte, et le
        resultat reste deterministe.

        Args:
            account_id: le compte interroge.
            group_id: le groupe dans lequel le role est cherche.
            at: l'instant de reference.

        Returns:
            Le role de perimetre groupe, ou None si aucune appartenance a ce
            groupe n'est active a cet instant.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """


class AssignmentRepository(ABC):
    """Acces aux affectations, exprime en entites du domaine.

    Depot TENANT : toute lecture passe par le filtre de groupe (BACK-06b), et
    exiger un perimetre pose n'est pas une gene mais la garantie -- une
    affectation ne se lit jamais hors du groupe qui la possede.
    """

    @abstractmethod
    async def list_active_for_account(self, account_id: UUID, at: datetime) -> Sequence[Assignment]:
        """Rend les affectations d'un compte actives dans le groupe actif.

        La requete de `require_role(scope="clinic")` (BACK-10c) : les roles de
        clinique se resolvent TOUJOURS a la requete, jamais depuis le jeton.
        Le groupe interroge est celui du contexte de tenance -- aucun
        parametre de groupe : le perimetre vient du claim, pas de l'appelant.

        Args:
            account_id: le compte dont on cherche les affectations.
            at: l'instant de reference -- celui de la requete HTTP.

        Returns:
            Les affectations actives dans le groupe actif, du debut le plus
            ancien au plus recent.

        Raises:
            InvalidWindowError: si l'instant est naif.
            MissingTenantContextError: si aucun perimetre de tenance n'est
                pose -- jamais un repli silencieux sur tous les groupes.
        """


class OrganizationUnitOfWork(AbstractUnitOfWork):
    """Unite de travail du module : sa transaction, ses depots, rien d'autre.

    UNE UNITE PAR MODULE, jamais une unite globale (ADR-0009) : `identity` et
    `organization` ne partagent pas leur atomicite. Les depots sont des
    PROPRIETES, pas des attributs -- chaque acces repasse par la garde du
    bloc, et lever hors bloc reste la regle du port, partout.

    Seuls les depots des deux relations sont exposes : aucun port ne lit
    `Group` ni `Clinic` dans ce ticket, et une propriete sans consommateur
    serait la surface de CRUD que la portee exclut. BACK-25 les ajoutera avec
    ses cas d'usage.
    """

    @property
    @abstractmethod
    def memberships(self) -> MembershipRepository:
        """Le depot d'appartenances, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """

    @property
    @abstractmethod
    def assignments(self) -> AssignmentRepository:
        """Le depot d'affectations, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
