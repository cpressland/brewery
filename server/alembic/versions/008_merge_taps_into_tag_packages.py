"""merge tag_taps into tag_packages

Revision ID: 008
Revises: 007
Create Date: 2026-06-30
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tag_taps = sa.table(
        "tag_taps",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("tag_id", UUID(as_uuid=True)),
        sa.column("name", sa.String()),
    )
    tag_packages = sa.table(
        "tag_packages",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("tag_id", UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("type", sa.String()),
        sa.column("policy", sa.String()),
    )
    rows = bind.execute(sa.select(tag_taps)).fetchall()
    if rows:
        existing = {
            (str(r.tag_id), r.name)
            for r in bind.execute(
                sa.select(tag_packages).where(tag_packages.c.type == "tap")
            ).fetchall()
        }
        inserts = [
            {"id": uuid.uuid4(), "tag_id": r.tag_id, "name": r.name, "type": "tap", "policy": "required"}
            for r in rows
            if (str(r.tag_id), r.name) not in existing
        ]
        if inserts:
            bind.execute(tag_packages.insert(), inserts)
    op.drop_table("tag_taps")


def downgrade() -> None:
    op.create_table(
        "tag_taps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("tags.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("tag_id", "name"),
    )
    bind = op.get_bind()
    tag_packages = sa.table(
        "tag_packages",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("tag_id", UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("type", sa.String()),
        sa.column("policy", sa.String()),
    )
    tag_taps = sa.table(
        "tag_taps",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("tag_id", UUID(as_uuid=True)),
        sa.column("name", sa.String()),
    )
    rows = bind.execute(
        sa.select(tag_packages).where(tag_packages.c.type == "tap")
    ).fetchall()
    if rows:
        bind.execute(
            tag_taps.insert(),
            [{"id": uuid.uuid4(), "tag_id": r.tag_id, "name": r.name} for r in rows],
        )
    bind.execute(tag_packages.delete().where(tag_packages.c.type == "tap"))
