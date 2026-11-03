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
    # Inline CHECK permits native SQLite ADD COLUMN without rebuilding a table
    # referenced by historical result foreign keys. PostgreSQL gets the same CHECK.
    op.add_column('competitions', sa.Column(
        'registration_notes', sa.String(2000),
        sa.CheckConstraint('registration_notes IS NULL OR length(registration_notes) <= 2000',
                           name='ck_competitions_registration_notes'), nullable=True))


def downgrade():
    raise RuntimeError('Destructive downgrade prohibited; restore a verified backup instead.')
