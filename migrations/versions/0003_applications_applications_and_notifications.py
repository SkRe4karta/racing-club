"""applications and notifications

Revision ID: 0003_applications
Revises: 0002_auth_foundation
Create Date: 2026-10-15 20:55:27.050698

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003_applications'
down_revision = '0002_auth_foundation'
branch_labels = None
depends_on = None


def upgrade():
    # Reviewed: additive tables/indexes and a nullable deadline; no historical rewrite.
    op.create_table('applications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('competition_id', sa.Integer(), nullable=False),
    sa.Column('horse_id', sa.Integer(), nullable=False),
    sa.Column('jockey_id', sa.Integer(), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=False),
    sa.Column('jockey_user_id', sa.Integer(), nullable=False),
    sa.Column('initiator_id', sa.Integer(), nullable=False),
    sa.Column('initiator_side', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('owner_confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('jockey_confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(status = 'awaiting_owner' AND owner_confirmed_at IS NULL AND jockey_confirmed_at IS NOT NULL AND initiator_side = 'jockey') OR (status = 'awaiting_jockey' AND owner_confirmed_at IS NOT NULL AND jockey_confirmed_at IS NULL AND initiator_side = 'owner') OR (status IN ('pending_admin', 'admin_confirmed') AND owner_confirmed_at IS NOT NULL AND jockey_confirmed_at IS NOT NULL) OR status IN ('rejected', 'cancelled')", name='ck_applications_consents'),
    sa.CheckConstraint("initiator_side IN ('owner', 'jockey')", name='ck_applications_side'),
    sa.CheckConstraint("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed', 'rejected', 'cancelled')", name='ck_applications_status'),
    sa.CheckConstraint('owner_user_id <> jockey_user_id', name='ck_applications_distinct_parties'),
    sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['horse_id'], ['horses.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['initiator_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['jockey_id'], ['jockeys.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['jockey_user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.create_index('ix_applications_jockey_created', ['jockey_user_id', 'created_at'], unique=False)
        batch_op.create_index('ix_applications_owner_created', ['owner_user_id', 'created_at'], unique=False)
        batch_op.create_index('uq_applications_active_horse', ['competition_id', 'horse_id'], unique=True, postgresql_where=sa.text("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed')"), sqlite_where=sa.text("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed')"))
        batch_op.create_index('uq_applications_active_jockey', ['competition_id', 'jockey_id'], unique=True, postgresql_where=sa.text("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed')"), sqlite_where=sa.text("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed')"))

    op.create_table('application_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("action IN ('created', 'confirmed', 'rejected', 'cancelled')", name='ck_application_events_action'),
    sa.CheckConstraint("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed', 'rejected', 'cancelled')", name='ck_application_events_status'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('application_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_application_events_application_id'), ['application_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('message', sa.String(length=300), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['event_id'], ['application_events.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'event_id', name='uq_notifications_recipient_event')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index('ix_notifications_user_read', ['user_id', 'read_at', 'id'], unique=False)

    with op.batch_alter_table('competitions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('registration_deadline', sa.DateTime(timezone=True), nullable=True))




def downgrade():
    raise RuntimeError("Destructive downgrade is disabled. Restore a verified backup instead.")
