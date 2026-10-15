"""Every test owns a new database; never read the application DATABASE_URL."""
import os
from contextlib import contextmanager
from uuid import uuid4

import sqlalchemy as sa


@contextmanager
def isolated_database():
    admin_url = os.environ.get('RACING_TEST_POSTGRES_URL')
    if not admin_url:
        yield 'sqlite:///:memory:'
        return
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != 'postgresql':
        raise RuntimeError('RACING_TEST_POSTGRES_URL must point to a disposable PostgreSQL server.')
    database = 'racing_test_' + uuid4().hex
    admin = sa.create_engine(url, isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
        try:
            yield url.set(database=database).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
    finally:
        admin.dispose()
