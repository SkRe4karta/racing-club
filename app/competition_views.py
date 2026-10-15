"""Unified public race lists and month-bounded, status-inclusive calendar."""
import calendar
from collections import defaultdict
from datetime import date, timedelta

from flask import render_template, request, url_for
from sqlalchemy import func, select
from app import db
from app.models import Competition, Result
from app.web import contains, csv_response


def calendar_month(value):
    try:
        year, month = map(int, (value or date.today().strftime('%Y-%m')).split('-'))
        if not 2 <= year <= 9998:
            raise ValueError
        return date(year, month, 1)
    except (ValueError, TypeError, OverflowError):
        return date.today().replace(day=1)


def browse(default='future'):
    """Only requested list page or month is loaded; all modes work without JS."""
    view = request.args.get('view', default)
    if view not in ('future', 'past', 'calendar'):
        view = default
    conditions = []
    if view != 'calendar':
        conditions.append(Competition.status == ('planned' if view == 'future' else 'completed'))
    if request.args.get('q', '').strip():
        conditions.append(contains(Competition.title, request.args['q'].strip()))
    if request.args.get('location', '').strip():
        conditions.append(contains(Competition.location, request.args['location'].strip()))
    try:
        if request.args.get('date'):
            conditions.append(Competition.event_date == date.fromisoformat(request.args['date']))
    except (ValueError, OverflowError):
        pass  # Preserve legacy URLs with invalid dates without producing a traceback.
    total = db.session.scalar(select(func.count()).select_from(Competition).where(*conditions))
    month = calendar_month(request.args.get('month'))
    following = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    previous = (month - timedelta(days=1)).replace(day=1)
    month_key = month.strftime('%Y-%m')

    def browse_url(mode=None, **changes):
        params = {key: value for key, value in request.args.items()
                  if key in ('q', 'location', 'date', 'sort', 'month', 'day') and value}
        params.update(view=mode or view, month=month_key)
        params.update(changes)
        return url_for('competitions.index', **params)

    orders = {'date': Competition.event_date.asc(), 'date_desc': Competition.event_date.desc(),
              'name': Competition.title.asc(), 'name_desc': Competition.title.desc()}
    sort = request.args.get('sort', 'date_desc' if view == 'past' else 'date')
    # Counts come from a grouped join rather than loading Result/Horse/Jockey objects.
    query = (select(Competition, func.count(Result.id).label('participants'))
             .outerjoin(Result).where(*conditions).group_by(Competition.id))
    context = dict(view=view, total=total, sort=sort, browse_url=browse_url, month=month)
    if view == 'calendar':
        query = query.where(Competition.event_date >= month, Competition.event_date < following)
    query = query.order_by(orders.get(sort, orders['date_desc' if view == 'past' else 'date']),
                           Competition.event_time, Competition.id)
    if request.args.get('export') == 'csv':
        rows = db.session.execute(query).all()
        return csv_response(['Название', 'Дата', 'Время', 'Место', 'Участников', 'Статус'],
            [(c.title, c.formatted_date, c.formatted_time, c.location, n,
              'Завершено' if c.is_completed else 'Запланировано') for c, n in rows], 'competitions-' + view)
    if view == 'calendar':
        events = db.session.execute(query).all()
        by_day = defaultdict(list)
        for competition, participants in events:
            by_day[competition.event_date].append((competition, participants))
        try:
            selected = date.fromisoformat(request.args.get('day', ''))
            if selected.replace(day=1) != month:
                raise ValueError
        except (ValueError, TypeError):
            selected = min(by_day) if by_day else month
        context.update(events=events, by_day=by_day, selected_day=selected,
            weeks=calendar.Calendar().monthdatescalendar(month.year, month.month),
            previous=previous.strftime('%Y-%m'), following=following.strftime('%Y-%m'),
            month_label=f'{("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")[month.month - 1]} {month.year}')
    else:
        pages = max(1, (total + 19) // 20)
        page = min(max(1, request.args.get('page', 1, type=int)), pages)
        context.update(entries=db.session.execute(query.limit(20).offset((page - 1) * 20)).all(),
                       page=page, pages=pages)
    return render_template('competitions/index.html', **context)
