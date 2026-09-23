from datetime import datetime, date, time
from sqlalchemy import UniqueConstraint
from app import db

class Owner(db.Model):
    __tablename__ = 'owners'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)

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
    
    finish_time_seconds = db.Column(db.Float, nullable=True)
    is_disqualified = db.Column(db.Boolean, nullable=False, default=False)
    place = db.Column(db.Integer, nullable=True)

    __table_args__ = (
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
