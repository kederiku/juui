"""Le test d'acceptation de BACK-19 : une seule detention active par animal.

La regle est pure -- elle se prouve sans Docker : `ensure_custody_openable`
recoit les detentions deja enregistrees d'un animal et refuse d'en ouvrir une
nouvelle tant qu'une autre reste OUVERTE (`end_at is None`), le predicat exact
de l'index unique partiel. La moitie physique est prouvee cote base par
`test_ports.py::test_second_open_custody_is_refused_by_the_database`.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.medical_records.domain.entities import Custody, ensure_custody_openable
from app.modules.medical_records.domain.exceptions import CustodyAlreadyActiveError

_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _custody(animal_id: UUID, *, start_at: datetime, end_at: datetime | None) -> Custody:
    """Fabrique une detention de l'animal teste, sur la fenetre donnee."""
    return Custody.create(
        animal_id=animal_id,
        account_id=uuid4(),
        start_at=start_at,
        end_at=end_at,
    )


def test_no_prior_custody_allows_the_opening() -> None:
    """Cas nominal : un animal jamais detenu accueille sa premiere detention."""
    ensure_custody_openable([])


def test_open_custody_refuses_a_second_opening() -> None:
    """Une detention ouverte bloque toute ouverture : une seule active a la fois."""
    animal_id = uuid4()
    custodies = [_custody(animal_id, start_at=_AT - timedelta(days=30), end_at=None)]
    with pytest.raises(CustodyAlreadyActiveError):
        ensure_custody_openable(custodies)


def test_closed_custodies_allow_the_next_opening() -> None:
    """La succession du critere 4 : toutes les fenetres closes, la suivante passe."""
    animal_id = uuid4()
    custodies = [
        _custody(animal_id, start_at=_AT - timedelta(days=90), end_at=_AT - timedelta(days=30)),
        _custody(animal_id, start_at=_AT - timedelta(days=30), end_at=_AT),
    ]
    ensure_custody_openable(custodies)


def test_one_open_among_closed_still_refuses() -> None:
    """L'historique ne blanchit rien : une seule ouverte au milieu des closes suffit."""
    animal_id = uuid4()
    custodies = [
        _custody(animal_id, start_at=_AT - timedelta(days=90), end_at=_AT - timedelta(days=30)),
        _custody(animal_id, start_at=_AT - timedelta(days=30), end_at=None),
    ]
    with pytest.raises(CustodyAlreadyActiveError):
        ensure_custody_openable(custodies)


def test_boundary_instant_belongs_to_the_next_custody() -> None:
    """Deux detentions raccordees ne partagent aucun instant : la borne est a la suivante."""
    animal_id = uuid4()
    handover_at = _AT - timedelta(days=30)
    previous = _custody(animal_id, start_at=_AT - timedelta(days=90), end_at=handover_at)
    following = _custody(animal_id, start_at=handover_at, end_at=None)
    assert not previous.is_active(handover_at)
    assert following.is_active(handover_at)
