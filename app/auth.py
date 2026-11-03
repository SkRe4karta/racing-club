"""Authentication, shared database throttles and initial ROOT provisioning."""
import hashlib
import hmac
import re
import secrets
import time

import click
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import AuthThrottle, Jockey, Owner, User, utc_now
from app.permissions import can

auth_bp = Blueprint('auth', __name__)
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Войдите в аккаунт для продолжения.'
login_manager.session_protection = 'strong'
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')


def credential_stamp(user):
    """Bind signed sessions to credentials without exposing the password hash."""
    key = current_app.secret_key
    key = key.encode() if isinstance(key, str) else key
    return hmac.new(key, user.password_hash.encode(), hashlib.sha256).hexdigest()


def normalize_email(value):
    value = value.strip().lower()
    if (len(value) > 254 or len(value.split('@')[0]) > 64
            or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value)
            or '..' in value or value.startswith('.') or '.@' in value
            or any(label.startswith('-') or label.endswith('-') or len(label) > 63
                   for label in value.rsplit('@', 1)[-1].split('.'))):
        raise ValueError('Введите корректный email (латинскими символами).')
    return value


@login_manager.user_loader
def load_user(user_id):
    if not user_id.isdecimal() or len(user_id) > 10 or not 0 < int(user_id) <= 2147483647:
        return None
    # populate_existing also observes a status/role change in a long-lived context.
    user = db.session.get(User, int(user_id), populate_existing=True)
    if not user or not user.is_active:
        return None
    stamp = session.get('credential_stamp', '')
    if not isinstance(stamp, str) or not hmac.compare_digest(stamp, credential_stamp(user)):
        return None
    return user


