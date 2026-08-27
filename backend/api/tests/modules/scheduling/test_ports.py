"""Tests d'integration des deux lectures publiques du module scheduling (BACK-21).

Le semis passe par la session BRUTE -- la verite terrain a laquelle chaque test
compare le comportement du depot -- et pose explicitement `group_id` sur chaque
fiche : le filtre vit dans le depot, pas dans la session. Il accepte aussi des
plages et des especes que le DOMAINE refuserait, ce qui est le seul moyen
d'eprouver les contraintes de la base et les refus de relecture.

AUCUN GROUPE NI AUCUNE CLINIQUE N'EST SEMEE, ET C'EST LE SUJET
`practitioner_profiles` ne porte AUCUNE cle etrangere -- ni vers `groups` ni
vers `clinics`, qui appartiennent a organization (ADR-0015). Les identifiants
sont nus, et une fiche s'insere sans qu'aucune de ces tables existe. C'est le
prix nomme de la frontiere : l'integrite reste applicative.

Les tests ne committent jamais ; le rollback du teardown annule tout.
"""

from calendar import Day
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scheduling.domain.entities import (
    PractitionerProfile,
    Species,
    WeeklyTimeRange,
)
from app.modules.scheduling.domain.exceptions import (
    PractitionerProfileNotFoundError,
    UnknownSpeciesError,
)
from app.modules.scheduling.infrastructure.db.models import (
    PractitionerHoursModel,
    PractitionerProfileModel,
    PractitionerSpeciesModel,
)
from app.modules.scheduling.infrastructure.db.repositories import (
    SqlAlchemyPractitionerProfileRepository,
)
from app.shared.infrastructure.tenancy import MissingTenantContextError, use_group

# Les trois tables du module naissent avec la fixture de session du conftest
# local -- demandee ici, et seulement ici : les tests purs n'exigent pas Docker.
pytestmark = [pytest.mark.scheduling, pytest.mark.usefixtures("_scheduling_tables")]

_EIGHT = 8 * 60
_NINE = 9 * 60
_TEN = 10 * 60
_ELEVEN = 11 * 60
_NOON = 12 * 60
_ONE_PM = 13 * 60
_TWO_PM = 14 * 60
_SIX_PM = 18 * 60
_MIDNIGHT = 24 * 60

_MONDAY_MORNING = WeeklyTimeRange.create(weekday=Day.MONDAY, start_minute=_NINE, end_minute=_NOON)
_MONDAY_TEN_TO_ELEVEN = WeeklyTimeRange.create(
    weekday=Day.MONDAY, start_minute=_TEN, end_minute=_ELEVEN
)
_TUESDAY_AFTERNOON = WeeklyTimeRange.create(
    weekday=Day.TUESDAY, start_minute=_TWO_PM, end_minute=_SIX_PM
)


async def _seed_profile(
    session: AsyncSession,
    *,
    group_id: UUID,
    account_id: UUID,
    clinic_id: UUID,
    hours: tuple[tuple[int, int, int], ...] = ((int(Day.MONDAY), _NINE, _NOON),),
    species: tuple[str, ...] = (Species.DOG.value,),
    profile_id: UUID | None = None,
) -> UUID:
    """Seme une fiche et ses enfants par la session brute, `group_id` pose a la main.

    Les plages sont des triplets `(weekday, start_minute, end_minute)` et les
    especes des chaines nues : le semis doit pouvoir ecrire ce que le domaine
    refuserait.
    """
    identifier = profile_id or uuid4()
    session.add(
        PractitionerProfileModel(
            id=identifier,
            group_id=group_id,
            account_id=account_id,
            clinic_id=clinic_id,
            hours=[
                PractitionerHoursModel(weekday=weekday, start_minute=start, end_minute=end)
                for weekday, start, end in hours
            ],
            treated_species=[PractitionerSpeciesModel(species=value) for value in species],
        )
    )
    await session.flush()
    return identifier


async def _count_hours(session: AsyncSession, profile_id: UUID) -> int:
    """Compte les plages d'une fiche par une requete brute, sans passer par le depot."""
    statement = (
        select(func.count())
        .select_from(PractitionerHoursModel)
        .where(PractitionerHoursModel.profile_id == profile_id)
    )
    return (await session.execute(statement)).scalar_one()


