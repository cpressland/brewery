"""add vulnerability ignore fields

Revision ID: 010
Revises: 009
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vulnerabilities", sa.Column("ignored", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("vulnerabilities", sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("vulnerabilities", sa.Column("ignored_reason", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("vulnerabilities", "ignored_reason")
    op.drop_column("vulnerabilities", "ignored_at")
    op.drop_column("vulnerabilities", "ignored")
