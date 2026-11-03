"""Organizer instructions: HTTP authorization, validation and persisted rendering."""
from app import db
from app.models import Competition
import unittest
from tests import test_alpha3 as alpha3


class RegistrationNotesTests(unittest.TestCase):
    setUp = alpha3.Alpha3Tests.setUp
    tearDown = alpha3.Alpha3Tests.tearDown
    token = alpha3.Alpha3Tests.token
    logged = alpha3.Alpha3Tests.logged
    login = alpha3.Alpha3Tests.login
    post = alpha3.Alpha3Tests.post
    new_data = alpha3.Alpha3Tests.new_data

    def test_notes_roundtrip_escaped_and_invalid_update_atomic(self):
        self.login('admin')
        data = self.new_data(registration_notes='  Ветеринарный паспорт <script>alert(1)</script>  ')
        self.assertEqual(self.post('/admin/competitions/new', data).status_code, 302)
        with self.app.app_context():
            comp = db.session.query(Competition).filter_by(title=data['title']).one()
            identifier = comp.id
            self.assertEqual(comp.registration_notes, data['registration_notes'].strip())
        page = self.client.get(f'/competitions/future/{identifier}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('&lt;script&gt;', page.text)
        self.assertNotIn('<script>alert(1)</script>', page.text)
        self.assertEqual(self.post(f'/admin/competitions/{identifier}/edit',
                                  self.new_data(registration_notes='x' * 2001)).status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.get(Competition, identifier).registration_notes,
                             data['registration_notes'].strip())


class NotesMigrationTests(unittest.TestCase):
    def test_upgrade_0005_preserves_competitions(self):
        from flask_migrate import upgrade
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from app import create_app
        from tests.support import isolated_database
        with isolated_database() as uri:
            app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': uri})
            with app.app_context():
                try:
                    upgrade(revision='0005_predictions')
                    db.session.execute(text("INSERT INTO competitions (id,title,event_date,event_time,location,status,revision) VALUES (1,'Сохранённый старт','2026-12-01','12:00','Москва','planned',0)"))
                    db.session.commit()
                    upgrade()
                    comp = db.session.get(Competition, 1)
                    self.assertEqual(comp.title, 'Сохранённый старт')
                    self.assertIsNone(comp.registration_notes)
                    comp.registration_notes = 'x' * 2001
                    with self.assertRaises(IntegrityError):
                        db.session.commit()
                    db.session.rollback()
                    self.assertEqual(db.session.get(Competition, 1).title, 'Сохранённый старт')
                finally:
                    db.session.remove()
                    db.engine.dispose()
