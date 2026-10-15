from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from app import db


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    """Account and exclusive profile association; legacy profiles stay unclaimed."""

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(512), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='VIEWER')
    status = db.Column(db.String(16), nullable=False, default='active')
    registered_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    last_login_at = db.Column(db.DateTime(timezone=True))
    owner_id = db.Column(db.Integer, db.ForeignKey('owners.id', ondelete='RESTRICT'), unique=True)
    jockey_id = db.Column(db.Integer, db.ForeignKey('jockeys.id', ondelete='RESTRICT'), unique=True)

    owner = db.relationship('Owner', back_populates='user')
    jockey = db.relationship('Jockey', back_populates='user')

    __table_args__ = (
        CheckConstraint("role IN ('ROOT', 'ADMIN', 'OWNER', 'JOCKEY', 'VIEWER')", name='ck_users_role'),
        CheckConstraint("status IN ('active', 'disabled')", name='ck_users_status'),
        CheckConstraint('email = lower(email)', name='ck_users_email_normalized'),
        CheckConstraint(
            "(role = 'OWNER' AND owner_id IS NOT NULL AND jockey_id IS NULL) OR "
            "(role = 'JOCKEY' AND jockey_id IS NOT NULL AND owner_id IS NULL) OR "
            "(role IN ('ROOT', 'ADMIN', 'VIEWER') AND owner_id IS NULL AND jockey_id IS NULL)",
            name='ck_users_profile_role',
        ),
        Index('uq_users_initial_root', 'role', unique=True,
              postgresql_where=text("role = 'ROOT'"), sqlite_where=text("role = 'ROOT'")),
    )

    @property
    def is_active(self):
        return self.status == 'active'

    def set_password(self, password):
        if not 12 <= len(password) <= 128 or not password.strip():
            raise ValueError('Пароль должен содержать от 12 до 128 символов.')
        self.password_hash = generate_password_hash(password, method='scrypt')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class AuthThrottle(db.Model):
    """Shared fixed-window counters; keys contain hashes, never raw credentials."""

    __tablename__ = 'auth_throttles'
    key = db.Column(db.String(64), primary_key=True)
    window_started = db.Column(db.BigInteger, nullable=False)
    attempts = db.Column(db.Integer, nullable=False)
    __table_args__ = (CheckConstraint('attempts > 0', name='ck_auth_throttles_attempts'),)