async def _count_species(session: AsyncSession, profile_id: UUID) -> int:
    """Compte les especes d'une fiche par une requete brute, sans passer par le depot."""
    statement = (
        select(func.count())
        .select_from(PractitionerSpeciesModel)
        .where(PractitionerSpeciesModel.profile_id == profile_id)
    )
    return (await session.execute(statement)).scalar_one()


# --- La requete du ticket : praticiens disponibles ---------------------------


async def test_available_practitioners_match_clinic_range_and_species(
    session: AsyncSession, group_a: UUID
) -> None:
    """Le chemin nominal du critere 3, de bout en bout contre PostgreSQL.

    Quatre fiches semees, une seule repond : les trois autres echouent chacune
    sur un critere different -- l'espece, l'horaire, la clinique.
    """
    clinic_a, clinic_b = uuid4(), uuid4()
    expected = uuid4()
    await _seed_profile(session, group_id=group_a, account_id=expected, clinic_id=clinic_a)
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=uuid4(),
        clinic_id=clinic_a,
        species=(Species.CAT.value,),
    )
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=uuid4(),
        clinic_id=clinic_a,
        hours=((int(Day.TUESDAY), _TWO_PM, _SIX_PM),),
    )
    # Le MEME compte, dans une autre clinique : la fiche existe, elle ne repond pas.
    await _seed_profile(session, group_id=group_a, account_id=expected, clinic_id=clinic_b)

    with use_group(group_a):
        available = await SqlAlchemyPractitionerProfileRepository(session).list_available(
            clinic_a, _MONDAY_TEN_TO_ELEVEN, Species.DOG
        )

    assert [profile.account_id for profile in available] == [expected]
    assert available[0].clinic_id == clinic_a


async def test_a_partially_covering_range_excludes_the_practitioner(
    session: AsyncSession, group_a: UUID
) -> None:
    """Le SQL exige la CONTENANCE, pas le recouvrement.

    Une disponibilite de 09:30 a 12:00 ne sert pas un rendez-vous de 09:00 a
    10:00 : le praticien ne serait la que pour la moitie.
    """
    clinic_id = uuid4()
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=uuid4(),
        clinic_id=clinic_id,
        hours=((int(Day.MONDAY), _NINE + 30, _NOON),),
    )
    wanted = WeeklyTimeRange.create(weekday=Day.MONDAY, start_minute=_NINE, end_minute=_TEN)

    with use_group(group_a):
        available = await SqlAlchemyPractitionerProfileRepository(session).list_available(
            clinic_id, wanted, Species.DOG
        )

    assert available == []


async def test_a_slot_straddling_a_junction_is_served_by_the_query(
    session: AsyncSession, group_a: UUID
) -> None:
    """Le repli des plages jointives atteint le SQL, et pas seulement le domaine.

    Une journee saisie en deux morceaux qui se touchent -- 09:00-12:00 puis
    12:00-18:00 -- est ecrite en UNE plage maximale par `_validated_hours`. Sans
    ce repli, l'`EXISTS` correle, qui sonde une seule ligne fille, ne trouverait
    aucune plage contenant 11:30-12:30 et le praticien disparaitrait de la
    requete du ticket, en silence.
    """
    account_id, clinic_id = uuid4(), uuid4()
    profile = PractitionerProfile.create(
        account_id=account_id,
        clinic_id=clinic_id,
        hours=[
            WeeklyTimeRange.create(weekday=Day.MONDAY, start_minute=_NINE, end_minute=_NOON),
            WeeklyTimeRange.create(weekday=Day.MONDAY, start_minute=_NOON, end_minute=_SIX_PM),
        ],
        treated_species=[Species.DOG],
    )
    straddling = WeeklyTimeRange.create(
        weekday=Day.MONDAY, start_minute=_NOON - 30, end_minute=_NOON + 30
    )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        await repository.add(profile)
        available = await repository.list_available(clinic_id, straddling, Species.DOG)

    assert await _count_hours(session, profile.id) == 1
    assert [found.id for found in available] == [profile.id]


