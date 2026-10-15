"""Public race discovery and private, CSRF-protected sporting predictions."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app import db
from app.models import Competition, Result, Prediction, PredictionChoice, Horse
from app.permissions import permission_required
from app.prediction_services import (accuracy_summary, prediction_query, predictions_open, save_prediction)
from app.admin_services import start_at

predictions_bp = Blueprint('predictions', __name__, url_prefix='/predictions')


@predictions_bp.after_request
def private_response(response):
    # An authenticated response contains the account's unreleased choices.
    if current_user.is_authenticated:
        response.headers['Cache-Control'] = 'no-store'
    return response


@predictions_bp.get('/')
def index():
    query = select(Competition).options(selectinload(Competition.results)).order_by(
        Competition.event_date.desc(), Competition.event_time.desc(), Competition.id.desc())
    if request.args.get('status', 'planned') == 'completed':
        query = query.where(Competition.status == 'completed')
    else:
        query = query.where(Competition.status == 'planned')
    page = db.paginate(query, per_page=12, error_out=False)
    return render_template('predictions/index.html', pagination=page, predictions_open=predictions_open)


@predictions_bp.route('/<int:comp_id>', methods=['GET', 'POST'])
def detail(comp_id):
    comp = db.get_or_404(Competition, comp_id)
    if request.method == 'POST':
        return submit(comp)
    rows = db.session.scalars(select(Result).where(Result.competition_id == comp.id)
        .options(selectinload(Result.horse), selectinload(Result.jockey))
        .order_by(Result.start_number, Result.id)).all()
    mine = {}
    if current_user.is_authenticated:
        mine = {p.mode: p for p in db.session.scalars(prediction_query().where(
            Prediction.user_id == current_user.id, Prediction.competition_id == comp.id))}
    official = {r.horse_id for r in rows}
    stale = any(c.horse_id not in official for p in mine.values() for c in p.choices)
    distribution = None
    community = None
    # No distribution, counts or other users' choices before closure.
    if not predictions_open(comp):
        community = db.session.execute(select(Prediction.mode, func.count(Prediction.id),
            func.sum(db.case((Prediction.winner_correct.is_(True), 1), else_=0)),
            func.sum(db.case((Prediction.exact_trio.is_(True), 1), else_=0)))
            .where(Prediction.competition_id == comp.id).group_by(Prediction.mode)).all()
    if community is not None:
        distribution = db.session.execute(select(Horse.nickname, func.count(PredictionChoice.id))
            .join(PredictionChoice, PredictionChoice.horse_id == Horse.id)
            .join(Prediction, Prediction.id == PredictionChoice.prediction_id)
            .where(Prediction.competition_id == comp.id, Prediction.mode == 'winner')
            .group_by(Horse.id, Horse.nickname).order_by(func.count(PredictionChoice.id).desc(), Horse.id)).all()
    return render_template('predictions/detail.html', comp=comp, rows=rows, mine=mine,
        opened=predictions_open(comp), deadline=start_at(comp), stale=stale, community=community, distribution=distribution)


@permission_required('predict')
def submit(comp):
    if set(request.form) - {'csrf_token', 'mode', 'revision', 'horse_1', 'horse_2', 'horse_3'}:
        abort(400)
    if any(len(request.form.getlist(key)) != 1 for key in request.form):
        abort(400)
    mode = request.form.get('mode')
    horses = [request.form.get(f'horse_{i}') for i in range(1, (2 if mode == 'winner' else 4))]
    try:
        save_prediction(current_user, comp.id, mode, horses, request.form.get('revision'))
    except PermissionError:
        abort(403)
    except ValueError as error:
        return render_template('errors/message.html', message=str(error)), 409
    flash('Спортивный прогноз сохранён. До начала соревнования его можно изменить.', 'success')
    return redirect(url_for('predictions.detail', comp_id=comp.id))


@predictions_bp.get('/history')
@login_required
def history():
    query = prediction_query().where(Prediction.user_id == current_user.id)
    page = db.paginate(query.order_by(Prediction.created_at.desc(), Prediction.id.desc()), per_page=20, error_out=False)
    # One bounded-column query for account accuracy, never relationships per row.
    all_mine = db.session.scalars(query).all()
    return render_template('predictions/history.html', pagination=page, summary=accuracy_summary(all_mine))
