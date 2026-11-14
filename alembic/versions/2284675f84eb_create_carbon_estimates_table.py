"""create_carbon_estimates_table

Revision ID: 2284675f84eb
Revises: a2057b43cf42
Create Date: 2026-11-14 22:19:14.919797

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2284675f84eb'
down_revision: Union[str, Sequence[str], None] = 'a2057b43cf42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create carbon_estimates table with foreign keys and indices."""
    op.create_table(
        "carbon_estimates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enrollment_id", sa.Integer(), nullable=False),
        sa.Column("methodology_id", sa.Integer(), nullable=False),
        sa.Column("methodology_version", sa.String(length=20), nullable=False),
        sa.Column("inputs_snapshot", sa.JSON(), nullable=False),
        sa.Column("co2e_tonnes", sa.Float(), nullable=False),
        sa.Column("uncertainty_pct", sa.Float(), nullable=False),
        sa.Column("buffer_pct", sa.Float(), nullable=False),
        sa.Column("net_credits", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "verified", "issued", name="estimate_status"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["methodology_id"], ["methodologies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_carbon_estimates_id"), "carbon_estimates", ["id"], unique=False)
    op.create_index(op.f("ix_carbon_estimates_enrollment_id"), "carbon_estimates", ["enrollment_id"], unique=False)
    op.create_index(op.f("ix_carbon_estimates_methodology_id"), "carbon_estimates", ["methodology_id"], unique=False)
    op.create_index(op.f("ix_carbon_estimates_methodology_version"), "carbon_estimates", ["methodology_version"], unique=False)
    op.create_index(op.f("ix_carbon_estimates_status"), "carbon_estimates", ["status"], unique=False)
    op.create_index(op.f("ix_carbon_estimates_computed_at"), "carbon_estimates", ["computed_at"], unique=False)


def downgrade() -> None:
    """Drop carbon_estimates table and enum."""
    op.drop_index(op.f("ix_carbon_estimates_computed_at"), table_name="carbon_estimates")
    op.drop_index(op.f("ix_carbon_estimates_status"), table_name="carbon_estimates")
    op.drop_index(op.f("ix_carbon_estimates_methodology_version"), table_name="carbon_estimates")
    op.drop_index(op.f("ix_carbon_estimates_methodology_id"), table_name="carbon_estimates")
    op.drop_index(op.f("ix_carbon_estimates_enrollment_id"), table_name="carbon_estimates")
    op.drop_index(op.f("ix_carbon_estimates_id"), table_name="carbon_estimates")
    op.drop_table("carbon_estimates")
    op.execute("DROP TYPE IF EXISTS estimate_status")