class Owner(db.Model):
    __tablename__ = 'owners'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    user = db.relationship('User', back_populates='owner', uselist=False)

    horses = db.relationship('Horse', back_populates='owner', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f"<Owner {self.full_name}>"


class Horse(db.Model):
    __tablename__ = 'horses'

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(100), nullable=False)
    gender = db.Column(db.String(20), nullable=False)  # Жеребец, Кобыла, Мерин
    age = db.Column(db.Integer, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('owners.id'), nullable=False)

    owner = db.relationship('Owner', back_populates='horses', lazy=True)
    results = db.relationship('Result', back_populates='horse', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f"<Horse {self.nickname}>"


class Jockey(db.Model):
    __tablename__ = 'jockeys'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    age = db.Column(db.Integer, nullable=False)
    rating = db.Column(db.Float, nullable=False, default=0.0)
    user = db.relationship('User', back_populates='jockey', uselist=False)

    results = db.relationship('Result', back_populates='jockey', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f"<Jockey {self.full_name}>"


class Competition(db.Model):
    __tablename__ = 'competitions'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='planned')  # 'planned' или 'completed'

    registration_deadline = db.Column(db.DateTime(timezone=True))
    distance = db.Column(db.Integer)
    max_participants = db.Column(db.Integer)
    revision = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    __table_args__ = (
        CheckConstraint('distance IS NULL OR distance BETWEEN 100 AND 100000', name='ck_competitions_distance'),
        CheckConstraint('max_participants IS NULL OR max_participants BETWEEN 1 AND 1000', name='ck_competitions_capacity'),
    )

    results = db.relationship('Result', back_populates='competition', cascade='all, delete-orphan', lazy=True)

    @property
    def formatted_date(self):
        if self.event_date:
            return self.event_date.strftime('%d.%m.%Y')
        return ''

    @property
    def formatted_time(self):
        if self.event_time:
            return self.event_time.strftime('%H:%M')
        return ''

    @property
    def is_completed(self):
        return self.status == 'completed'

    def __repr__(self):
        return f"<Competition {self.title} ({self.status})>"


class Result(db.Model):
    __tablename__ = 'results'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id'), nullable=False)
    horse_id = db.Column(db.Integer, db.ForeignKey('horses.id'), nullable=False)
    jockey_id = db.Column(db.Integer, db.ForeignKey('jockeys.id'), nullable=False)
    
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id', ondelete='RESTRICT'))
    start_number = db.Column(db.Integer)
    did_not_finish = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    application = db.relationship('Application')
    finish_time_seconds = db.Column(db.Float, nullable=True)
    is_disqualified = db.Column(db.Boolean, nullable=False, default=False)
    place = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint('application_id', name='uq_results_application'),
        UniqueConstraint('competition_id', 'start_number', name='uq_results_start_number'),
        CheckConstraint('start_number IS NULL OR start_number > 0', name='ck_results_start_number'),
        CheckConstraint('NOT (did_not_finish AND is_disqualified)', name='ck_results_outcome'),
        UniqueConstraint('competition_id', 'horse_id', name='uq_competition_horse'),
        UniqueConstraint('competition_id', 'jockey_id', name='uq_competition_jockey'),
    )

    competition = db.relationship('Competition', back_populates='results', lazy=True)
    horse = db.relationship('Horse', back_populates='results', lazy=True)
    jockey = db.relationship('Jockey', back_populates='results', lazy=True)

    @property
    def formatted_finish_time(self):
        if self.is_disqualified:
            return "Дисквалификация"
        if self.did_not_finish:
            return "Не финишировал (DNF)"
        if self.finish_time_seconds is None:
            return "—"
        total_seconds = float(self.finish_time_seconds)
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        if minutes > 0:
            return f"{minutes:02d}:{seconds:05.2f}"
        return f"{seconds:.2f} сек"

    def __repr__(self):
        return f"<Result Comp:{self.competition_id} Horse:{self.horse_id} Jockey:{self.jockey_id} Place:{self.place}>"


APPLICATION_LABELS = {
    'awaiting_owner': 'Ожидает согласования владельца',
    'awaiting_jockey': 'Ожидает согласования жокея',
    'pending_admin': 'Согласовано обеими сторонами · ожидает администратора',
    'admin_confirmed': 'Подтверждено администратором',
    'rejected': 'Отклонено',
    'cancelled': 'Отменено',
}
ACTIVE_APPLICATION_SQL = "status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed')"


