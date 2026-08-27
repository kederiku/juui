"""schema initial du module scheduling

Revision ID: 839fa5e76553
Revises: cf5643fdf4ce
Create Date: 2026-08-27 13:47:52.939915+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identifiants de revision utilises par Alembic.
revision: str = "839fa5e76553"
down_revision: str | Sequence[str] | None = "cf5643fdf4ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Applique la revision."""
    op.create_table(
        "practitioner_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practitioner_profiles")),
        sa.UniqueConstraint(
            "group_id",
            "clinic_id",
            "account_id",
            name=op.f("uq_practitioner_profiles_group_id_clinic_id_account_id"),
        ),
    )
    op.create_table(
        "practitioner_hours",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_minute", sa.SmallInteger(), nullable=False),
        sa.Column("end_minute", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "end_minute > start_minute", name=op.f("ck_practitioner_hours_range_bounds")
        ),
        sa.CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440",
            name=op.f("ck_practitioner_hours_minute_of_day_range"),
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_practitioner_hours_weekday_python_range")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["practitioner_profiles.id"],
            name=op.f("fk_practitioner_hours_profile_id_practitioner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "profile_id", "weekday", "start_minute", name=op.f("pk_practitioner_hours")
        ),
    )
    op.create_table(
        "practitioner_species",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("species", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["practitioner_profiles.id"],
            name=op.f("fk_practitioner_species_profile_id_practitioner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", "species", name=op.f("pk_practitioner_species")),
    )


def downgrade() -> None:
    """Annule la revision."""
    op.drop_table("practitioner_species")
    op.drop_table("practitioner_hours")
    op.drop_table("practitioner_profiles")
