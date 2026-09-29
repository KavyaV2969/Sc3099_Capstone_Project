"""Align implemented device fields with documented storage, preserving data.

Revision ID: 20260928_0006
Revises: 20260915_0005
"""
from alembic import op
import sqlalchemy as sa

revision = "20260928_0006"
down_revision = "20260915_0005"
branch_labels = None
depends_on = None


def upgrade():
    if not op.get_context().as_sql:
        connection = op.get_bind()
        oversized = connection.scalar(sa.text("SELECT count(*) FROM devices WHERE length(device_fingerprint) > 64"))
        duplicates = connection.scalar(sa.text("SELECT count(*) FROM (SELECT device_fingerprint FROM devices GROUP BY device_fingerprint HAVING count(*) > 1) d"))
        if oversized or duplicates:
            raise RuntimeError(f"Device migration refused: {oversized} overlength fingerprints, {duplicates} duplicate fingerprints; resolve without truncation or deletion")
    op.execute("UPDATE devices SET last_seen_at = first_seen_at WHERE last_seen_at IS NULL")
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("device_fingerprint", existing_type=sa.String(255), type_=sa.String(64), existing_nullable=False)
        batch.alter_column("device_name", existing_type=sa.String(255), nullable=True)
        batch.alter_column("platform", existing_type=sa.String(30), type_=sa.String(50), nullable=True)
        batch.alter_column("trust_score", existing_type=sa.String(10), type_=sa.String(20), existing_nullable=False)
        batch.alter_column("last_seen_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.drop_constraint("uq_devices_user_fingerprint", type_="unique")
        batch.create_unique_constraint("uq_devices_fingerprint", ["device_fingerprint"])
    op.drop_index("ix_devices_user_active", table_name="devices")
    op.create_index("ix_devices_user_id", "devices", ["user_id"])
    op.create_index("ix_devices_is_active", "devices", ["is_active"])
    op.create_index("ix_devices_is_trusted", "devices", ["is_trusted"])


def downgrade():
    # Refuse before any DDL if newer nullable values cannot fit the old contract.
    if not op.get_context().as_sql:
        invalid = op.get_bind().scalar(sa.text("SELECT count(*) FROM devices WHERE device_name IS NULL OR platform IS NULL OR length(platform) > 30"))
        if invalid:
            raise RuntimeError("Unsafe device downgrade: nullable/overlength values cannot fit the old schema; use a verified backup")
    op.drop_index("ix_devices_is_trusted", table_name="devices")
    op.drop_index("ix_devices_is_active", table_name="devices")
    op.drop_index("ix_devices_user_id", table_name="devices")
    with op.batch_alter_table("devices") as batch:
        batch.drop_constraint("uq_devices_fingerprint", type_="unique")
        batch.create_unique_constraint("uq_devices_user_fingerprint", ["user_id", "device_fingerprint"])
        batch.alter_column("device_fingerprint", existing_type=sa.String(64), type_=sa.String(255), existing_nullable=False)
        batch.alter_column("device_name", existing_type=sa.String(255), nullable=False)
        batch.alter_column("platform", existing_type=sa.String(50), type_=sa.String(30), nullable=False)
        batch.alter_column("trust_score", existing_type=sa.String(20), type_=sa.String(10), existing_nullable=False)
        batch.alter_column("last_seen_at", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.create_index("ix_devices_user_active", "devices", ["user_id", "is_active"])
