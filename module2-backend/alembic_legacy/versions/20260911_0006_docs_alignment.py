"""Align existing fields with documented names and widths, preserving evidence."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0006"
down_revision = "20260911_0005"
branch_labels = None
depends_on = None


def upgrade():
    # Never truncate a legacy fingerprint: remediation is required if one exceeds 64.
    if not op.get_context().as_sql:
        devices = sa.table("devices", sa.column("device_fingerprint", sa.String()))
        if op.get_bind().scalar(sa.select(sa.func.count()).select_from(devices).where(
                sa.func.length(devices.c.device_fingerprint) > 64)):
            raise RuntimeError("Legacy device fingerprints exceed 64 characters; re-register them before migrating")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("face_template_hash", new_column_name="face_embedding_hash", existing_type=sa.String(64))
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("device_fingerprint", existing_type=sa.String(255), type_=sa.String(64), existing_nullable=False)
        batch.alter_column("platform", existing_type=sa.String(20), type_=sa.String(50), existing_nullable=True)
    op.add_column("audit_logs", sa.Column("device_id", sa.String(36), nullable=True))


def downgrade():
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("device_id")
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("device_fingerprint", existing_type=sa.String(64), type_=sa.String(255), existing_nullable=False)
        batch.alter_column("platform", existing_type=sa.String(50), type_=sa.String(20), existing_nullable=True)
    with op.batch_alter_table("users") as batch:
        batch.alter_column("face_embedding_hash", new_column_name="face_template_hash", existing_type=sa.String(64))