def consume_limit(scope, value, limit):
    """Atomic upsert, so attempts cannot bypass limits across Gunicorn workers."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    now = int(time.time())
    window = current_app.config['AUTH_WINDOW_SECONDS']
    key = hashlib.sha256(f'{scope}:{value}'.encode()).hexdigest()
    insert = pg_insert if db.engine.dialect.name == 'postgresql' else sqlite_insert
    stale = AuthThrottle.window_started <= now - window
    statement = insert(AuthThrottle).values(key=key, window_started=now, attempts=1)
    statement = statement.on_conflict_do_update(
        index_elements=['key'],
        set_={'attempts': case((stale, 1), else_=AuthThrottle.attempts + 1),
              'window_started': case((stale, now), else_=AuthThrottle.window_started)},
    ).returning(AuthThrottle.attempts)
    attempts = db.session.execute(statement).scalar_one()
    db.session.commit()
    return attempts <= limit


def too_many():
    return (render_template('errors/message.html', message='Слишком много попыток. Повторите позже.'),
            429, {'Retry-After': str(current_app.config['AUTH_WINDOW_SECONDS'])})


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))
    if request.method == 'POST':
        if not consume_limit('register-ip', request.remote_addr or '', current_app.config['REGISTER_LIMIT']):
            return too_many()
        try:
            email = normalize_email(request.form.get('email', ''))
            role = request.form.get('role', 'VIEWER')
            if role not in ('OWNER', 'JOCKEY', 'VIEWER'):
                raise ValueError('Выберите разрешённый тип аккаунта.')
            if any(field in request.form for field in ('owner_id', 'jockey_id', 'user_id', 'status', 'rating')):
                raise ValueError('Присвоение существующего профиля или служебных полей запрещено.')
            user = User(email=email, role=role, status='active')
            password = request.form.get('password', '')
            if password != request.form.get('password_confirm', ''):
                raise ValueError('Пароли не совпадают.')
            user.set_password(password)
            if role in ('OWNER', 'JOCKEY'):
                full_name = request.form.get('full_name', '').strip()
                if not full_name or len(full_name) > 150:
                    raise ValueError('ФИО обязательно: от 1 до 150 символов.')
                if role == 'OWNER':
                    user.owner = Owner(full_name=full_name)
                else:
                    try:
                        age = int(request.form.get('age', ''))
                    except ValueError:
                        age = 0
                    if not 1 <= age <= 100:
                        raise ValueError('Возраст жокея должен быть от 1 до 100 лет.')
                    user.jockey = Jockey(full_name=full_name, age=age, rating=0.0)
            db.session.add(user)
            db.session.commit()
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            message = str(exc) if isinstance(exc, ValueError) else 'Регистрация с этим email недоступна.'
            flash(message, 'danger')
            return render_template('auth/register.html'), 400
        flash('Аккаунт создан. Войдите с вашим email и паролем.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))
    if request.method == 'POST':
        raw_email = request.form.get('email', '').strip().lower()
        ip_allowed = consume_limit('login-ip', request.remote_addr or '', current_app.config['LOGIN_IP_LIMIT'])
        if not ip_allowed:
            return too_many()
        email_allowed = consume_limit('login-email', raw_email, current_app.config['LOGIN_LIMIT'])
        if not email_allowed:
            return too_many()
        try:
            email = normalize_email(raw_email)
        except ValueError:
            email = ''
        user = db.session.scalar(select(User).where(User.email == email))
        password = request.form.get('password', '')
        valid = False
        if len(password) <= 128:
            valid = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
        if not user or not valid or not user.is_active:
            flash('Неверный email или пароль, либо аккаунт недоступен.', 'danger')
            return render_template('auth/login.html'), 400
        session.clear()
        login_user(user, remember=False, fresh=True)
        session['credential_stamp'] = credential_stamp(user)
        # Non-permanent sessions retain Flask-Login's strong fingerprint checks.
        # Flask still validates the signed cookie's maximum age (8h by default).
        session.permanent = False
        user.last_login_at = utc_now()
        db.session.commit()
        # A fixed internal destination also prevents open redirects via next.
        return redirect(url_for('auth.account'))
    return render_template('auth/login.html')


@auth_bp.post('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('main.index'))


@auth_bp.get('/account')
@login_required
def account():
    return render_template('auth/account.html')


@auth_bp.post('/account/password')
@login_required
def change_password():
    """Change only the current account, then invalidate all its signed sessions."""
    if not can('account'):
        abort(403)
    allowed = {'csrf_token', 'current_password', 'new_password', 'confirm_password'}
    if set(request.form) - allowed or any(len(request.form.getlist(key)) != 1 for key in request.form):
        abort(400)
    if not consume_limit('password-user', str(current_user.id), current_app.config['LOGIN_LIMIT']):
        return too_many()
    old_hash = current_user.password_hash
    current = request.form.get('current_password', '')
    new = request.form.get('new_password', '')
    confirmation = request.form.get('confirm_password', '')
    error = None
    if len(current) > 128 or not current_user.check_password(current):
        error = 'Текущий пароль указан неверно.'
    elif new != confirmation:
        error = 'Повтор нового пароля не совпадает.'
    elif new == current:
        error = 'Новый пароль должен отличаться от текущего.'
    if error:
        flash(error, 'danger')
        return render_template('auth/account.html'), 400
    try:
        credentials = User()
        credentials.set_password(new)
        changed = db.session.execute(update(User).where(User.id == current_user.id,
            User.status == 'active', User.password_hash == old_hash)
            .values(password_hash=credentials.password_hash).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise ValueError('Учётные данные изменились. Войдите заново перед сменой пароля.')
        db.session.commit()
    except (ValueError, SQLAlchemyError) as exc:
        db.session.rollback()
        flash(str(exc) if isinstance(exc, ValueError) else 'Не удалось сохранить пароль. Повторите позже.', 'danger')
        return render_template('auth/account.html'), 400
    logout_user()
    session.clear()
    flash('Пароль изменён. Все сеансы завершены. Войдите с новым паролем.', 'success')
    return redirect(url_for('auth.login'))


def setup_auth(app):
    login_manager.init_app(app)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.context_processor(lambda: {'can': can})

    @app.before_request
    def check_account():
        if session.get('_user_id') and not current_user.is_authenticated:
            session.clear()

    @app.after_request
    def secure_response(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if request.blueprint == 'auth' or session.get('_user_id'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.cli.command('create-root')
    @click.option('--email', prompt='Email ROOT')
    def create_root(email):
        """Create the initial singleton ROOT; never accept passwords in source."""
        try:
            email = normalize_email(email)
            if db.session.scalar(select(User.id).where(User.role == 'ROOT')):
                raise click.ClickException('ROOT уже существует. Повторное создание запрещено.')
            password = click.prompt('Пароль ROOT', hide_input=True, confirmation_prompt=True)
            user = User(email=email, role='ROOT', status='active')
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            message = str(exc) if isinstance(exc, ValueError) else 'Email занят или ROOT уже существует.'
            raise click.ClickException(message) from None
        click.echo('ROOT создан.')

    @app.cli.command('prune-auth-throttles')
    def prune_auth_throttles():
        """Remove expired anonymous counters without changing users or sports data."""
        cutoff = int(time.time()) - app.config['AUTH_WINDOW_SECONDS']
        db.session.execute(db.delete(AuthThrottle).where(AuthThrottle.window_started <= cutoff))
        db.session.commit()
        click.echo('Истёкшие счётчики удалены.')
