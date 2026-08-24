"""Configuration applicative du service d'API (BACK-03).

Tout ce que l'API lit de son environnement passe par ici, et par nulle part
ailleurs : aucun `os.getenv` n'a sa place dans le reste du code. Le module expose
un objet unique, `Settings`, compose de cinq sous-modeles thematiques, et la
fonction `get_settings()` qui le construit une fois pour toutes.

DEUX SOURCES, DEUX COMPORTEMENTS
Les valeurs viennent des variables d'environnement du PROCESSUS -- c'est ainsi
que le conteneur d'INFRA-04 sera configure -- et du FICHIER `backend/api/.env`,
c'est ainsi qu'on lance uvicorn sur son poste. Les premieres sont filtrees sur
les champs declares : une variable inconnue est ignoree, ce qui laisse le
conteneur recevoir sans broncher les `POSTGRES_HOST_PORT` et autres
`MINIO_API_HOST_PORT` qui ne le concernent pas. Le fichier, lui, est STRICT :
toute cle qu'aucun champ ne reclame empeche le demarrage. C'est ce que promet
`.env.example`, et c'est ce qui fait de ce gabarit le miroir exact des champs
declares ici. Voir `_OrphanKeyDotEnvSource` pour le detail du mecanisme.

NOMMAGE DES VARIABLES
Chaque sous-modele porte son propre `env_prefix` (`POSTGRES_`, `REDIS_`, `S3_`,
`JWT_`) plutot que le `env_nested_delimiter` prevu par la carte : `POSTGRES_USER`
et `MINIO_ROOT_USER` sont imposes par les images Docker, et un delimiteur
imposerait une couche de traduction pour rien. L'ecart est inscrit au README de
la racine, ou il a ete arbitre des SETUP-05.
"""

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import quote

