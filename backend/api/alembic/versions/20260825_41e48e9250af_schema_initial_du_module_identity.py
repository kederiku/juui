"""schema initial du module identity

Revision ID: 41e48e9250af
Revises:
Create Date: 2026-08-25 13:54:30.430204+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identifiants de revision utilises par Alembic.
revision: str = "41e48e9250af"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Applique la revision."""
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
    )
    op.create_index(op.f("ix_accounts_email"), "accounts", ["email"], unique=True)


def downgrade() -> None:
    """Annule la revision."""
    op.drop_index(op.f("ix_accounts_email"), table_name="accounts")
    op.drop_table("accounts")
