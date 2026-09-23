from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Jockey, Result

jockeys_bp = Blueprint('jockeys', __name__)

@jockeys_bp.route('/')
def list_jockeys():
    jockeys = Jockey.query.order_by(Jockey.full_name.asc()).all()
    return render_template('jockeys/list.html', jockeys=jockeys)

@jockeys_bp.route('/add', methods=['GET', 'POST'])
def add_jockey():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        address = request.form.get('address', '').strip()
        age_str = request.form.get('age', '').strip()
        rating_str = request.form.get('rating', '').strip().replace(',', '.')

        errors = []
        if not full_name:
            errors.append("Поле «ФИО жокея» обязательно для заполнения.")

        age = None
        try:
            age = int(age_str)
            if age <= 0 or age > 100:
                errors.append("Возраст жокея должен быть положительным числом (от 14 до 100).")
        except (ValueError, TypeError):
            errors.append("Возраст жокея должен быть целым положительным числом.")

        rating = 0.0
        if rating_str:
            try:
                rating = float(rating_str)
                if rating < 0:
                    errors.append("Рейтинг жокея не может быть отрицательным числом.")
            except (ValueError, TypeError):
                errors.append("Поле «Рейтинг» должно быть числовым значением.")
        else:
            errors.append("Поле «Рейтинг» обязательно для заполнения.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template('jockeys/form.html', full_name=full_name, address=address, age=age_str, rating=rating_str)

        jockey = Jockey(full_name=full_name, address=address or None, age=age, rating=round(rating, 2))
        db.session.add(jockey)
        db.session.commit()
        flash(f"Жокей «{jockey.full_name}» успешно добавлен.", "success")
        return redirect(url_for('jockeys.list_jockeys'))

    return render_template('jockeys/form.html')

@jockeys_bp.route('/<int:jockey_id>')
def detail_jockey(jockey_id):
    jockey = db.session.get(Jockey, jockey_id)
    if not jockey:
        flash("Жокей не найден.", "warning")
        return redirect(url_for('jockeys.list_jockeys'))

    results = Result.query.filter_by(jockey_id=jockey.id).all()
    return render_template('jockeys/detail.html', jockey=jockey, results=results)