class Application(db.Model):
    """Immutable pair: change it by cancelling and submitting a new application.

    Both consents imply pending_admin; administrative admission creates one Result.
    Frozen recipient accounts prevent historical profiles implying consent.
    """

    __tablename__ = 'applications'
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id', ondelete='RESTRICT'), nullable=False)
    horse_id = db.Column(db.Integer, db.ForeignKey('horses.id', ondelete='RESTRICT'), nullable=False)
    jockey_id = db.Column(db.Integer, db.ForeignKey('jockeys.id', ondelete='RESTRICT'), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    jockey_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    initiator_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    initiator_side = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(24), nullable=False)
    owner_confirmed_at = db.Column(db.DateTime(timezone=True))
    jockey_confirmed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    competition = db.relationship('Competition')
    horse = db.relationship('Horse')
    jockey = db.relationship('Jockey')
    events = db.relationship('ApplicationEvent', order_by='ApplicationEvent.id', passive_deletes=True)

    __table_args__ = (
        CheckConstraint("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed', 'rejected', 'cancelled')", name='ck_applications_status'),
        CheckConstraint("initiator_side IN ('owner', 'jockey')", name='ck_applications_side'),
        CheckConstraint('owner_user_id <> jockey_user_id', name='ck_applications_distinct_parties'),
        CheckConstraint(
            "(status = 'awaiting_owner' AND owner_confirmed_at IS NULL AND jockey_confirmed_at IS NOT NULL AND initiator_side = 'jockey') OR "
            "(status = 'awaiting_jockey' AND owner_confirmed_at IS NOT NULL AND jockey_confirmed_at IS NULL AND initiator_side = 'owner') OR "
            "(status IN ('pending_admin', 'admin_confirmed') AND owner_confirmed_at IS NOT NULL AND jockey_confirmed_at IS NOT NULL) OR "
            "status IN ('rejected', 'cancelled')", name='ck_applications_consents'),
        Index('uq_applications_active_horse', 'competition_id', 'horse_id', unique=True,
              postgresql_where=text(ACTIVE_APPLICATION_SQL), sqlite_where=text(ACTIVE_APPLICATION_SQL)),
        Index('uq_applications_active_jockey', 'competition_id', 'jockey_id', unique=True,
              postgresql_where=text(ACTIVE_APPLICATION_SQL), sqlite_where=text(ACTIVE_APPLICATION_SQL)),
        Index('ix_applications_owner_created', 'owner_user_id', 'created_at'),
        Index('ix_applications_jockey_created', 'jockey_user_id', 'created_at'),
    )

    def personal_consent(self, side):
        """Old ROOT timestamps are evidence of intervention, not personal consent."""
        account_id = self.owner_user_id if side == 'owner' else self.jockey_user_id
        stamp = self.owner_confirmed_at if side == 'owner' else self.jockey_confirmed_at
        action = 'created' if side == self.initiator_side else 'confirmed'
        return stamp is not None and any(event.action == action and event.actor_id == account_id
                                         for event in self.events)

    @property
    def status_label(self):
        return APPLICATION_LABELS[self.status]

    @property
    def is_active(self):
        return self.status not in ('cancelled', 'rejected')


class ApplicationEvent(db.Model):
    """Append-only decision history, committed with the application and notifications."""

    __tablename__ = 'application_events'
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id', ondelete='RESTRICT'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    action = db.Column(db.String(24), nullable=False)
    status = db.Column(db.String(24), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("action IN ('created', 'confirmed', 'rejected', 'cancelled')", name='ck_application_events_action'),
        CheckConstraint("status IN ('awaiting_owner', 'awaiting_jockey', 'pending_admin', 'admin_confirmed', 'rejected', 'cancelled')", name='ck_application_events_status'),
    )


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id', ondelete='RESTRICT'))
    event_id = db.Column(db.Integer, db.ForeignKey('application_events.id', ondelete='RESTRICT'))
    audit_id = db.Column(db.Integer, db.ForeignKey('audit_logs.id', ondelete='RESTRICT'))
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id', ondelete='RESTRICT'))
    message = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    read_at = db.Column(db.DateTime(timezone=True))
    application = db.relationship('Application')
    competition = db.relationship('Competition')
    __table_args__ = (
        UniqueConstraint('user_id', 'event_id', name='uq_notifications_recipient_event'),
        UniqueConstraint('user_id', 'audit_id', name='uq_notifications_recipient_audit'),
        CheckConstraint('(event_id IS NOT NULL AND application_id IS NOT NULL AND audit_id IS NULL) OR (event_id IS NULL AND audit_id IS NOT NULL)', name='ck_notifications_source'),
        Index('ix_notifications_user_read', 'user_id', 'read_at', 'id'),
    )


class AuditLog(db.Model):
    """Append-only administrative history. Writers use explicit safe field allowlists."""

    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    action = db.Column(db.String(48), nullable=False)
    object_type = db.Column(db.String(32), nullable=False)
    object_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    reason = db.Column(db.String(500))
    old_values = db.Column(db.JSON)
    new_values = db.Column(db.JSON)
    actor = db.relationship('User')
    __table_args__ = (Index('ix_audit_logs_object', 'object_type', 'object_id', 'id'),)
