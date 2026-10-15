from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.orm import selectinload
from app.models import Competition, Result, Horse, Jockey
from app.permissions import permission_required
from app.services import (
    complete_planned_competition
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
    from app.routes.admin import competition_form
    return competition_form()


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
        from app.routes.cabinet import reject_service_fields
        reject_service_fields({f'{prefix}_{r.id}' for r in results for prefix in ('time', 'disq', 'dnf')})
        # Сбор введенных результатов
        results_data = {}
        for r in results:
            time_str = request.form.get(f"time_{r.id}", '').strip()
            is_disq = f"disq_{r.id}" in request.form
            results_data[r.id] = {
                'time_str': time_str,
                'is_disqualified': is_disq,
                'did_not_finish': f'dnf_{r.id}' in request.form
            }

        try:
            complete_planned_competition(competition.id, results_data)
            flash(f"Состязание «{competition.title}» успешно завершено, места рассчитаны!", "success")
            return redirect(url_for('competitions.past_detail', comp_id=competition.id))
        except PermissionError:
            from flask import abort
            abort(403)
        except ValueError as ex:
            flash(str(ex), "danger")
            return render_template(
                'competitions/complete_form.html',
                competition=competition,
                results=results,
                submitted_data=results_data
            ), 400

    return render_template('competitions/complete_form.html', competition=competition, results=results, submitted_data={})


# --- Добавление прошедшего состязания сразу ---

@competitions_bp.route('/past/add', methods=['GET', 'POST'])
@permission_required('manage_competitions')
def past_add():
    # Retired write bypass; keep a useful navigation page at the old URL.
    if request.method == 'POST':
        return render_template('errors/message.html', message='Прямое создание протокола закрыто. Используйте создание соревнования, допуск и завершение.'), 410
    return render_template('admin/legacy_protocol.html')
