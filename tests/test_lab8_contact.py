"""Independent second business change for automatic migration acceptance."""
import unittest

from app import db
from app.models import Competition
from tests import test_alpha3 as alpha3


class OrganizerContactTests(unittest.TestCase):
    setUp = alpha3.Alpha3Tests.setUp
    tearDown = alpha3.Alpha3Tests.tearDown
    token = alpha3.Alpha3Tests.token
    logged = alpha3.Alpha3Tests.logged
    login = alpha3.Alpha3Tests.login
    post = alpha3.Alpha3Tests.post
    new_data = alpha3.Alpha3Tests.new_data

    def test_normalized_contact_public_invalid_edit_atomic_and_optional(self):
        self.login('admin')
        data = self.new_data(organizer_email='  Organizer@EXAMPLE.ORG  ')
        self.assertEqual(self.post('/admin/competitions/new', data).status_code, 302)
        with self.app.app_context():
            comp = db.session.query(Competition).filter_by(title=data['title']).one()
            identifier = comp.id
            self.assertEqual(comp.organizer_email, 'organizer@example.org')
        self.assertIn('organizer@example.org', self.client.get(f'/competitions/future/{identifier}').text)
        for value in ('bad email', 'evil@example.org\nBcc: user@example.org', 'a' * 255 + '@example.org'):
            self.assertEqual(self.post(f'/admin/competitions/{identifier}/edit',
                self.new_data(organizer_email=value)).status_code, 400)
            with self.app.app_context():
                self.assertEqual(db.session.get(Competition, identifier).organizer_email, 'organizer@example.org')
        self.assertEqual(self.post(f'/admin/competitions/{identifier}/edit',
            self.new_data(organizer_email='')).status_code, 302)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Competition, identifier).organizer_email)


class ContactMigrationTests(unittest.TestCase):
    def test_0006_records_preserved_and_database_rejects_unnormalized_email(self):
        from flask_migrate import upgrade
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from app import create_app
        from tests.support import isolated_database
        with isolated_database() as uri:
            app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': uri})
            with app.app_context():
                try:
                    upgrade(revision='0006_registration_notes')
                    db.session.execute(text("INSERT INTO competitions (id,title,event_date,event_time,location,status,revision,registration_notes) VALUES (1,'Existing start','2026-12-01','12:00','Test','planned',0,'Keep these requirements')"))
                    db.session.commit()
                    upgrade()
                    comp = db.session.get(Competition, 1)
                    self.assertEqual(comp.registration_notes, 'Keep these requirements')
                    self.assertIsNone(comp.organizer_email)
                    comp.organizer_email = 'Mixed@EXAMPLE.ORG'
                    with self.assertRaises(IntegrityError):
                        db.session.commit()
                    db.session.rollback()
                    self.assertEqual(db.session.get(Competition, 1).registration_notes, 'Keep these requirements')
                finally:
                    db.session.remove()
                    db.engine.dispose()
