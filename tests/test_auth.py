import re
import secrets
import unittest
from datetime import date, time, timedelta
from unittest.mock import patch

from flask_login import AnonymousUserMixin
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app import create_app, db
from app.models import AuthThrottle, Competition, Horse, Jockey, Owner, User
from app.permissions import can
from tests.support import isolated_database


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.database = isolated_database()
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': self.database.__enter__()})
        with self.app.app_context():
            db.create_all()
            owner = Owner(full_name='Исторический владелец')
            jockey = Jockey(full_name='Исторический жокей', age=25, rating=7.5)
            horse = Horse(nickname='Историческая лошадь', gender='Кобыла', age=4, owner=owner)
            db.session.add_all([owner, jockey, horse])
            db.session.add_all([
                Competition(title='Будущий старт', event_date=date(2027, 1, 1), event_time=time(12), location='Москва', status='planned'),
                Competition(title='Архивный старт', event_date=date(2025, 1, 1), event_time=time(12), location='Москва', status='completed'),
            ])
            db.session.commit()
            self.legacy_owner_id, self.legacy_jockey_id, self.legacy_horse_id = owner.id, jockey.id, horse.id
        self.client = self.app.test_client()
        self.password = secrets.token_urlsafe(24)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.database.__exit__(None, None, None)

    def token(self, path='/auth/login', client=None):
        response = (client or self.client).get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def post(self, path, data=None, token_path='/auth/login', client=None):
        client = client or self.client
        return client.post(path, data={**(data or {}), 'csrf_token': self.token(token_path, client)})

    def register(self, role='VIEWER', **changes):
        data = dict(email='new@example.test', role=role, password=self.password,
                    password_confirm=self.password, full_name='Новый участник', age='27')
        data.update(changes)
        return self.post('/auth/register', data, '/auth/register')

    def user(self, role='VIEWER', email=None, status='active'):
        with self.app.app_context():
            user = User(email=email or f'{role.lower()}@example.test', role=role, status=status)
            user.set_password(self.password)
            if role == 'OWNER':
                user.owner = Owner(full_name='Собственный владелец')
            if role == 'JOCKEY':
                user.jockey = Jockey(full_name='Собственный жокей', age=30, rating=0)
            db.session.add(user)
            db.session.commit()
            db.session.refresh(user)
            return user

    def login(self, user, password=None, client=None):
        return self.post('/auth/login', {'email': user.email, 'password': password or self.password}, client=client)

    def test_register_owner_creates_new_profile(self):
        self.assertEqual(self.register('OWNER').status_code, 302)
        with self.app.app_context():
            user = db.session.scalar(select(User))
            self.assertEqual(user.owner.full_name, 'Новый участник')
            self.assertNotEqual(user.owner_id, self.legacy_owner_id)
            self.assertEqual(db.session.query(Owner).count(), 2)
            self.assertEqual(user.status, 'active')
            self.assertIsNotNone(user.registered_at)
            self.assertIsNone(user.last_login_at)

    def test_register_jockey_sets_trusted_initial_rating(self):
        self.assertEqual(self.register('JOCKEY').status_code, 302)
        with self.app.app_context():
            user = db.session.scalar(select(User))
            self.assertNotEqual(user.jockey_id, self.legacy_jockey_id)
            self.assertEqual((user.jockey.age, user.jockey.rating), (27, 0))

    def test_register_viewer_has_no_profile(self):
        self.assertEqual(self.register().status_code, 302)
        with self.app.app_context():
            user = db.session.scalar(select(User))
            self.assertEqual(user.role, 'VIEWER')
            self.assertIsNone(user.owner_id)
            self.assertIsNone(user.jockey_id)
            self.assertEqual(db.session.query(Owner).count(), 1)
            self.assertEqual(db.session.query(Jockey).count(), 1)

    def test_email_normalization_unique_and_registration_atomic(self):
        self.assertEqual(self.register('OWNER', email='  MiXeD@example.TEST ').status_code, 302)
        self.assertEqual(self.register('OWNER', email='mixed@example.test').status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.query(User).count(), 1)
            self.assertEqual(db.session.query(Owner).count(), 2)
            self.assertEqual(db.session.scalar(select(User.email)), 'mixed@example.test')

    def test_password_hash_and_verification(self):
        self.register()
        with self.app.app_context():
            user = db.session.scalar(select(User))
            self.assertTrue(user.password_hash.startswith('scrypt:'))
            self.assertNotIn(self.password, user.password_hash)
            self.assertTrue(user.check_password(self.password))
            self.assertFalse(user.check_password('incorrect'))

    def test_registration_errors_and_escalation(self):
        cases = [dict(email='bad'), dict(email='a..b@example.test'), dict(email='a@-host.test'),
                 dict(password='short', password_confirm='short'), dict(password_confirm='mismatch'),
                 dict(role='ROOT'), dict(role='ADMIN'), dict(role='GUEST'),
                 dict(role='OWNER', full_name='  '), dict(role='JOCKEY', age='nan'),
                 dict(role='JOCKEY', age='101'), dict(role='OWNER', owner_id=self.legacy_owner_id),
                 dict(role='JOCKEY', jockey_id=self.legacy_jockey_id), dict(status='active'), dict(rating='99')]
        for case in cases:
            with self.subTest(case=case):
                # Fresh test IP prevents registration rate limits hiding validation.
                self.client.environ_base['REMOTE_ADDR'] = f'192.0.2.{cases.index(case) + 1}'
                response = self.register(**case)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn('Traceback', response.text)
                self.assertNotIn(self.password, response.text)
        with self.app.app_context():
            self.assertEqual(db.session.query(User).count(), 0)
            self.assertEqual(db.session.query(Owner).count(), 1)
            self.assertEqual(db.session.query(Jockey).count(), 1)

    def test_login_updates_timestamp_and_protects_account(self):
        user = self.user()
        self.assertEqual(self.client.get('/auth/account').status_code, 302)
        response = self.login(user)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/auth/account')
        self.assertIn(user.email, self.client.get('/auth/account').text)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(User, user.id).last_login_at)

    def test_login_wrong_password_unknown_and_disabled_same_message(self):
        user = self.user(status='disabled')
        other = self.user(email='active@example.test')
        messages = []
        for email, password in [(user.email, self.password), (other.email, 'wrong'), ('absent@example.test', self.password)]:
            response = self.post('/auth/login', dict(email=email, password=password))
            self.assertEqual(response.status_code, 400)
            messages.append('Неверный email или пароль, либо аккаунт недоступен.' in response.text)
            self.assertEqual(self.client.get('/auth/account').status_code, 302)
        self.assertTrue(all(messages))

    def test_logout_post_and_session_cleared(self):
        self.login(self.user())
        self.assertEqual(self.client.get('/auth/logout').status_code, 405)
        self.assertEqual(self.client.post('/auth/logout').status_code, 400)
        self.assertEqual(self.post('/auth/logout', token_path='/auth/account').status_code, 302)
        self.assertEqual(self.client.get('/auth/account').status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('_user_id', session)

    def test_disabled_user_loses_existing_session_and_permissions(self):
        user = self.user('ROOT')
        self.login(user)
        with self.app.app_context():
            db.session.get(User, user.id).status = 'disabled'
            db.session.commit()
        self.assertEqual(self.client.get('/owners/add').status_code, 302)
        self.assertEqual(self.client.get('/auth/account').status_code, 302)

    def test_current_role_rechecked_after_login(self):
        user = self.user('ADMIN')
        self.login(user)
        self.assertEqual(self.client.get('/competitions/future/add').status_code, 200)
        with self.app.app_context():
            db.session.get(User, user.id).role = 'VIEWER'
            db.session.commit()
        self.assertEqual(self.client.get('/competitions/future/add').status_code, 403)

    def test_guest_public_routes_and_actions_hidden(self):
        for path in ['/', '/health', '/owners/', '/horses/', '/jockeys/', '/competitions/future',
                     '/competitions/past', '/competitions/future?view=calendar', '/horses/?export=csv',
                     f'/owners/{self.legacy_owner_id}', f'/horses/{self.legacy_horse_id}', f'/jockeys/{self.legacy_jockey_id}']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        page = self.client.get('/').text
        for path in ['/owners/add', '/horses/add', '/jockeys/add', '/competitions/future/add', '/competitions/complete']:
            self.assertNotIn(f'href="{path}"', page)

    def test_guest_cannot_directly_get_or_post_writes(self):
        for path in ['/owners/add', '/horses/add', '/jockeys/add', '/competitions/future/add',
                     '/competitions/past/add', '/competitions/complete', '/competitions/complete/1']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 302)
                self.assertEqual(self.post(path, dict(full_name='HTTP bypass')).status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.query(Owner).count(), 1)
            self.assertEqual(db.session.query(Competition).count(), 2)

    def test_owner_cannot_manage_system_or_competitions(self):
        self.login(self.user('OWNER'))
        for path in ['/owners/add', '/jockeys/add', '/competitions/future/add',
                     '/competitions/past/add', '/competitions/complete/1']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
                self.assertEqual(self.post(path, token_path='/auth/account').status_code, 403)

    def test_owner_cannot_assign_horse_to_other_owner(self):
        user = self.user('OWNER')
        self.login(user)
        page = self.client.get('/horses/add').text
        self.assertNotIn('Исторический владелец', page)
        data = dict(nickname='Проверка доступа', gender='Кобыла', age='3', owner_id=str(self.legacy_owner_id))
        self.assertEqual(self.post('/horses/add', data, '/horses/add').status_code, 403)
        data['owner_id'] = str(user.owner_id)
        self.assertEqual(self.post('/horses/add', data, '/horses/add').status_code, 302)
        with self.app.app_context():
            horse = db.session.scalar(select(Horse).where(Horse.nickname == data['nickname']))
            self.assertEqual(horse.owner_id, user.owner_id)
            self.assertEqual(db.session.query(Horse).count(), 2)

    def test_jockey_cannot_modify_foreign_objects(self):
        self.login(self.user('JOCKEY'))
        for path in ['/horses/add', '/owners/add', '/jockeys/add', '/competitions/future/add']:
            self.assertEqual(self.post(path, {'owner_id': self.legacy_owner_id, 'jockey_id': self.legacy_jockey_id}, '/auth/account').status_code, 403)
        with self.app.app_context():
            self.assertEqual(db.session.query(Horse).count(), 1)
            self.assertEqual(db.session.get(Jockey, self.legacy_jockey_id).rating, 7.5)

    def test_viewer_read_only(self):
        self.login(self.user())
        for path in ['/owners/add', '/horses/add', '/jockeys/add', '/competitions/complete']:
            self.assertEqual(self.post(path, token_path='/auth/account').status_code, 403)

    def test_admin_creates_empty_competition_but_cannot_manage_profiles(self):
        self.login(self.user('ADMIN'))
        data = dict(title='Административный старт', event_date='2027-02-01', event_time='14:00', location='Москва',
                    distance='1600', max_participants='20')
        self.assertEqual(self.post('/competitions/future/add', data, '/competitions/future/add').status_code, 302)
        for path in ['/owners/add', '/jockeys/add', '/horses/add']:
            self.assertEqual(self.post(path, token_path='/auth/account').status_code, 403)
        with self.app.app_context():
            competition = db.session.scalar(select(Competition).where(Competition.title == data['title']))
            competition_id = competition.id
            self.assertEqual(competition.results, [])
        path = f'/competitions/complete/{competition_id}'
        self.assertEqual(self.post(path, {}, path).status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.get(Competition, competition_id).status, 'planned')

    def test_root_has_all_existing_write_permissions(self):
        self.login(self.user('ROOT'))
        for path in ['/owners/add', '/horses/add', '/jockeys/add', '/competitions/future/add', '/competitions/past/add', '/competitions/complete']:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.post('/owners/add', {'full_name': 'ROOT создал'}, '/owners/add').status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(db.session.scalar(select(Owner).where(Owner.full_name == 'ROOT создал')))

    def test_central_policy_ownership_and_default_deny(self):
        owner = self.user('OWNER')
        jockey = self.user('JOCKEY')
        admin = self.user('ADMIN')
        root = self.user('ROOT')
        with self.app.app_context():
            self.assertTrue(can('manage_owner', db.session.get(Owner, owner.owner_id), user=owner))
            self.assertFalse(can('manage_owner', db.session.get(Owner, self.legacy_owner_id), user=owner))
            self.assertTrue(can('manage_jockey', db.session.get(Jockey, jockey.jockey_id), user=jockey))
            self.assertFalse(can('manage_jockey', db.session.get(Jockey, self.legacy_jockey_id), user=jockey))
            self.assertFalse(can('manage_horse', db.session.get(Horse, self.legacy_horse_id), user=owner))
        self.assertFalse(can('manage_system', user=owner))
        self.assertFalse(can('manage_system', user=admin))
        self.assertTrue(can('manage_system', user=root))
        self.assertFalse(can('invented_permission', user=root))
        self.assertFalse(can('account', user=AnonymousUserMixin()))
        root.status = 'disabled'
        self.assertFalse(can('manage_system', user=root))

    def test_csrf_all_mutating_methods_and_session_rotation(self):
        user = self.user()
        old_token = self.token()
        self.assertEqual(self.client.post('/auth/register', data={'email': 'csrf@example.test'}).status_code, 400)
        self.assertEqual(self.client.post('/auth/login', data={'email': user.email, 'password': self.password, 'csrf_token': 'forged'}).status_code, 400)
        for method in ['put', 'patch', 'delete']:
            # There is no mutation handler for these verbs; routing rejects them.
            self.assertEqual(getattr(self.client, method)('/owners/add').status_code, 405)
        self.login(user)
        self.assertEqual(self.client.post('/auth/logout', data={'csrf_token': old_token}).status_code, 400)
        foreign = self.app.test_client()
        self.assertEqual(foreign.post('/auth/login', data={'csrf_token': self.token('/auth/account')}).status_code, 400)
        self.app.config['WTF_CSRF_TIME_LIMIT'] = -1
        self.assertEqual(self.client.post('/auth/logout', data={'csrf_token': self.token('/auth/account')}).status_code, 400)

    def test_repeated_logins_limit_survives_new_client_and_expires(self):
        user = self.user()
        for _ in range(5):
            self.assertEqual(self.login(user, 'wrong').status_code, 400)
        other = self.app.test_client()
        other.environ_base['REMOTE_ADDR'] = '192.0.2.90'
        response = self.login(user, client=other)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '900')
        with patch('app.auth.time.time', return_value=__import__('time').time() + 901):
            self.assertEqual(self.login(user, client=other).status_code, 302)

    def test_login_ip_limit_ignores_spoofed_forwarded_for(self):
        self.app.config['LOGIN_IP_LIMIT'] = 2
        for index in range(2):
            self.assertEqual(self.post('/auth/login', dict(email=f'unknown{index}@example.test', password='wrong')).status_code, 400)
        self.client.environ_base['HTTP_X_FORWARDED_FOR'] = '192.0.2.100'
        self.assertEqual(self.post('/auth/login', dict(email='new-address@example.test', password='wrong')).status_code, 429)

    def test_registration_limited_without_user_creation(self):
        self.app.config['REGISTER_LIMIT'] = 1
        self.assertEqual(self.register(email='invalid').status_code, 400)
        self.assertEqual(self.register().status_code, 429)
        with self.app.app_context():
            self.assertEqual(db.session.query(User).count(), 0)

    def test_secure_cookie_headers_and_external_next_ignored(self):
        user = self.user()
        response = self.post('/auth/login?next=https://evil.example', dict(email=user.email, password=self.password))
        cookie = response.headers['Set-Cookie']
        for flag in ['Secure', 'HttpOnly', 'SameSite=Lax']:
            self.assertIn(flag, cookie)
        self.assertEqual(response.location, '/auth/account')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_strong_session_protection_rejects_changed_user_agent(self):
        self.login(self.user())
        response = self.client.get('/auth/account', headers={'User-Agent': 'changed-client'})
        self.assertEqual(response.status_code, 302)

    def test_database_outage_renders_safe_error_for_authenticated_user(self):
        self.login(self.user())
        failure = OperationalError('SELECT private_data', {}, Exception('database unavailable'), hide_parameters=True)
        with patch('app.auth.db.session.get', side_effect=failure), self.assertLogs(self.app.logger, level='ERROR'):
            response = self.client.get('/auth/account')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Traceback', response.text)
        self.assertNotIn('private_data', response.text)
        self.assertNotIn('database unavailable', response.text)

    def test_tampered_cookie_and_session_expiry(self):
        self.login(self.user())
        cookie = self.client.get_cookie('session')
        self.client.set_cookie('session', cookie.value + 'tampered')
        self.assertEqual(self.client.get('/auth/account').status_code, 302)
        self.login(self.user(email='second@example.test'))
        self.app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=1)
        from itsdangerous.timed import TimestampSigner
        now = TimestampSigner.get_timestamp(TimestampSigner('test'))
        with patch.object(TimestampSigner, 'get_timestamp', return_value=now + 2):
            self.assertEqual(self.client.get('/auth/account').status_code, 302)

    def test_root_cli_hidden_password_and_singleton(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['create-root', '--email', ' Root@example.test '], input=self.password + '\n' + self.password + '\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn(self.password, result.output)
        with self.app.app_context():
            root = db.session.scalar(select(User))
            self.assertEqual((root.email, root.role), ('root@example.test', 'ROOT'))
            self.assertTrue(root.check_password(self.password))
        repeat = runner.invoke(args=['create-root', '--email', 'other@example.test'])
        self.assertNotEqual(repeat.exit_code, 0)
        self.assertIn('ROOT уже существует', repeat.output)
        with self.app.app_context():
            self.assertEqual(db.session.query(User).count(), 1)

    def test_root_cli_rejects_weak_password_and_duplicate_email(self):
        runner = self.app.test_cli_runner()
        weak = runner.invoke(args=['create-root', '--email', 'root@example.test'], input='short\nshort\n')
        self.assertNotEqual(weak.exit_code, 0)
        self.assertNotIn('short', weak.output)
        self.user(email='occupied@example.test')
        duplicate = runner.invoke(args=['create-root', '--email', 'occupied@example.test'], input=self.password + '\n' + self.password + '\n')
        self.assertNotEqual(duplicate.exit_code, 0)
        self.assertNotIn(self.password, duplicate.output)
        with self.app.app_context():
            self.assertEqual(db.session.query(User).count(), 1)

    def test_database_enforces_role_profile_uniqueness_and_root_singleton(self):
        owner = self.user('OWNER')
        self.user('ROOT')
        cases = [dict(role='OWNER', owner_id=owner.owner_id), dict(role='OWNER'),
                 dict(role='VIEWER', owner_id=self.legacy_owner_id), dict(role='ADMIN', status='unknown'),
                 dict(role='SUPERUSER'), dict(role='ROOT'), dict(role='VIEWER', email='UPPER@example.test')]
        for index, changes in enumerate(cases):
            with self.subTest(case=changes), self.app.app_context():
                user = User(email=f'constraint{index}@example.test', role='VIEWER', status='active')
                user.set_password(self.password)
                for field, value in changes.items():
                    setattr(user, field, value)
                db.session.add(user)
                with self.assertRaises(IntegrityError):
                    db.session.commit()
                db.session.rollback()
        with self.app.app_context():
            self.assertEqual(db.session.query(User).count(), 2)

    def test_prune_only_expired_counters(self):
        self.post('/auth/login', dict(email='unknown@example.test', password='wrong'))
        with self.app.app_context():
            db.session.add(AuthThrottle(key='a' * 64, window_started=1, attempts=1))
            db.session.commit()
        result = self.app.test_cli_runner().invoke(args=['prune-auth-throttles'])
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            self.assertEqual(db.session.query(AuthThrottle).count(), 2)
            self.assertIsNone(db.session.get(AuthThrottle, 'a' * 64))