async def test_a_practitioner_with_two_covering_ranges_appears_once(
    session: AsyncSession, group_a: UUID
) -> None:
    """Deux `EXISTS` correles, jamais deux jointures.

    LE SEMIS EST UN ETAT QUE LE DOMAINE REFUSERAIT, et c'est le seul qui
    discrimine : deux plages CHEVAUCHANTES du meme jour couvrant toutes deux le
    creneau demande. `ensure_hours_disjoint` les rejette, la session brute et la
    base les acceptent -- aucune contrainte `EXCLUDE` n'existe (models.py). Sur
    cet etat, une jointure rendrait la fiche DEUX fois, imposant un `DISTINCT` et
    faussant le `total` le jour ou cette requete sera paginee ; les deux `EXISTS`
    la rendent une seule.
    """
    clinic_id = uuid4()
    account_id = uuid4()
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=account_id,
        clinic_id=clinic_id,
        hours=((int(Day.MONDAY), _NINE, _NOON), (int(Day.MONDAY), _EIGHT, _ONE_PM)),
        species=(Species.DOG.value,),
    )

    with use_group(group_a):
        available = await SqlAlchemyPractitionerProfileRepository(session).list_available(
            clinic_id, _MONDAY_TEN_TO_ELEVEN, Species.DOG
        )

    assert [profile.account_id for profile in available] == [account_id]


async def test_available_practitioners_come_in_a_deterministic_order(
    session: AsyncSession, group_a: UUID
) -> None:
    """L'ordre est `(account_id, id)` : deux pages consecutives ne se recouvriraient pas."""
    clinic_id = uuid4()
    accounts = sorted(uuid4() for _ in range(3))
    for account_id in reversed(accounts):
        await _seed_profile(session, group_id=group_a, account_id=account_id, clinic_id=clinic_id)

    with use_group(group_a):
        available = await SqlAlchemyPractitionerProfileRepository(session).list_available(
            clinic_id, _MONDAY_TEN_TO_ELEVEN, Species.DOG
        )

    assert [profile.account_id for profile in available] == accounts


async def test_sql_and_domain_answer_with_one_voice(session: AsyncSession, group_a: UUID) -> None:
    """Les deux couches ne peuvent pas diverger, et c'est verifie plutot qu'espere.

    `list_available` en SQL et `is_available_for` en memoire repondent a la meme
    question. Sur une matrice de plages limites -- couvrante, debordante a
    gauche, debordante a droite, jointive, autre jour -- les deux rendent
    exactement le meme ensemble de comptes.
    """
    clinic_id = uuid4()
    matrix = (
        ((int(Day.MONDAY), _NINE, _NOON), True),
        ((int(Day.MONDAY), _TEN, _ELEVEN), True),
        ((int(Day.MONDAY), _TEN + 1, _ELEVEN), False),
        ((int(Day.MONDAY), _TEN, _ELEVEN - 1), False),
        ((int(Day.MONDAY), _ELEVEN, _NOON), False),
        ((int(Day.TUESDAY), _NINE, _NOON), False),
    )
    accounts = [uuid4() for _ in matrix]
    for account_id, (hours, _) in zip(accounts, matrix, strict=True):
        await _seed_profile(
            session,
            group_id=group_a,
            account_id=account_id,
            clinic_id=clinic_id,
            hours=(hours,),
        )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        from_sql = {
            profile.account_id
            for profile in await repository.list_available(
                clinic_id, _MONDAY_TEN_TO_ELEVEN, Species.DOG
            )
        }
        from_domain = set()
        for account_id in accounts:
            profile = await repository.find_for_account_in_clinic(account_id, clinic_id)
            assert profile is not None
            if profile.is_available_for(time_range=_MONDAY_TEN_TO_ELEVEN, species=Species.DOG):
                from_domain.add(account_id)

    assert from_sql == from_domain
    assert from_sql == {
        account_id for account_id, (_, expected) in zip(accounts, matrix, strict=True) if expected
    }


# --- Le grain de la fiche : par clinique, pas par compte ---------------------


