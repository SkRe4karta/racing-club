"""Beta 1: isolated migrated databases, real hashes, large history and refusal paths."""
from collections import Counter
from contextlib import contextmanager
from datetime import date
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import sqlalchemy as sa
from app import create_app, db
from app.demo import generate, guard_target, row_counts, validate, HistoryImport
from app.models import (Application, ApplicationEvent, AuthThrottle, Competition, Horse,
                        Notification, Prediction, PredictionChoice, Result, User)
from app.prediction_services import account_accuracy, accuracy_summary, prediction_query
from tests.support import isolated_database


@contextmanager
def demo_database():
    with tempfile.TemporaryDirectory(prefix='racing-beta1-test-') as directory:
        with isolated_database(prefix='racing_demo_') as uri:
            if uri.startswith('sqlite:'):
                uri = 'sqlite:///' + str(Path(directory) / 'racing_demo_test.sqlite')
            app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': uri, 'SESSION_COOKIE_SECURE': False})
            with app.app_context():
                result = app.test_cli_runner().invoke(args=['db', 'upgrade'])
                if result.exit_code: raise RuntimeError(result.output)
                try:
                    yield app, Path(directory)
                finally:
                    db.session.remove()
                    db.engine.dispose()


class LargeDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = demo_database()
        cls.app, cls.folder = cls.fixture.__enter__()
        cls.addClassCleanup(cls.fixture.__exit__, None, None, None)
        cls.report = generate('full', 20261016, date.today(), cls.folder / 'accounts.txt')

    def test_large_history_and_roles(self):
        counts = self.report['counts']
        for table, number in dict(users=360, owners=140, jockeys=80, horses=330, competitions=180,
                                  applications=2200, results=1680, predictions=2600, auth_throttles=0).items():
            self.assertEqual(counts[table], number)
        self.assertGreater(counts['notifications'], 1300)
        self.assertGreater(counts['audit_logs'], 700)
        self.assertEqual(Counter(db.session.scalars(sa.select(User.role))),
                         dict(ROOT=1, ADMIN=5, OWNER=140, JOCKEY=80, VIEWER=134))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Result).join(Competition)
                                          .where(Competition.status == 'completed')), 1500)
        self.assertGreaterEqual(len(self.report['months']), 24)
        self.assertEqual(len(self.report['statuses']), 6)
        public_names = list(db.session.scalars(sa.select(Competition.title)))
        public_names += list(db.session.scalars(sa.select(Competition.location)))
        public_names += list(db.session.scalars(sa.select(Horse.nickname)))
        from app.models import Owner, Jockey
        public_names += list(db.session.scalars(sa.select(Owner.full_name)))
        public_names += list(db.session.scalars(sa.select(Jockey.full_name)))
        for name in public_names:
            self.assertNotRegex(name.casefold(), r'\b(?:демо|demo|тест|test)\b|этап \d+')
        self.assertEqual(len(set(db.session.scalars(sa.select(Competition.title)))), 180)

        self.assertGreater(db.session.scalar(sa.select(sa.func.count()).select_from(Result).where(Result.did_not_finish)), 0)
        self.assertGreater(db.session.scalar(sa.select(sa.func.count()).select_from(Result).where(Result.is_disqualified)), 0)
        self.assertEqual((self.folder / 'accounts.txt').stat().st_mode & 0o777, 0o600)
        accounts = [line.split('\t') for line in (self.folder / 'accounts.txt').read_text().splitlines()[1:]]
        self.assertEqual(len({a[2] for a in accounts}), 360)
        for role in ('ROOT', 'ADMIN', 'OWNER', 'JOCKEY', 'VIEWER'):
            _, email, password = next(a for a in accounts if a[0] == role)
            user = db.session.scalar(sa.select(User).where(User.email == email))
            self.assertTrue(user.check_password(password))
        from app.analytics import seasons
        self.assertGreaterEqual(len(seasons()), 2)
        self.assertEqual(sum(row[1] for row in seasons()), 1500)

    def test_bounded_pages_queries_and_accuracy(self):
        client = self.app.test_client()
        # Each HTTP request owns a fresh app context, as it does under Gunicorn.
        # The outer context belongs only to the large database fixture.
        def http(method, path, **kwargs):
            with self.app.app_context():
                return client.open(path, method=method, **kwargs)
        counts, loaded = [], []
        def statement(*args): counts.append(args[2])
        def load(session, instance): loaded.append(type(instance).__name__)
        sa.event.listen(db.engine, 'before_cursor_execute', statement)
        sa.event.listen(db.session.session_factory.class_, 'loaded_as_persistent', load)
        try:
            paths = ['/competitions/', '/competitions/?view=past&page=2', '/competitions/?view=calendar&month=2026-10', '/', '/horses/?q=СЕВЕРНЫЙ', '/owners/?page=2', '/jockeys/', '/rankings',
                     '/competitions/past?page=4', '/competitions/future?view=calendar',
                     '/horses/1?page=2', '/jockeys/1?page=2', '/competitions/1/results.csv']
            for path in paths:
                counts.clear(); loaded.clear(); db.session.remove()
                response = http('GET',path)
                self.assertEqual(response.status_code, 200, path)
                self.assertLess(len(counts), 40, (path, len(counts)))
                self.assertLess(len(loaded), 650, (path, Counter(loaded)))
            self.assertIn('Северный', http('GET','/horses/?q=СЕВЕРНЫЙ').text)
            self.assertIn('Страница 2', http('GET','/horses/1?page=2').text)
            accounts = [line.split('\t') for line in (self.folder / 'accounts.txt').read_text().splitlines()[1:]]
            for role, dashboard in [('ROOT','/root/'), ('ADMIN','/admin/'), ('OWNER','/cabinet/'),
                                    ('JOCKEY','/cabinet/'), ('VIEWER','/predictions/history')]:
                client = self.app.test_client()
                _, email, password = next(a for a in accounts if a[0] == role)
                token = re.search(r'name="csrf_token" value="([^"]+)"', http('GET','/auth/login').text).group(1)
                self.assertEqual(http('POST','/auth/login', data=dict(email=email,password=password,csrf_token=token)).status_code, 302)
                counts.clear(); loaded.clear(); db.session.remove()
                response = http('GET',dashboard)
                self.assertEqual(response.status_code, 200, dashboard)
                self.assertLess(len(counts), 45, (dashboard, len(counts)))
                self.assertLess(len(loaded), 500, (dashboard, Counter(loaded)))
                if role == 'ADMIN': self.assertEqual(http('GET','/root/').status_code, 403)
                if role == 'VIEWER':
                    user = db.session.scalar(sa.select(User).where(User.email == email))
                    self.assertEqual(account_accuracy(user.id), accuracy_summary(db.session.scalars(
                        prediction_query().where(Prediction.user_id == user.id)).all()))
        finally:
            sa.event.remove(db.engine, 'before_cursor_execute', statement)
            sa.event.remove(db.session.session_factory.class_, 'loaded_as_persistent', load)


