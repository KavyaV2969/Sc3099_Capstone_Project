"""Activation credentials, device revocation and retained attendance roster.

Revision ID: 20260929_0007
Revises: 20260928_0006
"""
from alembic import op
import sqlalchemy as sa

revision = "20260929_0007"
down_revision = "20260928_0006"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("activation_token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("activation_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint("uq_users_activation_token_hash", ["activation_token_hash"])
    op.add_column("devices", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sessions", sa.Column("attendance_roster", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("sessions", "attendance_roster")
    op.drop_column("devices", "revoked_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_activation_token_hash", type_="unique")
        batch.drop_column("activation_expires_at")
        batch.drop_column("activation_token_hash")
