"""Administrative transactions: one competition lock, provenance, audit and messages.

PostgreSQL locks the competition before reading participants. A revision compare-and-
set provides the same stale-write rejection on SQLite. No operation commits halfway.
"""
import re
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import select, update, or_, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app import db
from app.models import (Application, ApplicationEvent, AuditLog, Competition, Horse,
                        Jockey, Notification, Owner, Result, User, utc_now)
from app.permissions import can
from app.services import participant_id, parse_time_input


def transaction(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise ValueError('Данные изменены другим запросом или не удалось сохранить операцию. Обновите страницу.') from exc
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def authorize(actor, system=False):
    if actor is None or not getattr(actor, 'is_authenticated', False):
        raise PermissionError('Недостаточно прав.')
    # Refresh status/role even when a caller holds an old ORM object.
    actor = db.session.scalar(select(User).where(User.id == actor.id)
                              .with_for_update().execution_options(populate_existing=True)) if actor else None
    if actor is None or not can('manage_system' if system else 'manage_competitions', user=actor):
        raise PermissionError('Недостаточно прав.')
    return actor


def reason_text(value):
    value = (value or '').strip()
    if not 5 <= len(value) <= 500:
        raise ValueError('Укажите причину: от 5 до 500 символов, без секретов.')
    if re.search(r'(?:postgres(?:ql)?(?:\+psycopg)?://|(?:password|token|cookie|secret|authorization)\s*[:=])', value, re.I):
        raise ValueError('Причина не должна содержать секреты или строки подключения.')
    return value


def audit(actor, action, kind, identifier, *, reason=None, old=None, new=None):
    entry = AuditLog(actor_id=actor.id, action=action, object_type=kind,
                     object_id=identifier, reason=reason, old_values=old, new_values=new)
    db.session.add(entry)
    db.session.flush()
    return entry


def message(entry, recipients, text, competition_id=None):
    for identifier in set(recipients):
        if identifier:
            db.session.add(Notification(user_id=identifier, audit_id=entry.id,
                                        competition_id=competition_id, message=text))


def lock_competition(identifier):
    comp = db.session.scalar(select(Competition).where(Competition.id == participant_id(identifier))
                             .with_for_update().execution_options(populate_existing=True))
    if comp is None:
        raise ValueError('Соревнование не найдено.')
    changed = db.session.execute(update(Competition).where(Competition.id == comp.id,
        Competition.revision == comp.revision).values(revision=Competition.revision + 1)
        .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        from app.application_services import ApplicationConflict
        raise ApplicationConflict('Соревнование изменено другим запросом. Обновите страницу.')
    db.session.refresh(comp)
    return comp


def start_at(comp):
    return datetime.combine(comp.event_date, comp.event_time,
                            tzinfo=ZoneInfo(current_app.config['CLUB_TIMEZONE']))


def before_start(comp):
    if comp.status != 'planned' or utc_now() >= start_at(comp):
        raise ValueError('Изменения допускаются только до начала запланированного соревнования.')


def competition_values(data):
    from app.application_services import as_utc
    allowed = {'title', 'location', 'event_date', 'event_time', 'distance', 'max_participants', 'registration_deadline'}
    if set(data) - allowed:
        raise ValueError('Переданы недопустимые поля соревнования.')
    values = {}
    for name, maximum in [('title', 200), ('location', 200)]:
        values[name] = str(data.get(name, '')).strip()
        if not 1 <= len(values[name]) <= maximum:
            raise ValueError(f'Поле {name}: от 1 до {maximum} символов.')
    try:
        values['event_date'] = datetime.strptime(str(data.get('event_date', '')), '%Y-%m-%d').date()
        values['event_time'] = datetime.strptime(str(data.get('event_time', '')), '%H:%M').time()
        for name, low, high in [('distance', 100, 100000), ('max_participants', 1, 1000)]:
            values[name] = int(data.get(name, ''))
            if not low <= values[name] <= high:
                raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Проверьте дату, время, дистанцию (100–100000 м) и лимит (1–1000).') from None
    deadline = data.get('registration_deadline')
    try:
        values['registration_deadline'] = as_utc(datetime.strptime(deadline, '%Y-%m-%dT%H:%M').replace(
            tzinfo=ZoneInfo(current_app.config['CLUB_TIMEZONE']))) if deadline else None
    except (ValueError, TypeError):
        raise ValueError('Некорректный срок регистрации.') from None
    candidate = Competition(**values, status='planned')
    if start_at(candidate) <= utc_now():
        raise ValueError('Начало соревнования должно быть в будущем.')
    if values['registration_deadline'] and (values['registration_deadline'] > start_at(candidate)
                                           or values['registration_deadline'] <= utc_now()):
        raise ValueError('Срок регистрации не может быть позже начала соревнования или в прошлом.')
    return values


def competition_snapshot(comp):
    return {key: (getattr(comp, key).isoformat() if hasattr(getattr(comp, key), 'isoformat') else getattr(comp, key))
            for key in ('title', 'location', 'event_date', 'event_time', 'distance', 'max_participants', 'registration_deadline')}


@transaction
def save_competition(actor, data, identifier=None):
    actor = authorize(actor)
    values = competition_values(data)
    if identifier is None:
        comp = Competition(**values, status='planned')
        db.session.add(comp)
        db.session.flush()
        old = None
    else:
        comp = lock_competition(identifier)
        before_start(comp)
        old = competition_snapshot(comp)
        # Existing invitations/consents refer to concrete conditions. Freeze those
        # conditions as soon as any active application or legacy participant exists.
        occupied = db.session.scalar(select(Result.id).where(Result.competition_id == comp.id).limit(1))
        active = db.session.scalar(select(Application.id).where(Application.competition_id == comp.id,
            Application.status.not_in(['rejected', 'cancelled'])).limit(1))
        if occupied or active:
            raise ValueError('Параметры зафиксированы действующими заявками или участниками. Изменение нарушит согласованные условия.')
        for key, value in values.items():
            setattr(comp, key, value)
    audit(actor, 'competition_updated' if identifier else 'competition_created', 'competition', comp.id,
          old=old, new=competition_snapshot(comp))
    db.session.commit()
    return comp


def participants(comp):
    return db.session.scalars(select(Result).where(Result.competition_id == comp.id)
                              .options(selectinload(Result.horse), selectinload(Result.application))
                              .order_by(Result.start_number, Result.id).execution_options(populate_existing=True)).all()


def reserve_participant(comp, horse_id, jockey_id, application=None):
    rows = participants(comp)
    if any(row.horse_id == horse_id or row.jockey_id == jockey_id for row in rows):
        raise ValueError('Лошадь или жокей уже присутствуют в стартовом списке.')
    if comp.max_participants is not None and len(rows) >= comp.max_participants:
        raise ValueError('Лимит участников исчерпан.')
    # Null historical numbers are displayed as legacy, never rewritten.
    number = max([row.start_number or 0 for row in rows] + [0]) + 1
    result = Result(competition_id=comp.id, horse_id=horse_id, jockey_id=jockey_id,
                    start_number=number, application_id=application.id if application else None)
    db.session.add(result)
    db.session.flush()
    return result


def valid_consents(application):
    """Legacy ROOT actions cannot qualify as either participant's personal consent."""
    from app.application_services import active_account
    owner = active_account(application.horse.owner_id, 'owner')
    jockey = active_account(application.jockey_id, 'jockey')
    if (owner.id, jockey.id) != (application.owner_user_id, application.jockey_user_id):
        raise ValueError('Изменена привязка профиля. Нужна новая заявка.')
    if not application.owner_confirmed_at or not application.jockey_confirmed_at:
        raise ValueError('Необходимо личное согласие обеих сторон.')
    events = db.session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == application.id,
        ApplicationEvent.action.in_(['created', 'confirmed']))).all()
    expected_initiator = owner.id if application.initiator_side == 'owner' else jockey.id
    expected_other = jockey.id if application.initiator_side == 'owner' else owner.id
    if (application.initiator_id != expected_initiator
        or not any(e.action == 'created' and e.actor_id == expected_initiator for e in events)
        or not any(e.action == 'confirmed' and e.actor_id == expected_other for e in events)):
        raise ValueError('История не подтверждает личное согласие сторон. Отмените и подайте новую заявку.')


