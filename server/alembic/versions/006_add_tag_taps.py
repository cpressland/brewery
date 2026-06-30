"""add tag_taps table

Revision ID: 006
Revises: 005
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tag_taps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("tags.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("tag_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("tag_taps")
