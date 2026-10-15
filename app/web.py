"""Общие средства представления: фильтры, экспорт и защита форм."""
import calendar
import csv
import io
from datetime import date
from flask import request, url_for, Response, render_template
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import selectinload
from app import db
from app.models import Owner, Horse, Jockey, Competition, Result


@event.listens_for(Engine, 'connect')
def sqlite_settings(connection, record):
    if type(connection).__module__.startswith('sqlite3'):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.create_function('casefold', 1, lambda value: (value or '').casefold(), deterministic=True)


def contains(column, text):
    text = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    if db.engine.dialect.name == 'sqlite':
        return db.func.casefold(column).like('%' + text.casefold() + '%', escape='\\')
    # PostgreSQL с локалью C не понижает регистр кириллицы.
    upper = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'
    folded = db.func.translate(column, upper, upper.lower())
    return folded.ilike('%' + text.casefold() + '%', escape='\\')


def csv_response(headers, rows, filename):
    def safe(value):
        value = '' if value is None else str(value)
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(headers)
    writer.writerows([safe(v) for v in row] for row in rows)
    return Response('\ufeff' + stream.getvalue(), content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}.csv"'})


def listing(kind):
    models = {'owners': Owner, 'horses': Horse, 'jockeys': Jockey, 'future': Competition, 'past': Competition}
    model = models[kind]
    query = model.query
    name = model.nickname if kind == 'horses' else model.title if kind in ('future', 'past') else model.full_name
    sorts = {'name': name.asc(), 'name_desc': name.desc()}
    if kind == 'owners':
        query = query.options(selectinload(Owner.horses))
        if request.args.get('phone'):
            query = query.filter(contains(Owner.phone, request.args['phone']))
    elif kind == 'horses':
        query = query.join(Horse.owner).options(selectinload(Horse.owner))
        if request.args.get('owner'):
            query = query.filter(contains(Owner.full_name, request.args['owner']))
        if request.args.get('gender') in ('Жеребец', 'Кобыла', 'Мерин'):
            query = query.filter(Horse.gender == request.args['gender'])
        age = request.args.get('age', type=int)
        if age is not None and 1 <= age <= 40:
            query = query.filter(Horse.age == age)
        sorts.update(age=Horse.age.asc(), age_desc=Horse.age.desc())
    elif kind == 'jockeys':
        sorts.update(age=Jockey.age.asc(), age_desc=Jockey.age.desc(), rating=Jockey.rating.desc(), rating_asc=Jockey.rating.asc())
    else:
        query = query.filter_by(status='planned' if kind == 'future' else 'completed').options(selectinload(Competition.results).selectinload(Result.horse), selectinload(Competition.results).selectinload(Result.jockey))
        sorts.update(date=Competition.event_date.asc(), date_desc=Competition.event_date.desc())
        if request.args.get('location'):
            query = query.filter(contains(Competition.location, request.args['location']))
        try:
            if request.args.get('date'):
                query = query.filter(Competition.event_date == date.fromisoformat(request.args['date']))
        except (ValueError, OverflowError):
            pass
    if request.args.get('q', '').strip():
        query = query.filter(contains(name, request.args['q'].strip()))
    query = query.order_by(sorts.get(request.args.get('sort'), sorts.get('date' if kind == 'future' else 'date_desc' if kind == 'past' else 'name')), model.id)
    if request.args.get('export') == 'csv':
        rows = query.all()
        if kind == 'owners':
            headers = ['ФИО', 'Адрес', 'Телефон', 'Лошадей']
            data = [(r.full_name, r.address, r.phone, len(r.horses)) for r in rows]
        elif kind == 'horses':
            headers = ['Кличка', 'Пол', 'Возраст', 'Владелец']
            data = [(r.nickname, r.gender, r.age, r.owner.full_name) for r in rows]
        elif kind == 'jockeys':
            headers = ['ФИО', 'Адрес', 'Возраст', 'Рейтинг']
            data = [(r.full_name, r.address, r.age, r.rating) for r in rows]
        else:
            headers = ['Название', 'Дата', 'Время', 'Место', 'Участников']
            data = [(r.title, r.formatted_date, r.formatted_time, r.location, len(r.results)) for r in rows]
        return csv_response(headers, data, kind)
    template = {
        'future': 'competitions/future_list.html',
        'past': 'competitions/past_list.html',
    }.get(kind, f'{kind}/list.html')
    context = {'kind': kind}
    if kind == 'future' and request.args.get('view') == 'calendar':
        try:
            year, month = map(int, request.args.get('month', date.today().strftime('%Y-%m')).split('-'))
            first = date(year, month, 1)
            if year < 2 or year > 9998:
                raise ValueError
        except (ValueError, OverflowError):
            first = date.today().replace(day=1)
        prev = (first.replace(day=1).toordinal() - 1)
        nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
        context.update(weeks=calendar.Calendar().monthdatescalendar(first.year, first.month), month=first,
                       previous=date.fromordinal(prev).strftime('%Y-%m'), following=nxt.strftime('%Y-%m'),
                       events=query.filter(Competition.event_date >= first, Competition.event_date < nxt).all())
        return render_template(template, total=len(context['events']), **context)
    page = max(1, request.args.get('page', 1, type=int))
    total = query.count()
    pages = max(1, (total + 19) // 20)
    page = min(page, pages)
    context.update(items=query.limit(20).offset((page - 1) * 20).all(), page=page, pages=pages, total=total)
    return render_template(template, **context)


def setup_web(app):
    @app.before_request
    def validate_forms():
        id_limit = 2147483647 if db.engine.dialect.name == 'postgresql' else 9223372036854775807
        if any(isinstance(value, int) and value > id_limit for value in (request.view_args or {}).values()):
            return render_template('errors/404.html'), 404
        if request.method == 'POST':
            labels = {'full_name': 'ФИО', 'address': 'Адрес', 'phone': 'Телефон', 'nickname': 'Кличка', 'gender': 'Пол', 'title': 'Название', 'location': 'Место проведения'}
            # Ограничения длины берём из существующей схемы.
            for field, length in {'full_name':150, 'address':255, 'phone':50, 'nickname':100, 'gender':20, 'title':200, 'location':200}.items():
                if len(request.form.get(field, '').strip()) > length:
                    return render_template('errors/message.html', message=f'Поле «{labels[field]}»: максимум {length} символов. Вернитесь к форме и сократите значение.'), 400

    @app.context_processor
    def common_context():
        def query_url(**changes):
            params = request.args.to_dict()
            params.update(changes)
            return url_for(request.endpoint, **(request.view_args or {}), **params)
        def performance(results):
            finished = sorted([r for r in results if r.competition.is_completed], key=lambda r:(r.competition.event_date, r.competition.event_time), reverse=True)
            wins = sum(r.place == 1 and not r.is_disqualified for r in finished)
            return dict(count=len(finished), wins=wins, seconds=sum(r.place == 2 and not r.is_disqualified for r in finished), thirds=sum(r.place == 3 and not r.is_disqualified for r in finished), disqualifications=sum(r.is_disqualified for r in finished), dnf=sum(r.did_not_finish for r in finished), podium=sum(r.place in (1,2,3) and not r.is_disqualified for r in finished), rate=round(wins / len(finished)*100,1) if finished else None, last=finished[0] if finished else None)
        from app.analytics import performance_chart, comparable_times
        return dict(today=date.today(), query_url=query_url, performance=performance, performance_chart=performance_chart, comparable_times=comparable_times)

    @app.get('/health')
    def health():
        db.session.execute(db.text('SELECT 1'))
        return {'status': 'ok'}

    @app.get('/competitions/<int:comp_id>/results.csv')
    def export_results(comp_id):
        comp = db.get_or_404(Competition, comp_id)
        rows = sorted(comp.results, key=lambda r:(r.place is None, r.place or 0, r.id))
        return csv_response(['Место','Лошадь','Жокей','Время','Статус'], [(r.place,r.horse.nickname,r.jockey.full_name,r.formatted_finish_time,'Дисквалификация' if r.is_disqualified else 'Не финишировал (DNF)' if r.did_not_finish else 'Завершено' if comp.is_completed else 'Заявлен') for r in rows], f'results-{comp.id}')
