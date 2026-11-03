"""Alpha 3: official starters, competition rules, append-only audit.

Revision ID: 0004_administration
Revises: 0003_applications
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_administration'
down_revision = '0003_applications'
branch_labels = None
depends_on = None


def upgrade():
    # Inline ADD COLUMN checks avoid rebuilding the referenced competitions table
    # on SQLite. Defaults preserve every legacy row and every old protocol value.
    op.add_column('competitions', sa.Column('distance', sa.Integer(), sa.CheckConstraint(
        'distance IS NULL OR distance BETWEEN 100 AND 100000', name='ck_competitions_distance')))
    op.add_column('competitions', sa.Column('max_participants', sa.Integer(), sa.CheckConstraint(
        'max_participants IS NULL OR max_participants BETWEEN 1 AND 1000', name='ck_competitions_capacity')))
    op.add_column('competitions', sa.Column('revision', sa.Integer(), nullable=False, server_default='0'))
    with op.batch_alter_table('results') as batch:
        batch.add_column(sa.Column('application_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('start_number', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('did_not_finish', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key('fk_results_application', 'applications', ['application_id'], ['id'], ondelete='RESTRICT')
        batch.create_unique_constraint('uq_results_application', ['application_id'])
        batch.create_unique_constraint('uq_results_start_number', ['competition_id', 'start_number'])
        batch.create_check_constraint('ck_results_start_number', 'start_number IS NULL OR start_number > 0')
        batch.create_check_constraint('ck_results_outcome', 'NOT (did_not_finish AND is_disqualified)')
    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('action', sa.String(48), nullable=False),
        sa.Column('object_type', sa.String(32), nullable=False),
        sa.Column('object_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.String(500)),
        sa.Column('old_values', sa.JSON()),
        sa.Column('new_values', sa.JSON()))
    op.create_index('ix_audit_logs_actor_id', 'audit_logs', ['actor_id'])
    op.create_index('ix_audit_logs_object', 'audit_logs', ['object_type', 'object_id', 'id'])
    with op.batch_alter_table('notifications') as batch:
        batch.alter_column('application_id', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('event_id', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('audit_id', sa.Integer()))
        batch.add_column(sa.Column('competition_id', sa.Integer()))
        batch.create_foreign_key('fk_notifications_audit', 'audit_logs', ['audit_id'], ['id'], ondelete='RESTRICT')
        batch.create_foreign_key('fk_notifications_competition', 'competitions', ['competition_id'], ['id'], ondelete='RESTRICT')
        batch.create_unique_constraint('uq_notifications_recipient_audit', ['user_id', 'audit_id'])
        batch.create_check_constraint('ck_notifications_source',
            '(event_id IS NOT NULL AND application_id IS NOT NULL AND audit_id IS NULL) OR (event_id IS NULL AND audit_id IS NOT NULL)')
    # No HTTP/CLI update or delete exists. Triggers also reject accidental ORM/raw
    # mutation of history, while migration/DBA ownership remains trusted.
    if op.get_context().dialect.name == 'postgresql':
        op.execute("""CREATE FUNCTION racing_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'audit history is append-only'; END $$""")
        op.execute('CREATE TRIGGER audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION racing_audit_immutable()')
    else:
        for action in ('UPDATE', 'DELETE'):
            op.execute(f"CREATE TRIGGER audit_logs_no_{action.lower()} BEFORE {action} ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit history is append-only'); END")


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled. Restore a verified backup instead.')
