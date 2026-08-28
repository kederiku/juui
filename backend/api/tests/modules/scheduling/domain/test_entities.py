"""Tests purs des entites du module scheduling (BACK-21) : sans Docker."""

from calendar import Day
from dataclasses import fields
from datetime import date
from uuid import uuid4

import pytest

from app.modules.scheduling.domain.entities import (
    PractitionerProfile,
    Species,
    WeeklyTimeRange,
    ensure_hours_disjoint,
)
from app.modules.scheduling.domain.exceptions import (
    InvalidTimeRangeError,
    OverlappingTimeRangesError,
)
from app.modules.scheduling.domain.policies import MINUTES_PER_DAY

pytestmark = pytest.mark.scheduling

_NINE = 9 * 60
_NOON = 12 * 60
_TWO_PM = 14 * 60
_SIX_PM = 18 * 60


def _range(
    weekday: Day = Day.MONDAY, start_minute: int = _NINE, end_minute: int = _NOON
) -> WeeklyTimeRange:
    """Fabrique une plage de reference : lundi 09:00-12:00."""
    return WeeklyTimeRange.create(weekday=weekday, start_minute=start_minute, end_minute=end_minute)


def _profile(
    *hours: WeeklyTimeRange, species: tuple[Species, ...] = (Species.DOG,)
) -> PractitionerProfile:
    """Fabrique une fiche de reference sur des identifiants neufs."""
    return PractitionerProfile.create(
        account_id=uuid4(), clinic_id=uuid4(), hours=hours, treated_species=species
    )


@pytest.mark.parametrize("end_minute", [_NINE, _NINE - 1])
def test_a_range_refuses_inverted_or_empty_bounds(end_minute: int) -> None:
    """Une fin qui ne suit pas STRICTEMENT le debut est refusee, egalite comprise."""
    with pytest.raises(InvalidTimeRangeError):
        WeeklyTimeRange.create(weekday=Day.MONDAY, start_minute=_NINE, end_minute=end_minute)


@pytest.mark.parametrize(
    ("start_minute", "end_minute"), [(-1, _NOON), (_NINE, MINUTES_PER_DAY + 1)]
)
def test_a_range_refuses_a_minute_outside_the_day(start_minute: int, end_minute: int) -> None:
    """Le domaine borne la journee, exactement ou la CheckConstraint la bornera."""
    with pytest.raises(InvalidTimeRangeError):
        WeeklyTimeRange.create(weekday=Day.MONDAY, start_minute=start_minute, end_minute=end_minute)


def test_a_range_may_end_at_midnight() -> None:
    """La vacation « 18:00 -> minuit » est exprimable, ce que `datetime.time` interdisait.

    `time.max` vaut 23:59:59.999999 et `time.fromisoformat("24:00")` rend
    `time(0, 0)` SANS lever : c'est la raison d'etre des minutes depuis minuit.
    """
    evening = _range(start_minute=_SIX_PM, end_minute=MINUTES_PER_DAY)

    assert evening.end_minute == MINUTES_PER_DAY
    assert str(evening) == "MONDAY 18:00-24:00"


def test_adjacent_ranges_do_not_overlap() -> None:
    """L'intervalle est DEMI-OUVERT : a la jonction, la seconde a deja pris le relais."""
    morning = _range(start_minute=_NINE, end_minute=_NOON)
    afternoon = _range(start_minute=_NOON, end_minute=_SIX_PM)

    assert not morning.overlaps(afternoon)
    ensure_hours_disjoint([morning, afternoon])


def test_adjacent_ranges_are_merged_into_one_maximal_range() -> None:
    """Deux plages qui se touchent ne disent rien d'autre qu'une seule plage large.

    Les laisser telles quelles ferait disparaitre le praticien de la requete du
    ticket des qu'un creneau chevauche la jonction : le predicat exige qu'UNE
    plage contienne le creneau. Le repli rend le predicat exact sans rien perdre.
    """
    profile = _profile(
        _range(start_minute=_NOON, end_minute=_SIX_PM),
        _range(start_minute=_NINE, end_minute=_NOON),
    )

    assert [str(declared) for declared in profile.hours] == ["MONDAY 09:00-18:00"]


