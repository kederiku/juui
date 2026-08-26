"""Ports metier du module medical_records (BACK-19).

Un port est un BESOIN exprime par le domaine, jamais une technologie. Ceux-ci
disent « je dois pouvoir repondre aux questions du dossier » ; ils ne disent
ni PostgreSQL, ni SQLAlchemy. L'adaptateur qui les remplit vit dans
`infrastructure/db/repositories.py`.

LES TROIS QUESTIONS DU SOCLE, ET RIEN D'AUTRE
Aucun cas d'usage n'existe encore (BACK-30 les apportera) ; la surface
publique se limite aux lectures qui prouvent le modele et que les tickets
suivants consommeront :

1. les animaux dont un compte a la detention ACTIVE -- la jointure
   quotidienne nommee par ADR-0006 (« les animaux de ce client »), celle de
   la liste de BACK-30 et du compteur de BACK-26 ; un animal cede disparait
   de la liste, pas de l'historique ;
2. la detention d'un animal en vigueur a un instant donne -- la question que
   chaque acte clinique posera avant de s'enregistrer (critere 2 du ticket) ;
3. l'historique complet des detentions d'un animal -- la preuve du critere
   4 : les detentions successives restent intactes, jamais reecrites.

PAS d'ecriture dans les ports : `add` et `save` existent sur les classes
concretes (depot generique), mais « le port ne s'elargit pas parce que la
classe sait faire plus » -- BACK-30 publiera les siens avec ses cas d'usage.
L'unite de travail expose deja les DEUX depots sur la meme session : creer
l'animal ET sa detention initiale dans une seule transaction est acquis.

`at` EST FOURNI PAR L'APPELANT, ET TOUJOURS AVEC FUSEAU
« En vigueur » ne veut rien dire sans instant, et une question d'audit est la
meme requete avec un autre `at`. Aucune horloge cachee dans l'adaptateur : le
port se teste sans injection de temps. Un instant NAIF est refuse
(`InvalidWindowError`, garde `ensure_aware_instant`) : lie tel quel a un
`timestamptz`, PostgreSQL l'interpreterait dans le fuseau de la session, en
silence.

AUCUN DEPOT TENANT ICI
`Animal` et `Custody` ne portent pas la tenance : leurs requetes tournent a
l'inscription et dans l'espace personnel du particulier, hors de tout groupe.
L'isolation vient de la RELATION -- chaque question est posee POUR un compte
ou POUR un animal, jamais « tout voir ».
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.medical_records.domain.entities import Animal, Custody
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork


class AnimalRepository(ABC):
    """Acces aux fiches animal, exprime en entites du domaine.

    Le port n'expose que la question que les tickets consommateurs poseront.
    L'implementation, qui herite du depot generique de `shared/`, sait aussi
    ajouter, charger et supprimer : le port ne s'elargit pas parce que la
    classe sait faire plus -- BACK-30 elargira le sien quand ses cas d'usage
    existeront.
    """

    @abstractmethod
    async def list_with_active_custody_for_account(
        self, account_id: UUID, at: datetime
    ) -> Sequence[Animal]:
        """Rend les animaux dont le compte a la detention active a l'instant donne.

        LA jointure d'ADR-0006 : « les animaux de ce client » devient une
        lecture de la detention en cours, plus une jointure -- c'est le cout
        assume de la decision. Un animal cede (detention close) disparait de
        la liste, mais pas de l'historique.

        Args:
            account_id: le compte particulier interroge.
            at: l'instant de reference -- celui de la requete.

        Returns:
            Les animaux detenus, du plus anciennement enregistre au plus
            recent. Vide si le compte ne detient rien : c'est un cas nominal,
            pas une erreur.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """


class CustodyRepository(ABC):
    """Acces aux detentions, exprime en entites du domaine."""

    @abstractmethod
    async def find_active_for_animal(self, animal_id: UUID, at: datetime) -> Custody | None:
        """Cherche la detention d'un animal en vigueur a l'instant donne.

        `find_` et non `get_` : ici l'absence est un RESULTAT ATTENDU -- un
        animal sans detenteur courant existe (cede, en attente de
        rattachement). C'est la question que chaque acte clinique posera au
        moment des faits (critere 2) : l'acte referencera cette detention,
        jamais le proprietaire courant. Si des fenetres closes se chevauchent
        (possible apres une fusion BACK-20), la detention rendue est celle au
        debut le plus recent, de maniere deterministe.

        Args:
            animal_id: l'animal interroge.
            at: l'instant de reference -- celui des faits.

        Returns:
            La detention en vigueur, ou None si aucune ne couvre l'instant.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """

    @abstractmethod
    async def list_for_animal(self, animal_id: UUID) -> Sequence[Custody]:
        """Rend TOUTES les detentions d'un animal, l'historique intact.

        La preuve du critere 4 : deux detentions successives restent deux
        lignes, bornes intactes -- l'historique ne se reecrit jamais. Pas de
        parametre `at` : l'historique n'a pas d'instant, il est la memoire.

        Args:
            animal_id: l'animal interroge.

        Returns:
            Les detentions, du debut le plus ancien au plus recent.
        """


class MedicalRecordsUnitOfWork(AbstractUnitOfWork):
    """Unite de travail du module : sa transaction, ses depots, rien d'autre.

    UNE UNITE PAR MODULE, jamais une unite globale (ADR-0009) : le dossier
    animal ne partage son atomicite avec personne. Les depots sont des
    PROPRIETES, pas des attributs -- chaque acces repasse par la garde du
    bloc, et lever hors bloc reste la regle du port, partout.

    Les deux depots partagent la session du bloc : c'est ce qui permettra a
    BACK-30 de creer l'animal ET sa detention initiale dans UNE transaction --
    jamais d'animal sans detenteur initial.
    """

    @property
    @abstractmethod
    def animals(self) -> AnimalRepository:
        """Le depot des fiches animal, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """

    @property
    @abstractmethod
    def custodies(self) -> CustodyRepository:
        """Le depot des detentions, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
