import math
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import update
from app import db
from app.models import Competition, Result, Horse, Jockey

def parse_time_input(time_str: str) -> float:
    """
    Парсит строку времени результата в секунды (float).
    Поддерживаемые форматы:
    - Секунды: "124", "124.5", "85.25"
    - Минуты и секунды: "02:04.50", "2:04.5", "1:45", "01:25"
    """
    if not time_str or not time_str.strip():
        raise ValueError("Время результата не заполнено")
    
    val = time_str.strip().replace(',', '.')
    
    # Формат MM:SS или MM:SS.ss
    if ':' in val:
        parts = val.split(':')
        if len(parts) != 2:
            raise ValueError("Некорректно указано время результата")
        try:
            minutes = int(parts[0])
            seconds = float(parts[1])
            if minutes < 0 or seconds < 0 or seconds >= 60:
                raise ValueError("Некорректно указано время результата")
            total = minutes * 60 + seconds
            if not math.isfinite(total) or round(total, 2) <= 0:
                raise ValueError("Некорректно указано время результата")
            return round(total, 2)
        except (ValueError, OverflowError):
            raise ValueError("Некорректно указано время результата")
    else:
        try:
            total = float(val)
            if not math.isfinite(total) or round(total, 2) <= 0:
                raise ValueError("Некорректно указано время результата")
            return round(total, 2)
        except (ValueError, OverflowError):
            raise ValueError("Некорректно указано время результата")


def participant_id(value):
    """Проверка диапазона Integer фактически выбранной СУБД."""
    try:
        identifier = int(value)
        limit = 2147483647 if db.engine.dialect.name == 'postgresql' else 9223372036854775807
        if not 1 <= identifier <= limit:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Выбрана несуществующая лошадь или жокей") from None
    return identifier


def create_future_competition(title: str, event_date_val, event_time_val, location: str, participants: list):
    """
    Создает запланированное состязание с парами (лошадь, жокей).
    participants: list of dicts [{'horse_id': int, 'jockey_id': int}, ...]
    """
    if not title or not title.strip():
        raise ValueError("Наименование состязания обязательно")
    if not location or not location.strip():
        raise ValueError("Место проведения (ипподром) обязательно")
    if not event_date_val:
        raise ValueError("Дата состязания обязательна")
    if not event_time_val:
        raise ValueError("Время состязания обязательно")
    if not participants or len(participants) < 1:
        raise ValueError("Необходимо заявить хотя бы одного участника")

    # Проверка уникальности лошадей и жокеев в списке
    horse_ids = set()
    jockey_ids = set()
    
    for p in participants:
        h_id = p.get('horse_id')
        j_id = p.get('jockey_id')

        if not h_id:
            raise ValueError("Для каждого участника необходимо выбрать лошадь")
        if not j_id:
            raise ValueError("Для выбранной лошади необходимо указать жокея")

        h_id = participant_id(h_id)
        j_id = participant_id(j_id)

        if h_id in horse_ids:
            horse = db.session.get(Horse, h_id)
            name = horse.nickname if horse else f"ID {h_id}"
            raise ValueError(f"Лошадь «{name}» уже заявлена на это состязание")
        if j_id in jockey_ids:
            jockey = db.session.get(Jockey, j_id)
            name = jockey.full_name if jockey else f"ID {j_id}"
            raise ValueError(f"Жокей «{name}» уже заявлен на это состязание")

        if not db.session.get(Horse, h_id) or not db.session.get(Jockey, j_id):
            raise ValueError("Выбрана несуществующая лошадь или жокей")

        horse_ids.add(h_id)
        jockey_ids.add(j_id)

    competition = Competition(
        title=title.strip(),
        event_date=event_date_val,
        event_time=event_time_val,
        location=location.strip(),
        status='planned'
    )
    db.session.add(competition)
    db.session.flush()

    for p in participants:
        res = Result(
            competition_id=competition.id,
            horse_id=int(p['horse_id']),
            jockey_id=int(p['jockey_id']),
            finish_time_seconds=None,
            is_disqualified=False,
            place=None
        )
        db.session.add(res)

    db.session.commit()
    return competition


