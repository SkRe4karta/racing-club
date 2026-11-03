"""Free sporting predictions. Historical sporting tables are left intact."""
from alembic import op
import sqlalchemy as sa

revision = '0005_predictions'
down_revision = '0004_administration'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('predictions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('competition_id', sa.Integer(), sa.ForeignKey('competitions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('mode', sa.String(12), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('evaluated_at', sa.DateTime(timezone=True)),
        sa.Column('protocol_revision', sa.Integer()),
        sa.Column('outcome', sa.String(12), nullable=False),
        sa.Column('winner_correct', sa.Boolean()),
        sa.Column('podium_hits', sa.Integer()),
        sa.Column('exact_trio', sa.Boolean()),
        sa.UniqueConstraint('user_id', 'competition_id', 'mode', name='uq_predictions_user_race_mode'),
        sa.CheckConstraint("mode IN ('winner', 'trio')", name='ck_predictions_mode'),
        sa.CheckConstraint("outcome IN ('pending', 'evaluated', 'void')", name='ck_predictions_outcome'),
        sa.CheckConstraint('revision > 0', name='ck_predictions_revision'),
        sa.CheckConstraint('podium_hits IS NULL OR podium_hits BETWEEN 0 AND 3', name='ck_predictions_hits'))
    op.create_index('ix_predictions_competition', 'predictions', ['competition_id'])
    op.create_index('ix_predictions_user_created', 'predictions', ['user_id', 'created_at'])
    op.create_table('prediction_choices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('prediction_id', sa.Integer(), sa.ForeignKey('predictions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('horse_id', sa.Integer(), sa.ForeignKey('horses.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('position_correct', sa.Boolean()),
        sa.UniqueConstraint('prediction_id', 'position', name='uq_prediction_choices_position'),
        sa.UniqueConstraint('prediction_id', 'horse_id', name='uq_prediction_choices_horse'),
        sa.CheckConstraint('position BETWEEN 1 AND 3', name='ck_prediction_choices_position'))


def downgrade():
    raise RuntimeError('Прогнозы и их история сохраняются. Используйте проверенную резервную копию для отката.')
