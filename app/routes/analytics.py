from datetime import date
from flask import Blueprint, abort, render_template, request
from app import db
from app.analytics import rankings, distance_averages, seasons

analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.get('/rankings')
@analytics_bp.get('/statistics')
def index():
    dates = []
    for key in ('from', 'to'):
        value = request.args.get(key, '')
        try:
            dates.append(date.fromisoformat(value) if value else None)
        except ValueError:
            abort(400, description='Укажите корректный период в формате ГГГГ-ММ-ДД.')
    start, end = dates
    if start and end and start > end:
        abort(400, description='Начало периода должно предшествовать его окончанию.')
    kind = 'jockeys' if request.args.get('kind') == 'jockeys' else 'horses'
    # SQL aggregate pagination avoids loading complete histories for leaderboard cards.
    page = db.paginate(rankings(kind, start, end), per_page=20, error_out=False)
    # db.paginate scalars unique entities; use explicit row query for metrics.
    rows = db.session.execute(rankings(kind, start, end).limit(20).offset((page.page - 1) * 20)).all()
    seasonal = seasons(start, end)
    chart = dict(labels=[str(int(r[0])) for r in seasonal], values=[r[1] for r in seasonal])
    return render_template('analytics/index.html', rows=rows, pagination=page, kind=kind,
        averages=distance_averages(start, end), seasonal=seasonal, chart=chart)
