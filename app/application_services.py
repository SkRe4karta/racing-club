"""Atomic application workflow. No operation here writes sporting results."""
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import db
from app.models import Application, ApplicationEvent, Competition, Horse, Jockey, Notification, Result, User, utc_now
from app.permissions import can
from app.services import participant_id


class ApplicationConflict(ValueError):
    """The form is stale, the pair is occupied, or the workflow has already changed."""


def workflow(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except IntegrityError as exc:
            db.session.rollback()
            raise ApplicationConflict('Лошадь или жокей уже заявлены на этот заезд. Обновите список заявок.') from exc
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise ApplicationConflict('Не удалось сохранить заявку. Обновите страницу и повторите попытку.') from exc
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def as_utc(value):
    # SQLite returns naive timestamps for DateTime(timezone=True).
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def registration_closes(competition):
    """Naive sporting date/time use the configured club timezone; deadlines use UTC."""
    start = datetime.combine(competition.event_date, competition.event_time,
                             tzinfo=ZoneInfo(current_app.config['CLUB_TIMEZONE'])).astimezone(timezone.utc)
    return min(start, as_utc(competition.registration_deadline)) if competition.registration_deadline else start


def registration_open(competition):
    return competition.status == 'planned' and utc_now() < registration_closes(competition)


def locked_competition(identifier):
    competition = db.session.scalar(select(Competition).where(
        Competition.id == participant_id(identifier)).with_for_update().execution_options(populate_existing=True))
    if not competition:
        raise ValueError('Соревнование не найдено.')
    if not registration_open(competition):
        raise ApplicationConflict('Регистрация закрыта или соревнование завершено.')
    return competition


def record_event(application, actor, action):
    event = ApplicationEvent(application_id=application.id, actor_id=actor.id,
                             action=action, status=application.status)
    db.session.add(event)
    db.session.flush()
    return event


def notify(application, event, recipients, message):
    for user_id in set(recipients):
        db.session.add(Notification(user_id=user_id, application_id=application.id,
                                    event_id=event.id, message=message))


def active_account(profile_id, side):
    column = User.owner_id if side == 'owner' else User.jockey_id
    user = db.session.scalar(select(User).where(column == profile_id,
                             User.role == side.upper(), User.status == 'active'))
    if not user:
        raise ValueError('У выбранного владельца или жокея нет активного связанного аккаунта. Согласие получить невозможно.')
    return user


@workflow
def create_application(actor, competition_id, horse_id, jockey_id=None, side=None):
    """The initiator consents once; only the other party can consent subsequently."""
    if not can('create_application', user=actor):
        raise PermissionError
    side = side if actor.role == 'ROOT' else actor.role.lower()
    if side not in ('owner', 'jockey'):
        raise ValueError('Выберите сторону подачи заявки.')
    competition = locked_competition(competition_id)
    horse = db.session.get(Horse, participant_id(horse_id))
    if not horse:
        raise ValueError('Лошадь не найдена.')
    if actor.role == 'OWNER' and horse.owner_id != actor.owner_id:
        raise PermissionError
    if actor.role == 'JOCKEY':
        if jockey_id is not None and participant_id(jockey_id) != actor.jockey_id:
            raise PermissionError
        jockey_id = actor.jockey_id
    jockey = db.session.get(Jockey, participant_id(jockey_id))
    if not jockey:
        raise ValueError('Жокей не найден.')
    owner_user = active_account(horse.owner_id, 'owner')
    jockey_user = active_account(jockey.id, 'jockey')
    # Preserve existing Alpha 1 planned participants: applications cannot replace them.
    occupied = db.session.scalar(select(Result.id).where(Result.competition_id == competition.id,
                                or_(Result.horse_id == horse.id, Result.jockey_id == jockey.id)))
    if occupied:
        raise ApplicationConflict('Лошадь или жокей уже включены в прежний список участников.')
    now = utc_now()
    application = Application(competition_id=competition.id, horse_id=horse.id, jockey_id=jockey.id,
                              owner_user_id=owner_user.id, jockey_user_id=jockey_user.id,
                              initiator_id=actor.id, initiator_side=side,
                              status='awaiting_jockey' if side == 'owner' else 'awaiting_owner',
                              owner_confirmed_at=now if side == 'owner' else None,
                              jockey_confirmed_at=now if side == 'jockey' else None,
                              created_at=now, updated_at=now)
    db.session.add(application)
    db.session.flush()  # Partial unique indexes arbitrate simultaneous submissions.
    event = record_event(application, actor, 'created')
    notify(application, event, [jockey_user.id if side == 'owner' else owner_user.id],
           'Получено приглашение: подтвердите или отклоните заявку.')
    db.session.commit()
    return application


@workflow
def decide_application(actor, application_id, action):
    """Lock competition before application, then compare-and-set for SQLite too."""
    application_id = participant_id(application_id)
    application = db.session.get(Application, application_id)
    if not application or not can('view_application', application, user=actor):
        raise PermissionError
    locked_competition(application.competition_id)
    application = db.session.scalar(select(Application).where(Application.id == application_id)
                                    .with_for_update().execution_options(populate_existing=True))
    permission = 'cancel_application' if action == 'cancel' else 'confirm_application'
    if not can(permission, application, user=actor):
        if not application.is_active or application.status == 'pending_admin':
            raise ApplicationConflict('Решение уже принято. Обновите страницу заявки.')
        raise PermissionError
    if action not in ('confirm', 'reject', 'cancel'):
        raise ValueError('Неизвестное действие.')
    # A disabled/unlinked participant cannot receive consent on their behalf.
    if action == 'confirm':
        owner = active_account(application.horse.owner_id, 'owner')
        jockey = active_account(application.jockey_id, 'jockey')
        if (owner.id, jockey.id) != (application.owner_user_id, application.jockey_user_id):
            raise ApplicationConflict('Связь аккаунта с профилем изменилась. Подайте новую заявку.')
    now = utc_now()
    values = dict(updated_at=now)
    if action == 'confirm':
        values['status'] = 'pending_admin'
        values['owner_confirmed_at' if application.status == 'awaiting_owner' else 'jockey_confirmed_at'] = now
    else:
        values['status'] = 'rejected' if action == 'reject' else 'cancelled'
    previous_status = application.status
    changed = db.session.execute(update(Application).where(Application.id == application.id,
                                 Application.status == previous_status).values(**values)
                                 .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ApplicationConflict('Заявка уже изменена другим запросом. Обновите страницу.')
    db.session.refresh(application)
    event = record_event(application, actor, {'confirm': 'confirmed', 'reject': 'rejected', 'cancel': 'cancelled'}[action])
    recipients = [application.owner_user_id, application.jockey_user_id]
    if action == 'confirm':
        notify(application, event, recipients, 'Заявка подтверждена второй стороной. Согласовано обеими сторонами; ожидает решения администратора. Это ещё не допуск к старту.')
    else:
        notify(application, event, recipients, 'Заявка отклонена.' if action == 'reject' else 'Заявка отменена инициатором.')
    db.session.commit()
    return application
