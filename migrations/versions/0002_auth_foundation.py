"""Add accounts and shared authentication throttles; preserve v1.1 tables."""
from alembic import op
import sqlalchemy as sa

revision = '0002_auth_foundation'
down_revision = '0001_v11_baseline'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_throttles',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('window_started', sa.BigInteger(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.CheckConstraint('attempts > 0', name='ck_auth_throttles_attempts'),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=512), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('registered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('jockey_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("(role = 'OWNER' AND owner_id IS NOT NULL AND jockey_id IS NULL) OR (role = 'JOCKEY' AND jockey_id IS NOT NULL AND owner_id IS NULL) OR (role IN ('ROOT', 'ADMIN', 'VIEWER') AND owner_id IS NULL AND jockey_id IS NULL)", name='ck_users_profile_role'),
    sa.CheckConstraint("role IN ('ROOT', 'ADMIN', 'OWNER', 'JOCKEY', 'VIEWER')", name='ck_users_role'),
    sa.CheckConstraint("status IN ('active', 'disabled')", name='ck_users_status'),
    sa.CheckConstraint('email = lower(email)', name='ck_users_email_normalized'),
    sa.ForeignKeyConstraint(['jockey_id'], ['jockeys.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_id'], ['owners.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('jockey_id'),
    sa.UniqueConstraint('owner_id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index('uq_users_initial_root', 'users', ['role'], unique=True, postgresql_where=sa.text("role = 'ROOT'"), sqlite_where=sa.text("role = 'ROOT'"))


def downgrade():
    raise RuntimeError("Destructive downgrade is disabled. Restore a verified backup instead.")
