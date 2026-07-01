"""add vulnerabilities

Revision ID: 009
Revises: 008
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vulnerabilities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("package_name", sa.String, nullable=False),
        sa.Column("package_type", sa.String, nullable=False),
        sa.Column("osv_id", sa.String, nullable=False),
        sa.Column("aliases", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("severity", sa.String, nullable=True),
        sa.Column("cvss_score", sa.Float, nullable=True),
        sa.Column("cvss_vector", sa.String, nullable=True),
        sa.Column("published", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint(
        "uq_vulnerabilities_pkg_osv",
        "vulnerabilities",
        ["package_name", "package_type", "osv_id"],
    )


def downgrade() -> None:
    op.drop_table("vulnerabilities")
