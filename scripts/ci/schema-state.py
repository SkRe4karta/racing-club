"""Inspect a STAGE database without exposing URLs, credentials or row contents."""
import hashlib
import json
import os
import sys
from importlib import import_module

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import create_app, db


def inspect_state():
    app = create_app()
    with app.app_context(), db.engine.connect() as connection:
        expected = os.environ['EXPECTED_DATABASE_NAME']
        actual = connection.exec_driver_sql('SELECT current_database()').scalar_one()
        if actual != expected or actual == 'racing_club':
            raise ValueError('Unexpected or historical database')
        inspector = sa.inspect(connection)
        names = set(inspector.get_table_names())
        revision = (connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
                    if 'alembic_version' in names else None)
        # Compare frozen columns so additive migrations keep identical fingerprints.
        memory = sa.create_engine('sqlite:///:memory:')
        try:
            with memory.begin() as baseline_connection:
                with Operations.context(MigrationContext.configure(baseline_connection)):
                    import_module('migrations.versions.0001_v11_baseline').upgrade()
                baseline = sa.MetaData()
                baseline.reflect(baseline_connection)
            tables = {}
            for table in baseline.tables.values():
                columns = ', '.join(column.name for column in table.columns)
                rows = connection.exec_driver_sql(f'SELECT {columns} FROM {table.name} ORDER BY id').all()
                encoded = json.dumps([list(row) for row in rows], default=str, ensure_ascii=False).encode()
                tables[table.name] = dict(count=len(rows), sha256=hashlib.sha256(encoded).hexdigest())
        finally:
            memory.dispose()
        invalid = connection.exec_driver_sql(
            "SELECT count(*) FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
            "AND NOT convalidated").scalar_one()
        if invalid:
            raise ValueError('Unvalidated database constraints')
        return dict(database=actual, revision=revision, table_count=len(names), tables=tables)


if __name__ == '__main__':
    try:
        print(json.dumps(inspect_state(), sort_keys=True))
    except Exception as error:
        print(f'Database inspection failed ({type(error).__name__}); inspect privately.', file=sys.stderr)
        raise SystemExit(1)
