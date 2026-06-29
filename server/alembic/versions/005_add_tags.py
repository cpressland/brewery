"""add tags tables

Revision ID: 005
Revises: 004
Create Date: 2026-06-23

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "host_tags",
        sa.Column("host_id", UUID(as_uuid=True), sa.ForeignKey("hosts.id"), nullable=False),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("tags.id"), nullable=False),
        sa.PrimaryKeyConstraint("host_id", "tag_id"),
    )
    op.create_table(
        "tag_packages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("tags.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("policy", sa.String(), nullable=False),
        sa.UniqueConstraint("tag_id", "name", "type"),
    )


def downgrade() -> None:
    op.drop_table("tag_packages")
    op.drop_table("host_tags")
    op.drop_table("tags")
