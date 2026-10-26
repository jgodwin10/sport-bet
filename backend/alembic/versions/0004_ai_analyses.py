"""ai analyses

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25 16:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table('ai_analyses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('fixture_id', sa.Integer(), nullable=False),
    sa.Column('prediction_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=60), nullable=True),
    sa.Column('key_slot', sa.Integer(), nullable=True),
    sa.Column('trigger', sa.String(length=30), nullable=False),
    sa.Column('requested_by', sa.String(length=255), nullable=True),
    sa.Column('content', JSONType, nullable=True),
    sa.Column('sources', JSONType, nullable=False),
    sa.Column('search_queries', JSONType, nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['fixture_id'], ['fixtures.id'], ),
    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ai_analyses_fixture_created', 'ai_analyses', ['fixture_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_analyses_fixture_created', table_name='ai_analyses')
    op.drop_table('ai_analyses')
