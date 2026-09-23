from flask import Blueprint, render_template
from app.models import Owner, Horse, Jockey, Competition

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
    recent_future = Competition.query.filter_by(status='planned').order_by(Competition.event_date.asc()).limit(5).all()
    recent_past = Competition.query.filter_by(status='completed').order_by(Competition.event_date.desc()).limit(5).all()
    return render_template('index.html', stats=stats, recent_future=recent_future, recent_past=recent_past)
