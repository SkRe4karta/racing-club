from itertools import zip_longest
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.orm import selectinload
from app.models import Competition, Result, Horse, Jockey
from app.permissions import permission_required
from app.services import (
    create_future_competition,
    complete_planned_competition,
    create_completed_competition_direct
)

competitions_bp = Blueprint('competitions', __name__)


def load_competition(comp_id):
    return Competition.query.options(
        selectinload(Competition.results).selectinload(Result.horse).selectinload(Horse.owner),
        selectinload(Competition.results).selectinload(Result.jockey),
    ).filter_by(id=comp_id).first()


# --- Будущие состязания ---

@competitions_bp.route('/future')
def future_list():
    from app.web import listing
    return listing('future')


@competitions_bp.route('/future/<int:comp_id>')
def future_detail(comp_id):
    competition = load_competition(comp_id)
    if not competition or competition.status != 'planned':
        flash("Запланированное состязание не найдено.", "warning")
        return redirect(url_for('competitions.future_list'))
    
    return render_template('competitions/future_detail.html', competition=competition)


@competitions_bp.route('/future/add', methods=['GET', 'POST'])
@permission_required('manage_competitions')
def future_add():
    horses = Horse.query.order_by(Horse.nickname.asc()).all()
    jockeys = Jockey.query.order_by(Jockey.full_name.asc()).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        location = request.form.get('location', '').strip()
        date_str = request.form.get('event_date', '').strip()
        time_str = request.form.get('event_time', '').strip()

        # Получаем динамические строки участников
        horse_ids = request.form.getlist('horse_id[]')
        jockey_ids = request.form.getlist('jockey_id[]')

        participants = []
        for h_id, j_id in zip_longest(horse_ids, jockey_ids, fillvalue=''):
            if h_id or j_id:
                participants.append({'horse_id': h_id, 'jockey_id': j_id})

        # Валидация даты и времени
        event_date_val = None
        event_time_val = None
        errors = []

        if not title:
            errors.append("Наименование состязания обязательно для заполнения.")
        if not location:
            errors.append("Место проведения (ипподром) обязательно для заполнения.")
        
        if date_str:
            try:
                event_date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                errors.append("Некорректный формат даты.")
        else:
            errors.append("Дата состязания обязательна.")

        if time_str:
            try:
                event_time_val = datetime.strptime(time_str, '%H:%M').time()
            except ValueError:
                errors.append("Некорректный формат времени.")
        else:
            errors.append("Время начала обязательно.")

        if not participants:
            errors.append("Необходимо добавить хотя бы одну пару «лошадь – жокей».")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                'competitions/future_form.html',
                horses=horses,
                jockeys=jockeys,
                title=title,
                location=location,
                date_val=date_str,
                time_val=time_str,
                participants=participants
            )

        try:
            from flask import current_app
            from zoneinfo import ZoneInfo
            deadline = None
            if request.form.get('registration_deadline'):
                try:
                    deadline = datetime.strptime(request.form['registration_deadline'], '%Y-%m-%dT%H:%M').replace(tzinfo=ZoneInfo(current_app.config['CLUB_TIMEZONE']))
                except ValueError:
                    raise ValueError('Некорректный срок регистрации.') from None
            comp = create_future_competition(
                title=title,
                event_date_val=event_date_val,
                event_time_val=event_time_val,
                location=location,
                participants=participants,
                registration_deadline=deadline
            )
            flash(f"Будущее состязание «{comp.title}» успешно создано.", "success")
            return redirect(url_for('competitions.future_list'))
        except ValueError as ex:
            flash(str(ex), "danger")
            return render_template(
                'competitions/future_form.html',
                horses=horses,
                jockeys=jockeys,
                title=title,
                location=location,
                date_val=date_str,
                time_val=time_str,
                participants=participants
            )

    return render_template('competitions/future_form.html', horses=horses, jockeys=jockeys, participants=[{}])


# --- Прошедшие состязания ---

@competitions_bp.route('/past')
def past_list():
    from app.web import listing
    return listing('past')


@competitions_bp.route('/past/<int:comp_id>')
def past_detail(comp_id):
    competition = load_competition(comp_id)
    if not competition or competition.status != 'completed':
        flash("Прошедшее состязание не найдено.", "warning")
        return redirect(url_for('competitions.past_list'))
    
    # Сортируем результаты: сначала по месту (1, 2, 3), в конце дисквалифицированные
    sorted_results = sorted(
        competition.results,
        key=lambda r: (1 if r.is_disqualified else 0, r.place or 9999)
    )
    return render_template('competitions/past_detail.html', competition=competition, results=sorted_results)


# --- Завершение состязания ---