def test_a_real_lunch_break_is_not_merged() -> None:
    """Une pause est un TROU, pas une jonction : deux plages disjointes le restent."""
    profile = _profile(
        _range(start_minute=_NINE, end_minute=_NOON),
        _range(start_minute=_TWO_PM, end_minute=_SIX_PM),
    )

    assert [str(declared) for declared in profile.hours] == [
        "MONDAY 09:00-12:00",
        "MONDAY 14:00-18:00",
    ]


def test_a_slot_straddling_a_junction_is_served() -> None:
    """Le cas que le repli existe pour couvrir, et que la version sans lui ratait.

    Un praticien present sans interruption de 09:00 a 18:00 doit repondre a une
    demande de 11:30 a 12:30, quelle que soit la facon dont il a saisi sa journee.
    """
    profile = _profile(
        _range(start_minute=_NINE, end_minute=_NOON),
        _range(start_minute=_NOON, end_minute=_SIX_PM),
    )
    straddling = _range(start_minute=_NOON - 30, end_minute=_NOON + 30)

    assert profile.is_available_for(time_range=straddling, species=Species.DOG)


def test_a_slot_straddling_a_real_break_is_not_served() -> None:
    """Le pendant : par-dessus un TROU, le praticien n'est pas la, et ne repond pas."""
    profile = _profile(
        _range(start_minute=_NINE, end_minute=_NOON),
        _range(start_minute=_TWO_PM, end_minute=_SIX_PM),
    )
    over_the_break = _range(start_minute=_NOON - 30, end_minute=_TWO_PM + 30)

    assert not profile.is_available_for(time_range=over_the_break, species=Species.DOG)


def test_overlapping_ranges_of_the_same_day_are_refused() -> None:
    """Un recouvrement d'UNE minute suffit : le domaine refuse, il ne fusionne pas."""
    morning = _range(start_minute=_NINE, end_minute=_NOON)
    straddling = _range(start_minute=_NOON - 1, end_minute=_SIX_PM)

    with pytest.raises(OverlappingTimeRangesError) as refusal:
        ensure_hours_disjoint([morning, straddling])

    assert "MONDAY 09:00-12:00" in str(refusal.value)
    assert "MONDAY 11:59-18:00" in str(refusal.value)


def test_ranges_on_different_weekdays_never_overlap() -> None:
    """Le jour fait partie de l'identite d'une plage, aux memes heures."""
    monday = _range(weekday=Day.MONDAY)
    tuesday = _range(weekday=Day.TUESDAY)

    assert not monday.overlaps(tuesday)
    assert not monday.covers(tuesday)


def test_the_python_weekday_convention_is_the_one_the_schema_assumes() -> None:
    """Epingle la PREMISSE de la bibliotheque standard sur laquelle repose le schema.

    `ck_practitioner_hours_weekday_python_range` et le mapping du depot tiennent
    pour acquis que `calendar.Day` compte lundi = 0, comme `date.weekday()` -- ni
    `EXTRACT(DOW)` (dimanche = 0), ni `EXTRACT(ISODOW)` (lundi = 1). Ce test
    n'exerce donc aucune ligne du module : il fige l'hypothese, et la garde du
    stockage vit ailleurs -- `test_the_database_refuses_an_out_of_range_weekday`
    et l'aller-retour de `test_hours_and_species_survive_a_round_trip_ordered`.
    """
    assert Day.MONDAY == 0
    assert Day.SUNDAY == 6
    # Du lundi 2026-08-24 au dimanche 2026-08-30, une semaine complete.
    for day_of_month, expected in enumerate(Day, start=24):
        assert Day(date(2026, 8, day_of_month).weekday()) is expected


@pytest.mark.parametrize(
    ("start_minute", "end_minute", "covered"),
    [
        (_NINE, _NOON, True),
        (_NINE + 1, _NOON - 1, True),
        (_NINE - 1, _NOON, False),
        (_NINE, _NOON + 1, False),
    ],
)
def test_covers_requires_full_containment(
    start_minute: int, end_minute: int, covered: bool
) -> None:
    """CONTENANCE et non chevauchement : deborder d'une minute suffit a exclure."""
    declared = _range(start_minute=_NINE, end_minute=_NOON)
    wanted = _range(start_minute=start_minute, end_minute=end_minute)

    assert declared.covers(wanted) is covered


