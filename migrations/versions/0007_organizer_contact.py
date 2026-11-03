"""Optional public organizer email: independent additive migration for automatic CD."""
from alembic import op
import sqlalchemy as sa

revision = '0007_organizer_contact'
down_revision = '0006_registration_notes'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '60s'")
    op.add_column('competitions', sa.Column('organizer_email', sa.String(254),
        sa.CheckConstraint("organizer_email IS NULL OR (length(organizer_email) BETWEEN 3 AND 254 AND organizer_email = lower(organizer_email) AND organizer_email LIKE '%@%')",
                           name='ck_competitions_organizer_email'), nullable=True))


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled; restore a verified backup instead.')
