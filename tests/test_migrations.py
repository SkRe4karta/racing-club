import os
import secrets
import tempfile
import unittest
from datetime import date, time
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from app import create_app, db
from app.models import Competition, Horse, Jockey, Owner, Result, User
from tests.support import isolated_database

LEGACY_TABLES = ('owners', 'horses', 'jockeys', 'competitions', 'results')


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.database = isolated_database()
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': self.database.__enter__()})
        self.context = self.app.app_context()
        self.context.push()
        self.runner = self.app.test_cli_runner()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.database.__exit__(None, None, None)

    def cli(self, *args):
        result = self.runner.invoke(args=list(args))
        self.assertEqual(result.exit_code, 0, result.output + str(result.exception or ''))
        return result

    def legacy(self):
        self.cli('db', 'upgrade', '0001_v11_baseline')
        owner = Owner(full_name='Сохранённый владелец', phone='123')
        horse = Horse(nickname='Сохранённая лошадь', gender='Кобыла', age=4, owner=owner)
        jockey = Jockey(full_name='Сохранённый жокей', age=25, rating=7.5)
        # Use frozen SQL columns: the current ORM includes Alpha 2's new deadline.
        db.session.execute(sa.text("INSERT INTO competitions (id, title, event_date, event_time, location, status) VALUES (1, 'Сохранённый протокол', '2025-01-01', '12:00:00', 'Москва', 'completed')"))
        result = Result(competition_id=1, horse=horse, jockey=jockey, finish_time_seconds=123.45, place=1, is_disqualified=False)
        db.session.add(result)
        db.session.commit()
        with db.engine.begin() as connection:
            connection.exec_driver_sql('DROP TABLE alembic_version')

    def snapshot(self):
        with db.engine.connect() as connection:
            return {name: list(connection.exec_driver_sql(f"SELECT {('id, title, event_date, event_time, location, status' if name == 'competitions' else '*')} FROM {name} ORDER BY id")) for name in LEGACY_TABLES}

    def test_factory_does_not_create_schema(self):
        self.assertEqual(sa.inspect(db.engine).get_table_names(), [])

    def test_fresh_install_schema_matches_models_and_auth_works(self):
        self.cli('db', 'upgrade')
        self.assertEqual(set(sa.inspect(db.engine).get_table_names()), set(LEGACY_TABLES) | {'users', 'auth_throttles', 'applications', 'application_events', 'notifications', 'alembic_version'})
        self.cli('db', 'check')
        password = secrets.token_urlsafe(24)
        root = self.runner.invoke(args=['create-root', '--email', 'root@example.test'], input=password + '\n' + password + '\n')
        self.assertEqual(root.exit_code, 0, root.output)
        client = self.app.test_client()
        import re
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get('/auth/login').text).group(1)
        response = client.post('/auth/login', data=dict(email='root@example.test', password=password, csrf_token=token))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get('/owners/add').status_code, 200)
        if db.engine.dialect.name == 'postgresql':
            self.assertTrue(db.session.scalar(sa.text('SHOW server_version')).startswith('18.'))

    def test_adopt_upgrade_preserves_all_legacy_rows_and_constraints(self):
        self.legacy()
        before = self.snapshot()
        self.cli('adopt-legacy')
        self.assertEqual(db.session.scalar(sa.text('SELECT version_num FROM alembic_version')), '0001_v11_baseline')
        db.session.remove()
        self.cli('db', 'upgrade')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(db.session.query(User).count(), 0)
        self.cli('db', 'check')
        client = self.app.test_client()
        for path in ['/', '/owners/1', '/horses/1', '/jockeys/1', '/competitions/past/1', '/competitions/1/results.csv']:
            self.assertEqual(client.get(path).status_code, 200)
        indexes = sa.inspect(db.engine).get_unique_constraints('results')
        self.assertEqual({item['name'] for item in indexes}, {'uq_competition_horse', 'uq_competition_jockey'})

    def test_adopt_refuses_empty_partial_and_changed_schema(self):
        self.assertNotEqual(self.runner.invoke(args=['adopt-legacy']).exit_code, 0)
        self.legacy()
        with db.engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE owners ADD COLUMN unexpected INTEGER')
        before = self.snapshot()
        self.assertNotEqual(self.runner.invoke(args=['adopt-legacy']).exit_code, 0)
        self.assertNotIn('alembic_version', sa.inspect(db.engine).get_table_names())
        self.assertEqual(self.snapshot(), before)

    def test_adopt_refuses_managed_database(self):
        self.cli('db', 'upgrade')
        self.assertNotEqual(self.runner.invoke(args=['adopt-legacy']).exit_code, 0)
        self.assertEqual(db.session.scalar(sa.text('SELECT version_num FROM alembic_version')), '0003_applications')

    def test_upgrade_idempotent_downgrade_refused_without_data_loss(self):
        self.legacy()
        self.cli('adopt-legacy')
        self.cli('db', 'upgrade')
        self.cli('db', 'upgrade')
        before = self.snapshot()
        downgrade = self.runner.invoke(args=['db', 'downgrade', '0001_v11_baseline'])
        self.assertNotEqual(downgrade.exit_code, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertIn('users', sa.inspect(db.engine).get_table_names())

    def test_postgresql_offline_sql_has_additive_auth_schema(self):
        # Generates the real PostgreSQL dialect's SQL without contacting a server.
        with tempfile.TemporaryDirectory(prefix='racing-sql-') as temporary:
            target = Path(temporary) / 'upgrade.sql'
            app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'postgresql+psycopg://unused@localhost/unused'})
            with app.app_context():
                result = app.test_cli_runner().invoke(args=['db', 'upgrade', '--sql'])
                self.assertEqual(result.exit_code, 0, result.output)
                target.write_text(result.output)
                self.assertIn('CREATE TABLE users', target.read_text())
                self.assertIn("WHERE role = 'ROOT'", target.read_text())
                self.assertNotIn('DROP TABLE', target.read_text())
                db.engine.dispose()

    def test_missing_secret_fails_closed_without_touching_database(self):
        with patch.dict(os.environ, {'SECRET_KEY': ''}):
            with self.assertRaisesRegex(RuntimeError, 'SECRET_KEY'):
                create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})

    def test_alpha1_upgrade_preserves_accounts_throttles_profiles_and_results(self):
        self.legacy()
        self.cli('adopt-legacy')
        self.cli('db', 'upgrade', '0002_auth_foundation')
        user = User(email='preserved@example.test', role='OWNER', status='active', owner_id=1)
        user.set_password(secrets.token_urlsafe(24))
        db.session.add(user)
        from app.models import AuthThrottle
        db.session.add(AuthThrottle(key='f'*64, window_started=123, attempts=3))
        db.session.commit()
        before = self.snapshot()
        with db.engine.connect() as connection:
            accounts = list(connection.exec_driver_sql('SELECT * FROM users ORDER BY id'))
            throttles = list(connection.exec_driver_sql('SELECT * FROM auth_throttles ORDER BY key'))
        self.cli('db', 'upgrade')
        self.assertEqual(self.snapshot(), before)
        with db.engine.connect() as connection:
            self.assertEqual(list(connection.exec_driver_sql('SELECT * FROM users ORDER BY id')), accounts)
            self.assertEqual(list(connection.exec_driver_sql('SELECT * FROM auth_throttles ORDER BY key')), throttles)
            self.assertIsNone(connection.exec_driver_sql('SELECT registration_deadline FROM competitions').scalar_one())
            for table in ['applications', 'application_events', 'notifications']:
                self.assertEqual(connection.exec_driver_sql(f'SELECT COUNT(*) FROM {table}').scalar_one(), 0)
        self.cli('db', 'check')
        indexes = {index['name']: index for index in sa.inspect(db.engine).get_indexes('applications')}
        self.assertTrue(indexes['uq_applications_active_horse']['unique'])
        self.assertTrue(indexes['uq_applications_active_jockey']['unique'])
        self.assertEqual(db.session.get(User, user.id).owner_id, 1)
