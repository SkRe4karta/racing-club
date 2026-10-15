"""Frozen v1.1 schema for clean installations."""
from alembic import op
import sqlalchemy as sa

revision = '0001_v11_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('competitions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('event_time', sa.Time(), nullable=False),
    sa.Column('location', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jockeys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=150), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=True),
    sa.Column('age', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('owners',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=150), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('horses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nickname', sa.String(length=100), nullable=False),
    sa.Column('gender', sa.String(length=20), nullable=False),
    sa.Column('age', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['owners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('competition_id', sa.Integer(), nullable=False),
    sa.Column('horse_id', sa.Integer(), nullable=False),
    sa.Column('jockey_id', sa.Integer(), nullable=False),
    sa.Column('finish_time_seconds', sa.Float(), nullable=True),
    sa.Column('is_disqualified', sa.Boolean(), nullable=False),
    sa.Column('place', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ),
    sa.ForeignKeyConstraint(['horse_id'], ['horses.id'], ),
    sa.ForeignKeyConstraint(['jockey_id'], ['jockeys.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('competition_id', 'horse_id', name='uq_competition_horse'),
    sa.UniqueConstraint('competition_id', 'jockey_id', name='uq_competition_jockey')
    )


def downgrade():
    raise RuntimeError("Destructive downgrade is disabled. Restore a verified backup instead.")