async def test_a_locum_has_distinct_profiles_per_clinic_of_one_group(
    session: AsyncSession, group_a: UUID
) -> None:
    """LE test du grain (criteres 1 et 2), et il tient DANS UN SEUL groupe.

    Un unique compte, deux cliniques du MEME groupe, sous un seul `use_group`.
    Un modele « fiche portee par le compte » echouerait ici -- alors qu'un test
    a deux groupes passerait tout aussi bien sous ce modele-la, la tenance
    suffisant a separer les deux fiches. C'est donc ce test, et lui seul, qui
    prouve que la fiche est portee par l'AFFECTATION a une clinique.
    """
    account_id = uuid4()
    clinic_a, clinic_b = uuid4(), uuid4()
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=account_id,
        clinic_id=clinic_a,
        hours=((int(Day.MONDAY), _NINE, _NOON),),
        species=(Species.DOG.value,),
    )
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=account_id,
        clinic_id=clinic_b,
        hours=((int(Day.TUESDAY), _TWO_PM, _SIX_PM),),
        species=(Species.CAT.value,),
    )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        in_a = await repository.find_for_account_in_clinic(account_id, clinic_a)
        in_b = await repository.find_for_account_in_clinic(account_id, clinic_b)
        available_in_a = await repository.list_available(
            clinic_a, _MONDAY_TEN_TO_ELEVEN, Species.DOG
        )
        available_in_b = await repository.list_available(
            clinic_b, _MONDAY_TEN_TO_ELEVEN, Species.DOG
        )

    assert in_a is not None
    assert in_b is not None
    assert in_a.id != in_b.id
    assert in_a.hours == (_MONDAY_MORNING,)
    assert in_b.hours == (_TUESDAY_AFTERNOON,)
    assert in_a.treated_species == frozenset({Species.DOG})
    assert in_b.treated_species == frozenset({Species.CAT})
    assert [profile.id for profile in available_in_a] == [in_a.id]
    assert available_in_b == []


async def test_a_second_profile_for_the_same_account_and_clinic_is_refused(
    session: AsyncSession, group_a: UUID
) -> None:
    """« Une fiche par praticien et par clinique » est PHYSIQUE, pas une convention.

    C'est aussi ce qui garantit que `find_for_account_in_clinic` n'aura jamais
    deux lignes a departager, et donc que son `scalar_one_or_none` ne criera pas.
    """
    account_id, clinic_id = uuid4(), uuid4()
    await _seed_profile(session, group_id=group_a, account_id=account_id, clinic_id=clinic_id)

    with pytest.raises(IntegrityError):
        await _seed_profile(session, group_id=group_a, account_id=account_id, clinic_id=clinic_id)


# --- Tenance ------------------------------------------------------------------


async def test_a_profile_added_through_the_repository_is_stamped_with_the_active_group(
    session: AsyncSession, group_a: UUID
) -> None:
    """Le socle estampille, jamais le mapping du module.

    L'entite ne porte aucun champ de groupe ; la ligne, elle, en porte un -- relu
    ici par une requete brute plutot que par l'objet deja en session.
    """
    profile = PractitionerProfile.create(
        account_id=uuid4(),
        clinic_id=uuid4(),
        hours=[_MONDAY_MORNING],
        treated_species=[Species.DOG],
    )

    with use_group(group_a):
        await SqlAlchemyPractitionerProfileRepository(session).add(profile)

    statement = select(PractitionerProfileModel.group_id).where(
        PractitionerProfileModel.id == profile.id
    )
    assert (await session.execute(statement)).scalar_one() == group_a


