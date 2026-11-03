"""Read-only hashes of every pre-migration column; no row contents in reports."""
import hashlib
import json
import os

import sqlalchemy as sa


def main():
    engine = sa.create_engine(os.environ['DATABASE_URL'])
    try:
        with engine.connect() as connection, connection.begin():
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            if connection.exec_driver_sql('SELECT current_database()').scalar_one() != os.environ['EXPECTED_DATABASE_NAME']:
                raise ValueError('Unexpected database')
            inspector = sa.inspect(connection)
            columns = json.loads(os.environ.get('PRESERVATION_COLUMNS', 'null'))
            if columns is None:
                columns = {name: [c['name'] for c in inspector.get_columns(name, schema='public')]
                           for name in sorted(inspector.get_table_names(schema='public')) if name != 'alembic_version'}
            quote = connection.dialect.identifier_preparer.quote
            hashes = {}
            for name, names in columns.items():
                selected = ', '.join(quote(n) for n in names)
                query = (f'SELECT row_to_json(t)::text FROM (SELECT {selected} FROM public.{quote(name)}) t '
                         'ORDER BY row_to_json(t)::text')
                digest = hashlib.sha256()
                count = 0
                for (row,) in connection.execution_options(stream_results=True).exec_driver_sql(query):
                    encoded = row.encode()
                    digest.update(len(encoded).to_bytes(8, 'big'))
                    digest.update(encoded)
                    count += 1
                hashes[name] = {'count': count, 'sha256': digest.hexdigest()}
            print(json.dumps({'columns': columns, 'tables': hashes}, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