class SeedSafetyTests(unittest.TestCase):
    def test_target_refuses_ambiguous_and_repository_paths(self):
        from seed import main
        with patch.dict(os.environ, {'DATABASE_URL': 'sqlite:////tmp/production.sqlite', 'RACING_DEMO_DATABASE_URL': ''}):
            self.assertEqual(main(['generate', '--confirm-demo', '--accounts', '/tmp/unused-beta1.txt']), 1)
        for uri in ('', 'sqlite:///:memory:', 'sqlite:///relative.sqlite',
                    'sqlite:////tmp/production.sqlite', 'postgresql+psycopg:///stage',
                    'sqlite:///' + str(Path.cwd() / 'racing_demo_bad.sqlite')):
            with self.subTest(uri=uri), self.assertRaises(ValueError): guard_target(uri)

    def test_nonempty_including_service_table_refused(self):
        for kind in ('user', 'throttle'):
            with self.subTest(kind=kind), demo_database() as (app, folder):
                if kind == 'user':
                    user = User(email='existing@example.test',role='VIEWER');user.set_password('Long-local-test-value')
                    db.session.add(user)
                else:
                    db.session.add(AuthThrottle(key='a'*64, window_started=1, attempts=1))
                db.session.commit()
                before = row_counts();db.session.remove()
                with self.assertRaisesRegex(ValueError, 'пустой'):
                    generate('small', 1, date(2026,10,16), folder / 'accounts.txt')
                self.assertEqual(row_counts(), before)
                self.assertFalse((folder / 'accounts.txt').exists())

    def test_private_file_and_atomic_rollback(self):
        with demo_database() as (app, folder):
            target = folder / 'accounts.txt'
            target.write_text('existing file')
            with self.assertRaises(FileExistsError): generate('small', 1, date(2026,10,16), target)
            self.assertEqual(target.read_text(), 'existing file')
            self.assertEqual(row_counts()['users'], 0);db.session.remove()
            with self.assertRaises(ValueError): generate('small', 1, date(2026,10,16), Path.cwd() / 'accounts.txt')
            with patch.object(HistoryImport, 'predictions', side_effect=RuntimeError('test rollback')):
                with self.assertRaises(RuntimeError): generate('small', 1, date(2026,10,16), folder / 'rollback.txt')
            self.assertFalse((folder / 'rollback.txt').exists())
            self.assertEqual(row_counts()['users'], 0)

    def test_repeatable_sporting_history_random_credentials(self):
        reports, passwords = [], []
        for _ in range(2):
            with demo_database() as (app, folder):
                reports.append(generate('small', 42, date(2026,10,16), folder / 'accounts.txt'))
                passwords.append((folder / 'accounts.txt').read_text())
                db.session.remove()
                with self.assertRaises(ValueError): generate('small', 42, date(2026,10,16), folder / 'again.txt')
        self.assertEqual(reports[0], reports[1])
        self.assertNotEqual(passwords[0], passwords[1])

    def test_validator_detects_broken_provenance_and_prediction(self):
        with demo_database() as (app, folder):
            generate('small', 1, date(2026,10,16), folder / 'accounts.txt')
            app_id = db.session.scalar(sa.select(Application.id).where(Application.status == 'admin_confirmed'))
            event = db.session.scalar(sa.select(ApplicationEvent).where(ApplicationEvent.application_id == app_id,
                                                                       ApplicationEvent.action == 'created'))
            event.actor_id = db.session.scalar(sa.select(User.id).where(User.role == 'ROOT'))
            db.session.flush()
            with self.assertRaisesRegex(ValueError, 'Личное согласие'): validate()
            db.session.rollback()
            prediction = db.session.scalar(sa.select(Prediction).where(Prediction.outcome == 'pending'))
            prediction.winner_correct = True; db.session.flush()
            with self.assertRaisesRegex(ValueError, 'Будущая оценка'): validate()
            db.session.rollback()
            self.assertTrue(validate()['valid'])