@transaction
def decide_admission(actor, identifier, action, reason=None):
    from app.application_services import record_event, notify
    actor = authorize(actor)
    application = db.session.get(Application, participant_id(identifier))
    if application is None:
        raise ValueError('Заявка не найдена.')
    comp = lock_competition(application.competition_id)
    before_start(comp)  # Admission may follow the registration deadline, before start.
    application = db.session.scalar(select(Application).where(Application.id == application.id)
        .with_for_update().execution_options(populate_existing=True))
    previous = application.status
    if action == 'approve':
        if previous != 'pending_admin':
            raise ValueError('Заявка уже рассмотрена или ещё не согласована обеими сторонами.')
        valid_consents(application)
        result = reserve_participant(comp, application.horse_id, application.jockey_id, application)
        application.status = 'admin_confirmed'
        entry = audit(actor, 'application_approved', 'application', application.id,
                      old={'status': previous}, new={'status': application.status, 'result_id': result.id, 'start_number': result.start_number})
        text = 'Заявка допущена администратором. Официальный стартовый список обновлён.'
        event_action = 'confirmed'
    elif action == 'reject':
        if previous not in ('awaiting_owner', 'awaiting_jockey', 'pending_admin'):
            raise ValueError('Заявка уже рассмотрена.')
        reason = reason_text(reason)
        application.status = 'rejected'
        entry = audit(actor, 'application_rejected', 'application', application.id, reason=reason,
                      old={'status': previous}, new={'status': application.status})
        text = 'Заявка отклонена администратором. Причина: ' + reason[:220]
        event_action = 'rejected'
    else:
        raise ValueError('Неизвестное действие.')
    application.updated_at = utc_now()
    event = record_event(application, actor, event_action)
    notify(application, event, [application.owner_user_id, application.jockey_user_id], text)
    if action == 'approve':
        recipients = starter_accounts(comp) - {application.owner_user_id, application.jockey_user_id}
        message(entry, recipients, 'Официальный стартовый список соревнования обновлён.', comp.id)
    db.session.commit()
    return application


