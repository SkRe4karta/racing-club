import math
from app import db

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


def create_future_competition(title, event_date_val, event_time_val, location,
                              participants=None, registration_deadline=None, *,
                              distance=1600, max_participants=20, actor=None):
    """Compatibility entrypoint: create only an empty, validated competition."""
    from app.admin_services import save_competition
    from flask_login import current_user
    if not event_date_val or not event_time_val:
        raise ValueError('Укажите дату и время соревнования.')
    if participants:
        raise ValueError('Создайте соревнование без участников. Используйте заявки и административный допуск.')
    if registration_deadline is not None:
        from app.application_services import as_utc
        from flask import current_app
        from zoneinfo import ZoneInfo
        registration_deadline = as_utc(registration_deadline).astimezone(ZoneInfo(current_app.config['CLUB_TIMEZONE']))
    data = dict(title=title, location=location, event_date=event_date_val.isoformat(),
                event_time=event_time_val.strftime('%H:%M'), distance=distance,
                max_participants=max_participants,
                registration_deadline=registration_deadline.strftime('%Y-%m-%dT%H:%M') if registration_deadline else '')
    return save_competition(actor if actor is not None else current_user, data)


def complete_planned_competition(competition_id, results_data, *, actor=None):
    """Publish the complete protocol through the single administrative workflow."""
    from app.admin_services import publish_protocol
    from flask_login import current_user
    return publish_protocol(actor if actor is not None else current_user, competition_id, results_data)


def create_completed_competition_direct(*args, **kwargs):
    """Legacy write bypass retired; historical records remain readable."""
    raise ValueError('Прямое создание завершённого протокола закрыто. Создайте соревнование, допустите участников и опубликуйте результаты.')