@pytest.mark.tenant_isolation
async def test_locum_profiles_stay_in_the_active_group(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """La FRONTIERE : le remplacant ne voit que les fiches du groupe actif.

    Ce test ne prouve PAS le grain de la fiche -- sous un modele « fiche portee
    par le compte », il passerait tout autant, la tenance separant deja les deux
    lignes. C'est `test_a_locum_has_distinct_profiles_per_clinic_of_one_group`
    qui porte cette preuve, et lui seul.
    """
    account_id = uuid4()
    clinic_in_a, clinic_in_b = uuid4(), uuid4()
    await _seed_profile(session, group_id=group_a, account_id=account_id, clinic_id=clinic_in_a)
    await _seed_profile(session, group_id=group_b, account_id=account_id, clinic_id=clinic_in_b)
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        assert await repository.find_for_account_in_clinic(account_id, clinic_in_a) is not None
        assert await repository.find_for_account_in_clinic(account_id, clinic_in_b) is None
        assert (
            await repository.list_available(clinic_in_b, _MONDAY_TEN_TO_ELEVEN, Species.DOG) == []
        )


async def test_reading_without_tenant_context_raises(session: AsyncSession, group_a: UUID) -> None:
    """Jamais de repli silencieux sur « tous groupes » : le depot LEVE."""
    account_id, clinic_id = uuid4(), uuid4()
    await _seed_profile(session, group_id=group_a, account_id=account_id, clinic_id=clinic_id)
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with pytest.raises(MissingTenantContextError):
        await repository.find_for_account_in_clinic(account_id, clinic_id)
    with pytest.raises(MissingTenantContextError):
        await repository.list_available(clinic_id, _MONDAY_TEN_TO_ELEVEN, Species.DOG)


async def test_a_profile_of_another_group_is_absent_not_forbidden(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """404 et jamais 403 : rien ne confirme que la fiche existe ailleurs."""
    account_id, clinic_id = uuid4(), uuid4()
    profile_id = await _seed_profile(
        session, group_id=group_b, account_id=account_id, clinic_id=clinic_id
    )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        assert await repository.find_for_account_in_clinic(account_id, clinic_id) is None
        with pytest.raises(PractitionerProfileNotFoundError) as cross:
            await repository.get(profile_id)
        with pytest.raises(PractitionerProfileNotFoundError) as absent:
            await repository.get(uuid4())

    assert type(cross.value) is type(absent.value)
    assert cross.value.code == absent.value.code
    assert str(cross.value) == (
        f"Aucune fiche technique de praticien ne porte l'identifiant {profile_id}."
    )


# --- Mapping et cycle de vie de l'agregat -------------------------------------


async def test_hours_and_species_survive_a_round_trip_ordered(
    session: AsyncSession, group_a: UUID
) -> None:
    """Le mapping manuel `Day` / `Species` tient dans les deux sens, plage par plage."""
    account_id, clinic_id = uuid4(), uuid4()
    evening = WeeklyTimeRange.create(weekday=Day.MONDAY, start_minute=_SIX_PM, end_minute=_MIDNIGHT)
    profile = PractitionerProfile.create(
        account_id=account_id,
        clinic_id=clinic_id,
        hours=[_TUESDAY_AFTERNOON, evening, _MONDAY_MORNING],
        treated_species=[Species.FERRET, Species.DOG],
    )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        await repository.add(profile)
        reloaded = await repository.find_for_account_in_clinic(account_id, clinic_id)

    assert reloaded is not None
    assert reloaded.hours == (_MONDAY_MORNING, evening, _TUESDAY_AFTERNOON)
    assert [declared.weekday for declared in reloaded.hours] == [
        Day.MONDAY,
        Day.MONDAY,
        Day.TUESDAY,
    ]
    assert reloaded.treated_species == frozenset({Species.DOG, Species.FERRET})


async def test_a_half_empty_profile_is_stored_and_matches_nothing(
    session: AsyncSession, group_a: UUID
) -> None:
    """L'ensemble vide vaut « rien de declare », JAMAIS « tout », cote base aussi.

    Les deux moities sont eprouvees separement : des heures sans espece, puis une
    espece sans heure. Chacune se relit fidelement -- l'aller-retour du mapping
    tient sur une collection vide -- et aucune ne repond a la requete.
    """
    clinic_id = uuid4()
    hours_only, species_only = uuid4(), uuid4()
    await _seed_profile(
        session, group_id=group_a, account_id=hours_only, clinic_id=clinic_id, species=()
    )
    await _seed_profile(
        session, group_id=group_a, account_id=species_only, clinic_id=clinic_id, hours=()
    )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        without_species = await repository.find_for_account_in_clinic(hours_only, clinic_id)
        without_hours = await repository.find_for_account_in_clinic(species_only, clinic_id)
        available = await repository.list_available(clinic_id, _MONDAY_TEN_TO_ELEVEN, Species.DOG)

    assert without_species is not None
    assert without_species.treated_species == frozenset()
    assert without_species.hours == (_MONDAY_MORNING,)
    assert without_hours is not None
    assert without_hours.hours == ()
    assert without_hours.treated_species == frozenset({Species.DOG})
    assert available == []


async def test_stored_children_come_back_in_canonical_order(
    session: AsyncSession, group_a: UUID
) -> None:
    """Ce sont les `order_by` des deux relations qui font l'ordre rendu.

    Ecrire par le depot ne saurait pas le prouver : `_validated_hours` trie deja
    les plages et `_apply_to_model` trie les especes, si bien que l'ordre des
    lignes coincide toujours avec l'ordre canonique. Le semis BRUT en ordre
    inverse est le seul chemin qui decouple les deux.
    """
    account_id, clinic_id = uuid4(), uuid4()
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=account_id,
        clinic_id=clinic_id,
        hours=(
            (int(Day.TUESDAY), _TWO_PM, _SIX_PM),
            (int(Day.MONDAY), _TWO_PM, _SIX_PM),
            (int(Day.MONDAY), _NINE, _NOON),
        ),
        species=(Species.FERRET.value, Species.CAT.value, Species.DOG.value),
    )

    with use_group(group_a):
        profile = await SqlAlchemyPractitionerProfileRepository(session).find_for_account_in_clinic(
            account_id, clinic_id
        )

    assert profile is not None
    assert [(declared.weekday, declared.start_minute) for declared in profile.hours] == [
        (Day.MONDAY, _NINE),
        (Day.MONDAY, _TWO_PM),
        (Day.TUESDAY, _TWO_PM),
    ]
    assert profile.treated_species == frozenset({Species.CAT, Species.DOG, Species.FERRET})


async def test_saving_a_profile_replaces_its_collections_within_the_block(
    session: AsyncSession, group_a: UUID
) -> None:
    """NON-REGRESSION DU SOCLE : `flush([model])` propage bien `delete-orphan`.

    Le depot ne surcharge NI `add` NI `save` : le flush restreint du socle suffit,
    verifie a l'execution. Ce test verrouille la propriete -- il mordrait le jour
    ou une montee de SQLAlchemy changerait ce comportement, et la fiche relue par
    une REQUETE (jamais par l'identity map) montrerait alors l'etat d'avant.
    """
    account_id, clinic_id = uuid4(), uuid4()
    profile = PractitionerProfile.create(
        account_id=account_id,
        clinic_id=clinic_id,
        hours=[_MONDAY_MORNING, _TUESDAY_AFTERNOON],
        treated_species=[Species.DOG, Species.FERRET],
    )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        await repository.add(profile)
        assert await _count_hours(session, profile.id) == 2
        assert await _count_species(session, profile.id) == 2

        profile.set_hours([_TUESDAY_AFTERNOON])
        profile.treated_species = frozenset({Species.CAT})
        await repository.save(profile)

        reloaded = await repository.find_for_account_in_clinic(account_id, clinic_id)

    assert await _count_hours(session, profile.id) == 1
    assert await _count_species(session, profile.id) == 1
    assert reloaded is not None
    assert reloaded.hours == (_TUESDAY_AFTERNOON,)
    assert reloaded.treated_species == frozenset({Species.CAT})


async def test_deleting_a_profile_takes_its_children_with_it(
    session: AsyncSession, group_a: UUID
) -> None:
    """La cascade `delete-orphan` et le flush COMPLET de `delete`, tous deux herites.

    Sans le flush complet du socle, le DELETE de la ligne parente partirait seul
    et heurterait la cle etrangere des enfants.
    """
    profile = PractitionerProfile.create(
        account_id=uuid4(),
        clinic_id=uuid4(),
        hours=[_MONDAY_MORNING],
        treated_species=[Species.DOG],
    )
    repository = SqlAlchemyPractitionerProfileRepository(session)

    with use_group(group_a):
        await repository.add(profile)
        await repository.delete(profile.id)

    assert await _count_hours(session, profile.id) == 0


# --- Ce que la base refuse, et ce que la relecture refuse ---------------------


@pytest.mark.parametrize(
    "hours",
    [
        ((int(Day.MONDAY), _NOON, _NINE),),
        ((int(Day.MONDAY), _NOON, _NOON),),
    ],
)
async def test_the_database_refuses_an_inverted_range(
    session: AsyncSession, group_a: UUID, hours: tuple[tuple[int, int, int], ...]
) -> None:
    """`ck_practitioner_hours_range_bounds` existe reellement, egalite comprise."""
    with pytest.raises(IntegrityError):
        await _seed_profile(
            session, group_id=group_a, account_id=uuid4(), clinic_id=uuid4(), hours=hours
        )


@pytest.mark.parametrize(
    "hours",
    [
        ((int(Day.MONDAY), -1, _NOON),),
        ((int(Day.MONDAY), _NINE, _MIDNIGHT + 1),),
    ],
)
async def test_the_database_refuses_a_minute_outside_the_day(
    session: AsyncSession, group_a: UUID, hours: tuple[tuple[int, int, int], ...]
) -> None:
    """`ck_practitioner_hours_minute_of_day_range` borne la journee a 0..1440."""
    with pytest.raises(IntegrityError):
        await _seed_profile(
            session, group_id=group_a, account_id=uuid4(), clinic_id=uuid4(), hours=hours
        )


async def test_the_database_accepts_a_range_ending_at_midnight(
    session: AsyncSession, group_a: UUID
) -> None:
    """1440 est une fin VALIDE : la vacation « 18:00 -> minuit » s'insere."""
    account_id, clinic_id = uuid4(), uuid4()
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=account_id,
        clinic_id=clinic_id,
        hours=((int(Day.MONDAY), _SIX_PM, _MIDNIGHT),),
    )

    with use_group(group_a):
        profile = await SqlAlchemyPractitionerProfileRepository(session).find_for_account_in_clinic(
            account_id, clinic_id
        )

    assert profile is not None
    assert profile.hours[0].end_minute == _MIDNIGHT


