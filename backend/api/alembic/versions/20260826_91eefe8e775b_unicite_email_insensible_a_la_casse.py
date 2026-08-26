"""unicite email insensible a la casse

Revision ID: 91eefe8e775b
Revises: 8031bccd1506
Create Date: 2026-08-26 09:13:04.506335+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identifiants de revision utilises par Alembic.
revision: str = "91eefe8e775b"
down_revision: str | Sequence[str] | None = "8031bccd1506"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Applique la revision."""
    # Ramene les lignes existantes a la forme canonique du domaine avant de
    # poser l'index. Deux lignes qui ne different que par la casse feraient
    # echouer la migration -- volontaire : un tel etat est impossible via le
    # domaine, et une base de developpement s'assainit par `make db-reset`.
    # Le DDL etant transactionnel, l'echec annule tout proprement.
    op.execute("UPDATE accounts SET email = lower(btrim(email)) WHERE email <> lower(btrim(email))")
    # L'index fonctionnel subsume l'unicite exacte de `ix_accounts_email` :
    # on remplace, on n'empile pas. Nom explicite, seule entorse a `op.f()` --
    # la convention de nommage ne sait pas nommer une expression (INFRA-09,
    # ADR-0016).
    op.drop_index(op.f("ix_accounts_email"), table_name="accounts")
    op.create_index(
        "ix_accounts_email_lower", "accounts", [sa.literal_column("lower(email)")], unique=True
    )


def downgrade() -> None:
    """Annule la revision."""
    # La normalisation de l'upgrade n'est pas reversible : on retablit l'index
    # d'origine, pas les casses perdues.
    op.drop_index("ix_accounts_email_lower", table_name="accounts")
    op.create_index(op.f("ix_accounts_email"), "accounts", ["email"], unique=True)
