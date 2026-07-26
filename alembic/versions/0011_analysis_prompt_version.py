"""analyses.prompt_version (prompt versioning)

Revision ID: 0011_analysis_prompt_version
Revises: 0010_ticket_status
Create Date: 2026-07-10

Adds the nullable ``prompt_version`` column recording which prompt version
produced each analysis (M5.1). Additive/back-compatible — existing rows keep
NULL, like the ``model`` column.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_analysis_prompt_version"
down_revision: str | None = "0010_ticket_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("prompt_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "prompt_version")
