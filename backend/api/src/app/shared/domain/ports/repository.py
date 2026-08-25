"""Protocole generique des depots -- le vocabulaire commun (BACK-06a).

Ce module decrit ce que TOUTE implementation generique de depot sait faire :
cinq operations, exprimees en entites du domaine. Le depot SQLAlchemy de
BACK-06a les fournit, la doublure en memoire de BACK-06c les fournira, et le
test de conformite commun des deux s'ecrira contre ce protocole. C'est aussi
l'appui des machineries transverses : le filtre de tenance (BACK-06b) raisonne
sur ce vocabulaire, la pagination (BACK-24) fera de meme -- jamais sur un depot
particulier.

UN PROTOCOLE STRUCTUREL, PAS UN PORT A HERITER
Les ports metier des modules -- `AccountRepository` en tete -- ne descendent
PAS d'ici, et c'est le point : en heriter ferait entrer `list` et `delete`
dans leur contrat, alors que chaque port n'expose que ce que ses cas d'usage
ont le droit de faire. Le port metier RETRECIT la surface ; ce protocole decrit
la surface complete que l'infrastructure generique fournit. Une meme classe
concrete satisfait les deux sans conflit.

LES ARGUMENTS SONT POSITIONNELS, ET C'EST UNE GARANTIE
Chaque port metier garde son vocabulaire (`account_id` chez identity, un autre
nom ailleurs) quand l'implementation generique parle d'`entity_id`. Mypy ne
compare pas les noms de parametres positionnels d'un heritage a l'autre : un
appel par mot-cle traverserait le typage et casserait a l'execution. Le `/`
ferme ce trou en interdisant le mot-cle des deux cotes.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class Identified(Protocol):
    """Ce que le depot exige d'une entite : une identite, rien d'autre.

    Une PROPRIETE en lecture seule et non un attribut : le protocole n'exige
    ainsi qu'une LECTURE -- un champ de dataclass, une propriete calculee ou un
    attribut nu le satisfont tous -- et surtout il n'autorise personne a ecrire
    l'identifiant a travers lui. Telle quelle, une entite du domaine
    (`Account`) le satisfait sans rien declarer.

    Le type est fixe a `UUID` a dessein : `UUIDPrimaryKey` (BACK-05) fait de
    l'identifiant UUIDv7 battu par le domaine LA convention du socle, et un
    parametre de type sans second cas reel serait de la generalite speculative.
    """

    @property
    def id(self) -> UUID:
        """L'identifiant de l'entite, attribue par le domaine a la creation."""
        ...


class Repository[EntityT: Identified](Protocol):
    """Depot generique : les cinq operations que toute implementation fournit.

    Toutes echangent des ENTITES DU DOMAINE -- jamais un modele de persistance,
    jamais un dictionnaire. La ou l'absence est une erreur (`get`, `save`,
    `delete`), l'implementation leve l'exception d'absence du module concret
    (`AccountNotFoundError` chez identity) : ce protocole ne peut pas la
    nommer, il n'en connait aucune -- chaque classe concrete declare la sienne.

    AUCUNE OPERATION NE VALIDE LA TRANSACTION. Ecrire, c'est inscrire dans le
    bloc courant -- et une entite ajoutee est aussitot VISIBLE du reste de son
    bloc, pour `get`, `save`, `delete` comme pour les requetes du module.
    Decider que le bloc tient, c'est `commit()` sur l'unite de travail, et
    rien d'autre.
    """

    async def get(self, entity_id: UUID, /) -> EntityT:
        """Retourne l'entite portant cet identifiant.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            L'entite reconstituee.

        Raises:
            DomainError: l'erreur d'absence du module concret, si aucune entite
                ne porte cet identifiant.
        """
        ...

    async def list(self) -> Sequence[EntityT]:
        """Retourne toutes les entites, dans leur ordre de creation.

        SANS BORNE, ET C'EST ASSUME : la pagination -- parametres, enveloppe,
        maximum impose -- est une convention de BACK-24, pas un choix a figer
        ici en douce.

        Returns:
            Les entites, de la plus ancienne a la plus recente.
        """
        ...

    async def add(self, entity: EntityT, /) -> None:
        """Enregistre une entite qui n'existait pas.

        L'ecriture est aussitot visible du reste du bloc -- la relire, la
        modifier ou la supprimer avant le commit fonctionne -- mais rien n'est
        valide : seule l'unite de travail decide que le bloc tient. C'est
        aussi ici que les contraintes du stockage se manifestent, depuis
        l'ecriture qui les viole.

        Args:
            entity: l'entite a creer.
        """
        ...

    async def save(self, entity: EntityT, /) -> None:
        """Reporte sur la persistance l'etat d'une entite deja connue.

        Args:
            entity: l'entite modifiee.

        Raises:
            DomainError: l'erreur d'absence du module concret, si l'entite
                n'a jamais ete enregistree.
        """
        ...

    async def delete(self, entity_id: UUID, /) -> None:
        """Supprime l'entite portant cet identifiant.

        L'absence LEVE plutot que de rendre un booleen : on supprime par un
        identifiant qu'on tient d'un jeton ou d'une URL, et un second appel
        signale un rejeu -- meme doctrine que `get`. Le booleen de
        `Cache.delete` et `FileStorage.delete` porte une autre semantique,
        celle d'un stockage idempotent.

        Args:
            entity_id: l'identifiant de l'entite a supprimer.

        Raises:
            DomainError: l'erreur d'absence du module concret, si aucune entite
                ne porte cet identifiant.
        """
        ...