class PostgresDemoTests(unittest.TestCase):
    def test_import_constraints_and_preservation(self):
        if not os.environ.get('RACING_TEST_POSTGRES_URL'):
            self.skipTest('Requires an explicit disposable PostgreSQL 18 server')
        with demo_database() as (app, folder):
            report = generate('small', 18, date(2026,10,16), folder / 'accounts.txt')
            self.assertTrue(report['valid'])
            self.assertTrue(db.session.scalar(sa.text('SHOW server_version')).startswith('18.'))
            original = db.session.scalar(sa.select(Result).order_by(Result.id))
            identifiers = (original.competition_id, original.horse_id, original.jockey_id, original.start_number)
            db.session.remove()
            # Real PostgreSQL UNIQUE, FK and CHECK violations, each rolled back.
            bad_rows = [dict(competition_id=identifiers[0],horse_id=identifiers[1],jockey_id=identifiers[2],start_number=identifiers[3]),
                        dict(competition_id=2147483647,horse_id=identifiers[1],jockey_id=identifiers[2]),
                        dict(competition_id=identifiers[0],horse_id=identifiers[1],jockey_id=identifiers[2],start_number=0)]
            for values in bad_rows:
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.add(Result(**values));db.session.flush()
                db.session.rollback()
            self.assertEqual(validate(), report)


