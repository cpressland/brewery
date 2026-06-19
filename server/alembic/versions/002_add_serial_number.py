"""Replace hostname unique key with serial_number; keep hostname as display field

Revision ID: 002
Revises: 001
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add serial_number as nullable first so we can backfill
    op.add_column("hosts", sa.Column("serial_number", sa.String(), nullable=True))

    # Seed from existing hostname values so the NOT NULL constraint can be applied
    op.execute("UPDATE hosts SET serial_number = hostname")

    op.alter_column("hosts", "serial_number", nullable=False)
    op.create_unique_constraint("uq_hosts_serial_number", "hosts", ["serial_number"])

    # hostname is now a display-only field; drop its unique constraint
    op.drop_constraint("hosts_hostname_key", "hosts", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("hosts_hostname_key", "hosts", ["hostname"])
    op.drop_constraint("uq_hosts_serial_number", "hosts", type_="unique")
    op.drop_column("hosts", "serial_number")
