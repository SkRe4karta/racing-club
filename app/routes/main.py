from datetime import date
from flask import Blueprint, render_template
from sqlalchemy.orm import selectinload
from app import db
from app.models import Owner, Horse, Jockey, Competition, Result

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    stats = {
        'owners_count': Owner.query.count(),
        'horses_count': Horse.query.count(),
        'jockeys_count': Jockey.query.count(),
        'future_competitions_count': Competition.query.filter_by(status='planned').count(),
        'past_competitions_count': Competition.query.filter_by(status='completed').count(),
    }
    recent_future = Competition.query.options(selectinload(Competition.results)).filter(Competition.status == 'planned', Competition.event_date >= date.today()).order_by(Competition.event_date, Competition.event_time).limit(5).all()
    overdue = Competition.query.filter(Competition.status == 'planned', Competition.event_date < date.today()).count()
    recent_past = Competition.query.options(selectinload(Competition.results)).filter_by(status='completed').order_by(Competition.event_date.desc(), Competition.event_time.desc()).limit(5).all()
    leaders = db.session.query(Horse, db.func.count(Result.id).label('wins')).join(Result).join(Competition).filter(Competition.status == 'completed', Result.place == 1, Result.is_disqualified.is_(False)).group_by(Horse.id).order_by(db.func.count(Result.id).desc(), Horse.id).limit(3).all()
    return render_template('index.html', stats=stats, recent_future=recent_future, recent_past=recent_past, overdue=overdue, leaders=leaders)
