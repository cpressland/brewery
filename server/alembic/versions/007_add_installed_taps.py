"""add installed_taps table

Revision ID: 007
Revises: 006
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installed_taps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", UUID(as_uuid=True), sa.ForeignKey("hosts.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("host_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("installed_taps")
