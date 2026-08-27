"""Ports metier du module scheduling (BACK-21).

Un port est un BESOIN exprime par le domaine, jamais une technologie. Ceux-ci
disent « je dois pouvoir repondre aux deux questions de la fiche technique » ;
ils ne disent ni PostgreSQL, ni SQLAlchemy. L'adaptateur qui les remplit vit
dans `infrastructure/db/repositories.py`.

LES DEUX QUESTIONS DU SOCLE, ET RIEN D'AUTRE
Elles sont la SEULE surface publique du module -- aucun autre module n'accede a
ses tables :

1. les praticiens disponibles dans une clinique, sur un creneau et pour une
   espece -- LA requete du ticket, celle que la prise de rendez-vous posera ;
2. la fiche d'un compte dans une clinique -- la lecture que l'ecran « mon
   compte » modifiera, et celle qui rend observable le grain de l'agregat : un
   remplacant a des fiches DISTINCTES selon la structure.

PAS d'ecriture dans les ports : `add` et `save` existent sur la classe concrete
(depot generique), mais « le port ne s'elargit pas parce que la classe sait
faire plus ». Le ticket qui livrera l'ecriture de la fiche publiera les siens.

LE DEPOT EST TENANT, ET `clinic_id` RESTE UN PARAMETRE
Toute lecture passe par le filtre de groupe (BACK-06b) et leve hors de tout
perimetre. Mais le contexte de tenance porte le GROUPE, jamais la clinique
(`current_group_id`), et un groupe compte N cliniques : c'est l'appelant qui
designe laquelle. `current_clinic_id` existe bien, mais c'est une variable de
CORRELATION pour les journaux (BACK-11, ADR-0012) -- s'en servir dans un depot
ferait de la clinique une dependance ambiante, invisible dans les signatures.

LA PLAGE PASSE PAR L'OBJET-VALEUR
`list_available` prend un `WeeklyTimeRange` et non trois entiers : un parametre
au lieu de trois, la garde de bornes reutilisee sans y penser, et le port parle
la langue de la fiche. Ces heures sont des minutes d'HORLOGE MURALE, sans
fuseau -- convertir un instant absolu en jour et minute locale suppose de
connaitre le fuseau de la clinique, que ce module ne possede pas.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.modules.scheduling.domain.entities import (
    PractitionerProfile,
    Species,
    WeeklyTimeRange,
)
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork


class PractitionerProfileRepository(ABC):
    """Acces aux fiches techniques, exprime en entites du domaine.

    Depot TENANT : toute lecture passe par le filtre de groupe (BACK-06b), et
    exiger un perimetre pose n'est pas une gene mais la garantie -- une fiche ne
    se lit jamais hors du groupe qui la possede.
    """

    @abstractmethod
    async def list_available(
        self, clinic_id: UUID, time_range: WeeklyTimeRange, species: Species
    ) -> Sequence[PractitionerProfile]:
        """Rend les praticiens declares disponibles sur ce creneau, pour cette espece.

        LA requete du ticket. Le predicat est celui d'`is_available_for`, ecrit
        en SQL : l'espece figure aux competences de la fiche, ET l'une de ses
        plages declarees CONTIENT entierement le creneau demande.

        CONTENANCE, PAS CHEVAUCHEMENT. Un rendez-vous de 09:00 a 10:00 n'est pas
        servi par une disponibilite de 09:30 a 12:00 : le praticien ne serait la
        que pour la moitie. Le chevauchement se derive de la contenance ;
        l'inverse est faux.

        UN CRENEAU NE TRAVERSE PAS MINUIT
        `WeeklyTimeRange` porte UN jour et exige une fin strictement posterieure
        au debut : un creneau de 23:45 a 00:15 n'est pas CONSTRUCTIBLE, et le
        refus tombe chez l'appelant, a `create()`, avant d'atteindre ce port. Une
        garde de nuit se demande donc en DEUX appels -- lundi 23:45-24:00 puis
        mardi 00:00-00:15 -- dont l'appelant INTERSECTE les resultats : n'est
        disponible que le praticien rendu par les deux.

        CE QUE « DISPONIBLE » NE VEUT PAS DIRE ICI
        La disponibilite rendue est DECLAREE : les plages et les especes que le
        praticien a saisies pour CETTE clinique. La fiche n'a aucune fenetre de
        validite -- ni conges, ni exceptions, ni rendez-vous deja pris : la
        portee du ticket les exclut. Une fiche SURVIT donc a l'affectation qui
        l'a motivee, et un ancien remplacant reste declare disponible.
        L'appelant DOIT croiser ce resultat avec les affectations actives, par
        `OrganizationUnitOfWork.assignments.list_active_for_account(account_id,
        at)` -- qui rend des affectations deja filtrees par groupe et porteuses
        de leur `clinic_id`. Ce croisement ne peut pas vivre ici : le contrat
        `module-independence` interdit a scheduling d'atteindre organization, et
        `main.py` est le seul espace autorise a connaitre deux modules.

        Args:
            clinic_id: la clinique interrogee. Elle est designee par l'appelant
                et non lue dans le contexte, qui ne porte que le groupe.
            time_range: le creneau cherche, en minutes d'horloge murale locale
                de la clinique.
            species: l'espece a prendre en charge.

        Returns:
            Les fiches correspondantes dans le groupe actif, ordonnees par
            compte. Vide si personne ne s'est declare : c'est un cas nominal --
            une clinique dont aucun praticien n'a rempli sa fiche --, pas une
            erreur.

        Raises:
            MissingTenantContextError: si aucun perimetre de tenance n'est pose
                -- jamais un repli silencieux sur tous les groupes.
            InvalidTimeRangeError: si une plage relue en base est mal formee.
            UnknownSpeciesError: si une espece relue en base ne figure plus au
                catalogue du domaine.
        """

    @abstractmethod
    async def find_for_account_in_clinic(
        self, account_id: UUID, clinic_id: UUID
    ) -> PractitionerProfile | None:
        """Cherche la fiche d'un compte dans une clinique donnee.

        `find_` et non `get_` : ici l'absence est un RESULTAT ATTENDU -- un
        praticien affecte qui n'a rien rempli n'a pas de fiche, et ce n'est pas
        une anomalie. Meme doctrine que `find_active_role` chez organization.

        L'unicite `(group_id, clinic_id, account_id)`, physique en base,
        garantit qu'il n'y a jamais deux lignes a departager.

        Args:
            account_id: le compte du praticien.
            clinic_id: la clinique interrogee.

        Returns:
            La fiche, ou None si le praticien n'en a aucune dans cette clinique
            du groupe actif.

        Raises:
            MissingTenantContextError: si aucun perimetre de tenance n'est pose.
            InvalidTimeRangeError: si une plage relue en base est mal formee.
            UnknownSpeciesError: si une espece relue en base ne figure plus au
                catalogue du domaine.
        """


class SchedulingUnitOfWork(AbstractUnitOfWork):
    """Unite de travail du module : sa transaction, son depot, rien d'autre.

    UNE UNITE PAR MODULE, jamais une unite globale (ADR-0009). Le depot est une
    PROPRIETE, pas un attribut -- chaque acces repasse par la garde du bloc, et
    lever hors bloc reste la regle du port, partout.

    Un seul depot, et la forme ne change pas pour autant : ce qui justifie
    l'unite est la GARDE -- lever hors bloc, annuler en sortie sans commit --,
    pas le nombre de depots.
    """

    @property
    @abstractmethod
    def practitioner_profiles(self) -> PractitionerProfileRepository:
        """Le depot de fiches techniques, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
