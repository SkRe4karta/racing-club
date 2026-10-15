"""Offline synthetic importer, separate from live sporting transactions.

One transaction, constraints enabled, no DELETE/DDL/reset. Seed controls sporting
content; passwords and scrypt salts always use operating-system entropy.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import secrets
from zoneinfo import ZoneInfo
import sqlalchemy as sa
from sqlalchemy.orm import selectinload
from app import db
from app.demo_names import VENUES, competition_title
from app.models import (APPLICATION_LABELS, Application, ApplicationEvent, AuditLog, Competition, Horse,
                        Jockey, Notification, Owner, Prediction, PredictionChoice, Result, User)
from app.admin_services import prepare_protocol, protocol_snapshot, competition_snapshot, start_at
from app.prediction_services import assess_predictions, prediction_query

REPOSITORY = Path(__file__).resolve().parents[1]
SIZES = {
    'full': dict(owners=140, jockeys=80, horses=330, admins=5, viewers=134,
                 past=150, future=30, applications=2200, predictions=2600),
    'small': dict(owners=14, jockeys=16, horses=40, admins=1, viewers=14,
                  past=15, future=3, applications=140, predictions=260),
}
UTC = timezone.utc
MSK = ZoneInfo('Europe/Moscow')


class DemoError(ValueError):
    """A safe operator-facing diagnostic containing no driver parameters or secrets."""


def guard_target(uri):
    """Require an explicit demo namespace; no fallback to the application database."""
    if not uri:
        raise DemoError('Задайте RACING_DEMO_DATABASE_URL явно.')
    url = sa.engine.make_url(uri)
    if url.get_backend_name() == 'sqlite':
        path = Path(url.database or '')
        if not path.is_absolute() or not path.name.startswith('racing_demo_'):
            raise DemoError('Нужен абсолютный SQLite путь racing_demo_*.sqlite.')
        if path.resolve().is_relative_to(REPOSITORY):
            raise DemoError('БД должна находиться вне репозитория.')
    elif url.drivername == 'postgresql+psycopg':
        if not (url.database or '').startswith('racing_demo_'):
            raise DemoError('Имя отдельной БД должно начинаться с racing_demo_.')
    else:
        raise DemoError('Поддерживаются PostgreSQL/psycopg и отдельный SQLite.')


def row_counts():
    return {name: db.session.scalar(sa.select(sa.func.count()).select_from(sa.table(name)))
            for name in sorted(sa.inspect(db.session.connection()).get_table_names())}


def _stamp(day, hour=12):
    return datetime.combine(day, time(hour), tzinfo=MSK).astimezone(UTC)


def _name(index):
    surnames = ('Луговой', 'Зорин', 'Ветров', 'Северин', 'Рощин', 'Озеров', 'Миронов', 'Яснов', 'Лесков', 'Полевой')
    names = ('Алексей', 'Михаил', 'Даниил', 'Илья', 'Павел', 'Артём', 'Виктор', 'Никита')
    patronyms = ('Сергеевич', 'Андреевич', 'Дмитриевич', 'Игоревич', 'Алексеевич')
    return f'{surnames[index % 10]} {names[index // 10 % 8]} {patronyms[index // 80 % 5]}'


class HistoryImport:
    """Actual sporting-side actors supply personal consent, never ROOT."""
    def __init__(self, size, seed, as_of, credentials):
        self.cfg, self.rng = SIZES[size], random.Random(seed)
        self.as_of, self.credentials = as_of, credentials
        self.epoch = _stamp(as_of - timedelta(days=800))
        self.events, self.audits = [], []

    def log(self, actor, action, kind, identifier, stamp, old=None, new=None, reason=None):
        entry = AuditLog(actor_id=actor.id, action=action, object_type=kind, object_id=identifier,
                         created_at=stamp, old_values=old, new_values=new, reason=reason)
        db.session.add(entry)
        self.audits.append(entry)
        return entry

    def profiles(self):
        cfg, rng = self.cfg, self.rng
        self.owners = [Owner(full_name=_name(i))
                       for i in range(cfg['owners'])]
        self.jockeys = [Jockey(full_name=_name(i + 160), age=rng.randint(22, 48), rating=0) for i in range(cfg['jockeys'])]
        db.session.add_all(self.owners + self.jockeys)
        db.session.flush()
        self.users, self.owner_users, self.jockey_users, self.viewers, self.admins = [], {}, {}, [], []
        roles = [('ROOT', None)] + [('ADMIN', None)] * cfg['admins']
        roles += [('OWNER', owner.id) for owner in self.owners]
        roles += [('JOCKEY', jockey.id) for jockey in self.jockeys]
        roles += [('VIEWER', None)] * cfg['viewers']
        for index, (role, profile) in enumerate(roles, 1):
            user = User(email=f'demo.{role.lower()}.{index:03d}@example.test', role=role,
                        status='active', registered_at=self.epoch,
                        owner_id=profile if role == 'OWNER' else None,
                        jockey_id=profile if role == 'JOCKEY' else None)
            password = secrets.token_urlsafe(24)
            user.set_password(password)
            self.credentials.write(f'{role}\t{user.email}\t{password}\n')
            self.users.append(user)
            if role == 'OWNER': self.owner_users[profile] = user
            elif role == 'JOCKEY': self.jockey_users[profile] = user
            elif role == 'VIEWER': self.viewers.append(user)
            elif role == 'ADMIN': self.admins.append(user)
        self.root = self.users[0]
        db.session.add_all(self.users)
        db.session.flush()
        colors = ('Северный', 'Лунный', 'Золотой', 'Тихий', 'Вольный', 'Янтарный', 'Степной', 'Серебряный', 'Звёздный', 'Алый', 'Лесной')
        nouns = ('Ветер', 'Гром', 'Сокол', 'Рассвет', 'Алмаз', 'Вихрь', 'Берег', 'Метеор', 'Огонь', 'Туман', 'Бриз', 'Восход', 'Парус', 'Рубеж', 'Кедр', 'Исток', 'Шторм', 'Топаз', 'Марс', 'Орион', 'Факел', 'Шёлк', 'Аккорд', 'Каньон', 'Спутник', 'Мираж', 'Кристалл', 'Гранит', 'Шелест', 'Персей')
        self.horses = []
        for i in range(cfg['horses']):
            # First quarter of owners retain exactly one horse.
            owner_index = i if i < cfg['owners'] else cfg['owners'] // 4 + (i - cfg['owners']) % (cfg['owners'] - cfg['owners'] // 4)
            horse = Horse(nickname=f'{colors[i // 30 % len(colors)]} {nouns[i % 30]}',
                          gender=rng.choice(('Жеребец', 'Кобыла', 'Мерин')), age=rng.randint(5, 10),
                          owner_id=self.owners[owner_index].id)
            if i >= cfg['horses'] - 3: horse.age = 2
            self.horses.append(horse)
        db.session.add_all(self.horses)
        db.session.flush()
        self.horses_by_id = {horse.id: horse for horse in self.horses}
        viewer = self.viewers[-1]
        self.log(self.root, 'user_updated', 'user', viewer.id, self.epoch + timedelta(days=1),
                 old={'role': 'VIEWER', 'status': 'active'}, new={'role': 'ADMIN', 'status': 'active'},
                 reason='временное назначение администратора учебного сезона')
        self.log(self.root, 'user_updated', 'user', viewer.id, self.epoch + timedelta(days=2),
                 old={'role': 'ADMIN', 'status': 'active'}, new={'role': 'VIEWER', 'status': 'active'},
                 reason='завершение временных полномочий')

    def application(self, comp, horse, jockey, status, stamp, side='owner'):
        owner, rider = self.owner_users[horse.owner_id], self.jockey_users[jockey.id]
        both = status not in ('awaiting_owner', 'awaiting_jockey')
        if status == 'awaiting_owner': side = 'jockey'
        if status == 'awaiting_jockey': side = 'owner'
        first, other = (owner, rider) if side == 'owner' else (rider, owner)
        waiting = 'awaiting_jockey' if side == 'owner' else 'awaiting_owner'
        later = stamp + timedelta(hours=2)
        app = Application(competition_id=comp.id, horse_id=horse.id, jockey_id=jockey.id,
            owner_user_id=owner.id, jockey_user_id=rider.id, initiator_id=first.id,
            initiator_side=side, status=status, created_at=stamp,
            updated_at=later + timedelta(hours=1) if both else stamp,
            owner_confirmed_at=stamp if side == 'owner' else later if both else None,
            jockey_confirmed_at=stamp if side == 'jockey' else later if both else None)
        db.session.add(app)
        self.events.append((app, first, 'created', waiting, stamp, other))
        if both: self.events.append((app, other, 'confirmed', 'pending_admin', later, first))
        if status in ('admin_confirmed', 'rejected', 'cancelled'):
            actor = first if status == 'cancelled' else self.admins[comp.id % len(self.admins)]
            action = {'admin_confirmed': 'confirmed', 'rejected': 'rejected', 'cancelled': 'cancelled'}[status]
            self.events.append((app, actor, action, status, app.updated_at, None))
        return app

    def persist_events(self):
        db.session.flush()
        pending = []
        for app, actor, action, status, stamp, recipient in self.events:
            event = ApplicationEvent(application_id=app.id, actor_id=actor.id, action=action,
                                     status=status, created_at=stamp)
            db.session.add(event)
            pending.append((event, app, recipient))
        db.session.flush()
        for event, app, recipient in pending:
            recipients = [recipient.id] if recipient else [app.owner_user_id, app.jockey_user_id]
            for identifier in recipients:
                db.session.add(Notification(user_id=identifier, event_id=event.id, application_id=app.id,
                    competition_id=app.competition_id, message=f'Заявка №{app.id} · {APPLICATION_LABELS[event.status]}',
                    created_at=event.created_at, read_at=event.created_at + timedelta(hours=1)
                    if event.created_at < _stamp(self.as_of - timedelta(days=25)) else None))
        self.events.clear()

    def races(self):
        cfg, rng = self.cfg, self.rng
        self.competitions, self.official = [], {}
        remaining = cfg['applications']
        for i in range(cfg['past'] + cfg['future']):
            completed = i < cfg['past']
            day = self.as_of - timedelta(days=730 - i * 729 // (cfg['past'] - 1)) if completed else self.as_of + timedelta(days=7 + (i - cfg['past']) * 4)
            comp = Competition(title=competition_title(i, day, (1000, 1200, 1600, 2000, 2400)[i % 5]),
                event_date=day, event_time=time(10 + i % 8, (i % 4) * 15),
                location=VENUES[i % len(VENUES)],
                status='completed' if completed else 'planned', distance=(1000, 1200, 1600, 2000, 2400)[i % 5],
                registration_deadline=_stamp(day - timedelta(days=2)), max_participants=16, revision=0)
            db.session.add(comp)
            db.session.flush()
            created = _stamp(day - timedelta(days=35) if completed else self.as_of - timedelta(days=35))
            admin = self.admins[comp.id % len(self.admins)]
            self.log(admin, 'competition_created', 'competition', comp.id, created, new=competition_snapshot(comp))
            count = (8 + i % 5 if completed else 4 + i % 5) if cfg['past'] == 150 else (4 + i % 3 if completed else 4)
            pool = self.horses[:-max(3, len(self.horses) // 20)] if completed else self.horses[:-3]
            chosen = [self.horses[0], self.horses[1]] + rng.sample(pool[2:], count - 2)
            if i % 3:
                rng.shuffle(chosen)
            riders = [self.jockeys[0]] + rng.sample(self.jockeys[1:], count - 1)
            # Vary the long-serving rider's position independently of horse ability.
            offset = i % count
            riders = riders[offset:] + riders[:offset]
            rows = []
            stamp = created + timedelta(days=7)
            pairs = [(horse, jockey, self.application(comp, horse, jockey, 'admin_confirmed', stamp,
                     'jockey' if n % 2 else 'owner')) for n, (horse, jockey) in enumerate(zip(chosen, riders), 1)]
            db.session.flush()
            for n, (horse, jockey, app) in enumerate(pairs, 1):
                row = Result(competition_id=comp.id, horse_id=horse.id, jockey_id=jockey.id,
                    application_id=app.id, start_number=n, did_not_finish=False, is_disqualified=False)
                db.session.add(row)
                rows.append(row)
                remaining -= 1
            db.session.flush()
            for row, (_, _, app) in zip(rows, pairs):
                self.log(admin, 'application_approved', 'application', app.id, app.updated_at,
                    old={'status': 'pending_admin'}, new={'status': 'admin_confirmed', 'result_id': row.id, 'start_number': row.start_number})
            comp.revision = len(rows)
            if not completed:
                spare_horses = [h for h in pool if h not in chosen]
                spare_jockeys = [j for j in self.jockeys if j not in riders]
                for k, status in enumerate(('awaiting_owner', 'awaiting_jockey', 'pending_admin')):
                    self.application(comp, spare_horses[k], spare_jockeys[k], status, stamp + timedelta(days=2))
                    remaining -= 1
            self.persist_events()
            if completed:
                empty = protocol_snapshot(rows)
                data = {}
                base = comp.distance / (16.4 + rng.random())
                for n, row in enumerate(rows):
                    if n == len(rows) - 1 and i % 7 == 0: item = {'did_not_finish': True}
                    elif n == len(rows) - 2 and i % 11 == 0: item = {'is_disqualified': True}
                    else: item = {'time_str': str(round(base + (0 if i % 13 == 0 and n == 1 else n * .73), 2))}
                    data[row.id] = item
                for row, values in prepare_protocol(rows, data):
                    for key, value in values.items(): setattr(row, key, value)
                comp.revision += 1
                published = start_at(comp).astimezone(UTC) + timedelta(hours=1)
                self.log(admin, 'competition_completed', 'competition', comp.id, published,
                         old=empty, new=protocol_snapshot(rows))
                if i % 37 == 0:
                    old = protocol_snapshot(rows)
                    for finisher in rows:
                        if finisher.finish_time_seconds:
                            finisher.finish_time_seconds = round(finisher.finish_time_seconds + .12, 2)
                    comp.revision += 1
                    self.log(self.root, 'protocol_corrected', 'competition', comp.id, published + timedelta(hours=1),
                        old=old, new=protocol_snapshot(rows), reason='уточнение хронометража после сверки фотофиниша')
            self.competitions.append(comp)
            self.official[comp.id] = rows
        for i in range(remaining):
            comp = self.competitions[i % len(self.competitions)]
            created = _stamp(comp.event_date - timedelta(days=34) if comp.is_completed else self.as_of - timedelta(days=34)) + timedelta(hours=4 * (i // len(self.competitions)))
            app = self.application(comp, rng.choice(self.horses[:-3]), rng.choice(self.jockeys),
                                   'rejected' if i % 2 == 0 else 'cancelled', created, 'jockey' if i % 3 else 'owner')
            if app.status == 'rejected':
                db.session.flush()
                self.log(self.admins[comp.id % len(self.admins)], 'application_rejected', 'application', app.id,
                    app.updated_at, old={'status': 'pending_admin'}, new={'status': 'rejected'},
                    reason='пара не прошла проверку условий учебного старта')
        self.persist_events()
        db.session.flush()
        for entry in self.audits:
            if entry.action not in ('competition_completed', 'protocol_corrected'): continue
            recipients = {self.owner_users[self.horses_by_id[row.horse_id].owner_id].id for row in self.official[entry.object_id]}
            recipients |= {self.jockey_users[row.jockey_id].id for row in self.official[entry.object_id]}
            for identifier in recipients:
                db.session.add(Notification(user_id=identifier, audit_id=entry.id, competition_id=entry.object_id,
                    message='Опубликован протокол' if entry.action == 'competition_completed' else 'Опубликована коррекция протокола',
                    created_at=entry.created_at, read_at=entry.created_at + timedelta(hours=1)))

    def predictions(self):
        total, count = self.cfg['predictions'], len(self.competitions)
        for i, comp in enumerate(self.competitions):
            rows = self.official[comp.id]
            for k in range(total // count + (i < total % count)):
                viewer = self.viewers[0] if k < 2 else self.viewers[1 + (i * 7 + k // 2 - 1) % (len(self.viewers) - 1)]
                mode = 'winner' if k % 2 == 0 else 'trio'
                created = _stamp(comp.event_date - timedelta(days=5) if comp.is_completed else self.as_of - timedelta(days=1))
                prediction = Prediction(user_id=viewer.id, competition_id=comp.id, mode=mode,
                                        created_at=created, updated_at=created, revision=1, outcome='pending')
                chosen = rows[:1 if mode == 'winner' else 3] if k % 3 == 0 else self.rng.sample(rows, 1 if mode == 'winner' else 3)
                prediction.choices = [PredictionChoice(horse_id=row.horse_id, position=n) for n, row in enumerate(chosen, 1)]
                db.session.add(prediction)
            db.session.flush()
            if comp.is_completed:
                assess_predictions(comp, rows)
                evaluated = start_at(comp).astimezone(UTC) + timedelta(hours=2 if i % 37 == 0 else 1)
                for prediction in db.session.scalars(sa.select(Prediction).where(Prediction.competition_id == comp.id)):
                    prediction.evaluated_at = evaluated


def generate(size, seed, as_of, accounts_path):
    """Only a migrated empty demo target. Any failure rolls back every inserted row."""
    guard_target(db.engine.url.render_as_string(hide_password=False))
    if size not in SIZES or not date(2000, 1, 1) <= as_of <= date(9998, 1, 1):
        raise DemoError('Некорректный размер или опорная дата (2000–9998).')
    target = Path(accounts_path).absolute()
    if target.resolve().is_relative_to(REPOSITORY) or not target.parent.is_dir():
        raise DemoError('Создайте каталог accounts вне репозитория.')
    descriptor = None
    try:
        if db.engine.dialect.name == 'postgresql':
            db.session.execute(sa.text('SELECT pg_advisory_xact_lock(20261016)'))
            names = ', '.join('"' + table.name + '"' for table in db.metadata.sorted_tables)
            db.session.execute(sa.text(f'LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE'))
        else:
            db.session.execute(sa.text('BEGIN IMMEDIATE'))
        counts = row_counts()
        if set(counts) != set(db.metadata.tables) | {'alembic_version'}:
            raise DemoError('Схема неизвестна; сначала выполните миграции.')
        if db.session.scalar(sa.text('SELECT version_num FROM alembic_version')) != '0005_predictions':
            raise DemoError('Нужна текущая миграция 0005_predictions.')
        if any(value for name, value in counts.items() if name != 'alembic_version'):
            raise DemoError('Генерация разрешена только в пустой БД, включая служебные таблицы.')
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as credentials:
            credentials.write('ДЕМОНСТРАЦИОННЫЕ АККАУНТЫ — не публиковать. ROLE\tEMAIL\tPASSWORD\n')
            importer = HistoryImport(size, seed, as_of, credentials)
            importer.profiles()
            importer.log(importer.root, 'demo_initialized', 'demo', 1, _stamp(as_of), new={
                'version': '2.0.0-beta.1', 'size': size, 'seed': seed, 'as_of': as_of.isoformat()})
            importer.races()
            importer.predictions()
            db.session.flush()
            report = validate()
            credentials.flush()
            os.fsync(credentials.fileno())
            db.session.commit()
        return report
    except BaseException:
        db.session.rollback()
        if descriptor is not None: target.unlink(missing_ok=True)
        raise


def validate():
    """Read-only independent FK, chronology, consent, protocol and assessment checks.

    Read history by race. Fingerprint excludes password hashes and login counters.
    """
    errors = []
    def check(condition, message):
        if not condition and len(errors) < 40: errors.append(message)
    def utc(value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    marker = db.session.scalar(sa.select(AuditLog).where(AuditLog.action == 'demo_initialized'))
    if not marker: raise DemoError('Отсутствует отметка демонстрационной генерации.')
    as_of = date.fromisoformat(marker.new_values['as_of'])
    end = _stamp(as_of + timedelta(days=1), 0)
    users = {u.id: u for u in db.session.scalars(sa.select(User))}
    horses = {h.id: h for h in db.session.scalars(sa.select(Horse))}
    jockeys = {j.id: j for j in db.session.scalars(sa.select(Jockey))}
    for user in users.values():
        check(user.email.endswith('@example.test') and user.status == 'active', 'Аккаунт не является активным demo')
        check(user.password_hash.startswith('scrypt:'), 'Небезопасный пароль')
    digest = hashlib.sha256()
    connection = db.session.connection()
    for table in db.metadata.sorted_tables:
        for fk in table.foreign_keys:
            source, dest = table.c[fk.parent.name], fk.column
            count = connection.scalar(sa.select(sa.func.count()).select_from(table.outerjoin(dest.table, source == dest))
                                      .where(source.is_not(None), dest.is_(None)))
            check(count == 0, f'FK {table.name}.{source.name}')
        if table.name == 'auth_throttles': continue
        columns = [c for c in table.c if c.name not in ('password_hash', 'last_login_at')]
        for row in connection.execute(sa.select(*columns).order_by(*table.primary_key.columns)).yield_per(500):
            digest.update(json.dumps(list(row), default=str, ensure_ascii=False, sort_keys=True).encode())
    statuses, months = Counter(), Counter()
    for comp in db.session.scalars(sa.select(Competition).order_by(Competition.id)):
        start = start_at(comp).astimezone(UTC)
        check(comp.is_completed == (comp.event_date < as_of), f'Дата/статус старта {comp.id}')
        check(utc(comp.registration_deadline) < start, f'Дедлайн старта {comp.id}')
        months[comp.event_date.strftime('%Y-%m')] += 1
        rows = db.session.scalars(sa.select(Result).where(Result.competition_id == comp.id)).all()
        check(0 < len(rows) <= comp.max_participants, f'Вместимость {comp.id}')
        check(len({r.horse_id for r in rows}) == len(rows) and len({r.jockey_id for r in rows}) == len(rows)
              and len({r.start_number for r in rows}) == len(rows), f'Повтор участника {comp.id}')
        applications = db.session.scalars(sa.select(Application).where(Application.competition_id == comp.id)
            .options(selectinload(Application.events))).all()
        apps = {a.id: a for a in applications}
        for field in ('horse_id', 'jockey_id'):
            active = [getattr(a, field) for a in applications if a.is_active]
            check(len(active) == len(set(active)), f'Конфликт заявок {comp.id}/{field}')
        for app in applications:
            statuses[app.status] += 1
            horse, jockey = horses[app.horse_id], jockeys[app.jockey_id]
            owner, rider = users[app.owner_user_id], users[app.jockey_user_id]
            check(owner.role == 'OWNER' and owner.owner_id == horse.owner_id
                  and rider.role == 'JOCKEY' and rider.jockey_id == jockey.id, f'Стороны {app.id}')
            check(app.initiator_id == (owner.id if app.initiator_side == 'owner' else rider.id), f'Инициатор {app.id}')
            check(utc(app.created_at) <= utc(app.updated_at) < start and utc(app.updated_at) < end, f'Хронология заявки {app.id}')
            check(utc(app.created_at) < utc(comp.registration_deadline), f'Подача после срока {app.id}')
            for stamp in (app.owner_confirmed_at, app.jockey_confirmed_at):
                if stamp: check(utc(app.created_at) <= utc(stamp) <= utc(app.updated_at), f'Дата согласия {app.id}')
            check(bool(app.events) and app.events[-1].status == app.status, f'Цепочка событий {app.id}')
            for event in app.events:
                check(utc(app.created_at) <= utc(event.created_at) <= utc(app.updated_at), f'Дата события {event.id}')
            if app.status in ('pending_admin', 'admin_confirmed'):
                check(app.personal_consent('owner') and app.personal_consent('jockey'), f'Личное согласие {app.id}')
            if app.status == 'admin_confirmed':
                check(any(users[e.actor_id].role == 'ADMIN' and e.status == app.status for e in app.events), f'Решение {app.id}')
                check(sum(r.application_id == app.id for r in rows) == 1, f'Утверждение без участия {app.id}')
        for row in rows:
            app = apps.get(row.application_id)
            check(app is not None and app.status == 'admin_confirmed' and
                  (app.horse_id, app.jockey_id) == (row.horse_id, row.jockey_id), f'Допуск {row.id}')
            check(horses[row.horse_id].age >= 4 and jockeys[row.jockey_id].age >= 20, f'Возраст {row.id}')
            check(not (row.did_not_finish and row.is_disqualified), f'DNF/DSQ {row.id}')
            if not comp.is_completed:
                check(row.place is None and row.finish_time_seconds is None and not row.did_not_finish
                      and not row.is_disqualified, f'Будущий результат {row.id}')
            elif row.did_not_finish or row.is_disqualified:
                check(row.place is None and row.finish_time_seconds is None, f'Место DNF/DSQ {row.id}')
            else:
                seconds = row.finish_time_seconds
                check(seconds is not None and math.isfinite(seconds) and comp.distance / 20 < seconds < comp.distance / 10,
                      f'Время/дистанция {row.id}')
                if seconds:
                    check(row.place == 1 + sum(r.finish_time_seconds < seconds for r in rows if r.finish_time_seconds), f'Место {row.id}')
        official = {r.horse_id for r in rows}
        groups = defaultdict(set)
        for row in rows:
            if row.place: groups[row.place].add(row.horse_id)
        ambiguous = {p for place, group in groups.items() if len(group) > 1 for p in range(place, place + len(group))}
        podium = set().union(*(group for place, group in groups.items() if place <= 3))
        for prediction in db.session.scalars(prediction_query().where(Prediction.competition_id == comp.id)):
            choices = prediction.choices
            check(len(choices) == (1 if prediction.mode == 'winner' else 3) and
                  [c.position for c in choices] == list(range(1, len(choices) + 1)) and
                  len({c.horse_id for c in choices}) == len(choices) and {c.horse_id for c in choices} <= official,
                  f'Выбор {prediction.id}')
            latest_admission = max(utc(apps[r.application_id].updated_at) for r in rows)
            check(latest_admission <= utc(prediction.created_at) <= utc(prediction.updated_at) < start
                  and utc(prediction.updated_at) < end, f'Срок прогноза {prediction.id}')
            if not comp.is_completed:
                check(prediction.outcome == 'pending' and prediction.evaluated_at is None and
                      prediction.protocol_revision is None and prediction.winner_correct is None and
                      prediction.exact_trio is None and prediction.podium_hits is None and
                      all(c.position_correct is None for c in choices), f'Будущая оценка {prediction.id}')
            else:
                check(prediction.outcome == 'evaluated' and prediction.protocol_revision == comp.revision and
                      prediction.evaluated_at is not None and start <= utc(prediction.evaluated_at) < end, f'Оценка {prediction.id}')
                if prediction.mode == 'winner':
                    expected = choices[0].horse_id in groups[1] if groups[1] else None
                    check(prediction.winner_correct == expected and choices[0].position_correct == expected, f'Победитель {prediction.id}')
                else:
                    expected = [None if c.position in ambiguous or not groups[c.position] else c.horse_id in groups[c.position] for c in choices]
                    exact = all(expected) if all(len(groups[p]) == 1 for p in (1, 2, 3)) else None
                    check([c.position_correct for c in choices] == expected and prediction.exact_trio == exact
                          and prediction.podium_hits == sum(c.horse_id in podium for c in choices), f'Тройка {prediction.id}')
    for entry in db.session.scalars(sa.select(AuditLog)):
        check(utc(entry.created_at) < end and entry.actor_id in users, f'Аудит {entry.id}')
        if entry.action == 'protocol_corrected':
            check(users[entry.actor_id].role == 'ROOT' and entry.reason and entry.old_values != entry.new_values
                  and set(entry.old_values) == set(entry.new_values), f'Коррекция {entry.id}')
    events = {e.id: e for e in db.session.scalars(sa.select(ApplicationEvent))}
    app_parties = {a.id: (a.owner_user_id, a.jockey_user_id) for a in db.session.scalars(sa.select(Application))}
    for item in db.session.scalars(sa.select(Notification)):
        check(utc(item.created_at) < end and (item.read_at is None or utc(item.created_at) <= utc(item.read_at) < end), f'Уведомление {item.id}')
        if item.event_id:
            event = events[item.event_id]
            check(event.application_id == item.application_id and item.user_id in app_parties[item.application_id]
                  and utc(item.created_at) == utc(event.created_at), f'Источник уведомления {item.id}')
    if errors: raise DemoError('; '.join(errors))
    return dict(valid=True, as_of=as_of.isoformat(), counts=row_counts(), statuses=dict(statuses),
                months=dict(sorted(months.items())), sporting_sha256=digest.hexdigest())
