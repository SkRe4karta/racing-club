"""Server-authorized ADMIN workspace and ROOT-only account administration."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app import db
from app import admin_services as service
from app.models import APPLICATION_LABELS, Application, AuditLog, Competition, Horse, Jockey, Owner, Result, User
from app.permissions import permission_required
from app.routes.cabinet import reject_service_fields
from app.routes.competitions import load_competition
from app.web import contains

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
root_bp = Blueprint('root', __name__, url_prefix='/root')


def audit_query():
    query = select(AuditLog).options(selectinload(AuditLog.actor)).order_by(AuditLog.id.desc())
    return query if current_user.role == 'ROOT' else query.where(AuditLog.actor_id == current_user.id)


@admin_bp.get('/')
@permission_required('manage_competitions')
def dashboard():
    counts = {
        'Предстоящие соревнования': db.session.scalar(select(func.count()).select_from(Competition).where(Competition.status == 'planned')),
        'Завершённые соревнования': db.session.scalar(select(func.count()).select_from(Competition).where(Competition.status == 'completed')),
        'Ожидают решения': db.session.scalar(select(func.count()).select_from(Application).where(Application.status == 'pending_admin')),
        'Подтверждённые участники будущих стартов': db.session.scalar(select(func.count()).select_from(Result).join(Result.competition).where(Competition.status == 'planned')),
    }
    upcoming = db.session.scalars(select(Competition).where(Competition.status == 'planned')
                                  .order_by(Competition.event_date, Competition.event_time).limit(8)).all()
    return render_template('admin/dashboard.html', counts=counts, upcoming=upcoming,
                           entries=db.session.scalars(audit_query().limit(8)).all())


@admin_bp.get('/competitions')
@permission_required('manage_competitions')
def competitions():
    query = select(Competition).order_by(Competition.event_date.desc(), Competition.id.desc())
    status = request.args.get('status')
    if status in ('planned', 'completed'):
        query = query.where(Competition.status == status)
    page = db.paginate(query, per_page=20, error_out=False)
    return render_template('admin/competitions.html', pagination=page)


def competition_form(identifier=None):
    comp = db.get_or_404(Competition, identifier) if identifier else None
    code = 200
    data = request.form if request.method == 'POST' else service.competition_snapshot(comp) if comp else {}
    if request.method == 'POST':
        reject_service_fields({'title', 'event_date', 'event_time', 'location', 'distance', 'max_participants', 'registration_deadline'})
        try:
            comp = service.save_competition(current_user, {k: v for k, v in request.form.items() if k != 'csrf_token'}, identifier)
            flash('Соревнование сохранено. Стартовый список формируется отдельным допуском заявок.', 'success')
            return redirect(url_for('admin.competition_detail', identifier=comp.id))
        except PermissionError:
            abort(403)
        except ValueError as error:
            flash(str(error), 'danger')
            code = 400
    if request.method == 'GET' and comp:
        data['event_time'] = comp.event_time.strftime('%H:%M')
        if comp.registration_deadline:
            from app.application_services import as_utc
            from zoneinfo import ZoneInfo
            from flask import current_app
            data['registration_deadline'] = as_utc(comp.registration_deadline).astimezone(
                ZoneInfo(current_app.config['CLUB_TIMEZONE'])).strftime('%Y-%m-%dT%H:%M')
    return render_template('admin/competition_form.html', competition=comp, data=data), code


@admin_bp.route('/competitions/new', methods=['GET', 'POST'])
@permission_required('manage_competitions')
def competition_new():
    return competition_form()


@admin_bp.route('/competitions/<int:identifier>/edit', methods=['GET', 'POST'])
@permission_required('manage_competitions')
def competition_edit(identifier):
    return competition_form(identifier)


@admin_bp.get('/competitions/<int:identifier>')
@permission_required('manage_competitions')
def competition_detail(identifier):
    comp = load_competition(identifier)
    if not comp:
        abort(404)
    return render_template('admin/competition_detail.html', competition=comp)


def applications_query():
    return select(Application).options(selectinload(Application.events), selectinload(Application.competition),
        selectinload(Application.horse).selectinload(Horse.owner), selectinload(Application.jockey))


@admin_bp.get('/applications')
@permission_required('manage_competitions')
def applications():
    query = applications_query().order_by(Application.created_at.desc(), Application.id.desc())
    if request.args.get('status') in APPLICATION_LABELS:
        query = query.where(Application.status == request.args['status'])
    identifier = request.args.get('competition_id', type=int)
    if identifier is not None:
        query = query.where(Application.competition_id == identifier)
    page = db.paginate(query, per_page=20, error_out=False)
    comps = db.session.scalars(select(Competition).order_by(Competition.event_date.desc())).all()
    return render_template('admin/applications.html', pagination=page, competitions=comps, labels=APPLICATION_LABELS)


@admin_bp.post('/applications/<int:identifier>/<action>')
@permission_required('manage_competitions')
def admission(identifier, action):
    reject_service_fields({'reason'})
    if action not in ('approve', 'reject', 'root-cancel'):
        abort(404)
    try:
        if action == 'root-cancel':
            service.root_cancel(current_user, identifier, request.form.get('reason'))
        else:
            service.decide_admission(current_user, identifier, action, request.form.get('reason'))
    except PermissionError:
        abort(403)
    except ValueError as error:
        flash(str(error), 'danger')
        return render_template('errors/message.html', message=str(error)), 409
    flash('Решение сохранено вместе с аудитом и уведомлениями.', 'success')
    return redirect(url_for('admin.applications'))


@admin_bp.route('/competitions/<int:identifier>/manual', methods=['GET', 'POST'])
@permission_required('manage_system')
def manual(identifier):
    comp = db.get_or_404(Competition, identifier)
    if request.method == 'POST':
        reject_service_fields({'horse_id', 'jockey_id', 'reason'})
        try:
            service.manual_participant(current_user, identifier, request.form.get('horse_id'),
                                       request.form.get('jockey_id'), request.form.get('reason'))
            flash('Участник добавлен административным исключением ROOT. Личные согласия не подменялись.', 'success')
            return redirect(url_for('admin.competition_detail', identifier=identifier))
        except PermissionError:
            abort(403)
        except ValueError as error:
            return render_template('errors/message.html', message=str(error)), 409
    return render_template('admin/manual.html', competition=comp,
        horses=db.session.scalars(select(Horse).order_by(Horse.nickname)).all(),
        jockeys=db.session.scalars(select(Jockey).order_by(Jockey.full_name)).all())


@admin_bp.route('/competitions/<int:identifier>/correct', methods=['GET', 'POST'])
@permission_required('manage_system')
def correct(identifier):
    comp = load_competition(identifier)
    if not comp or not comp.is_completed:
        abort(404)
    submitted = {}
    code = 200
    if request.method == 'POST':
        allowed = {'reason', 'revision'} | {f'{prefix}_{row.id}' for row in comp.results for prefix in ('time', 'disq', 'dnf')}
        reject_service_fields(allowed)
        submitted = protocol_form(comp.results)
        try:
            service.publish_protocol(current_user, identifier, submitted, correction_reason=request.form.get('reason', ''),
                                     expected_revision=request.form.get('revision'))
            flash('Коррекция опубликована. Предыдущий протокол сохранён в аудите.', 'success')
            return redirect(url_for('competitions.past_detail', comp_id=identifier))
        except PermissionError:
            abort(403)
        except ValueError as error:
            flash(str(error), 'danger')
            code = 409
    else:
        submitted = {r.id: {'time_str': str(r.finish_time_seconds) if r.finish_time_seconds is not None else '',
                            'is_disqualified': r.is_disqualified, 'did_not_finish': r.did_not_finish} for r in comp.results}
    return render_template('competitions/complete_form.html', competition=comp, results=comp.results,
                           submitted_data=submitted, correction=True), code


def protocol_form(rows):
    return {row.id: {'time_str': request.form.get(f'time_{row.id}', '').strip(),
                     'is_disqualified': f'disq_{row.id}' in request.form,
                     'did_not_finish': f'dnf_{row.id}' in request.form} for row in rows}


@admin_bp.get('/audit')
@permission_required('manage_competitions')
def audit():
    page = db.paginate(audit_query(), per_page=20, error_out=False)
    return render_template('admin/audit.html', pagination=page)


@root_bp.get('/')
@permission_required('manage_system')
def dashboard_root():
    return render_template('admin/root.html')


@root_bp.get('/users')
@permission_required('manage_system')
def users():
    query = select(User).options(selectinload(User.owner), selectinload(User.jockey)).order_by(User.id)
    if request.args.get('email', '').strip():
        query = query.where(contains(User.email, request.args['email'].strip()))
    if request.args.get('role') in ('ROOT', 'ADMIN', 'OWNER', 'JOCKEY', 'VIEWER'):
        query = query.where(User.role == request.args['role'])
    if request.args.get('status') in ('active', 'disabled'):
        query = query.where(User.status == request.args['status'])
    return render_template('admin/users.html', pagination=db.paginate(query, per_page=20, error_out=False))


@root_bp.route('/users/<int:identifier>', methods=['GET', 'POST'])
@permission_required('manage_system')
def user_detail(identifier):
    user = db.get_or_404(User, identifier)
    code = 200
    if request.method == 'POST':
        reject_service_fields({'role', 'status', 'reason'})
        try:
            service.update_user(current_user, identifier, role=request.form.get('role'),
                                status=request.form.get('status'), reason=request.form.get('reason'))
            flash('Аккаунт обновлён.', 'success')
            return redirect(url_for('root.user_detail', identifier=identifier))
        except PermissionError:
            abort(403)
        except ValueError as error:
            flash(str(error), 'danger')
            code = 400
    return render_template('admin/user.html', user=user), code


@root_bp.route('/users/<int:identifier>/link', methods=['GET', 'POST'])
@permission_required('manage_system')
def profile_link(identifier):
    user = db.get_or_404(User, identifier)
    code = 200
    if request.method == 'POST':
        reject_service_fields({'side', 'profile_id', 'reason', 'verified'})
        if request.form.get('verified') != 'yes':
            flash('Подтвердите внешнюю проверку принадлежности профиля.', 'danger')
            code = 400
        else:
            try:
                service.link_profile(current_user, identifier, request.form.get('side'),
                                     request.form.get('profile_id'), request.form.get('reason'))
                flash('Исторический профиль привязан. Спортивная история сохранена.', 'success')
                return redirect(url_for('root.user_detail', identifier=identifier))
            except PermissionError:
                abort(403)
            except ValueError as error:
                flash(str(error), 'danger')
                code = 400
    return render_template('admin/link.html', user=user,
        owners=db.session.scalars(select(Owner).where(~select(User.id).where(User.owner_id == Owner.id).exists())).all(),
        jockeys=db.session.scalars(select(Jockey).where(~select(User.id).where(User.jockey_id == Jockey.id).exists())).all()), code
