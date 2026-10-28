"""Which model wrote each answer: a stand-in for an unavailable one, or a
stronger one asked again after the first answer failed the checks.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("model", sa.String(128)))
        batch.add_column(sa.Column("escalated", sa.Boolean()))
        batch.add_column(sa.Column("fallback", sa.Boolean()))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("fallback")
        batch.drop_column("escalated")
        batch.drop_column("model")