async def test_the_database_refuses_an_out_of_range_weekday(
    session: AsyncSession, group_a: UUID
) -> None:
    """`ck_practitioner_hours_weekday_python_range` borne le jour a 0..6."""
    with pytest.raises(IntegrityError):
        await _seed_profile(
            session,
            group_id=group_a,
            account_id=uuid4(),
            clinic_id=uuid4(),
            hours=((7, _NINE, _NOON),),
        )


async def test_a_corrupted_species_in_a_stored_row_raises(
    session: AsyncSession, group_a: UUID
) -> None:
    """UNE VALEUR INCONNUE LEVE, ELLE N'EST PAS IGNOREE.

    L'avaler rendrait un praticien silencieusement competent pour rien, et
    l'ecart ne se verrait qu'a l'appariement -- la ou personne ne le cherche.
    """
    account_id, clinic_id = uuid4(), uuid4()
    await _seed_profile(
        session,
        group_id=group_a,
        account_id=account_id,
        clinic_id=clinic_id,
        species=("fish",),
    )

    with use_group(group_a), pytest.raises(UnknownSpeciesError) as refusal:
        await SqlAlchemyPractitionerProfileRepository(session).find_for_account_in_clinic(
            account_id, clinic_id
        )

    assert "fish" in str(refusal.value)


async def test_hours_are_stored_as_small_integers_of_minutes(session: AsyncSession) -> None:
    """La decision « heure murale, jamais un instant » est GRAVEE dans le schema.

    Aucune colonne de type `time` ni `timestamp` sur les tables filles : une
    migration future qui la changerait fera rougir ce test avant tout le reste.
    """
    statement = text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_name IN ('practitioner_hours', 'practitioner_species')"
    )
    columns = {
        (row.table_name, row.column_name): row.data_type
        for row in (await session.execute(statement)).all()
    }

    assert columns[("practitioner_hours", "weekday")] == "smallint"
    assert columns[("practitioner_hours", "start_minute")] == "smallint"
    assert columns[("practitioner_hours", "end_minute")] == "smallint"
    assert not any(data_type.startswith(("time", "timestamp")) for data_type in columns.values())
