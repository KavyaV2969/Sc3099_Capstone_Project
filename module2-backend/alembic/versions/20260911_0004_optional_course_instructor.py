"""Make the optional course instructor extension match the revised starter spec."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0004"
down_revision = "20260911_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("courses") as batch:
        batch.alter_column("instructor_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    # Reassignment is needed before downgrading if unassigned courses now exist.
    with op.batch_alter_table("courses") as batch:
        batch.alter_column("instructor_id", existing_type=sa.String(36), nullable=False)
