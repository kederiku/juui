"""Briques transverses du service d'API.

`core/` porte ce dont toutes les couches ont besoin sans que ce soit du metier :
la configuration (BACK-03), puis la journalisation (BACK-11). Rien de ce qui s'y
trouve ne doit connaitre le domaine, et le domaine ne doit rien y importer d'autre
que des reglages.

A ne pas confondre avec les trois couches de l'architecture hexagonale --
`domain/`, `application/`, `infrastructure/` -- que posera BACK-04 : celles-ci
decrivent le sens des dependances, `core/` n'est qu'un socle technique.
"""

from app.core.config import (
    AppSettings,
    ConfigurationError,
    DatabaseSettings,
    JWTSettings,
    RedisSettings,
    S3Settings,
    Settings,
    SettingsDep,
    get_settings,
)

# Re-export EXPLICITE : Mypy tourne avec `no_implicit_reexport` (implique par
# `strict`), un simple import ne suffirait donc pas a rendre ces noms
# importables depuis `app.core`.
__all__ = [
    "AppSettings",
    "ConfigurationError",
    "DatabaseSettings",
    "JWTSettings",
    "RedisSettings",
    "S3Settings",
    "Settings",
    "SettingsDep",
    "get_settings",
]
