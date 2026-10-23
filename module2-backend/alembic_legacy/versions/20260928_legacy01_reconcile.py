"""Reconcile the recovered legacy schema to canonical 20260928_0006.

Only executed by the evidence-gated recovery tool in an outer transaction.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260928_legacy01"
down_revision = "20260911_0007"
branch_labels = None
depends_on = None


def upgrade():
    if not op.get_context().config.attributes.get("verified_recovery"):
        raise RuntimeError("Use python -m scripts.reconcile_database with verified backup evidence")
    with op.batch_alter_table("checkins") as batch:
        for name, datatype in (
            ("verified_at", sa.DateTime(timezone=True)),
            ("reviewed_by_id", sa.String(36)), ("reviewed_at", sa.DateTime(timezone=True)),
            ("review_notes", sa.Text()), ("appeal_reason", sa.Text()),
            ("appealed_at", sa.DateTime(timezone=True)),
            ("scheduled_deletion_at", sa.DateTime(timezone=True)),
        ):
            batch.add_column(sa.Column(name, datatype, nullable=True))
        batch.alter_column("risk_factors", existing_type=sa.Text(), nullable=True, server_default=None)
        batch.drop_constraint("ck_checkins_status", type_="check")
        batch.create_check_constraint("ck_checkins_status", "status IN ('pending', 'approved', 'flagged', 'rejected', 'appealed')")
        batch.drop_constraint("fk_checkins_device_id", type_="foreignkey")
        batch.create_foreign_key("fk_checkins_device", "devices", ["device_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_checkins_reviewer", "users", ["reviewed_by_id"], ["id"])
    op.execute("UPDATE checkins SET scheduled_deletion_at = checked_in_at + INTERVAL '30 days', verified_at = CASE WHEN status = 'approved' THEN checked_in_at ELSE NULL END")
    with op.batch_alter_table("checkins") as batch:
        batch.alter_column("scheduled_deletion_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    for name, columns in (
        ("ix_checkins_student_id", ["student_id"]),
        ("ix_checkins_checked_in_at", ["checked_in_at"]),
        ("ix_checkins_status_checked_in", ["status", "checked_in_at"]),
        ("ix_checkins_risk_score", ["risk_score"]),
        ("ix_checkins_scheduled_deletion_at", ["scheduled_deletion_at"]),
    ):
        op.create_index(name, "checkins", columns)
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("ix_courses_is_active", "courses", ["is_active"])
    with op.batch_alter_table("devices") as batch:
        batch.drop_constraint("devices_device_fingerprint_key", type_="unique")
        batch.create_unique_constraint("uq_devices_fingerprint", ["device_fingerprint"])
        batch.create_check_constraint("ck_devices_trust_score", "trust_score IN ('low', 'medium', 'high')")
        batch.alter_column("is_trusted", existing_type=sa.Boolean(), server_default=sa.false())
        batch.alter_column("is_active", existing_type=sa.Boolean(), server_default=sa.true())
        batch.alter_column("trust_score", existing_type=sa.String(20), server_default="low")
        batch.alter_column("total_checkins", existing_type=sa.Integer(), server_default="0")
    op.create_index("ix_devices_is_active", "devices", ["is_active"])
    op.create_index("ix_devices_is_trusted", "devices", ["is_trusted"])


def downgrade():
    raise RuntimeError("Legacy recovery is forward-only; restore a verified backup into a separate database")
