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


def legacy_competition(title, event_date_val, event_time_val, location, participants, *, completed=False):
    """Frozen pre-v2 sporting fixture; never a production write path.

    The retired direct-create API is tested separately as forbidden. These rows
    exercise continued reading and completion of real v1.1 protocols.
    """
    from app import db
    from app.models import Competition, Result
    from app.admin_services import prepare_protocol
    comp = Competition(title=title, event_date=event_date_val, event_time=event_time_val,
                       location=location, status='completed' if completed else 'planned')
    db.session.add(comp)
    db.session.flush()
    rows = []
    data = {}
    for item in participants:
        row = Result(competition_id=comp.id, horse_id=item['horse_id'], jockey_id=item['jockey_id'])
        db.session.add(row)
        db.session.flush()
        rows.append(row)
        data[row.id] = {k: v for k, v in item.items() if k not in ('horse_id', 'jockey_id')}
    if completed:
        for row, values in prepare_protocol(rows, data):
            for key, value in values.items():
                setattr(row, key, value)
    db.session.commit()
    return comp


def legacy_completed(*args, **kwargs):
    return legacy_competition(*args, **kwargs, completed=True)