def starter_accounts(comp):
    rows = participants(comp)
    owner_ids = [row.horse.owner_id for row in rows]
    jockey_ids = [row.jockey_id for row in rows]
    return set(db.session.scalars(select(User.id).where(or_(User.owner_id.in_(owner_ids), User.jockey_id.in_(jockey_ids)))))


@transaction
def manual_participant(actor, identifier, horse_id, jockey_id, reason):
    """ROOT exception; it records administrative admission, never personal consent."""
    actor = authorize(actor, system=True)
    reason = reason_text(reason)
    comp = lock_competition(identifier)
    before_start(comp)
    horse = db.session.get(Horse, participant_id(horse_id))
    jockey = db.session.get(Jockey, participant_id(jockey_id))
    if not horse or not jockey:
        raise ValueError('Лошадь или жокей не найдены.')
    disabled = db.session.scalar(select(User.id).where(User.status != 'active',
        or_(User.owner_id == horse.owner_id, User.jockey_id == jockey.id)).limit(1))
    if disabled:
        raise ValueError('Участник связан с заблокированным аккаунтом. Ручной допуск запрещён.')
    conflict = db.session.scalar(select(Application.id).where(Application.competition_id == comp.id,
        Application.status.not_in(['rejected', 'cancelled']),
        or_(Application.horse_id == horse.id, Application.jockey_id == jockey.id)).limit(1))
    if conflict:
        raise ValueError('У пары есть действующая заявка. Используйте процедуру согласования и допуска.')
    row = reserve_participant(comp, horse.id, jockey.id)
    entry = audit(actor, 'participant_manually_added', 'result', row.id, reason=reason,
                  new={'competition_id': comp.id, 'horse_id': horse.id, 'jockey_id': jockey.id, 'start_number': row.start_number})
    message(entry, starter_accounts(comp), 'ROOT изменил официальный стартовый список административным исключением.', comp.id)
    db.session.commit()
    return row


