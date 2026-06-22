"""add commands table

Revision ID: 004
Revises: 003
Create Date: 2026-06-22

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", UUID(as_uuid=True), sa.ForeignKey("hosts.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("package_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("commands")
