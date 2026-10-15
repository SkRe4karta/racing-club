"""Sporting aggregates use completed protocols only; times stay distance-specific."""
from sqlalchemy import select, func, case, and_, extract
from app.models import Competition, Horse, Jockey, Result
from app import db


def completed_conditions(start=None, end=None):
    conditions = [Competition.status == 'completed']
    if start:
        conditions.append(Competition.event_date >= start)
    if end:
        conditions.append(Competition.event_date <= end)
    return conditions


def rankings(kind='horses', start=None, end=None):
    model = Jockey if kind == 'jockeys' else Horse
    identity = Result.jockey_id if kind == 'jockeys' else Result.horse_id
    valid = and_(Result.is_disqualified.is_(False), Result.did_not_finish.is_(False),
                 Result.finish_time_seconds > 0)
    wins = func.sum(case((and_(valid, Result.place == 1), 1), else_=0))
    podium = func.sum(case((and_(valid, Result.place.between(1, 3)), 1), else_=0))
    return (select(model, func.count(Result.id).label('starts'), wins.label('wins'), podium.label('podium'),
        func.sum(case((Result.is_disqualified.is_(True), 1), else_=0)).label('dsq'),
        func.sum(case((Result.did_not_finish.is_(True), 1), else_=0)).label('dnf'))
        .join(Result, identity == model.id).join(Competition)
        .where(*completed_conditions(start, end)).group_by(model.id)
        .order_by(wins.desc(), podium.desc(), func.count(Result.id).desc(), model.id))


def distance_averages(start=None, end=None):
    return db.session.execute(select(Competition.distance, func.avg(Result.finish_time_seconds), func.count(Result.id))
        .join(Result).where(*completed_conditions(start, end), Competition.distance.is_not(None),
            Result.is_disqualified.is_(False), Result.did_not_finish.is_(False), Result.finish_time_seconds > 0)
        .group_by(Competition.distance).order_by(Competition.distance)).all()


def seasons(start=None, end=None):
    return db.session.execute(select(extract('year', Competition.event_date).label('season'),
        func.count(Result.id), func.sum(case((and_(Result.place == 1,
            Result.is_disqualified.is_(False), Result.did_not_finish.is_(False), Result.finish_time_seconds > 0), 1), else_=0)))
        .join(Result).where(*completed_conditions(start, end)).group_by('season').order_by('season')).all()


def performance_chart(results):
    completed = sorted((r for r in results if r.competition.is_completed),
                       key=lambda r: (r.competition.event_date, r.competition.event_time, r.id))[-24:]
    return dict(labels=[r.competition.formatted_date for r in completed],
                values=[r.place if not r.is_disqualified and not r.did_not_finish else None for r in completed])


def comparable_times(results):
    groups = {}
    for row in results:
        if (row.competition.is_completed and row.competition.distance and row.finish_time_seconds
                and not row.is_disqualified and not row.did_not_finish):
            groups.setdefault(row.competition.distance, []).append(row.finish_time_seconds)
    return [(distance, round(sum(times) / len(times), 2), len(times)) for distance, times in sorted(groups.items())]


def filter_history(query):
    """Apply explicit inclusive dates to an already joined performance query."""
    from datetime import date
    from flask import abort, request
    bounds = []
    for key in ('from', 'to'):
        value = request.args.get(key)
        try:
            bounds.append(date.fromisoformat(value) if value else None)
        except ValueError:
            abort(400, description='Некорректный период истории выступлений.')
    start, end = bounds
    if start and end and start > end:
        abort(400, description='Некорректный период истории выступлений.')
    if start:
        query = query.filter(Competition.event_date >= start)
    if end:
        query = query.filter(Competition.event_date <= end)
    return query


def sporting_summary(results):
    """Facts for compact cards; caller supplies the already eager-loaded history."""
    completed = [row for row in results if row.competition.is_completed]
    finishers = [row for row in completed if row.finish_time_seconds and
                 not row.did_not_finish and not row.is_disqualified]
    return dict(starts=len(completed), wins=sum(row.place == 1 for row in finishers),
                podium=sum(row.place in (1, 2, 3) for row in finishers))


def horse_card_data(horses, results):
    from app.admin_services import start_at
    from app.models import utc_now
    histories = {horse.id: [] for horse in horses}
    for row in results:
        if row.horse_id in histories:
            histories[row.horse_id].append(row)
    data = {}
    now = utc_now()
    for horse in horses:
        history = histories[horse.id]
        upcoming = [row for row in history if row.competition.status == 'planned'
                    and start_at(row.competition) > now]
        data[horse.id] = {**sporting_summary(history), 'next_result': min(
            upcoming, key=lambda row: start_at(row.competition), default=None)}
    return data
