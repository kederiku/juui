"""Sauter faute de service -- ou echouer, quand on a demande le contraire.

UN SEUL ENDROIT POUR LES QUATRE SERVICES (BACK-12). Avant ce ticket ils avaient
trois comportements pour une meme situation : Redis, MinIO et Mailpit sautaient
chacun avec son `pytest.skip` muet, et PostgreSQL tuait la SESSION ENTIERE par
`pytest.exit()` -- y compris les moities en memoire, qui n'ont besoin de rien.

ICI ET NON DANS `conftest.py`, parce que sept fichiers de test appellent
`require_service` : un conftest n'est pas un module d'API, et la regle que ce
ticket vient d'ecrire est que ce qui AIDE a tester vit dans `tests/support/`.
Les deux hooks pytest restent dans le conftest -- c'est le seul endroit ou pytest
les collecte -- et delegent ici.

Ce module ne commence pas par `test_` : pytest ne le collecte pas.
"""

from typing import Final, NoReturn

import pytest

# Noms des services de la pile locale. Des constantes plutot que des litteraux
# repetes dans sept fichiers : c'est le recensement qui les regroupe, et deux
# orthographes en feraient deux services.
POSTGRES: Final = "postgres"
REDIS: Final = "redis"
MINIO: Final = "minio"
MAILPIT: Final = "mailpit"

# Remedes, un par service. Ils nomment le geste, pas seulement la faute.
STACK_UP: Final = "`make dev` a la racine demarre la pile"
REDIS_REMEDY: Final = f"{STACK_UP} (INFRA-02)."
MINIO_REMEDY: Final = f"{STACK_UP} (INFRA-03)."
MAILPIT_REMEDY: Final = f"{STACK_UP} (INFRA-07)."

# Services de la pile locale qui n'ont pas repondu, et leur remede. Un ENSEMBLE
# et non un compteur : ce qui interesse le lecteur du rapport n'est pas combien
# de tests ont saute -- le resume `-rs` le dit deja -- mais LESQUELS des quatre
# services manquaient, donc quelle part de la suite n'a rien prouve.
MISSING_SERVICES: Final = pytest.StashKey[dict[str, str]]()


def require_service(config: pytest.Config, *, name: str, remedy: str) -> NoReturn:
    """Saute le test faute de service -- ou echoue, si on a demande le contraire.

    Le saut est RECENSE, et c'est la piece qui manquait : un `skip` se lit dans
    `-rs`, mais il s'y noie. Le bloc de fin de session dit lesquels des quatre
    services ont manque.

    Args:
        config: la configuration de la session, qui porte le recensement.
        name: le service qui n'a pas repondu.
        remedy: le geste qui le rend joignable, en toutes lettres.

    Raises:
        Failed: sous `--require-services`, ou l'absence est une panne.
        Skipped: sinon.
    """
    message = f"{name} ne repond pas. {remedy}"
    if config.getoption("--require-services"):
        pytest.fail(message, pytrace=False)
    config.stash[MISSING_SERVICES][name] = remedy
    pytest.skip(message)


def report_missing_services(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Nomme les services absents, donc la part de la suite qui n'a rien prouve.

    Sans ce bloc, une execution verte sur un poste sans Redis ressemble trait
    pour trait a une execution verte sur un poste complet. La page Tests appelait
    cela « le piege de cette suite » ; c'est ici qu'il se referme.

    Args:
        terminalreporter: le rapporteur, dont on lit le decompte des sauts.
        config: la configuration de la session, qui porte le recensement.
    """
    missing = config.stash.get(MISSING_SERVICES, {})
    if not missing:
        return
    skipped = len(terminalreporter.stats.get("skipped", []))
    terminalreporter.write_sep("=", "services absents", yellow=True, bold=True)
    for name, remedy in sorted(missing.items()):
        terminalreporter.write_line(f"  {name} -- {remedy}")
    terminalreporter.write_line(
        f"{skipped} test(s) sautes : cette execution NE PROUVE PAS ce qu'ils couvrent. "
        "`--require-services` fait echouer la suite au lieu de sauter."
    )