def test_covers_requires_the_same_weekday() -> None:
    """Une plage du lundi ne couvre pas un creneau du mardi, memes heures."""
    assert not _range(weekday=Day.MONDAY).covers(_range(weekday=Day.TUESDAY))


def test_create_sorts_hours_and_mints_an_identifier() -> None:
    """Les plages ressortent triees, et l'identifiant est battu par le DOMAINE."""
    profile = _profile(
        _range(weekday=Day.TUESDAY, start_minute=_TWO_PM, end_minute=_SIX_PM),
        _range(weekday=Day.MONDAY, start_minute=_NINE, end_minute=_NOON),
    )

    assert [str(declared) for declared in profile.hours] == [
        "MONDAY 09:00-12:00",
        "TUESDAY 14:00-18:00",
    ]
    assert profile.id.version == 7


def test_create_refuses_overlapping_hours() -> None:
    """L'invariant est verifie des la naissance, pas seulement a la modification."""
    with pytest.raises(OverlappingTimeRangesError):
        _profile(
            _range(start_minute=_NINE, end_minute=_SIX_PM),
            _range(start_minute=_NOON, end_minute=_TWO_PM),
        )


def test_set_hours_revalidates_and_resorts() -> None:
    """L'invariant survit a la modification : pas de porte de derriere."""
    profile = _profile(_range())

    profile.set_hours(
        [
            _range(weekday=Day.TUESDAY, start_minute=_TWO_PM, end_minute=_SIX_PM),
            _range(weekday=Day.MONDAY, start_minute=_NINE, end_minute=_NOON),
        ]
    )
    assert [declared.weekday for declared in profile.hours] == [Day.MONDAY, Day.TUESDAY]

    with pytest.raises(OverlappingTimeRangesError):
        profile.set_hours(
            [
                _range(start_minute=_NINE, end_minute=_NOON),
                _range(start_minute=_NOON - 30, end_minute=_SIX_PM),
            ]
        )


def test_species_duplicates_collapse() -> None:
    """`frozenset` rend le doublon non representable : aucune erreur n'a a exister."""
    profile = _profile(species=(Species.DOG, Species.DOG, Species.CAT))

    assert profile.treated_species == frozenset({Species.DOG, Species.CAT})


def test_a_profile_without_species_matches_nothing() -> None:
    """L'ensemble vide vaut « rien de declare », JAMAIS « toutes les especes ».

    Comportement voulu et surprenant, donc teste : une fiche neuve -- l'etat a
    l'ouverture de l'ecran « mon compte » -- rend le praticien invisible de
    l'appariement plutot que disponible pour tout.
    """
    profile = PractitionerProfile.create(account_id=uuid4(), clinic_id=uuid4(), hours=[_range()])

    assert profile.treated_species == frozenset()
    assert not profile.is_available_for(time_range=_range(), species=Species.DOG)


@pytest.mark.parametrize(
    ("species", "wanted", "available"),
    [
        (Species.DOG, _NINE, True),
        (Species.CAT, _NINE, False),
        (Species.DOG, _TWO_PM, False),
    ],
)
def test_is_available_for_requires_both_species_and_hours(
    species: Species, wanted: int, available: bool
) -> None:
    """Les deux conditions du critere 3 sont CONJOINTES, et tiennent sans Docker."""
    profile = _profile(_range(start_minute=_NINE, end_minute=_NOON), species=(Species.DOG,))
    time_range = _range(start_minute=wanted, end_minute=wanted + 60)

    assert profile.is_available_for(time_range=time_range, species=species) is available


def test_a_profile_carries_neither_group_nor_validity_window() -> None:
    """Criteres 2 et 4 cote domaine : la portee limitee se lit dans la dataclass.

    Aucun `group_id` -- la tenance est estampillee par le socle (BACK-06b) et
    l'entite tenant ne porte pas la colonne. Aucun `start_at` ni `end_at` -- ni
    conges, ni exceptions, ni moteur de rendez-vous. Un champ ajoute ici ferait
    echouer ce test, ce qui est le but.
    """
    assert {field.name for field in fields(PractitionerProfile)} == {
        "id",
        "account_id",
        "clinic_id",
        "hours",
        "treated_species",
    }