@competitions_bp.route('/complete', methods=['GET', 'POST'])
@competitions_bp.route('/complete/<int:comp_id>', methods=['GET', 'POST'])
@permission_required('manage_competitions')
def complete(comp_id=None):
    if comp_id is None:
        comp_id_arg = request.args.get('comp_id')
        if comp_id_arg:
            try:
                comp_id = int(comp_id_arg)
            except ValueError:
                pass

    if not comp_id:
        planned_comps = Competition.query.options(selectinload(Competition.results)).filter_by(status='planned').order_by(Competition.event_date.asc()).all()
        # Если не выбран ID, отображаем страницу выбора состязания
        return render_template('competitions/complete_select.html', planned_comps=planned_comps)

    competition = load_competition(comp_id)
    if not competition:
        flash("Состязание не найдено.", "danger")
        return redirect(url_for('competitions.past_list'))

    if competition.is_completed:
        flash("Результаты завершенного состязания изменять нельзя.", "danger")
        return redirect(url_for('competitions.past_detail', comp_id=competition.id))

    results = competition.results

    if request.method == 'POST':
        # Сбор введенных результатов
        results_data = {}
        for r in results:
            time_str = request.form.get(f"time_{r.id}", '').strip()
            is_disq = f"disq_{r.id}" in request.form
            results_data[r.id] = {
                'time_str': time_str,
                'is_disqualified': is_disq
            }

        try:
            complete_planned_competition(competition.id, results_data)
            flash(f"Состязание «{competition.title}» успешно завершено, места рассчитаны!", "success")
            return redirect(url_for('competitions.past_detail', comp_id=competition.id))
        except ValueError as ex:
            flash(str(ex), "danger")
            return render_template(
                'competitions/complete_form.html',
                competition=competition,
                results=results,
                submitted_data=results_data
            )

    return render_template('competitions/complete_form.html', competition=competition, results=results, submitted_data={})


# --- Добавление прошедшего состязания сразу ---

@competitions_bp.route('/past/add', methods=['GET', 'POST'])
@permission_required('manage_competitions')
def past_add():
    horses = Horse.query.order_by(Horse.nickname.asc()).all()
    jockeys = Jockey.query.order_by(Jockey.full_name.asc()).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        location = request.form.get('location', '').strip()
        date_str = request.form.get('event_date', '').strip()
        time_str = request.form.get('event_time', '').strip()

        horse_ids = request.form.getlist('horse_id[]')
        jockey_ids = request.form.getlist('jockey_id[]')
        time_inputs = request.form.getlist('finish_time[]')
        # Для чекбоксов в динамических строках собираем по индексам
        row_count = max(len(horse_ids), len(jockey_ids), len(time_inputs))

        participants = []
        for i in range(row_count):
            h_id = horse_ids[i] if i < len(horse_ids) else None
            j_id = jockey_ids[i] if i < len(jockey_ids) else None
            t_str = time_inputs[i] if i < len(time_inputs) else ''
            is_disq = f"disq_{i}" in request.form

            if h_id or j_id or t_str or is_disq:
                participants.append({
                    'horse_id': h_id,
                    'jockey_id': j_id,
                    'time_str': t_str,
                    'is_disqualified': is_disq
                })

        errors = []
        event_date_val = None
        event_time_val = None

        if not title:
            errors.append("Наименование состязания обязательно для заполнения.")
        if not location:
            errors.append("Место проведения (ипподром) обязательно для заполнения.")

        if date_str:
            try:
                event_date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                errors.append("Некорректный формат даты.")
        else:
            errors.append("Дата состязания обязательна.")

        if time_str:
            try:
                event_time_val = datetime.strptime(time_str, '%H:%M').time()
            except ValueError:
                errors.append("Некорректный формат времени.")
        else:
            errors.append("Время начала обязательно.")

        if not participants:
            errors.append("Необходимо добавить хотя бы одного участника с результатом.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                'competitions/past_form.html',
                horses=horses,
                jockeys=jockeys,
                title=title,
                location=location,
                date_val=date_str,
                time_val=time_str,
                participants=participants
            )

        try:
            comp = create_completed_competition_direct(
                title=title,
                event_date_val=event_date_val,
                event_time_val=event_time_val,
                location=location,
                participants=participants
            )
            flash(f"Прошедшее состязание «{comp.title}» успешно добавлено и места рассчитаны!", "success")
            return redirect(url_for('competitions.past_detail', comp_id=comp.id))
        except ValueError as ex:
            flash(str(ex), "danger")
            return render_template(
                'competitions/past_form.html',
                horses=horses,
                jockeys=jockeys,
                title=title,
                location=location,
                date_val=date_str,
                time_val=time_str,
                participants=participants
            )

    return render_template('competitions/past_form.html', horses=horses, jockeys=jockeys, participants=[{}])
