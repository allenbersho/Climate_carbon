"""create_methodologies_table

Revision ID: a2057b43cf42
Revises: 258d43d5d8fa
Create Date: 2026-11-14 21:49:14.076972

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2057b43cf42'
down_revision: Union[str, Sequence[str], None] = '258d43d5d8fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create methodologies table with indices and unique constraint."""
    op.create_table(
        "methodologies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_methodology_name_version"),
    )
    op.create_index(op.f("ix_methodologies_id"), "methodologies", ["id"], unique=False)
    op.create_index(op.f("ix_methodologies_name"), "methodologies", ["name"], unique=False)
    op.create_index(op.f("ix_methodologies_version"), "methodologies", ["version"], unique=False)
    op.create_index(op.f("ix_methodologies_is_active"), "methodologies", ["is_active"], unique=False)


def downgrade() -> None:
    """Drop methodologies table."""
    op.drop_index(op.f("ix_methodologies_is_active"), table_name="methodologies")
    op.drop_index(op.f("ix_methodologies_version"), table_name="methodologies")
    op.drop_index(op.f("ix_methodologies_name"), table_name="methodologies")
    op.drop_index(op.f("ix_methodologies_id"), table_name="methodologies")
    op.drop_table("methodologies")
