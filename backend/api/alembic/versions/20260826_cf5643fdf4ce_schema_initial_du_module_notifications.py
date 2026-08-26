"""schema initial du module notifications

Revision ID: cf5643fdf4ce
Revises: 91eefe8e775b
Create Date: 2026-08-26 14:35:29.195422+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Identifiants de revision utilises par Alembic.
revision: str = "cf5643fdf4ce"
down_revision: str | Sequence[str] | None = "91eefe8e775b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Applique la revision."""
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("channels_by_event", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint("account_id", name=op.f("uq_notification_preferences_account_id")),
    )


def downgrade() -> None:
    """Annule la revision."""
    op.drop_table("notification_preferences")
