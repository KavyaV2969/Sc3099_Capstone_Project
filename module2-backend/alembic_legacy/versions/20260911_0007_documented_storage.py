"""Store risk JSON in TEXT and initialize required device last-seen timestamps."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0007"
down_revision = "20260911_0006"
branch_labels = None
depends_on = None


def upgrade():
    devices = sa.table("devices", sa.column("last_seen_at", sa.DateTime()), sa.column("first_seen_at", sa.DateTime()))
    op.execute(devices.update().where(devices.c.last_seen_at.is_(None)).values(last_seen_at=devices.c.first_seen_at))
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("last_seen_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    with op.batch_alter_table("checkins") as batch:
        batch.alter_column("risk_factors", server_default=None)
        batch.alter_column("risk_factors", existing_type=sa.JSON(), type_=sa.Text(), existing_nullable=False,
                           postgresql_using="risk_factors::text")
        batch.alter_column("risk_factors", server_default="[]")


def downgrade():
    with op.batch_alter_table("checkins") as batch:
        batch.alter_column("risk_factors", server_default=None)
        batch.alter_column("risk_factors", existing_type=sa.Text(), type_=sa.JSON(), existing_nullable=False,
                           postgresql_using="risk_factors::json")
        batch.alter_column("risk_factors", server_default="[]")
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("last_seen_at", existing_type=sa.DateTime(timezone=True), nullable=True)
