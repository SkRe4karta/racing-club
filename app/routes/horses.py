from sqlalchemy.orm import selectinload
from flask import Blueprint, abort, render_template, request, redirect, url_for, flash
from flask_login import current_user
from app.analytics import filter_history
from app import db
from app.models import Horse, Owner, Result, Competition
from app.permissions import permission_required

horses_bp = Blueprint('horses', __name__)

@horses_bp.route('/')
def list_horses():
    from app.web import listing
    return listing('horses')

@horses_bp.route('/add', methods=['GET', 'POST'])
@permission_required('create_horse')
def add_horse():
    owners = ([current_user.owner] if current_user.role == 'OWNER'
              else Owner.query.order_by(Owner.full_name.asc()).all())
    if request.method == 'POST':
        if set(request.form) - {'nickname', 'gender', 'age', 'owner_id', 'csrf_token'}:
            abort(400)
        nickname = request.form.get('nickname', '').strip()
        gender = request.form.get('gender', '').strip()
        age_str = request.form.get('age', '').strip()
        owner_id_str = request.form.get('owner_id', '').strip()
        if current_user.role == 'OWNER' and owner_id_str != str(current_user.owner_id):
            abort(403)

        errors = []
        if not nickname:
            errors.append("Поле «Кличка» обязательно для заполнения.")
        if gender not in ('Жеребец', 'Кобыла', 'Мерин'):
            errors.append("Поле «Пол» обязательно для выбора.")
        
        age = None
        try:
            age = int(age_str)
            if age <= 0 or age > 40:
                errors.append("Возраст лошади должен быть положительным числом (от 1 до 40).")
        except (ValueError, TypeError):
            errors.append("Поле «Возраст» должно быть целым числом.")

        owner_id = None
        try:
            owner_id = int(owner_id_str)
            id_limit = 2147483647 if db.engine.dialect.name == 'postgresql' else 9223372036854775807
            owner = db.session.get(Owner, owner_id) if 1 <= owner_id <= id_limit else None
            if not owner:
                errors.append("Выбран несуществующий владелец.")
        except (ValueError, TypeError):
            errors.append("Необходимо выбрать владельца из списка.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                'horses/form.html',
                owners=owners,
                nickname=nickname,
                gender=gender,
                age=age_str,
                selected_owner_id=owner_id
            )

        horse = Horse(nickname=nickname, gender=gender, age=age, owner_id=owner_id)
        db.session.add(horse)
        db.session.commit()
        flash(f"Лошадь «{horse.nickname}» успешно добавлена.", "success")
        return redirect(url_for('horses.list_horses'))

    return render_template('horses/form.html', owners=owners, selected_owner_id=current_user.owner_id if current_user.role == 'OWNER' else None)

@horses_bp.route('/<int:horse_id>')
def detail_horse(horse_id):
    horse = db.session.get(Horse, horse_id)
    if not horse:
        flash("Лошадь не найдена.", "warning")
        return redirect(url_for('horses.list_horses'))
    
    # Получаем историю состязаний лошади
    history_query = filter_history(Result.query.options(selectinload(Result.competition), selectinload(Result.horse), selectinload(Result.jockey)).filter_by(horse_id=horse.id).join(Result.competition).order_by(Competition.event_date.desc(), Competition.event_time.desc()))
    from app.analytics import history_context
    history = history_context(history_query)
    from app.models import Application
    from app.permissions import can
    applications = []
    if can('manage_horse', horse):
        applications = db.session.scalars(db.select(Application).where(Application.horse_id == horse.id, Application.status.not_in(['rejected', 'cancelled']))
            .options(selectinload(Application.competition)).order_by(Application.created_at.desc()).limit(30)).all()
    return render_template('horses/detail.html', horse=horse, **history, applications=applications)


@horses_bp.route('/<int:horse_id>/edit', methods=['GET', 'POST'])
@permission_required('create_horse')
def edit_horse(horse_id):
    from app.permissions import can
    horse = db.get_or_404(Horse, horse_id)
    if not can('manage_horse', horse):
        abort(403)
    if request.method == 'POST':
        if set(request.form) - {'nickname', 'gender', 'age', 'csrf_token'}:
            abort(400)
        nickname = request.form.get('nickname', '').strip()
        gender = request.form.get('gender', '').strip()
        try:
            age = int(request.form.get('age', ''))
        except ValueError:
            age = 0
        if not nickname or len(nickname) > 100 or gender not in ('Жеребец', 'Кобыла', 'Мерин') or not 1 <= age <= 40:
            flash('Укажите кличку (до 100 символов), пол и возраст от 1 до 40 лет.', 'danger')
            return render_template('horses/form.html', horse=horse, owners=[horse.owner],
                nickname=nickname, gender=gender, age=request.form.get('age', '')), 400
        horse.nickname, horse.gender, horse.age = nickname, gender, age
        db.session.commit()
        flash('Информация о лошади сохранена.', 'success')
        return redirect(url_for('horses.detail_horse', horse_id=horse.id))
    return render_template('horses/form.html', horse=horse, owners=[horse.owner],
        nickname=horse.nickname, gender=horse.gender, age=horse.age)
