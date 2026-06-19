"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hostname", sa.String(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hostname"),
    )
    op.create_table(
        "packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host_id", "name", "type"),
    )
    op.create_index("ix_packages_host_id", "packages", ["host_id"])
    op.create_index("ix_packages_name", "packages", ["name"])


def downgrade() -> None:
    op.drop_index("ix_packages_name", table_name="packages")
    op.drop_index("ix_packages_host_id", table_name="packages")
    op.drop_table("packages")
    op.drop_table("hosts")
