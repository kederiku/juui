"""Adaptateur SQLAlchemy du port du module scheduling (BACK-21).

Le mapping est ECRIT A LA MAIN, comme partout : `int` et `str` en base, `Day` et
`Species` dans le domaine, et l'ecart echoue chez Mypy plutot qu'en production.
UNE VALEUR ILLISIBLE LEVE, ELLE N'EST PAS IGNOREE -- doctrine reprise de
notifications : avaler une espece retiree du catalogue rendrait un praticien
silencieusement competent pour rien.

LE PREDICAT SQL EST LE JUMEAU DE `PractitionerProfile.is_available_for`
Les deux repondent a la meme question, l'un en base et l'autre en memoire. Toute
modification de l'un se fait dans le MEME commit que l'autre, et
`test_sql_and_domain_answer_with_one_voice` les confronte sur une matrice de
plages limites.

DEUX `EXISTS` CORRELES, JAMAIS DEUX JOINTURES
`list_available` filtre par `.any()`, qui compile en `EXISTS`. Deux jointures
dupliqueraient la fiche des que deux plages couvrent le creneau demande,
imposeraient un `DISTINCT`, et fausseraient le `total` le jour ou cette requete
sera paginee. Chaque `EXISTS` est sonde par le prefixe `profile_id` de la cle
primaire naturelle de l'enfant -- aucun index supplementaire.

AUCUNE SURCHARGE D'`add`, DE `save` NI DE `delete`
Le socle suffit, et ce n'est pas une supposition : `flush([model])` propage les
cascades `save-update` et `delete-orphan`, a l'insertion comme au remplacement
integral d'une collection -- verifie a l'execution, et
`test_saving_a_profile_replaces_its_collections_within_the_block` le verrouille
par un comptage brut pris avant tout commit. Surcharger aurait de plus oblige a reimplanter
`_to_model`, donc l'estampillage `group_id` du depot tenant.

Toute requete maison part de `self._select()` -- jamais d'un `select(...)`
importe : c'est la couture que le filtre tenant sait atteindre.
"""

from calendar import Day
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_

from app.modules.scheduling.domain.entities import (
    PractitionerProfile,
    Species,
    WeeklyTimeRange,
)
from app.modules.scheduling.domain.exceptions import (
    InvalidTimeRangeError,
    PractitionerProfileNotFoundError,
    UnknownSpeciesError,
)
from app.modules.scheduling.domain.ports import PractitionerProfileRepository
from app.modules.scheduling.infrastructure.db.models import (
    PractitionerHoursModel,
    PractitionerProfileModel,
    PractitionerSpeciesModel,
)
from app.shared.infrastructure.db.repositories.tenant import TenantSqlAlchemyRepository


def _to_weekday(value: int) -> Day:
    """Retrouve le jour de la semaine derriere une valeur relue en base.

    La contrainte `ck_practitioner_hours_weekday_python_range` l'interdit deja
    en base ; ce refus-ci est la seconde ceinture, et il NOMME la valeur fautive
    -- une `ValueError` nue d'enum ne dirait pas d'ou elle vient.

    Args:
        value: l'entier stocke, dans la convention de `calendar.Day`.

    Returns:
        Le jour de la semaine.

    Raises:
        InvalidTimeRangeError: si l'entier ne designe aucun jour.
    """
    try:
        return Day(value)
    except ValueError as error:
        message = (
            f"Le jour « {value} » ne designe aucun jour de la semaine : la colonne "
            "suit la convention de `calendar.Day`, lundi = 0 a dimanche = 6."
        )
        raise InvalidTimeRangeError(message) from error


def _to_species(value: str) -> Species:
    """Retrouve l'espece derriere une valeur relue en base.

    Args:
        value: la valeur stockee dans `practitioner_species.species`.

    Returns:
        L'espece du catalogue.

    Raises:
        UnknownSpeciesError: si aucune espece ne porte cette valeur.
    """
    try:
        return Species(value)
    except ValueError as error:
        message = f"L'espece « {value} » est inconnue du catalogue du module scheduling."
        raise UnknownSpeciesError(message) from error