def complete_planned_competition(competition_id: int, results_data: dict):
    """
    Завершает ранее запланированное состязание.
    results_data: словарь {result_id: {'time_str': str, 'is_disqualified': bool}}
    """
    competition = db.session.execute(db.select(Competition).where(Competition.id == competition_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not competition:
        raise ValueError("Состязание не найдено")
    
    if competition.status != 'planned':
        raise ValueError("Результаты завершенного состязания изменять нельзя")

    results = Result.query.filter_by(competition_id=competition.id).all()
    if not results:
        raise ValueError("У данного состязания отсутствуют участники")

    # Валидация: каждый участник должен иметь либо время, либо дисквалификацию
    prepared_results = []
    for r in results:
        data = results_data.get(r.id) or results_data.get(str(r.id))
        if not data:
            raise ValueError("Для каждого участника необходимо указать время или дисквалификацию")

        is_disq = bool(data.get('is_disqualified', False))
        time_str = data.get('time_str', '').strip()

        if not is_disq and not time_str:
            raise ValueError("Для каждого участника необходимо указать время или дисквалификацию")

        if is_disq and time_str:
            raise ValueError("Нельзя одновременно указать время и дисквалификацию")

        parsed_time = None
        if not is_disq:
            parsed_time = parse_time_input(time_str)

        prepared_results.append({
            'result_obj': r,
            'is_disqualified': is_disq,
            'time_seconds': parsed_time
        })

    # Расчет мест
    # Сортируем недисквалифицированных по возрастанию времени
    non_disqualified = [pr for pr in prepared_results if not pr['is_disqualified']]
    non_disqualified.sort(key=lambda x: x['time_seconds'])

    current_place = 1
    for i, pr in enumerate(non_disqualified):
        # Присваиваем места 1, 2, 3...
        # Если время совпадает с предыдущим, делят место или последовательно
        if i > 0 and pr['time_seconds'] == non_disqualified[i - 1]['time_seconds']:
            pr['place'] = non_disqualified[i - 1]['place']
        else:
            pr['place'] = current_place
        current_place += 1

    # Compare-and-set защищает от двух одновременных завершений и в SQLite,
    # где SELECT FOR UPDATE не поддерживается. Обновление входит в общую транзакцию.
    changed = db.session.execute(
        update(Competition).where(
            Competition.id == competition.id, Competition.status == 'planned'
        ).values(status='completed').execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise ValueError("Результаты завершенного состязания изменять нельзя")

    # Записываем в базу
    for pr in prepared_results:
        r = pr['result_obj']
        r.is_disqualified = pr['is_disqualified']
        r.finish_time_seconds = pr['time_seconds']
        r.place = pr.get('place', None)

    competition.status = 'completed'
    db.session.commit()
    return competition


def create_completed_competition_direct(title: str, event_date_val, event_time_val, location: str, participants: list):
    """
    Создает прошедшее состязание «в один проход» сразу со статусом completed.
    participants: list of dicts [{'horse_id': int, 'jockey_id': int, 'time_str': str, 'is_disqualified': bool}]
    """
    if not title or not title.strip():
        raise ValueError("Наименование состязания обязательно")
    if not location or not location.strip():
        raise ValueError("Место проведения (ипподром) обязательно")
    if not event_date_val:
        raise ValueError("Дата состязания обязательна")
    if not event_time_val:
        raise ValueError("Время состязания обязательно")
    if not participants or len(participants) < 1:
        raise ValueError("Необходимо заявить хотя бы одного участника")

    horse_ids = set()
    jockey_ids = set()
    prepared = []

    for p in participants:
        h_id = p.get('horse_id')
        j_id = p.get('jockey_id')

        if not h_id:
            raise ValueError("Для каждого участника необходимо выбрать лошадь")
        if not j_id:
            raise ValueError("Для выбранной лошади необходимо указать жокея")

        h_id = participant_id(h_id)
        j_id = participant_id(j_id)

        if h_id in horse_ids:
            horse = db.session.get(Horse, h_id)
            name = horse.nickname if horse else f"ID {h_id}"
            raise ValueError(f"Лошадь «{name}» уже заявлена на это состязание")
        if j_id in jockey_ids:
            jockey = db.session.get(Jockey, j_id)
            name = jockey.full_name if jockey else f"ID {j_id}"
            raise ValueError(f"Жокей «{name}» уже заявлен на это состязание")

        if not db.session.get(Horse, h_id) or not db.session.get(Jockey, j_id):
            raise ValueError("Выбрана несуществующая лошадь или жокей")

        horse_ids.add(h_id)
        jockey_ids.add(j_id)

        is_disq = bool(p.get('is_disqualified', False))
        time_str = p.get('time_str', '').strip()

        if not is_disq and not time_str:
            raise ValueError("Для каждого участника необходимо указать время или дисквалификацию")

        if is_disq and time_str:
            raise ValueError("Нельзя одновременно указать время и дисквалификацию")

        parsed_time = None
        if not is_disq:
            parsed_time = parse_time_input(time_str)

        prepared.append({
            'horse_id': h_id,
            'jockey_id': j_id,
            'is_disqualified': is_disq,
            'time_seconds': parsed_time
        })

    # Расчет мест
    non_disqualified = [item for item in prepared if not item['is_disqualified']]
    non_disqualified.sort(key=lambda x: x['time_seconds'])

    current_place = 1
    for i, item in enumerate(non_disqualified):
        if i > 0 and item['time_seconds'] == non_disqualified[i - 1]['time_seconds']:
            item['place'] = non_disqualified[i - 1]['place']
        else:
            item['place'] = current_place
        current_place += 1

    competition = Competition(
        title=title.strip(),
        event_date=event_date_val,
        event_time=event_time_val,
        location=location.strip(),
        status='completed'
    )
    db.session.add(competition)
    db.session.flush()

    for item in prepared:
        res = Result(
            competition_id=competition.id,
            horse_id=item['horse_id'],
            jockey_id=item['jockey_id'],
            finish_time_seconds=item['time_seconds'],
            is_disqualified=item['is_disqualified'],
            place=item.get('place', None)
        )
        db.session.add(res)

    db.session.commit()
    return competition


def atomic(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise ValueError("Не удалось сохранить состязание. Проверьте участников и повторите попытку.") from exc
        except Exception:
            db.session.rollback()
            raise
    return wrapped

create_future_competition = atomic(create_future_competition)
complete_planned_competition = atomic(complete_planned_competition)
create_completed_competition_direct = atomic(create_completed_competition_direct)
