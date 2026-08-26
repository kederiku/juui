"""Exporte le schema OpenAPI du service vers le dossier du client genere (SHARED-03).

SANS SERVEUR ET SANS BASE DE DONNEES. Le schema se construit en memoire, par
`create_app().openapi()` : `app.main` est importable sans effet de bord -- toutes
les ressources s'ouvrent dans le lifespan, jamais a l'import --, ce que la
docstring de ce lifespan annonce nommement pour « les futurs exports d'OpenAPI ».

POURQUOI PAS L'ENDPOINT HTTP. `/openapi.json` repond en developpement, mais il
est FERME en production (BACK-08, ecart consigne au registre) et la verification
de CI n'a aucun serveur a interroger. Le document rendu ici est par ailleurs le
MEME sous ENVIRONMENT=development, staging et production : seule la route se
ferme, pas le schema. L'export ne depend donc ni d'un port, ni d'un conteneur,
ni d'un .env.

CE FICHIER VIT HORS DE src/, ET CE N'EST PAS UN RANGEMENT PAR DEFAUT. Le contrat
`service-spaces` de BACK-04b est declare `exhaustive` : tout nouveau dossier a la
racine du paquet `app` -- un `app/cli/`, par exemple -- fait echouer `make lint`
tant que sa place dans la hierarchie main > modules > shared > core n'est pas
ecrite. Un exportateur est de l'outillage, pas un cinquieme espace du service :
il n'a pas a elargir la definition de l'architecture pour exister.
"""

import json
from pathlib import Path

from app.main import create_app

# Destination ANCREE SUR CE FICHIER et non sur le repertoire courant -- meme
# geste que le `_ENV_FILE` de app/core/config.py, et pour la meme raison : la
# commande doit produire le meme fichier d'ou qu'on la lance.
# scripts/ -> backend/api -> backend -> racine du depot.
_DESTINATION = Path(__file__).resolve().parents[3] / "packages" / "api-client" / "openapi.json"


def render() -> str:
    """Rend le schema OpenAPI sous sa forme canonique, terminee par un saut de ligne."""
    return (
        json.dumps(
            create_app().openapi(),
            # Un objet par ligne. Sans indentation, chaque evolution du contrat
            # serait UNE ligne illisible en revue -- or c'est precisement la
            # lisibilite de ce diff qui justifie de versionner le fichier
            # (ADR-0007). 2 espaces : la valeur de .editorconfig pour tout ce
            # qui n'est pas Python.
            indent=2,
            # Les accents s'ecrivent en clair plutot qu'en \\uXXXX. Le depot est
            # en UTF-8, et une description de champ illisible en diff ne sert
            # personne.
            ensure_ascii=False,
            # CEINTURE ET BRETELLES, assume. FastAPI trie deja components.schemas
            # et Pydantic trie recursivement les sous-schemas ; ce qui reste non
            # trie -- l'ordre de montage des routes, les clefs de premier
            # niveau -- s'est revele stable d'un processus a l'autre. Mais cette
            # stabilite est celle du code d'un tiers, pas une garantie qu'il nous
            # donne : trier ici rend le fichier independant de cet ordre pour de
            # bon, et c'est `make generate-api-check` qui en depend.
            sort_keys=True,
            # Le defaut quand `indent` est fourni. Ecrit en clair parce que c'est
            # la seule des quatre options precedentes dont la valeur ne se
            # lirait pas dans l'appel.
            separators=(",", ": "),
        )
        # json.dumps n'en met pas ; .editorconfig en exige un, et son absence
        # produirait un « \\ No newline at end of file » dans chaque diff.
        + "\n"
    )


def main() -> None:
    """Ecrit le schema a sa destination et annonce le chemin produit."""
    # Le rendu AVANT l'ouverture du fichier : une exception pendant la
    # construction du schema laisse alors la version precedente intacte, au lieu
    # d'un fichier tronque a zero octet que la verification suivante signalerait
    # comme une derive du contrat.
    document = render()

    # `encoding` ET `newline` explicites, les deux. Sans le premier, Python
    # ecrirait dans l'encodage de la plateforme -- cp1252 sous Windows, ou les
    # accents seraient perdus. Sans le second, chaque \\n deviendrait \\r\\n sous
    # Windows : le .gitattributes du depot rattraperait le diff, mais le fichier
    # sur le disque differerait malgre tout d'une machine a l'autre.
    _DESTINATION.write_text(document, encoding="utf-8", newline="\n")
    print(f"SHARED-03 : schema OpenAPI ecrit dans {_DESTINATION}")


if __name__ == "__main__":
    main()
