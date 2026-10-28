"""top pick entries

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('top_pick_entries',
    sa.Column('fixture_id', sa.Integer(), nullable=False),
    sa.Column('selection_id', sa.Integer(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('best_rank', sa.Integer(), nullable=False),
    sa.Column('tier', sa.String(length=20), nullable=False),
    sa.Column('in_list', sa.Boolean(), nullable=False),
    sa.Column('first_listed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_listed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['fixture_id'], ['fixtures.id'], ),
    sa.ForeignKeyConstraint(['selection_id'], ['selections.id'], ),
    sa.PrimaryKeyConstraint('fixture_id')
    )


def downgrade() -> None:
    op.drop_table('top_pick_entries')
