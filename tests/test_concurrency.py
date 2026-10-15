import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import create_app, db
from app.auth import consume_limit
from app.models import AuthThrottle
from tests.support import isolated_database


class SharedThrottleTests(unittest.TestCase):
    def test_atomic_limit_across_independent_applications(self):
        with isolated_database() as uri, tempfile.TemporaryDirectory(prefix='racing-limit-') as temporary:
            if uri == 'sqlite:///:memory:':
                uri = 'sqlite:///' + str(Path(temporary) / 'throttle.sqlite')
            apps = [create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': uri}) for _ in range(2)]
            try:
                with apps[0].app_context():
                    db.create_all()
                def attempt(index):
                    with apps[index % 2].app_context():
                        return consume_limit('concurrency-test', 'same-account', 5)
                with ThreadPoolExecutor(max_workers=8) as pool:
                    allowed = list(pool.map(attempt, range(16)))
                self.assertEqual(sum(allowed), 5)
                with apps[1].app_context():
                    counter = db.session.query(AuthThrottle).one()
                    self.assertEqual(counter.attempts, 16)
            finally:
                for app in apps:
                    with app.app_context():
                        db.session.remove()
                        db.engine.dispose()