from fastapi import Depends
from pydantic import (
    AliasChoices,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Fichier d'environnement du service, ANCRE sur backend/api/ et non sur le
# repertoire courant. Un `uv run uvicorn` lance depuis la racine du monorepo
# chargerait sinon le .env de la RACINE, celui de docker compose -- exactement ce
# que son gabarit interdit. Dans l'image d'INFRA-04 le chemin n'existera pas, et
# pydantic-settings ignore silencieusement un env_file absent : le conteneur
# n'est configure que par ses variables d'environnement.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Valeur que .env.example livre pour JWT_SECRET_KEY. Ce n'est pas une cle mais un
# marqueur, deliberement non hexadecimal ; le laisser en place en production est
# une faille, pas une negligence de style.
_JWT_PLACEHOLDER = "changer-cette-valeur-voir-openssl-rand-hex-32"


class ConfigurationError(RuntimeError):
    """Configuration absente, incomplete ou invalide : l'API ne peut pas demarrer.

    Levee par `get_settings()` a la place de la `ValidationError` de pydantic,
    dont le message nomme des champs (`user`) la ou l'exploitant a besoin de noms
    de variables (`POSTGRES_USER`).
    """


class _SettingsSection(BaseSettings):
    """Socle commun aux cinq sous-modeles thematiques.

    Les trois reglages qui comptent :

    - `env_file` : les cinq classes lisent le MEME fichier, chacune n'y prenant
      que son prefixe.
    - `dotenv_filtering="only_existing"` : sans lui, `DatabaseSettings` verrait
      `REDIS_HOST` comme une cle surnumeraire et refuserait de se construire --
      la cohabitation de cinq sous-modeles dans un seul fichier tient a cette
      ligne.
    - `extra="forbid"` : le defaut de pydantic-settings, conserve. Il ne porte
      plus sur le fichier (voir ci-dessus) mais toujours sur les arguments passes
      au constructeur, ce qui protege les surcharges de test d'une faute de
      frappe silencieuse.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        dotenv_filtering="only_existing",
        extra="forbid",
    )


class AppSettings(_SettingsSection):
    """Reglages generaux de l'application. Sans prefixe (BACK-03, BACK-11)."""

    # Prefixe vide EXPLICITE, alors que c'est deja le defaut : les cinq
    # sous-modeles annoncent ainsi tous leur prefixe au meme endroit, et
    # `ENVIRONMENT` ou `LOG_LEVEL` se lisent pour ce qu'ils sont -- des variables
    # nues, et non un oubli.
    model_config = SettingsConfigDict(env_prefix="")

    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # `NoDecode` n'est pas decoratif : sans lui, pydantic-settings voit un type
    # complexe et tente un json.loads sur
    # « http://localhost:3001,http://localhost:3002 », qui echoue avant toute
    # validation. Le decoupage se fait donc dans le validateur ci-dessous.
    #
    # list[str] et NON list[AnyHttpUrl] : Starlette compare les origines
    # caractere par caractere, or AnyHttpUrl normalise en ajoutant une barre
    # finale. Le CORS tomberait alors en silence, sans la moindre erreur.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accepte la liste separee par des virgules que documente .env.example."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        """Vrai en production, ou /docs se ferme (BACK-08) et ou les logs passent en JSON."""
        return self.environment == "production"


class DatabaseSettings(_SettingsSection):
    """Connexion PostgreSQL. Prefixe `POSTGRES_` (BACK-03, BACK-05)."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    # Aucun defaut : ces trois valeurs identifient une base reelle, et un defaut
    # ne ferait que retarder l'echec jusqu'a la premiere requete.
    user: str
    password: SecretStr
    db: str

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)

    # Reglages du POOL DE CONNEXIONS, cote client. Rien a voir avec un reglage
    # du serveur PostgreSQL, malgre le prefixe : c'est le nombre de connexions
    # que CE processus garde ouvertes.
    #
    # Le calcul qui compte : connexions totales = workers x (pool_size +
    # max_overflow). Avec les valeurs ci-dessous et quatre workers, l'API seule
    # peut en reclamer 60, avant le worker TaskIQ (BACK-15) et pgAdmin -- contre
    # un `max_connections` de 100 par defaut cote serveur.
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=10, ge=0)

    # Age au-dela duquel une connexion est retiree du pool plutot que reprise.
    # `pool_pre_ping` verifie les connexions a l'emprunt, mais il attendrait le
    # delai TCP sur une socket coupee en silence par un intermediaire ; ce
    # recyclage les retire avant d'en arriver la. -1 desactive le mecanisme.
    pool_recycle_seconds: int = Field(default=1800, ge=-1)

    # Journalisation de chaque requete SQL emise, PARAMETRES LIES COMPRIS.
    #
    # Un champ a soi, et non une deduction de `LOG_LEVEL` : ces parametres
    # portent les adresses e-mail aujourd'hui, les empreintes de mot de passe a
    # partir de BACK-10b et le secret TOTP a partir de BACK-18. Passer
    # `LOG_LEVEL=DEBUG` pour suivre un probleme de routage ne doit pas les
    # deverser dans la chaine de journalisation par effet de bord.
    echo: bool = False

    @property
    def sqlalchemy_url(self) -> str:
        """URL asynchrone attendue par `create_async_engine` (BACK-05).

        Valeur DERIVEE : elle se recompose a partir des composants ci-dessus, ce
        qui evite la seconde source de verite qu'aurait ete un `DATABASE_URL`
        saisi a la main.

        Le mot de passe y figure EN CLAIR. C'est une propriete et non un
        `computed_field` pour cette raison precise : elle n'entre ni dans le
        `repr` ni dans `model_dump()`. Ne jamais la journaliser telle quelle.
        """
        # `quote` est indispensable : pydantic ne reencode pas ce qu'on lui donne
        # (verifie), et un `@` ou un `/` dans un mot de passe de production
        # couperait l'URL en deux sans lever la moindre erreur.
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=quote(self.user, safe=""),
                password=quote(self.password.get_secret_value(), safe=""),
                host=self.host,
                port=self.port,
                # Sans barre initiale : pydantic l'ajoute, et la doubler
                # produirait une base nommee « /juui ».
                path=self.db,
            )
        )


class RedisSettings(_SettingsSection):
    """Connexion Redis. Prefixe `REDIS_` (BACK-03, BACK-14, BACK-15).

    Les deux bases sont separees a dessein depuis INFRA-02 : purger le cache ne
    doit jamais vider la file de taches.
    """

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = Field(default=6379, ge=1, le=65535)
    cache_db: int = Field(default=0, ge=0, le=15)
    broker_db: int = Field(default=1, ge=0, le=15)

    # L'instance de developpement n'a pas de mot de passe. `None` et non chaine
    # vide : une chaine vide serait un mot de passe, pas une absence.
    password: SecretStr | None = None

    @property
    def cache_url(self) -> str:
        """URL du cache applicatif, base `REDIS_CACHE_DB` (BACK-14)."""
        return self._url(self.cache_db)

    @property
    def broker_url(self) -> str:
        """URL du broker TaskIQ, base `REDIS_BROKER_DB` (BACK-15)."""
        return self._url(self.broker_db)

    def _url(self, database: int) -> str:
        """Compose l'URL d'une base Redis. Contient le mot de passe : ne pas journaliser."""
        quoted_password = (
            None if self.password is None else quote(self.password.get_secret_value(), safe="")
        )
        return str(
            RedisDsn.build(
                scheme="redis",
                password=quoted_password,
                host=self.host,
                port=self.port,
                path=str(database),
            )
        )


class S3Settings(_SettingsSection):
    """Stockage objet compatible S3. Prefixe `S3_` (BACK-03, BACK-13)."""

    # `validate_by_name` autorise a construire la classe par les NOMS de champs
    # (`S3Settings(access_key=...)`) en plus des alias ci-dessous. Sans lui, deux
    # champs obligatoires ne seraient atteignables que par leur alias, ce que le
    # greffon Mypy de pydantic signale a juste titre : une surcharge de test
    # devrait ecrire `S3Settings(S3_ACCESS_KEY=...)`. La lecture par alias, elle,
    # reste active -- c'est le defaut.
    model_config = SettingsConfigDict(env_prefix="S3_", validate_by_name=True)

    # Les alias de repli sont ceux qu'annonce le .env.example de la RACINE : en
    # developpement, les clefs d'acces VALENT les identifiants racine de MinIO, et
    # personne n'a a ecrire deux fois la meme valeur. Le prefixe `S3_` ne
    # s'applique pas aux alias (`env_prefix_target` vaut « variable » par
    # defaut) : les deux noms sont donc lus tels quels.
    access_key: SecretStr = Field(
        validation_alias=AliasChoices("S3_ACCESS_KEY", "MINIO_ROOT_USER"),
    )
    secret_key: SecretStr = Field(
        validation_alias=AliasChoices("S3_SECRET_KEY", "MINIO_ROOT_PASSWORD"),
    )
    bucket: str

    # SEUL parametre qui distingue MinIO d'Amazon S3. Laisse vide en production,
    # boto3 retombe sur les endpoints AWS reels.
    endpoint_url: str | None = None

    # MinIO ignore la region, mais boto3 refuse de construire un client sans elle.
    region: str = "us-east-1"


class JWTSettings(_SettingsSection):
    """Signature des jetons d'authentification. Prefixe `JWT_` (BACK-03, BACK-10)."""

    model_config = SettingsConfigDict(env_prefix="JWT_")

    secret_key: SecretStr
    algorithm: str = "HS256"

    # Court par construction : ce jeton circule a chaque requete.
    access_token_expire_minutes: int = Field(default=15, gt=0)
    refresh_token_expire_days: int = Field(default=7, gt=0)


# Ordre d'affichage dans les messages d'erreur, et source unique du jeu de cles
# admises dans le fichier .env.
_SETTINGS_SECTIONS: tuple[type[BaseSettings], ...] = (
    AppSettings,
    DatabaseSettings,
    RedisSettings,
    S3Settings,
    JWTSettings,
)


def _env_keys_for_field(model: type[BaseSettings], field: str) -> list[str]:
    """Noms de variables d'environnement reconnus pour un champ donne.

    Args:
        model: la classe de reglages qui declare le champ.
        field: le nom du champ.

    Returns:
        Les noms en majuscules, par ordre de priorite de lecture.
    """
    alias = model.model_fields[field].validation_alias
    if isinstance(alias, AliasChoices):
        # Un champ a alias porte deja son nom complet : le prefixe ne s'y ajoute
        # pas, `env_prefix_target` valant « variable » par defaut.
        return [choice.upper() for choice in alias.choices if isinstance(choice, str)]
    if isinstance(alias, str):
        return [alias.upper()]
    prefix = str(model.model_config.get("env_prefix", ""))
    return [f"{prefix}{field}".upper()]


def _env_keys(model: type[BaseSettings]) -> set[str]:
    """Toutes les variables d'environnement qu'un sous-modele reconnait.

    Args:
        model: la classe de reglages a inspecter.

    Returns:
        Les noms en majuscules, prefixes appliques, alias compris.
    """
    return {key for field in model.model_fields for key in _env_keys_for_field(model, field)}


# Jeu des cles admises dans le fichier .env, calcule par introspection : ajouter
# un champ a un sous-modele l'etend tout seul, il n'y a aucune liste a tenir a
# jour a la main.
_SECTION_ENV_KEYS = frozenset[str]().union(*(_env_keys(m) for m in _SETTINGS_SECTIONS))


class _OrphanKeyDotEnvSource(DotEnvSettingsSource):
    """Source du fichier .env qui ne laisse remonter que les cles orphelines.

    C'est la piece qui rend le fichier STRICT, et elle merite son explication.

    La source dotenv de pydantic-settings verse dans le dictionnaire de
    validation toute cle du fichier qui ne correspond a aucun champ de la classe
    -- charge a l'`extra` du modele de l'accepter ou non. Sur `Settings`, qui ne
    declare que cinq sous-modeles, cela reviendrait a refuser le fichier entier.
    On retire donc d'abord les cles qu'un sous-modele revendique ; ce qui reste
    n'appartient a personne et tombe sur `extra="forbid"`, avec le nom de la cle
    fautive dans l'erreur.

    Une `COMPOSE_PROJECT_NAME` ou une `PGADMIN_DEFAULT_EMAIL` copiee du .env de la
    racine arrete donc bien le demarrage, comme le promet le gabarit.

    La source des variables du PROCESSUS n'est pas touchee : elle n'ajoute jamais
    d'extra, et c'est ce qui laisse le conteneur d'INFRA-04 en recevoir autant
    qu'il veut.
    """

    def __call__(self) -> dict[str, Any]:
        """Retire du fichier les cles deja prises en charge par un sous-modele."""
        return {
            key: value
            for key, value in super().__call__().items()
            if key.upper() not in _SECTION_ENV_KEYS
        }


class Settings(BaseSettings):
    """Configuration complete du service, assemblee a partir des cinq sous-modeles.

    S'obtient par `get_settings()` -- ne pas instancier directement en dehors des
    tests, sous peine de relire l'environnement a chaque appel.
    """

    # `env_file` est indispensable ici : c'est ce fichier que `_OrphanKeyDotEnvSource`
    # relit pour y traquer les cles orphelines. `extra` reste a « forbid », le
    # defaut, et c'est lui qui refuse ces cles.
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    # `default_factory` et non une valeur par defaut : l'environnement doit etre
    # relu a CHAQUE construction de Settings. Une instance partagee entre tous
    # les objets figerait la configuration a l'import de ce module et rendrait
    # inoperantes les surcharges de test.
    app: AppSettings = Field(default_factory=AppSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Remplace la source du fichier .env par celle qui traque les cles orphelines."""
        return (
            init_settings,
            env_settings,
            _OrphanKeyDotEnvSource(settings_cls),
            file_secret_settings,
        )

    # N804 est un faux positif ici, et il vient de BACK-02 : le pyproject apprend
    # a Ruff que `model_validator` produit des methodes de CLASSE, ce qui n'est
    # vrai qu'en mode « before » ou « wrap ». Un validateur « after » recoit le
    # modele deja construit, donc `self` -- le renommer en `cls` casserait
    # l'acces aux sous-modeles.
    @model_validator(mode="after")
    def _reject_jwt_placeholder_in_production(self) -> Self:  # noqa: N804
        """Interdit de partir en production avec la cle de signature du gabarit.

        Seule regle qui traverse deux sous-modeles, d'ou sa place ici. Elle
        transforme un gabarit recopie sans etre relu -- l'oubli le plus banal
        d'une premiere mise en production -- en refus de demarrage.
        """
        if self.app.is_production and self.jwt.secret_key.get_secret_value() == _JWT_PLACEHOLDER:
            message = (
                "JWT_SECRET_KEY porte encore la valeur du gabarit, qui est un marqueur et "
                "non une cle. En generer une propre : openssl rand -hex 32"
            )
            raise ValueError(message)
        return self


_ALL_SETTINGS_MODELS: tuple[type[BaseSettings], ...] = (*_SETTINGS_SECTIONS, Settings)
_MODELS_BY_NAME: dict[str, type[BaseSettings]] = {
    model.__name__: model for model in _ALL_SETTINGS_MODELS
}

# Traduction des codes d'erreur pydantic les plus frequents. Les autres passent
# avec leur message d'origine, qui reste plus precis qu'une reformulation vague.
_REASONS = {
    "missing": "variable absente",
    "extra_forbidden": "cle inconnue -- aucun champ de Settings ne la reclame",
}


def _variable_name(title: str, location: Iterable[int | str]) -> str:
    """Reconstitue le nom de la variable d'environnement derriere un champ en erreur.

    Args:
        title: le nom de la classe en defaut, tel que pydantic le rapporte.
        location: le `loc` de l'erreur.

    Returns:
        Le nom de la variable en majuscules, prefixe applique. A defaut de champ
        connu -- le cas d'une cle orpheline du fichier .env -- l'emplacement tel
        quel, qui EST deja le nom de la variable.
    """
    field = ".".join(str(part) for part in location)
    model = _MODELS_BY_NAME.get(title)
    if model is None or field not in model.model_fields:
        return field.upper()
    return _env_keys_for_field(model, field)[0]


def _faults(error: ValidationError) -> dict[str, str]:
    """Traduit une erreur de validation en couples « variable : motif ».

    Args:
        error: l'erreur levee par pydantic.

    Returns:
        Un dictionnaire ordonne, indexe par nom de variable -- ce qui dedoublonne
        au passage une meme variable rapportee par deux modeles.
    """
    return {
        # `removeprefix` retire le « Value error, » dont pydantic prefixe les
        # erreurs de validateur : le message qu'on y a ecrit se suffit a lui-meme.
        _variable_name(error.title, detail["loc"]): _REASONS.get(
            detail["type"], detail["msg"].removeprefix("Value error, ")
        )
        for detail in error.errors()
    }


def _explicit_message(error: ValidationError) -> str:
    """Reformule une erreur de validation en termes de variables d'environnement.

    Args:
        error: l'erreur levee au moment de construire `Settings`.

    Returns:
        Un message multiligne nommant chaque variable fautive et le fichier a corriger.
    """
    # `Settings` s'arrete a la PREMIERE fabrique de sous-modele en defaut : une
    # configuration vide ne signalerait que PostgreSQL, puis JWT au lancement
    # suivant, et ainsi de suite. On reinterroge donc les cinq sous-modeles pour
    # tout dire d'un coup. S'ils sont tous sains, la faute est a la racine -- une
    # cle orpheline dans le fichier .env -- et l'erreur d'origine fait foi.
    faults: dict[str, str] = {}
    for model in _SETTINGS_SECTIONS:
        try:
            model()
        except ValidationError as failure:
            faults.update(_faults(failure))

    return "\n".join(
        [
            "Configuration invalide : le service d'API ne peut pas demarrer.",
            "",
            # Une regle qui porte sur le modele entier -- et non sur un champ --
            # n'a pas de variable a nommer : sa seule phrase tient lieu de ligne.
            *(
                f"  - {variable} : {reason}" if variable else f"  - {reason}"
                for variable, reason in (faults or _faults(error)).items()
            ),
            "",
            f"Corriger les variables d'environnement ou {_ENV_FILE}.",
            "Le gabarit .env.example, a cote, documente chaque variable.",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    """Retourne la configuration du service, construite une seule fois.

    Dependance FastAPI : `Depends(get_settings)`, ou l'alias `SettingsDep`
    ci-dessous. Les tests la surchargent par
    `app.dependency_overrides[get_settings] = lambda: settings_de_test`, et
    `get_settings.cache_clear()` remet le cache a zero entre deux cas.

    Returns:
        L'instance unique de `Settings`.

    Raises:
        ConfigurationError: si une variable obligatoire manque, si une valeur est
            invalide, ou si le fichier .env porte une cle qu'aucun champ ne
            reclame.
    """
    try:
        return Settings()
    except ValidationError as error:
        raise ConfigurationError(_explicit_message(error)) from error


# Alias a annoter les parametres de route : `settings: SettingsDep`. Il evite de
# repeter `Annotated[Settings, Depends(get_settings)]` a chaque signature, a
# partir de BACK-08.
SettingsDep = Annotated[Settings, Depends(get_settings)]
