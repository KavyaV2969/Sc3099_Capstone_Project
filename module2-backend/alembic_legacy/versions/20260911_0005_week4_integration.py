"""Add device binding, face enrollment hash and check-in verification evidence."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0005"
down_revision = "20260911_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("face_template_hash", sa.String(64), nullable=True))
    op.create_table("devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_fingerprint", sa.String(255), nullable=False, unique=True),
        sa.Column("device_name", sa.String(255)), sa.Column("platform", sa.String(20)),
        sa.Column("public_key", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_trusted", sa.Boolean(), nullable=False),
        sa.Column("trust_score", sa.String(20), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("total_checkins", sa.Integer(), nullable=False))
    op.create_index("ix_devices_user_id", "devices", ["user_id"])
    with op.batch_alter_table("checkins") as batch:
        batch.add_column(sa.Column("risk_factors", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("device_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_checkins_device_id", "devices", ["device_id"], ["id"])
        batch.add_column(sa.Column("face_match_passed", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("face_match_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("liveness_passed", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("liveness_score", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("checkins") as batch:
        batch.drop_constraint("fk_checkins_device_id", type_="foreignkey")
        for name in ("liveness_score", "liveness_passed", "face_match_score", "face_match_passed", "device_id", "risk_factors"):
            batch.drop_column(name)
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_table("devices")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("face_template_hash")