class SqlAlchemyPractitionerProfileRepository(
    TenantSqlAlchemyRepository[PractitionerProfile, PractitionerProfileModel],
    PractitionerProfileRepository,
):
    """Depot de fiches techniques adosse a PostgreSQL -- tenant, filtre herite."""

    _model_type = PractitionerProfileModel
    _not_found_error = PractitionerProfileNotFoundError
    _not_found_message = "Aucune fiche technique de praticien ne porte l'identifiant {entity_id}."

    def _to_entity(self, model: PractitionerProfileModel) -> PractitionerProfile:
        """Reconstitue l'entite du domaine a partir d'une ligne et de ses enfants.

        Les plages passent par `WeeklyTimeRange.create()` et NON par le
        constructeur nu : un objet-valeur EST ses valeurs, et une ligne
        corrompue doit LEVER plutot que produire une plage silencieusement
        inerte. C'est l'exception a la regle « le constructeur nu est reserve a
        la reconstitution », qui ne vaut que pour les agregats.

        Le `group_id` de la ligne n'est PAS reporte : l'entite tenant ne porte
        pas la colonne du socle.

        Args:
            model: la ligne relue par SQLAlchemy, collections deja chargees par
                `lazy="selectin"`.

        Returns:
            La fiche, jours et especes convertis dans les types du domaine.

        Raises:
            InvalidTimeRangeError: si une plage stockee est mal formee.
            UnknownSpeciesError: si une espece stockee est hors catalogue.
        """
        return PractitionerProfile(
            id=model.id,
            account_id=model.account_id,
            clinic_id=model.clinic_id,
            hours=tuple(
                WeeklyTimeRange.create(
                    weekday=_to_weekday(row.weekday),
                    start_minute=row.start_minute,
                    end_minute=row.end_minute,
                )
                for row in model.hours
            ),
            treated_species=frozenset(_to_species(row.species) for row in model.treated_species),
        )

    def _apply_to_model(self, entity: PractitionerProfile, model: PractitionerProfileModel) -> None:
        """Reporte l'etat d'une fiche sur sa ligne, sans `id` ni `group_id`.

        Les deux collections sont REMPLACEES et non modifiees en place : c'est
        ce qui laisse la cascade `delete-orphan` emettre les DELETE des lignes
        disparues et les INSERT des nouvelles, en une seule passe. L'agregat
        s'ecrit d'un bloc, il ne se retouche pas ligne a ligne.

        Les especes sont TRIEES a l'ecriture : un `frozenset` n'a pas d'ordre, et
        sans ce tri deux enregistrements du meme etat produiraient deux jeux de
        lignes differents -- des diffs de journal illisibles pour rien.

        La tenance est estampillee par le socle a l'insertion ; un mapping qui
        s'en melerait serait refuse par la garde de `_to_model`, qui court APRES
        cet appel.

        Args:
            entity: la fiche dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """
        model.account_id = entity.account_id
        model.clinic_id = entity.clinic_id
        model.hours = [
            PractitionerHoursModel(
                weekday=int(declared.weekday),
                start_minute=declared.start_minute,
                end_minute=declared.end_minute,
            )
            for declared in entity.hours
        ]
        model.treated_species = [
            PractitionerSpeciesModel(species=species.value)
            for species in sorted(entity.treated_species)
        ]

    async def list_available(
        self, clinic_id: UUID, time_range: WeeklyTimeRange, species: Species
    ) -> Sequence[PractitionerProfile]:
        """Rend les praticiens declares disponibles sur ce creneau, pour cette espece.

        Le filtre de groupe est HERITE : `self._select()` restreint deja la
        requete au perimetre du contexte, ou leve hors de tout perimetre. Le
        prefixe `(group_id, clinic_id)` de la contrainte d'unicite sert cette
        requete sans index supplementaire.

        Args:
            clinic_id: la clinique interrogee.
            time_range: le creneau cherche, en minutes d'horloge murale.
            species: l'espece a prendre en charge.

        Returns:
            Les fiches correspondantes du groupe actif, ordonnees par compte
            puis par identifiant -- deux fiches d'un meme compte ne pouvant de
            toute facon pas coexister dans une clinique, l'identifiant ne
            departage qu'entre cliniques.

        Raises:
            MissingTenantContextError: si aucun perimetre de tenance n'est pose.
            InvalidTimeRangeError: si une plage relue est mal formee.
            UnknownSpeciesError: si une espece relue est hors catalogue.
        """
        statement = (
            self._select()
            .where(
                PractitionerProfileModel.clinic_id == clinic_id,
                PractitionerProfileModel.hours.any(
                    and_(
                        PractitionerHoursModel.weekday == int(time_range.weekday),
                        PractitionerHoursModel.start_minute <= time_range.start_minute,
                        PractitionerHoursModel.end_minute >= time_range.end_minute,
                    )
                ),
                PractitionerProfileModel.treated_species.any(
                    PractitionerSpeciesModel.species == species.value
                ),
            )
            .order_by(PractitionerProfileModel.account_id, PractitionerProfileModel.id)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._to_entity(model) for model in models]

    async def find_for_account_in_clinic(
        self, account_id: UUID, clinic_id: UUID
    ) -> PractitionerProfile | None:
        """Cherche la fiche d'un compte dans une clinique donnee.

        `scalar_one_or_none` et non `first()` : sous un perimetre de groupe,
        l'unicite `(group_id, clinic_id, account_id)` garantit qu'il n'y a jamais
        deux lignes. Sous `use_all_groups`, ou le filtre de groupe tombe, la
        garantie ne tient plus que par l'unicite du `clinic_id` demande, qu'un
        seul groupe porte. Si l'invariant tombait malgre tout, la lecture doit
        CRIER plutot que departager au hasard -- un praticien verrait alors, une
        fois sur deux, des horaires qui ne sont pas les siens. Le cri est un
        `MultipleResultsFound` nu : le symptome d'une base incoherente, pas un
        refus metier, et c'est voulu.

        Args:
            account_id: le compte du praticien.
            clinic_id: la clinique interrogee.

        Returns:
            La fiche, ou None si le praticien n'en a aucune dans cette clinique
            du groupe actif.

        Raises:
            MissingTenantContextError: si aucun perimetre de tenance n'est pose.
            InvalidTimeRangeError: si une plage relue est mal formee.
            UnknownSpeciesError: si une espece relue est hors catalogue.
        """
        statement = self._select().where(
            PractitionerProfileModel.account_id == account_id,
            PractitionerProfileModel.clinic_id == clinic_id,
        )
        model = (await self._session.execute(statement)).scalar_one_or_none()
        return None if model is None else self._to_entity(model)
