"""Alpha 2 acceptance: real CSRF-protected HTTP and isolated migrated databases."""
import re
import secrets
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, time, timedelta
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from flask_migrate import upgrade
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.application_services import ApplicationConflict, create_application, decide_application, registration_closes
from app.models import (Application, ApplicationEvent, Competition, Horse, Jockey, Notification,
                        Owner, Result, User, utc_now)
from tests.support import isolated_database


class Alpha2Tests(unittest.TestCase):
    def setUp(self):
        self.database = isolated_database()
        uri = self.database.__enter__()
        self.temporary = tempfile.TemporaryDirectory(prefix='racing-alpha2-test-')
        if uri == 'sqlite:///:memory:':
            uri = 'sqlite:///' + str(Path(self.temporary.name) / 'test.sqlite')
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': uri})
        self.password = secrets.token_urlsafe(24)
        self.ids = {}
        self.clients = {}
        with self.app.app_context():
            upgrade()
            password_hash = generate_password_hash(self.password)
            for name, role in [('owner', 'OWNER'), ('other_owner', 'OWNER'), ('jockey', 'JOCKEY'),
                               ('other_jockey', 'JOCKEY'), ('admin', 'ADMIN'), ('root', 'ROOT'), ('viewer', 'VIEWER')]:
                user = User(email=name + '@example.test', role=role, status='active', password_hash=password_hash)
                if role == 'OWNER':
                    user.owner = Owner(full_name='Владелец ' + name, address='Москва', phone='123')
                elif role == 'JOCKEY':
                    user.jockey = Jockey(full_name='Жокей ' + name, age=27, rating=7.5)
                db.session.add(user)
                db.session.flush()
                self.ids[name] = user.id
                if role == 'OWNER':
                    horse = Horse(nickname='Лошадь ' + name, gender='Кобыла', age=4, owner=user.owner)
                    db.session.add(horse)
                    db.session.flush()
                    self.ids[name + '_profile'] = user.owner_id
                    self.ids[name + '_horse'] = horse.id
                elif role == 'JOCKEY':
                    self.ids[name + '_profile'] = user.jockey_id
            legacy_owner = Owner(full_name='Без аккаунта')
            legacy_horse = Horse(nickname='Историческая', gender='Мерин', age=6, owner=legacy_owner)
            legacy_jockey = Jockey(full_name='Без аккаунта', age=35, rating=8)
            future = Competition(title='Открытый заезд', event_date=date.today() + timedelta(days=10), event_time=time(12),
                                 location='Москва', status='planned', registration_deadline=utc_now() + timedelta(days=5))
            past = Competition(title='Архивный заезд', event_date=date.today() - timedelta(days=10), event_time=time(12),
                               location='Москва', status='completed')
            db.session.add_all([legacy_horse, legacy_jockey, future, past])
            db.session.flush()
            result = Result(competition_id=past.id, horse_id=self.ids['owner_horse'], jockey_id=self.ids['jockey_profile'],
                            place=1, finish_time_seconds=123.4, is_disqualified=False)
            db.session.add(result)
            db.session.commit()
            self.ids.update(future=future.id, past=past.id, legacy_horse=legacy_horse.id, legacy_jockey=legacy_jockey.id)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.database.__exit__(None, None, None)
        self.temporary.cleanup()

    def token(self, client=None):
        client = client or self.client
        page = client.get('/auth/account' if client.get_cookie('session') and self.logged(client) else '/auth/login')
        self.assertEqual(page.status_code, 200)
        return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    def logged(self, client):
        with client.session_transaction() as session:
            return '_user_id' in session

    def login(self, name, client=None):
        if client is None and name in self.clients:
            self.client = self.clients[name]
            return self.client
        client = client or self.app.test_client()
        self.assertEqual(client.post('/auth/login', data={'csrf_token': self.token(client),
                         'email': name + '@example.test', 'password': self.password}).status_code, 302)
        self.client = client
        self.clients[name] = client
        return client

    def post(self, path, data=None, client=None):
        client = client or self.client
        return client.post(path, data={**(data or {}), 'csrf_token': self.token(client)})

    def create(self, name='owner', **changes):
        self.login(name)
        data = dict(competition_id=self.ids['future'], horse_id=self.ids['owner_horse'])
        if name != 'jockey':
            data['jockey_id'] = self.ids['jockey_profile']
        data.update(changes)
        return self.post('/cabinet/applications/new', data)

    def application_id(self):
        with self.app.app_context():
            return db.session.scalar(sa.select(Application.id).order_by(Application.id.desc()))

    def state(self, identifier=None):
        with self.app.app_context():
            return db.session.get(Application, identifier or self.application_id()).status

    def counts(self):
        with self.app.app_context():
            return tuple(db.session.scalar(sa.select(sa.func.count()).select_from(model))
                         for model in (Application, ApplicationEvent, Notification, Result))

    def test_owner_dashboard_profile_horses_statistics_and_invitation(self):
        self.login('owner')
        page = self.client.get('/cabinet/')
        self.assertEqual(page.status_code, 200)
        for label in ['Кабинет владельца', 'Лошадь owner', 'Добавить лошадь', 'История заявок', '02:03.40', '100.0%']:
            self.assertIn(label, page.text)
        self.assertNotIn('Лошадь other_owner', page.text)

    def test_jockey_dashboard_history_win_rate_and_invitations(self):
        self.create()
        self.login('jockey')
        page = self.client.get('/cabinet/')
        self.assertEqual(page.status_code, 200)
        for label in ['Кабинет жокея', 'Архивный заезд', '100.0%', 'Ожидает согласования жокея', 'Последние уведомления']:
            self.assertIn(label, page.text)

    def test_guest_viewer_admin_boundaries_and_private_cache(self):
        self.assertEqual(self.client.get('/cabinet/').status_code, 302)
        for name in ['viewer', 'admin']:
            self.login(name)
            for path in ['/cabinet/', '/cabinet/applications', '/cabinet/applications/new']:
                self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.get('/cabinet/notifications').status_code, 200)
        self.login('owner')
        self.assertEqual(self.client.get('/cabinet/').headers['Cache-Control'], 'no-store')

    def test_owner_profile_edit_and_foreign_profile_denied(self):
        self.login('owner')
        path = f"/cabinet/profile/owner/{self.ids['owner_profile']}/edit"
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.post(path, dict(full_name='Обновлённый', address='Тверь', phone='456')).status_code, 302)
        foreign = f"/cabinet/profile/owner/{self.ids['other_owner_profile']}/edit"
        self.assertEqual(self.client.get(foreign).status_code, 403)
        self.assertEqual(self.post(foreign, dict(full_name='Подмена')).status_code, 403)
        with self.app.app_context():
            owner = db.session.get(Owner, self.ids['owner_profile'])
            self.assertEqual((owner.full_name, owner.address, owner.phone), ('Обновлённый', 'Тверь', '456'))

    def test_jockey_edit_rating_injection_and_invalid_ages(self):
        self.login('jockey')
        path = f"/cabinet/profile/jockey/{self.ids['jockey_profile']}/edit"
        for age in ['', '0', '101', 'nan']:
            self.assertEqual(self.post(path, dict(full_name='Жокей', age=age)).status_code, 400)
        self.assertEqual(self.post(path, dict(full_name='Новый жокей', age='30', address='Казань')).status_code, 302)
        self.assertEqual(self.post(path, dict(full_name='Подмена', age='30', rating='999')).status_code, 400)
        foreign = f"/cabinet/profile/jockey/{self.ids['other_jockey_profile']}/edit"
        self.assertEqual(self.post(foreign, dict(full_name='Подмена', age='30')).status_code, 403)
        with self.app.app_context():
            jockey = db.session.get(Jockey, self.ids['jockey_profile'])
            self.assertEqual((jockey.full_name, jockey.age, jockey.rating), ('Новый жокей', 30, 7.5))

    def test_profile_validation_lengths_and_escaping(self):
        self.login('owner')
        path = f"/cabinet/profile/owner/{self.ids['owner_profile']}/edit"
        for data in [dict(full_name=''), dict(full_name='x'*151), dict(full_name='Имя', address='x'*256),
                     dict(full_name='Имя', phone='x'*51), dict(full_name='Имя', owner_id=self.ids['other_owner_profile'])]:
            self.assertEqual(self.post(path, data).status_code, 400)
        self.assertEqual(self.post(path, dict(full_name='<script>alert(1)</script>')).status_code, 302)
        self.assertNotIn('<script>alert(1)</script>', self.client.get('/cabinet/').text)
        self.assertIn('&lt;script&gt;', self.client.get('/cabinet/').text)

    def test_horse_creation_edit_ownership_and_history_preserved(self):
        self.login('owner')
        data = dict(nickname='Новая', gender='Мерин', age='5', owner_id=self.ids['owner_profile'])
        self.assertEqual(self.post('/horses/add', data).status_code, 302)
        path = f"/horses/{self.ids['owner_horse']}/edit"
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.post(path, dict(nickname='Обновлена', gender='Кобыла', age='5')).status_code, 302)
        foreign = f"/horses/{self.ids['other_owner_horse']}/edit"
        self.assertEqual(self.client.get(foreign).status_code, 403)
        self.assertEqual(self.post(foreign, dict(nickname='Подмена', gender='Мерин', age='2')).status_code, 403)
        self.assertIn('Архивный заезд', self.client.get(f"/horses/{self.ids['owner_horse']}").text)
        self.assertEqual(self.counts()[-1], 1)

    def test_horse_transfer_system_fields_and_deletion_denied(self):
        self.login('owner')
        path = f"/horses/{self.ids['owner_horse']}/edit"
        for field in ['owner_id', 'status', 'rating', 'id']:
            self.assertEqual(self.post(path, dict(nickname='Подмена', gender='Мерин', age='4', **{field: '1'})).status_code, 400)
        self.assertEqual(self.client.delete(f"/horses/{self.ids['owner_horse']}").status_code, 405)
        for age in ['0', '41', 'nan']:
            self.assertEqual(self.post(path, dict(nickname='Ошибка', gender='Мерин', age=age)).status_code, 400)

    def test_owner_submission_initial_consent_notification_and_no_result(self):
        response = self.create()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        with self.app.app_context():
            item = db.session.get(Application, self.application_id())
            self.assertEqual(item.status, 'awaiting_jockey')
            self.assertIsNotNone(item.owner_confirmed_at)
            self.assertIsNone(item.jockey_confirmed_at)
            note = db.session.scalar(sa.select(Notification))
            self.assertEqual(note.user_id, self.ids['jockey'])
        self.assertNotIn('Лошадь owner', self.app.test_client().get(f"/competitions/future/{self.ids['future']}").text)

    def test_jockey_submission_uses_own_profile_and_requires_owner_confirmation(self):
        self.assertEqual(self.create('jockey').status_code, 302)
        identifier = self.application_id()
        self.assertEqual(self.state(identifier), 'awaiting_owner')
        self.login('owner')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/confirm').status_code, 302)
        self.assertEqual(self.state(identifier), 'pending_admin')
        self.assertEqual(self.counts(), (1, 2, 3, 1))

    def test_second_party_confirmation_history_and_notifications(self):
        self.create()
        identifier = self.application_id()
        self.login('jockey')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/confirm').status_code, 302)
        page = self.client.get(f'/cabinet/applications/{identifier}')
        self.assertIn('Подтверждена второй стороной', page.text)
        self.assertIn('Согласовано обеими сторонами', page.text)
        self.assertEqual(self.counts(), (1, 2, 3, 1))
        self.assertEqual(self.state(identifier), 'pending_admin')

    def test_initiator_cannot_confirm_or_reject_instead_of_second_party(self):
        self.create()
        identifier = self.application_id()
        for action in ['confirm', 'reject']:
            self.assertEqual(self.post(f'/cabinet/applications/{identifier}/{action}').status_code, 403)
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_rejection_terminal_and_slot_reusable(self):
        self.create()
        identifier = self.application_id()
        self.login('jockey')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/reject').status_code, 302)
        self.assertEqual(self.state(identifier), 'rejected')
        for action in ['confirm', 'reject']:
            self.assertEqual(self.post(f'/cabinet/applications/{identifier}/{action}').status_code, 409)
        self.assertEqual(self.counts(), (1, 2, 3, 1))
        self.assertEqual(self.create().status_code, 302)
        self.assertEqual(self.counts()[0], 2)

    def test_cancel_own_and_cannot_cancel_others_invitation(self):
        self.create()
        identifier = self.application_id()
        self.login('jockey')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/cancel').status_code, 403)
        self.login('owner')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/cancel').status_code, 302)
        self.assertEqual(self.state(identifier), 'cancelled')
        self.login('jockey')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/confirm').status_code, 409)
        self.assertEqual(self.counts(), (1, 2, 3, 1))

    def test_jockey_can_cancel_own_application(self):
        self.create('jockey')
        self.assertEqual(self.post(f'/cabinet/applications/{self.application_id()}/cancel').status_code, 302)
        self.assertEqual(self.state(), 'cancelled')

    def test_pending_admin_can_be_cancelled_by_initiator(self):
        self.create()
        identifier = self.application_id()
        self.login('jockey')
        self.post(f'/cabinet/applications/{identifier}/confirm')
        self.login('owner')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/cancel').status_code, 302)
        self.assertEqual(self.state(), 'cancelled')

    def test_repeat_confirmation_does_not_duplicate_notifications(self):
        self.create()
        identifier = self.application_id()
        self.login('jockey')
        self.post(f'/cabinet/applications/{identifier}/confirm')
        before = self.counts()
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/confirm').status_code, 409)
        self.assertEqual(self.counts(), before)

    def test_foreign_application_private_views_and_actions_not_found(self):
        self.create()
        identifier = self.application_id()
        for name in ['other_owner', 'other_jockey']:
            self.login(name)
            self.assertNotIn('Лошадь owner', self.client.get('/cabinet/applications').text)
            self.assertEqual(self.client.get(f'/cabinet/applications/{identifier}').status_code, 404)
            for action in ['confirm', 'reject', 'cancel']:
                self.assertEqual(self.post(f'/cabinet/applications/{identifier}/{action}').status_code, 404)

    def test_author_confirmation_status_and_pair_injection_rejected(self):
        self.login('owner')
        data = dict(competition_id=self.ids['future'], horse_id=self.ids['owner_horse'], jockey_id=self.ids['jockey_profile'])
        for field in ['initiator_id', 'owner_user_id', 'jockey_user_id', 'owner_confirmed_at', 'status', 'side']:
            self.assertEqual(self.post('/cabinet/applications/new', {**data, field: '1'}).status_code, 400)
        self.assertEqual(self.counts(), (0, 0, 0, 1))
        self.create()
        self.login('jockey')
        self.assertEqual(self.post(f'/cabinet/applications/{self.application_id()}/confirm', {'horse_id': self.ids['other_owner_horse']}).status_code, 400)
        self.assertEqual(self.state(), 'awaiting_jockey')

    def test_owner_cannot_submit_foreign_horse_and_jockey_cannot_impersonate(self):
        self.assertEqual(self.create(horse_id=self.ids['other_owner_horse']).status_code, 403)
        self.assertEqual(self.create('jockey', jockey_id=self.ids['other_jockey_profile']).status_code, 403)
        self.assertEqual(self.counts(), (0, 0, 0, 1))

    def test_missing_huge_invalid_identifiers_safe_and_atomic(self):
        for field in ['competition_id', 'horse_id', 'jockey_id']:
            for value in ['0', '-1', '9'*100, 'nan', '99999', '']:
                self.assertEqual(self.create(**{field: value}).status_code, 400)
        self.assertEqual(self.counts(), (0, 0, 0, 1))

    def test_legacy_profiles_without_accounts_cannot_imply_consent(self):
        self.assertEqual(self.create('jockey', horse_id=self.ids['legacy_horse']).status_code, 400)
        self.assertEqual(self.create(jockey_id=self.ids['legacy_jockey']).status_code, 400)
        self.assertEqual(self.counts(), (0, 0, 0, 1))

    def test_disabled_recipient_unavailable_but_cancellation_possible(self):
        self.create()
        identifier = self.application_id()
        with self.app.app_context():
            db.session.get(User, self.ids['jockey']).status = 'disabled'
            db.session.commit()
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/cancel').status_code, 302)
        self.assertEqual(self.create().status_code, 400)

    def test_duplicates_same_horse_and_same_jockey_rollback(self):
        self.assertEqual(self.create().status_code, 302)
        self.assertEqual(self.create(jockey_id=self.ids['other_jockey_profile']).status_code, 409)
        self.assertEqual(self.create('other_owner', horse_id=self.ids['other_owner_horse']).status_code, 409)
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_completed_and_expired_registration_rejected_for_all_actions(self):
        self.assertEqual(self.create(competition_id=self.ids['past']).status_code, 409)
        self.create()
        identifier = self.application_id()
        with self.app.app_context():
            db.session.get(Competition, self.ids['future']).registration_deadline = utc_now() - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/cancel').status_code, 409)
        self.login('jockey')
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/confirm').status_code, 409)
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/reject').status_code, 409)
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_default_deadline_at_start_and_explicit_earlier_deadline(self):
        from datetime import datetime, timezone
        with self.app.app_context():
            comp = db.session.get(Competition, self.ids['future'])
            comp.registration_deadline = None
            self.assertEqual(registration_closes(comp).hour, 9)  # 12:00 Moscow.
            comp.registration_deadline = datetime.combine(comp.event_date, time(8), tzinfo=timezone.utc)
            self.assertEqual(registration_closes(comp).hour, 8)
            comp.event_date = date.today() - timedelta(days=1)
            db.session.commit()
        self.assertEqual(self.create().status_code, 409)

    def test_legacy_planned_participants_conflict_preserve_protocol(self):
        with self.app.app_context():
            db.session.add(Result(competition_id=self.ids['future'], horse_id=self.ids['owner_horse'],
                                  jockey_id=self.ids['jockey_profile'], is_disqualified=False))
            db.session.commit()
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.counts(), (0, 0, 0, 2))

    def test_notifications_recipient_only_read_idempotence_and_counts(self):
        self.create()
        with self.app.app_context():
            identifier = db.session.scalar(sa.select(Notification.id))
        self.assertEqual(self.client.get(f'/cabinet/notifications/{identifier}').status_code, 404)
        self.assertEqual(self.post(f'/cabinet/notifications/{identifier}').status_code, 404)
        self.login('jockey')
        page = self.client.get('/cabinet/notifications')
        self.assertIn('1 непрочитанных', page.text)
        self.assertEqual(self.client.get(f'/cabinet/notifications/{identifier}').status_code, 200)
        self.assertIn('1 непрочитанных', self.client.get('/cabinet/notifications').text)
        self.assertEqual(self.post(f'/cabinet/notifications/{identifier}').status_code, 302)
        with self.app.app_context():
            first_read = db.session.get(Notification, identifier).read_at
        self.assertEqual(self.post(f'/cabinet/notifications/{identifier}').status_code, 302)
        self.assertIn('0 непрочитанных', self.client.get('/cabinet/notifications').text)
        with self.app.app_context():
            self.assertEqual(db.session.get(Notification, identifier).read_at, first_read)

    def test_csrf_every_new_mutation_missing_forged_and_foreign(self):
        self.create()
        identifier = self.application_id()
        self.login('jockey')
        foreign_token = self.token(self.app.test_client())
        paths = ['/cabinet/applications/new', f'/cabinet/applications/{identifier}/confirm',
                 f'/cabinet/applications/{identifier}/reject', f'/cabinet/applications/{identifier}/cancel',
                 '/cabinet/notifications/1', f"/cabinet/profile/jockey/{self.ids['jockey_profile']}/edit"]
        for path in paths:
            for data in [{}, {'csrf_token': 'forged'}, {'csrf_token': foreign_token}]:
                self.assertEqual(self.client.post(path, data=data).status_code, 400)
        self.login('owner')
        for path in ['/horses/add', f"/horses/{self.ids['owner_horse']}/edit",
                     f"/cabinet/profile/owner/{self.ids['owner_profile']}/edit"]:
            self.assertEqual(self.client.post(path).status_code, 400)
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_disabled_actor_session_revoked_on_new_routes(self):
        self.create()
        with self.app.app_context():
            db.session.get(User, self.ids['owner']).status = 'disabled'
            db.session.commit()
        self.assertEqual(self.client.get('/cabinet/').status_code, 302)
        self.assertEqual(self.client.get('/cabinet/applications').status_code, 302)

    def test_root_cannot_impersonate_personal_consent_and_admin_boundaries(self):
        self.assertEqual(self.create('root', side='owner').status_code, 403)
        self.assertEqual(self.counts(), (0, 0, 0, 1))
        self.create()
        identifier = self.application_id()
        self.login('root')
        self.assertEqual(self.client.get(f'/cabinet/applications/{identifier}').status_code, 200)
        for action in ('confirm', 'reject', 'cancel'):
            self.assertEqual(self.post(f'/cabinet/applications/{identifier}/{action}').status_code, 403)
        self.assertEqual(self.state(), 'awaiting_jockey')
        self.login('admin')
        self.assertEqual(self.client.get(f'/cabinet/applications/{identifier}').status_code, 403)
        self.assertEqual(self.client.get('/owners/add').status_code, 403)
        self.assertEqual(self.client.get('/competitions/future/add').status_code, 200)

    def test_notification_failure_rolls_back_entire_submission_and_decision(self):
        self.login('owner')
        failure = OperationalError('private', {}, Exception('simulated'), hide_parameters=True)
        with patch('app.application_services.notify', side_effect=failure):
            self.assertEqual(self.post('/cabinet/applications/new', dict(competition_id=self.ids['future'],
                horse_id=self.ids['owner_horse'], jockey_id=self.ids['jockey_profile'])).status_code, 409)
        self.assertEqual(self.counts(), (0, 0, 0, 1))
        self.create()
        self.login('jockey')
        with patch('app.application_services.notify', side_effect=failure):
            self.assertEqual(self.post(f'/cabinet/applications/{self.application_id()}/confirm').status_code, 409)
        self.assertEqual(self.state(), 'awaiting_jockey')
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_database_checks_consents_foreign_keys_and_partial_uniqueness(self):
        self.create()
        with self.app.app_context():
            item = db.session.get(Application, self.application_id())
            for changes in [dict(status='pending_admin', jockey_confirmed_at=None),
                            dict(status='unknown'), dict(horse_id=99999),
                            dict(initiator_side='invalid'), dict(owner_user_id=self.ids['jockey'])]:
                with self.assertRaises(IntegrityError):
                    db.session.execute(sa.update(Application).where(Application.id == item.id).values(**changes))
                    db.session.commit()
                db.session.rollback()
            # Raw insert bypasses the service; unique indexes still prevent both conflicts.
            original = db.session.get(Application, item.id)
            values = {column.name: getattr(original, column.name) for column in Application.__table__.columns if column.name != 'id'}
            for changes in [dict(jockey_id=self.ids['other_jockey_profile']), dict(horse_id=self.ids['other_owner_horse'])]:
                with self.assertRaises(IntegrityError):
                    db.session.execute(sa.insert(Application).values(**{**values, **changes}))
                    db.session.commit()
                db.session.rollback()
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_concurrent_submissions_two_apps_exactly_one_commit(self):
        other_app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': self.app.config['SQLALCHEMY_DATABASE_URI']})
        apps = [self.app, other_app]
        def submit(index):
            with apps[index % 2].app_context():
                actor = db.session.get(User, self.ids['owner'])
                try:
                    create_application(actor, self.ids['future'], self.ids['owner_horse'], self.ids['jockey_profile'])
                    return 'created'
                except ApplicationConflict:
                    return 'conflict'
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(submit, range(4)))
            self.assertEqual(outcomes.count('created'), 1)
            self.assertEqual(outcomes.count('conflict'), 3)
            self.assertEqual(self.counts(), (1, 1, 1, 1))
        finally:
            with other_app.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_concurrent_confirmation_creates_one_decision_and_no_duplicate_messages(self):
        self.create()
        identifier = self.application_id()
        def confirm(_):
            with self.app.app_context():
                try:
                    decide_application(db.session.get(User, self.ids['jockey']), identifier, 'confirm')
                    return 'confirmed'
                except ApplicationConflict:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(confirm, range(4)))
        self.assertEqual(outcomes.count('confirmed'), 1)
        self.assertEqual(self.state(), 'pending_admin')
        self.assertEqual(self.counts(), (1, 2, 3, 1))

    def test_pair_cannot_be_edited_and_fresh_submission_requires_fresh_consent(self):
        self.create()
        identifier = self.application_id()
        self.login('jockey')
        self.post(f'/cabinet/applications/{identifier}/confirm')
        self.login('owner')
        self.post(f'/cabinet/applications/{identifier}/cancel')
        self.assertEqual(self.create(jockey_id=self.ids['other_jockey_profile']).status_code, 302)
        self.assertEqual(self.state(), 'awaiting_jockey')
        with self.app.app_context():
            item = db.session.get(Application, self.application_id())
            self.assertIsNone(item.jockey_confirmed_at)
            self.assertNotEqual(item.id, identifier)
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/edit').status_code, 404)

    def test_admin_creation_deadline_validation_and_existing_behavior(self):
        self.login('admin')
        data = dict(title='Срок', event_date=(date.today() + timedelta(days=10)).isoformat(), event_time='12:00',
                    location='Москва', distance='1600', max_participants='20')
        late = (date.today() + timedelta(days=11)).isoformat() + 'T12:00'
        response = self.post('/competitions/future/add', {**data, 'registration_deadline': late})
        self.assertIn('Срок регистрации не может', response.text)
        valid = (date.today() + timedelta(days=9)).isoformat() + 'T12:00'
        self.assertEqual(self.post('/competitions/future/add', {**data, 'registration_deadline': valid}).status_code, 302)
        with self.app.app_context():
            comp = db.session.scalar(sa.select(Competition).where(Competition.title == 'Срок'))
            self.assertIsNotNone(comp.registration_deadline)
            from app.application_services import as_utc
            self.assertEqual(as_utc(comp.registration_deadline).hour, 9)
            self.assertEqual(len(comp.results), 0)
