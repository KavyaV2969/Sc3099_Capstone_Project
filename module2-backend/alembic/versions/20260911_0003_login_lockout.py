"""Persist consecutive password failures for account-level lockout."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0003"
down_revision = "20260908_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "failed_login_attempts")
