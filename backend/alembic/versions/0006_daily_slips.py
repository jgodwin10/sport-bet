"""daily slips

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade() -> None:
    op.create_table('daily_slips',
    sa.Column('slip_date', sa.Date(), nullable=False),
    sa.Column('legs', JSON_TYPE, nullable=False),
    sa.Column('combined_odds', sa.Float(), nullable=True),
    sa.Column('combined_probability', sa.Float(), nullable=True),
    sa.Column('analysed', sa.Integer(), nullable=False),
    sa.Column('spare', sa.Integer(), nullable=False),
    sa.Column('rejected', JSON_TYPE, nullable=False),
    sa.Column('changes', JSON_TYPE, nullable=False),
    sa.Column('first_built_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('slip_date')
    )


def downgrade() -> None:
    op.drop_table('daily_slips')
