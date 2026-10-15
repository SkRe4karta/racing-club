"""Private dashboards, immutable application workflow and recipient-only inbox."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app import db
from app.application_services import (ApplicationConflict, create_application, decide_application,
                                      registration_closes, registration_open)
from app.models import (APPLICATION_LABELS, Application, Competition, Horse, Jockey,
                        Notification, Result, User, utc_now)
from app.permissions import can, permission_required

cabinet_bp = Blueprint('cabinet', __name__)


def application_query():
    query = select(Application).options(selectinload(Application.competition),
                                       selectinload(Application.horse), selectinload(Application.jockey))
    if current_user.role == 'ROOT':
        return query
    if current_user.role == 'OWNER':
        return query.where(Application.owner_user_id == current_user.id)
    if current_user.role == 'JOCKEY':
        return query.where(Application.jockey_user_id == current_user.id)
    abort(403)


def application_or_404(identifier):
    application = db.session.scalar(application_query().where(Application.id == identifier))
    if not application or not can('view_application', application):
        abort(404)
    return application


def reject_service_fields(allowed):
    if set(request.form) - set(allowed) - {'csrf_token'}:
        abort(400)


@cabinet_bp.get('/')
@permission_required('cabinet')
def dashboard():
    query = select(Result).join(Result.horse).options(selectinload(Result.competition),
            selectinload(Result.horse), selectinload(Result.jockey))
    horses = []
    if current_user.role == 'OWNER':
        horses = db.session.scalars(select(Horse).where(Horse.owner_id == current_user.owner_id)
                                    .order_by(Horse.nickname)).all()
        query = query.where(Horse.owner_id == current_user.owner_id)
    elif current_user.role == 'JOCKEY':
        query = query.where(Result.jockey_id == current_user.jockey_id)
    results = db.session.scalars(query.join(Result.competition).order_by(
        Competition.event_date.desc(), Competition.event_time.desc())).all()
    applications = db.session.scalars(application_query().order_by(Application.created_at.desc())).all()
    notifications = db.session.scalars(select(Notification).where(Notification.user_id == current_user.id)
                                       .order_by(Notification.id.desc()).limit(5)).all()
    upcoming = db.session.scalars(select(Competition).where(Competition.status == 'planned')
                                  .order_by(Competition.event_date, Competition.event_time)).all()
    upcoming = [item for item in upcoming if registration_open(item)]
    return render_template('cabinet/dashboard.html', horses=horses, results=results,
                           applications=applications, notifications=notifications, upcoming=upcoming)


@cabinet_bp.get('/applications')
@permission_required('cabinet')
def applications():
    query = application_query().order_by(Application.created_at.desc(), Application.id.desc())
    status = request.args.get('status', '')
    if status in APPLICATION_LABELS:
        query = query.where(Application.status == status)
    horse_id = request.args.get('horse_id', type=int)
    if horse_id is not None:
        query = query.where(Application.horse_id == horse_id)
    page = db.paginate(query, per_page=20, error_out=False)
    return render_template('cabinet/applications.html', pagination=page, labels=APPLICATION_LABELS)


@cabinet_bp.route('/applications/new', methods=['GET', 'POST'])
@permission_required('create_application')
def application_new():
    if request.method == 'POST':
        reject_service_fields({'competition_id', 'horse_id', 'jockey_id', 'side'})
        if current_user.role != 'ROOT' and 'side' in request.form:
            abort(400)
        try:
            application = create_application(current_user, request.form.get('competition_id'),
                request.form.get('horse_id'), request.form.get('jockey_id'), request.form.get('side'))
            flash('Приглашение отправлено. Ожидается явное согласие второй стороны.', 'success')
            return redirect(url_for('cabinet.application_detail', application_id=application.id))
        except PermissionError:
            abort(403)
        except ValueError as error:
            flash(str(error), 'danger')
            status_code = 409 if isinstance(error, ApplicationConflict) else 400
    else:
        status_code = 200
    competitions = db.session.scalars(select(Competition).where(Competition.status == 'planned')
                                      .order_by(Competition.event_date, Competition.event_time)).all()
    competitions = [item for item in competitions if registration_open(item)]
    horse_query = select(Horse).join(User, User.owner_id == Horse.owner_id).where(
        User.role == 'OWNER', User.status == 'active').options(selectinload(Horse.owner)).order_by(Horse.nickname)
    if current_user.role == 'OWNER':
        horse_query = horse_query.where(Horse.owner_id == current_user.owner_id)
    horses = db.session.scalars(horse_query).all()
    jockeys = db.session.scalars(select(Jockey).join(User, User.jockey_id == Jockey.id).where(
        User.role == 'JOCKEY', User.status == 'active').order_by(Jockey.full_name)).all()
    return render_template('cabinet/application_form.html', competitions=competitions, horses=horses,
                           jockeys=jockeys), status_code


@cabinet_bp.get('/applications/<int:application_id>')
@permission_required('cabinet')
def application_detail(application_id):
    return render_template('cabinet/application_detail.html', application=application_or_404(application_id))


@cabinet_bp.post('/applications/<int:application_id>/<action>')
@permission_required('cabinet')
def application_decision(application_id, action):
    reject_service_fields(set())
    application_or_404(application_id)
    if action not in ('confirm', 'reject', 'cancel'):
        abort(404)
    try:
        decide_application(current_user, application_id, action)
    except PermissionError:
        abort(403)
    except ValueError as error:
        flash(str(error), 'danger')
        return render_template('cabinet/application_detail.html',
                               application=application_or_404(application_id)), 409
    flash('Решение сохранено. Уведомления отправлены.', 'success')
    return redirect(url_for('cabinet.application_detail', application_id=application_id))


@cabinet_bp.get('/notifications')
@login_required
def notifications():
    page = db.paginate(select(Notification).where(Notification.user_id == current_user.id)
                       .order_by(Notification.id.desc()), per_page=20, error_out=False)
    return render_template('cabinet/notifications.html', pagination=page)


@cabinet_bp.route('/notifications/<int:notification_id>', methods=['GET', 'POST'])
@login_required
def notification_detail(notification_id):
    item = db.session.scalar(select(Notification).where(Notification.id == notification_id,
                              Notification.user_id == current_user.id))
    if not item or not can('notification', item):
        abort(404)
    if request.method == 'POST':
        reject_service_fields(set())
        db.session.execute(update(Notification).where(Notification.id == item.id,
                           Notification.user_id == current_user.id, Notification.read_at.is_(None))
                           .values(read_at=utc_now()))
        db.session.commit()
        return redirect(url_for('cabinet.notification_detail', notification_id=item.id))
    return render_template('cabinet/notification_detail.html', notification=item)


def setup_cabinet_context(app):
    @app.context_processor
    def inbox_context():
        unread = 0
        if current_user.is_authenticated:
            unread = db.session.scalar(select(db.func.count()).select_from(Notification).where(
                Notification.user_id == current_user.id, Notification.read_at.is_(None)))
        from flask import current_app
        from zoneinfo import ZoneInfo
        return dict(unread_notifications=unread, registration_open=registration_open,
                    registration_closes=registration_closes, application_labels=APPLICATION_LABELS,
                    club_timezone=ZoneInfo(current_app.config['CLUB_TIMEZONE']))


@cabinet_bp.route('/profile/<side>/<int:profile_id>/edit', methods=['GET', 'POST'])
@login_required
def profile_edit(side, profile_id):
    from app.models import Owner
    model = {'owner': Owner, 'jockey': Jockey}.get(side)
    if model is None:
        abort(404)
    profile = db.get_or_404(model, profile_id)
    if not can('manage_' + side, profile):
        abort(403)
    if request.method == 'POST':
        allowed = {'full_name', 'address', 'phone'} if side == 'owner' else {'full_name', 'address', 'age'}
        reject_service_fields(allowed)
        try:
            name = request.form.get('full_name', '').strip()
            address = request.form.get('address', '').strip()
            phone = request.form.get('phone', '').strip()
            if not name or len(name) > 150 or len(address) > 255 or len(phone) > 50:
                raise ValueError('Проверьте ФИО и длину контактных данных.')
            if side == 'jockey':
                try:
                    age = int(request.form.get('age', ''))
                except ValueError:
                    age = 0
                if not 1 <= age <= 100:
                    raise ValueError('Возраст жокея: от 1 до 100 лет.')
                profile.age = age
            else:
                profile.phone = phone or None
            profile.full_name = name
            profile.address = address or None
            db.session.commit()
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'danger')
            return render_template('cabinet/profile_form.html', profile=profile, side=side), 400
        flash('Профиль сохранён.', 'success')
        return redirect(url_for('cabinet.dashboard'))
    return render_template('cabinet/profile_form.html', profile=profile, side=side)
