"""Preserve unknown GPS accuracy as NULL without inventing measurements.

Revision ID: 20260929_0009
Revises: 20260929_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20260929_0009"
down_revision = "20260929_0008"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("checkins") as batch:
        batch.alter_column("location_accuracy_meters", existing_type=sa.Float(), nullable=True)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM checkins WHERE location_accuracy_meters IS NULL")):
        raise RuntimeError("Cannot downgrade: check-ins with unknown GPS accuracy exist")
    with op.batch_alter_table("checkins") as batch:
        batch.alter_column("location_accuracy_meters", existing_type=sa.Float(), nullable=False)
