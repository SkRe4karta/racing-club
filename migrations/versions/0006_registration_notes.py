"""Optional organizer participation instructions; additive, no data rewrite."""
from alembic import op
import sqlalchemy as sa

revision = '0006_registration_notes'
down_revision = '0005_predictions'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '60s'")
    with op.batch_alter_table('competitions') as batch:
        batch.add_column(sa.Column('registration_notes', sa.String(2000), nullable=True))
        batch.create_check_constraint('ck_competitions_registration_notes',
                                      'registration_notes IS NULL OR length(registration_notes) <= 2000')


def downgrade():
    raise RuntimeError('Destructive downgrade prohibited; restore a verified backup instead.')
