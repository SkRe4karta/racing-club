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
    from app.analytics import rankings
    leaders = db.session.execute(rankings(start=date(date.today().year, 1, 1)).limit(3)).all()
    top_jockeys = db.session.execute(rankings('jockeys').limit(3)).all()
    featured_horses = db.session.scalars(db.select(Horse).options(selectinload(Horse.owner)).order_by(Horse.id).limit(3)).all()
    return render_template('index.html', stats=stats, recent_future=recent_future, recent_past=recent_past,
                           overdue=overdue, leaders=leaders, top_jockeys=top_jockeys, featured_horses=featured_horses)
