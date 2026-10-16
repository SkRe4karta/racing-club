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


def history_context(query):
    """Page ORM histories; compute period totals in SQL and load 24 chart points."""
    from sqlalchemy.orm import selectinload
    identifiers = query.with_entities(Result.id).order_by(None).statement
    base = select(Result).where(Result.id.in_(identifiers)).join(Result.competition)
    completed = base.where(Competition.status == 'completed')
    valid = and_(Result.is_disqualified.is_(False), Result.did_not_finish.is_(False))
    columns = [func.count(Result.id)] + [func.coalesce(func.sum(case((and_(valid, Result.place == place), 1), else_=0)), 0)
                                       for place in (1, 2, 3)]
    columns += [func.coalesce(func.sum(case((column.is_(True), 1), else_=0)), 0)
                for column in (Result.is_disqualified, Result.did_not_finish)]
    count, wins, seconds, thirds, dsq, dnf = db.session.execute(completed.with_only_columns(*columns)).one()
    loaded = base.options(selectinload(Result.competition), selectinload(Result.horse), selectinload(Result.jockey))
    order = (Competition.event_date.desc(), Competition.event_time.desc(), Result.id.desc())
    pagination = db.paginate(loaded.order_by(*order), per_page=20, error_out=False)
    chart_rows = db.session.scalars(loaded.where(Competition.status == 'completed').order_by(*order).limit(24)).all()
    averages = db.session.execute(completed.where(valid, Result.finish_time_seconds > 0, Competition.distance.is_not(None))
        .with_only_columns(Competition.distance, func.avg(Result.finish_time_seconds), func.count(Result.id))
        .group_by(Competition.distance).order_by(Competition.distance)).all()
    metric = dict(count=count, wins=wins, seconds=seconds, thirds=thirds, podium=wins+seconds+thirds,
                  disqualifications=dsq, dnf=dnf, rate=round(100*wins/count, 1) if count else None,
                  last=chart_rows[0] if chart_rows else None)
    return dict(results=pagination.items, pagination=pagination, history_metric=metric,
                history_chart=performance_chart(chart_rows),
                history_averages=[(distance, round(average, 2), n) for distance, average, n in averages])


def horse_cards_from_database(horses):
    """Aggregate all performances without materializing a horse's complete history."""
    identifiers = [h.id for h in horses]
    valid = and_(Result.is_disqualified.is_(False), Result.did_not_finish.is_(False))
    rows = db.session.execute(select(Result.horse_id, func.count(Result.id),
        func.sum(case((and_(valid, Result.place == 1), 1), else_=0)),
        func.sum(case((and_(valid, Result.place.between(1, 3)), 1), else_=0)))
        .join(Competition).where(Result.horse_id.in_(identifiers), Competition.status == 'completed')
        .group_by(Result.horse_id)).all()
    data = {h.id: dict(starts=0, wins=0, podium=0, next_result=None) for h in horses}
    for identifier, starts, wins, podium in rows:
        data[identifier].update(starts=starts, wins=wins, podium=podium)
    from app.models import utc_now
    from app.admin_services import start_at
    from sqlalchemy.orm import selectinload
    for row in db.session.scalars(select(Result).join(Competition)
            .where(Result.horse_id.in_(identifiers), Competition.status == 'planned')
            .options(selectinload(Result.competition), selectinload(Result.horse), selectinload(Result.jockey))
            .order_by(Competition.event_date, Competition.event_time)):
        if start_at(row.competition) > utc_now() and data[row.horse_id]['next_result'] is None:
            data[row.horse_id]['next_result'] = row
    return data
