"""Contexte automatique des lignes de journal (BACK-11, critere 4).

« Ces valeurs sont posees par la dependance d'authentification, jamais
renseignees a la main » : BACK-10c n'etant pas livre, les contextvars sont ici
posees par leurs gestionnaires de contexte -- exactement ce que fera cette
dependance. Ce qui se prouve, c'est le CHEMIN entre la contextvar et la ligne
rendue, et c'est lui qui manquait.
"""

import json
from uuid import UUID, uuid4

import pytest
from taskiq import TaskiqMessage

from app.core.correlation import use_account_id, use_clinic_id, use_request_id
from app.core.logging import ConsoleFormatter, JsonFormatter
from app.shared.infrastructure.tasks.middlewares import REQUEST_ID_LABEL, CorrelationMiddleware
from app.shared.infrastructure.tenancy import current_group_label, use_all_groups, use_group
from tests.core.logging_probes import make_record

pytestmark = pytest.mark.observability

# `current_group_label` de `shared/` passe en argument, comme le font les deux
# points d'entree du processus : `core` ne peut pas importer `shared`.
_PROVIDERS = {"group_id": current_group_label}


def _rendered(**providers: object) -> dict[str, object]:
    """Rend une ligne JSON avec les fournisseurs de contexte du service."""
    formatter = JsonFormatter(context_providers=_PROVIDERS)
    parsed: dict[str, object] = json.loads(formatter.format(make_record()))
    return parsed


def test_a_line_logged_outside_any_request_carries_no_identifier() -> None:
    """L'absence de contexte est un etat NORMAL : une sonde, un script, l'ordonnanceur."""
    rendered = _rendered()
    assert list(rendered) == ["timestamp", "level", "logger", "message"]


def test_the_request_id_of_the_context_appears_in_the_line() -> None:
    with use_request_id("req-sonde"):
        assert _rendered()["request_id"] == "req-sonde"


def test_the_account_id_of_the_context_appears_in_the_line() -> None:
    account_id = uuid4()
    with use_account_id(account_id):
        assert _rendered()["account_id"] == str(account_id)


def test_the_clinic_id_of_the_context_appears_in_the_line() -> None:
    clinic_id = uuid4()
    with use_clinic_id(clinic_id):
        assert _rendered()["clinic_id"] == str(clinic_id)


def test_the_active_group_id_of_the_context_appears_in_the_line() -> None:
    """Le groupe vient de `shared/` par injection : une seule source de verite."""
    group_id = uuid4()
    with use_group(group_id):
        assert _rendered()["group_id"] == str(group_id)


def test_the_four_identifiers_appear_together_on_a_single_line() -> None:
    """Le critere 4, litteralement : sans qu'aucun appelant y pense."""
    account_id, group_id, clinic_id = uuid4(), uuid4(), uuid4()
    with (
        use_request_id("req-sonde"),
        use_account_id(account_id),
        use_group(group_id),
        use_clinic_id(clinic_id),
    ):
        rendered = _rendered()
    assert rendered["request_id"] == "req-sonde"
    assert rendered["account_id"] == str(account_id)
    assert rendered["group_id"] == str(group_id)
    assert rendered["clinic_id"] == str(clinic_id)


def test_the_all_groups_mode_is_rendered_without_crashing() -> None:
    """`current_group_id` porte TROIS etats, et le troisieme n'est pas un UUID.

    Un fournisseur ecrit en supposant un `UUID` leverait dans le seed d'INFRA-08
    ou la CLI superadmin -- c'est-a-dire dans un formateur de journal, l'endroit
    du service ou une exception est la plus difficile a voir. La raison de
    l'echappatoire, elle, n'a pas sa place sur chaque ligne.
    """
    with use_all_groups(reason="jeu de donnees de demonstration"):
        assert _rendered()["group_id"] == "*"


def test_the_readable_line_omits_the_identifiers_that_are_not_set() -> None:
    line = ConsoleFormatter(context_providers=_PROVIDERS, colors=False).format(make_record())
    assert "request_id=" not in line
    assert "group_id=" not in line


def test_the_readable_line_carries_the_identifiers_that_are_set() -> None:
    with use_request_id("req-sonde"):
        line = ConsoleFormatter(context_providers=_PROVIDERS, colors=False).format(make_record())
    assert "request_id=req-sonde" in line


def test_a_context_key_never_shadows_a_schema_key() -> None:
    """Un fournisseur mal nomme ne doit pas pouvoir reecrire le niveau."""
    formatter = JsonFormatter(context_providers={"logger": lambda: "usurpe"})
    rendered = json.loads(formatter.format(make_record(logger_name="app.vrai")))
    assert rendered["logger"] == "usurpe"


def test_a_line_logged_in_a_worker_carries_the_request_id_of_its_caller() -> None:
    """La propagation vers le worker etait livree par BACK-15 ; il lui manquait un lecteur.

    `pre_execute` est appele ici directement : ni Redis, ni worker, et le critere
    « propage » cesse d'etre une affaire de sonde manuelle seulement.
    """
    # `pre_execute` pose la contextvar SANS la remettre, et c'est correct cote
    # worker : le receiver execute chaque message dans sa propre tache asyncio,
    # dont le contexte meurt avec lui. Ici il n'y a pas de tache : le bloc rend
    # au test ce que le worker obtient gratuitement -- et le garde-fou du
    # conftest racine refuse de laisser passer l'oubli.
    with use_request_id(None):
        message = CorrelationMiddleware().pre_execute(
            _taskiq_message(labels={REQUEST_ID_LABEL: "req-de-l-appelant"})
        )
        assert message.labels[REQUEST_ID_LABEL] == "req-de-l-appelant"
        assert _rendered()["request_id"] == "req-de-l-appelant"


def _taskiq_message(*, labels: dict[str, str]) -> TaskiqMessage:
    """Construit un message TaskIQ minimal, sans broker ni file."""
    return TaskiqMessage(
        task_id="sonde",
        task_name="tests.sonde",
        labels=labels,
        labels_types=None,
        args=[],
        kwargs={},
    )


def test_the_group_label_covers_the_three_states_of_the_contextvar() -> None:
    """Le `match` du fournisseur est exhaustif : les trois etats se rendent."""
    assert current_group_label() is None
    group_id = UUID(int=1)
    with use_group(group_id):
        assert current_group_label() == str(group_id)
    with use_all_groups(reason="sonde"):
        assert current_group_label() == "*"
