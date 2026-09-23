from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Horse, Owner, Result

horses_bp = Blueprint('horses', __name__)

@horses_bp.route('/')
def list_horses():
    horses = Horse.query.order_by(Horse.nickname.asc()).all()
    return render_template('horses/list.html', horses=horses)

@horses_bp.route('/add', methods=['GET', 'POST'])
def add_horse():
    owners = Owner.query.order_by(Owner.full_name.asc()).all()
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        gender = request.form.get('gender', '').strip()
        age_str = request.form.get('age', '').strip()
        owner_id_str = request.form.get('owner_id', '').strip()

        errors = []
        if not nickname:
            errors.append("Поле «Кличка» обязательно для заполнения.")
        if not gender:
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
            owner = db.session.get(Owner, owner_id)
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

    return render_template('horses/form.html', owners=owners)

@horses_bp.route('/<int:horse_id>')
def detail_horse(horse_id):
    horse = db.session.get(Horse, horse_id)
    if not horse:
        flash("Лошадь не найдена.", "warning")
        return redirect(url_for('horses.list_horses'))
    
    # Получаем историю состязаний лошади
    results = Result.query.filter_by(horse_id=horse.id).join(Result.competition).order_by(Result.competition.has()).all()
    # Сортируем: сначала завершенные по дате убывания, потом запланированные
    return render_template('horses/detail.html', horse=horse, results=results)