class CompetitionNavigationTests(unittest.TestCase):
    """Real HTTP navigation, month-limited SQL and same-day mixed-status races."""
    def setUp(self):
        from datetime import time
        self.fixture = demo_database()
        self.app, self.folder = self.fixture.__enter__()
        self.client = self.app.test_client()
        self.rows = [
            Competition(title='Осенний кубок', event_date=date(2026,10,5), event_time=time(10), location='Ипподром «Север»', status='completed'),
            Competition(title='Приз скорости', event_date=date(2026,10,5), event_time=time(15), location='Ипподром «Волга»', status='planned'),
            Competition(title='Большой приз октября', event_date=date(2026,10,23), event_time=time(12), location='Ипподром «Север»', status='planned'),
            Competition(title='Кубок ноября', event_date=date(2026,11,2), event_time=time(12), location='Ипподром «Волга»', status='planned'),
            Competition(title='Сентябрьский приз', event_date=date(2026,9,10), event_time=time(12), location='Ипподром «Север»', status='completed'),
        ]
        db.session.add_all(self.rows);db.session.commit()
        self.ids = [c.id for c in self.rows]
        self.rows = None
        db.session.remove()

    def tearDown(self):
        self.fixture.__exit__(None, None, None)

    def test_lists_filters_csv_and_legacy_routes(self):
        for path,number,mode in (('/competitions/',3,'future'),('/competitions/future',3,'future'),
                                 ('/competitions/past',2,'past'),('/competitions/?view=past',2,'past')):
            text = self.client.get(path).text
            self.assertIn(f'data-total="{number}"',text)
            self.assertRegex(text,rf'<a href="[^"]*view={mode}[^"]*" aria-current="page">')
            self.assertEqual(text.count('<tbody>'),1)
        text = self.client.get('/competitions/?view=past&q=ОСЕННИЙ&date=2026-10-05&location=СЕВЕР&sort=name').text
        self.assertIn('data-total="1"',text);self.assertIn('Осенний кубок',text)
        response = self.client.get('/competitions/?view=past&export=csv')
        self.assertEqual(response.status_code,200);self.assertIn('text/csv',response.content_type)
        self.assertIn('Осенний кубок',response.text);self.assertNotIn('Кубок ноября',response.text)
        self.assertIn('Завершено',response.text)
        for path in (f'/competitions/past/{self.ids[0]}', f'/competitions/future/{self.ids[2]}',
                     '/competitions/future?view=list','/competitions/?view=unknown'):
            self.assertEqual(self.client.get(path).status_code,200,path)

    def test_calendar_both_statuses_multiple_events_and_bounded_sql(self):
        from flask import template_rendered
        contexts, statements = [], []
        def rendered(sender, template, context, **extra): contexts.append(context)
        def statement(*args): statements.append(args[2])
        template_rendered.connect(rendered,self.app)
        sa.event.listen(db.engine,'before_cursor_execute',statement)
        try:
            response = self.client.get('/competitions/?view=calendar&month=2026-10&day=2026-10-05')
            self.assertEqual(response.status_code,200)
            context = contexts[-1]
            self.assertEqual(len(context['events']),3)
            self.assertEqual(len(context['by_day'][date(2026,10,5)]),2)
            self.assertEqual(context['total'],5)
            self.assertEqual({c.status for c,_ in context['events']},{'planned','completed'})
            self.assertNotIn('Сентябрьский приз',response.text);self.assertNotIn('Кубок ноября',response.text)
            self.assertIn('✓ Завершено',response.text);self.assertIn('● Запланировано',response.text)
            self.assertLess(len(statements),7)
            self.assertTrue(any('event_date >=' in sql and 'event_date <' in sql for sql in statements))
            text = self.client.get('/competitions/future?view=calendar&month=2026-10').text
            self.assertIn('Осенний кубок',text)  # Legacy calendar now includes completed races.
            for identifier,kind in ((self.ids[0],'past'),(self.ids[1],'future')):
                card = self.client.get(f'/competitions/{kind}/{identifier}?view=calendar&month=2026-10&day=2026-10-05')
                self.assertIn('view=calendar',card.text);self.assertIn('month=2026-10',card.text)
                self.assertIn('Календарь соревнований',card.text)
        finally:
            template_rendered.disconnect(rendered,self.app)
            sa.event.remove(db.engine,'before_cursor_execute',statement)

    def test_calendar_year_month_day_fallbacks_and_navigation_links(self):
        from flask import template_rendered
        contexts=[]
        def rendered(sender,template,context,**extra): contexts.append(context)
        template_rendered.connect(rendered,self.app)
        try:
            for value in ('garbage','0001-01','9999-12','2026-13'):
                response=self.client.get('/competitions/?view=calendar&month='+value)
                self.assertEqual(response.status_code,200)
                self.assertEqual(contexts[-1]['month'],date.today().replace(day=1))
            response=self.client.get('/competitions/?view=calendar&month=2026-11&day=2026-10-05')
            self.assertEqual(contexts[-1]['selected_day'],date(2026,11,2))
            self.assertIn('month=2026-12',response.text);self.assertIn('month=2026-10',response.text)
            self.assertIn('value="2026-11"',response.text)
            self.assertEqual(self.client.get('/competitions/?view=calendar&month=2027-01').status_code,200)
            self.assertEqual(contexts[-1]['events'],[])
            for path in ('/','/competitions/','/competitions/?view=past'):
                response=self.client.get(path)
                self.assertIn('href="/competitions/"',response.text)
        finally:
            template_rendered.disconnect(rendered,self.app)
