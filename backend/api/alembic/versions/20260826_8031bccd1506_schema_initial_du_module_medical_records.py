"""schema initial du module medical records

Revision ID: 8031bccd1506
Revises: 43316d205ba2
Create Date: 2026-08-26 08:21:20.840011+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identifiants de revision utilises par Alembic.
revision: str = "8031bccd1506"
down_revision: str | Sequence[str] | None = "43316d205ba2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Applique la revision."""
    op.create_table(
        "animals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("species", sa.String(length=20), nullable=False),
        sa.Column("breed", sa.String(length=100), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.String(length=20), nullable=False),
        sa.Column("sterilization", sa.String(length=20), nullable=False),
        sa.Column("microchip_number", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_animals")),
    )
    op.create_table(
        "custodies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("animal_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "end_at IS NULL OR end_at > start_at", name=op.f("ck_custodies_window_bounds")
        ),
        sa.ForeignKeyConstraint(
            ["animal_id"], ["animals.id"], name=op.f("fk_custodies_animal_id_animals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custodies")),
    )
    op.create_index(
        op.f("ix_custodies_account_id_end_at"), "custodies", ["account_id", "end_at"], unique=False
    )
    op.create_index(
        op.f("ix_custodies_animal_id"),
        "custodies",
        ["animal_id"],
        unique=True,
        postgresql_where=sa.text("end_at IS NULL"),
    )
    op.create_index(
        op.f("ix_custodies_animal_id_start_at"),
        "custodies",
        ["animal_id", "start_at"],
        unique=False,
    )


def downgrade() -> None:
    """Annule la revision."""
    op.drop_index(op.f("ix_custodies_animal_id_start_at"), table_name="custodies")
    op.drop_index(
        op.f("ix_custodies_animal_id"),
        table_name="custodies",
        postgresql_where=sa.text("end_at IS NULL"),
    )
    op.drop_index(op.f("ix_custodies_account_id_end_at"), table_name="custodies")
    op.drop_table("custodies")
    op.drop_table("animals")
