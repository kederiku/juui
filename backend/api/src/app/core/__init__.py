"""Briques transverses du service d'API.

`core/` porte ce dont toutes les couches ont besoin sans que ce soit du metier :
la configuration (BACK-03), le contexte de correlation (`correlation.py`, livre
par BACK-15 en anticipation), puis la journalisation (BACK-11). Rien de ce qui s'y
trouve ne doit connaitre le domaine, et le domaine ne doit rien y importer d'autre
que des reglages.

A ne pas confondre avec les trois couches de l'architecture hexagonale --
`domain/`, `application/`, `infrastructure/`, posees par BACK-04 : celles-ci
decrivent le sens des dependances, `core/` n'est qu'un socle technique.

A ne pas confondre non plus avec `app.shared`, qui porte le noyau partage par
les modules metier -- racine des erreurs, ports techniques, socles de
persistance et d'API. BACK-04 laisse `core/` en place a dessein : ce qu'il
contient regle le PROCESSUS, pas l'architecture.
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
