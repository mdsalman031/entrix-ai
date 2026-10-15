"""Create the Entrix AI initial relational schema.

Revision ID: 0001_initial_schema
"""

from alembic import op

from app.database import Base
import app.models  # noqa: F401  Register mapped tables before create_all.

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
