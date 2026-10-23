"""Store risk_signals per check-in factor; record enrollment drops (recommended schema).

Revision ID: 20261013_0010
Revises: 20260929_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0010"
down_revision = "20260929_0009"
branch_labels = depends_on = None


def upgrade():
    op.add_column("enrollments", sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("risk_signals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("checkin_id", sa.String(length=36), nullable=False),
        sa.Column("signal_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_risk_signals_severity"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_risk_signals_confidence"),
        sa.CheckConstraint("weight >= 0", name="ck_risk_signals_weight"),
        sa.ForeignKeyConstraint(["checkin_id"], ["checkins.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, column in (("ix_risk_signals_checkin_id", "checkin_id"), ("ix_risk_signals_signal_type", "signal_type"),
                         ("ix_risk_signals_severity", "severity"), ("ix_risk_signals_detected_at", "detected_at")):
        op.create_index(name, "risk_signals", [column], unique=False)


def downgrade():
    op.drop_table("risk_signals")
    op.drop_column("enrollments", "dropped_at")