def prepare_protocol(rows, data):
    if not rows or {str(key) for key in data} != {str(row.id) for row in rows}:
        raise ValueError('Заполните полный протокол только для всех допущенных участников.')
    prepared = []
    for row in rows:
        item = data.get(row.id, data.get(str(row.id)))
        if not isinstance(item, dict) or set(item) - {'time_str', 'is_disqualified', 'did_not_finish'}:
            raise ValueError('Некорректные поля результата.')
        if any(key in item and not isinstance(item[key], bool) for key in ('is_disqualified', 'did_not_finish')):
            raise ValueError('Исход результата должен быть логическим значением.')
        disq, dnf = bool(item.get('is_disqualified')), bool(item.get('did_not_finish'))
        value = str(item.get('time_str', '')).strip()
        if (disq and dnf) or ((disq or dnf) and value):
            raise ValueError('Укажите ровно один исход: время, дисквалификация или отсутствие финиша.')
        seconds = None if disq or dnf else parse_time_input(value)
        prepared.append((row, {'finish_time_seconds': seconds, 'is_disqualified': disq,
                                'did_not_finish': dnf, 'place': None}))
    finishers = sorted((item for item in prepared if item[1]['finish_time_seconds'] is not None),
                       key=lambda item: item[1]['finish_time_seconds'])
    for index, (_, values) in enumerate(finishers):
        values['place'] = (finishers[index-1][1]['place'] if index and values['finish_time_seconds'] ==
                           finishers[index-1][1]['finish_time_seconds'] else index + 1)
    return prepared


def protocol_snapshot(rows):
    return {str(row.id): {key: getattr(row, key) for key in
            ('horse_id', 'jockey_id', 'start_number', 'application_id', 'finish_time_seconds', 'is_disqualified', 'did_not_finish', 'place')}
            for row in rows}


@transaction
def publish_protocol(actor, identifier, data, *, correction_reason=None, expected_revision=None):
    correction = correction_reason is not None
    actor = authorize(actor, system=correction)
    if correction:
        correction_reason = reason_text(correction_reason)
    comp = lock_competition(identifier)
    if correction:
        if comp.status != 'completed':
            raise ValueError('Коррекция доступна только для опубликованного протокола.')
        if expected_revision is None or int(expected_revision) != comp.revision - 1:
            raise ValueError('Протокол уже изменён. Обновите форму коррекции.')
    elif comp.status != 'planned':
        raise ValueError('Результаты завершенного состязания изменять нельзя')
    elif start_at(comp) > utc_now():
        raise ValueError('Соревнование ещё не началось.')
    rows = participants(comp)
    for row in rows:
        if row.application_id and (row.application.status != 'admin_confirmed'
            or (row.application.competition_id, row.application.horse_id, row.application.jockey_id)
               != (comp.id, row.horse_id, row.jockey_id)):
            raise ValueError('Протокол содержит участника без действительного допуска.')
    old = protocol_snapshot(rows)
    prepared = prepare_protocol(rows, data)
    for row, values in prepared:
        for key, value in values.items():
            setattr(row, key, value)
    if correction and old == protocol_snapshot(rows):
        raise ValueError('Протокол не изменён. Коррекция не требуется.')
    comp.status = 'completed'
    entry = audit(actor, 'protocol_corrected' if correction else 'competition_completed', 'competition', comp.id,
                  reason=correction_reason, old=old, new=protocol_snapshot(rows))
    message(entry, starter_accounts(comp), 'Опубликована коррекция протокола.' if correction else
            'Соревнование завершено. Опубликованы результаты.', comp.id)
    db.session.commit()
    return comp


