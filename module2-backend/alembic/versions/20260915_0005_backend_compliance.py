"""Add device, verification, appeal, review, and retention support.

Revision ID: 20260915_0005
Revises: 20260911_0004
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260915_0005"
down_revision: str | None = "20260911_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("face_embedding_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("device_id", sa.String(36), nullable=True))
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("ix_courses_is_active", "courses", ["is_active"])

    op.create_table(
        "devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_fingerprint", sa.String(255), nullable=False),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=True),
        sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trust_score", sa.String(10), nullable=False, server_default="low"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_checkins", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("trust_score IN ('low', 'medium', 'high')", name="ck_devices_trust_score"),
        sa.UniqueConstraint("user_id", "device_fingerprint", name="uq_devices_user_fingerprint"),
    )
    op.create_index("ix_devices_user_active", "devices", ["user_id", "is_active"])

    with op.batch_alter_table("checkins") as batch:
        batch.drop_constraint("ck_checkins_status", type_="check")
        batch.create_check_constraint(
            "ck_checkins_status",
            "status IN ('pending', 'approved', 'flagged', 'rejected', 'appealed')",
        )
        batch.add_column(sa.Column("device_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("risk_factors", sa.Text(), nullable=True))
        batch.add_column(sa.Column("liveness_passed", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("liveness_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("face_match_passed", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("face_match_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("reviewed_by_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("review_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("appeal_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("appealed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("scheduled_deletion_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_checkins_device", "devices", ["device_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_checkins_reviewer", "users", ["reviewed_by_id"], ["id"])

    if op.get_bind().dialect.name == "sqlite":
        op.execute("UPDATE checkins SET scheduled_deletion_at = datetime(checked_in_at, '+30 days'), verified_at = CASE WHEN status = 'approved' THEN checked_in_at ELSE NULL END")
    else:
        op.execute("UPDATE checkins SET scheduled_deletion_at = checked_in_at + INTERVAL '30 days', verified_at = CASE WHEN status = 'approved' THEN checked_in_at ELSE NULL END")
    with op.batch_alter_table("checkins") as batch:
        batch.alter_column("scheduled_deletion_at", nullable=False)
    op.create_index("ix_checkins_student_id", "checkins", ["student_id"])
    op.create_index("ix_checkins_checked_in_at", "checkins", ["checked_in_at"])
    op.create_index("ix_checkins_status_checked_in", "checkins", ["status", "checked_in_at"])
    op.create_index("ix_checkins_risk_score", "checkins", ["risk_score"])
    op.create_index("ix_checkins_scheduled_deletion_at", "checkins", ["scheduled_deletion_at"])


def downgrade() -> None:
    op.drop_index("ix_checkins_scheduled_deletion_at", table_name="checkins")
    op.drop_index("ix_checkins_risk_score", table_name="checkins")
    op.drop_index("ix_checkins_status_checked_in", table_name="checkins")
    op.drop_index("ix_checkins_checked_in_at", table_name="checkins")
    op.drop_index("ix_checkins_student_id", table_name="checkins")
    with op.batch_alter_table("checkins") as batch:
        batch.drop_constraint("fk_checkins_reviewer", type_="foreignkey")
        batch.drop_constraint("fk_checkins_device", type_="foreignkey")
        for column in (
            "scheduled_deletion_at", "appealed_at", "appeal_reason", "review_notes",
            "reviewed_at", "reviewed_by_id", "face_match_score", "face_match_passed",
            "liveness_score", "liveness_passed", "risk_factors", "verified_at", "device_id",
        ):
            batch.drop_column(column)
        batch.drop_constraint("ck_checkins_status", type_="check")
        batch.create_check_constraint(
            "ck_checkins_status", "status IN ('pending', 'approved', 'flagged', 'rejected')"
        )
    op.drop_index("ix_devices_user_active", table_name="devices")
    op.drop_table("devices")
    op.drop_index("ix_courses_is_active", table_name="courses")
    op.drop_index("ix_audit_logs_resource", table_name="audit_logs")
    op.drop_column("audit_logs", "device_id")
    op.drop_column("users", "face_embedding_hash")
