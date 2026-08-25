"""schema initial du module organization

Revision ID: 43316d205ba2
Revises: 41e48e9250af
Create Date: 2026-08-25 21:07:24.454567+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Identifiants de revision utilises par Alembic.
revision: str = "43316d205ba2"
down_revision: str | Sequence[str] | None = "41e48e9250af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Applique la revision."""
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
    )
    op.create_table(
        "clinics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_clinics_group_id_groups")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinics")),
        sa.UniqueConstraint("id", "group_id", name=op.f("uq_clinics_id_group_id")),
    )
    op.create_index(op.f("ix_clinics_group_id_name"), "clinics", ["group_id", "name"], unique=False)
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
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
            "end_at IS NULL OR end_at > start_at", name=op.f("ck_memberships_window_bounds")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_memberships_group_id_groups")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
    )
    op.create_index(
        op.f("ix_memberships_account_id_group_id"),
        "memberships",
        ["account_id", "group_id"],
        unique=False,
    )
    op.create_table(
        "assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
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
            "end_at IS NULL OR end_at > start_at", name=op.f("ck_assignments_window_bounds")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "group_id"],
            ["clinics.id", "clinics.group_id"],
            name=op.f("fk_assignments_clinic_id_group_id_clinics"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignments")),
    )
    op.create_index(
        op.f("ix_assignments_group_id_account_id"),
        "assignments",
        ["group_id", "account_id"],
        unique=False,
    )


def downgrade() -> None:
    """Annule la revision."""
    op.drop_index(op.f("ix_assignments_group_id_account_id"), table_name="assignments")
    op.drop_table("assignments")
    op.drop_index(op.f("ix_memberships_account_id_group_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_clinics_group_id_name"), table_name="clinics")
    op.drop_table("clinics")
    op.drop_table("groups")