@transaction
def root_cancel(actor, identifier, reason):
    from app.application_services import record_event, notify
    actor = authorize(actor, system=True)
    reason = reason_text(reason)
    application = db.session.get(Application, participant_id(identifier))
    if not application:
        raise ValueError('Заявка не найдена.')
    comp = lock_competition(application.competition_id)
    before_start(comp)
    db.session.refresh(application)
    if application.status not in ('awaiting_owner', 'awaiting_jockey', 'pending_admin'):
        raise ValueError('Нельзя отменить рассмотренную заявку или официальный стартовый список.')
    old = application.status
    application.status = 'cancelled'
    application.updated_at = utc_now()
    audit(actor, 'root_application_cancelled', 'application', application.id, reason=reason,
          old={'status': old}, new={'status': 'cancelled'})
    event = record_event(application, actor, 'cancelled')
    notify(application, event, [application.owner_user_id, application.jockey_user_id], 'Заявка отменена ROOT. Причина: ' + reason[:230])
    db.session.commit()


@transaction
def update_user(actor, identifier, *, role, status, reason):
    actor = authorize(actor, system=True)
    reason = reason_text(reason)
    user = db.session.scalar(select(User).where(User.id == participant_id(identifier))
        .with_for_update().execution_options(populate_existing=True))
    if not user:
        raise ValueError('Аккаунт не найден.')
    if user.role == 'ROOT' or role == 'ROOT':
        raise ValueError('ROOT защищён: изменение роли и отключение через интерфейс запрещены.')
    if role not in ('ADMIN', 'VIEWER', 'OWNER', 'JOCKEY') or status not in ('active', 'disabled'):
        raise ValueError('Недопустимая роль или статус.')
    if role != user.role and (user.owner_id or user.jockey_id or role in ('OWNER', 'JOCKEY')):
        raise ValueError('Нельзя менять спортивную роль с нарушением привязок. Для исторического профиля используйте доверенную привязку.')
    old = {'role': user.role, 'status': user.status}
    new = {'role': role, 'status': status}
    if old == new:
        raise ValueError('Изменений нет.')
    changed = db.session.execute(update(User).where(User.id == user.id, User.role == old['role'],
        User.status == old['status']).values(role=role, status=status).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ValueError('Аккаунт изменён другим запросом. Обновите страницу.')
    db.session.refresh(user)
    entry = audit(actor, 'user_updated', 'user', user.id, reason=reason, old=old, new=new)
    if old['status'] != status:
        message(entry, [user.id], 'Аккаунт восстановлен.' if status == 'active' else 'Аккаунт заблокирован.')
    db.session.commit()
    return user


@transaction
def link_profile(actor, identifier, side, profile_id, reason):
    """After external ownership verification, link an unclaimed historic profile.

    Only an active VIEWER without profiles can be promoted. Existing sport accounts
    keep their profiles; no history or application recipients are silently moved.
    """
    actor = authorize(actor, system=True)
    reason = reason_text(reason)
    if side not in ('owner', 'jockey'):
        raise ValueError('Недопустимый тип профиля.')
    user = db.session.scalar(select(User).where(User.id == participant_id(identifier)).with_for_update()
                             .execution_options(populate_existing=True))
    if not user or user.role != 'VIEWER' or not user.is_active or user.owner_id or user.jockey_id:
        raise ValueError('Привязка доступна только активному зрителю без спортивного профиля.')
    model = Owner if side == 'owner' else Jockey
    profile = db.session.scalar(select(model).where(model.id == participant_id(profile_id)).with_for_update())
    if not profile:
        raise ValueError('Исторический профиль не найден.')
    column = User.owner_id if side == 'owner' else User.jockey_id
    if db.session.scalar(select(User.id).where(column == profile.id)):
        raise ValueError('Профиль уже принадлежит другому аккаунту.')
    old = {'role': user.role, 'owner_id': user.owner_id, 'jockey_id': user.jockey_id}
    changed = db.session.execute(update(User).where(User.id == user.id, User.role == 'VIEWER',
        User.status == 'active', User.owner_id.is_(None), User.jockey_id.is_(None))
        .values(**{'role': side.upper(), side + '_id': profile.id}).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ValueError('Аккаунт уже изменён другим запросом. Обновите страницу.')
    db.session.refresh(user)
    audit(actor, 'profile_linked', 'user', user.id, reason=reason, old=old,
          new={'role': user.role, 'owner_id': user.owner_id, 'jockey_id': user.jockey_id})
    db.session.commit()
    return user
