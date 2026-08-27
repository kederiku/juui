"""Fixtures des tests de securite : les vraies tables du module organization.

RE-EXPORT ET NON COPIE. La fixture est celle de `tests/modules/organization/`,
importee telle quelle plutot que redefinie : une seconde fixture creerait et
DETRUIRAIT les memes tables sur sa propre duree de vie, si bien que la premiere
suite terminee emporterait les tables de l'autre. Un seul objet de fixture, un
seul cycle -- pytest la partage entre les deux repertoires.

Le jour ou BACK-12 appliquera les migrations a la base de test, ce fichier
disparait avec celui qu'il importe.
"""

from tests.modules.organization.conftest import _organization_tables

__all__ = ["_organization_tables"]
