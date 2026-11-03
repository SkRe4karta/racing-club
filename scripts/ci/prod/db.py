"""Read-only snapshot/hash helper, run inside the approved application image."""
import json
import os
import sys

import sqlalchemy as sa
from schema_snapshot import snapshot


def main():
    engine = sa.create_engine(os.environ['DATABASE_URL'])
    try:
        with engine.connect() as connection, connection.begin():
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            name = connection.exec_driver_sql('SELECT current_database()').scalar_one()
            if name != os.environ['EXPECTED_DATABASE_NAME']:
                raise ValueError('WRONG_DATABASE')
            structure, fingerprint = snapshot(connection)
            revision = 'legacy'
            if 'alembic_version' in structure['tables']:
                versions = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalars().all()
                if len(versions) != 1:
                    raise ValueError('UNKNOWN_MIGRATION_HISTORY')
                revision = versions[0]
            print(json.dumps({'database': name, 'revision': revision, 'structure': structure,
                              'fingerprint': fingerprint, 'postgres': connection.exec_driver_sql('SHOW server_version').scalar_one()}, default=list))
    finally:
        engine.dispose()


if __name__ == '__main__':
    if sys.argv[1:] == ['snapshot']:
        main()
    else:
        raise SystemExit('Usage: db.py snapshot')
