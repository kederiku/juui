"""Convention de nommage des cles de cache (BACK-14).

C'est ici, et NULLE PART AILLEURS, qu'une cle logique devient une cle physique :

    {environnement}:g-{group_id}:{cle logique}     -- CacheScope.TENANT
    {environnement}:shared:{cle logique}           -- CacheScope.SHARED

POURQUOI CETTE COMPOSITION VIT DANS L'INFRASTRUCTURE
Elle a besoin de deux choses que le domaine ne peut pas atteindre : la
configuration -- le contrat `domain-purity` lui interdit `app.core`, meme
indirectement -- et le contexte de tenance. Le port expose donc des cles
LOGIQUES, et l'adaptateur les prefixe. L'appelant ne peut pas oublier le groupe :
ce n'est pas son travail.

CE QUE LE SEGMENT DE GROUPE EMPECHE
Un veterinaire remplacant qui bascule de structure change de segment de cle. Sans
lui, il relirait les donnees mises en cache par la structure precedente -- sur
des donnees medicales entre groupes distincts, c'est une fuite et non un defaut
d'affichage. Le corollaire vaut pour l'invalidation : un motif, si large
soit-il, reste enferme dans son perimetre, et une purge inter-groupes n'est pas
exprimable.

POURQUOI `shared` EST ECRIT PLUTOT QU'OMIS
Une entree non tenant porte un segment `shared` EXPLICITE. Si l'absence de groupe
se traduisait par l'absence de segment, un oubli de perimetre produirait une cle
d'apparence normale ; avec un segment ecrit, il produit une cle visiblement
partagee.
"""

from dataclasses import dataclass
from typing import Literal, assert_never

from app.core import Settings
from app.shared.domain.ports.cache import CacheScope
from app.shared.infrastructure.tenancy import require_current_group_id

# Separateur de segments. Deux-points est la convention de fait de l'ecosysteme
# Redis : les consoles d'inspection s'en servent pour presenter les cles en
# arborescence.
_SEPARATOR = ":"


@dataclass(frozen=True, slots=True)
class CacheKeyBuilder:
    """Compose les cles physiques d'un environnement donne.

    Gelee : l'environnement est fixe pour la duree du processus, et une instance
    partagee par tout un service n'a aucune raison d'etre mutable.
    """

    environment: str

    def key(self, logical_key: str, scope: CacheScope) -> str:
        """Compose la cle physique d'une entree.

        Args:
            logical_key: la cle telle que l'appelant l'a ecrite.
            scope: le perimetre de l'entree.

        Returns:
            La cle physique, prefixee de l'environnement et du perimetre.

        Raises:
            ValueError: si la cle logique est vide.
            MissingTenantContextError: si le perimetre est `TENANT` et qu'aucun
                groupe n'est actif.
        """
        return self._compose(logical_key, scope, label="cle")

    def pattern(self, logical_pattern: str, scope: CacheScope) -> str:
        """Compose le motif physique d'une invalidation.

        Args:
            logical_pattern: le motif tel que l'appelant l'a ecrit.
            scope: le perimetre a purger.

        Returns:
            Le motif physique, enferme dans son perimetre.

        Raises:
            ValueError: si le motif est vide.
            MissingTenantContextError: si le perimetre est `TENANT` et qu'aucun
                groupe n'est actif.
        """
        return self._compose(logical_pattern, scope, label="motif")

    def _compose(self, value: str, scope: CacheScope, *, label: str) -> str:
        """Assemble environnement, perimetre et valeur, apres controle."""
        if not value:
            message = f"Un {label} de cache ne peut pas etre vide."
            raise ValueError(message)
        return _SEPARATOR.join((self.environment, self._scope_segment(scope), value))

    def _scope_segment(self, scope: CacheScope) -> str:
        """Rend le segment de perimetre : `g-{group_id}`, ou `shared`.

        Seul endroit du service qui compose un segment de tenance -- et seul
        endroit, par consequent, ou une erreur de cloisonnement pourrait naitre.
        """
        match scope:
            case CacheScope.TENANT:
                return f"g-{require_current_group_id()}"
            case CacheScope.SHARED:
                return "shared"
            case _:
                assert_never(scope)


def build_key_builder(settings: Settings) -> CacheKeyBuilder:
    """Construit le compositeur de cles du processus.

    Args:
        settings: la configuration du service, dont l'environnement.

    Returns:
        Le compositeur, a partager pour toute la duree du processus.
    """
    return CacheKeyBuilder(environment=_environment_slug(settings.app.environment))


def _environment_slug(environment: Literal["development", "staging", "production"]) -> str:
    """Abrege l'environnement en premier segment de cle.

    `development` devient `dev` et `production` devient `prod` : c'est la
    promesse que les deux `.env.example` publient au-dessus d'`ENVIRONMENT`
    depuis SETUP-05, et cette fonction est ce qui la tient.

    Un `match` exhaustif plutot qu'un dictionnaire : le jour ou un quatrieme
    environnement s'ajoute au `Literal` de `AppSettings`, `assert_never` fait
    ECHOUER MYPY ici. Un `dict.get()` aurait rendu `None`, et le service aurait
    produit des cles « None:shared:… » en silence.

    Args:
        environment: l'environnement declare par la configuration.

    Returns:
        Le segment correspondant.
    """
    match environment:
        case "development":
            return "dev"
        case "staging":
            return "staging"
        case "production":
            return "prod"
        case _:
            assert_never(environment)
