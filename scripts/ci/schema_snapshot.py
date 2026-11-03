"""Read-only structural fingerprint; no credentials or row contents in output."""
import argparse
import hashlib
import json
import os

import sqlalchemy as sa


def snapshot(connection):
    schemas = connection.exec_driver_sql(
        "SELECT nspname FROM pg_namespace WHERE left(nspname, 3) <> 'pg_' "
        "AND nspname NOT IN ('information_schema', 'public')").scalars().all()
    if schemas:
        raise ValueError('Unreviewed custom schemas: ' + ', '.join(schemas))
    inspector = sa.inspect(connection)
    tables = {}
    for name in sorted(inspector.get_table_names(schema='public')):
        tables[name] = {
            'columns': [{'name': c['name'], 'type': str(c['type']), 'nullable': c['nullable'],
                         'default': c.get('default'), 'identity': c.get('identity')}
                        for c in inspector.get_columns(name, schema='public')],
            'primary_key': inspector.get_pk_constraint(name, schema='public'),
            'foreign_keys': sorted(inspector.get_foreign_keys(name, schema='public'), key=lambda c: c['name'] or ''),
            'unique': sorted(inspector.get_unique_constraints(name, schema='public'), key=lambda c: c['name'] or ''),
            'checks': sorted(inspector.get_check_constraints(name, schema='public'), key=lambda c: c['name'] or ''),
            'indexes': sorted(inspector.get_indexes(name, schema='public'), key=lambda c: c['name'] or ''),
        }
    # Include views, sequences and extension inventory, not only Alembic revision.
    structure = {'tables': tables,
                 'views': {n: inspector.get_view_definition(n, schema='public')
                           for n in sorted(inspector.get_view_names(schema='public'))},
                 'sequences': sorted(inspector.get_sequence_names(schema='public')),
                 'extensions': connection.exec_driver_sql('SELECT extname, extversion FROM pg_extension ORDER BY extname').all()}
    structure['functions'] = connection.exec_driver_sql(
        "SELECT p.oid::regprocedure::text, pg_get_functiondef(p.oid) "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' ORDER BY 1").all()
    structure['triggers'] = connection.exec_driver_sql(
        "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid), t.tgenabled "
        "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2").all()
    encoded = json.dumps(structure, sort_keys=True, default=list).encode()
    return structure, hashlib.sha256(encoded).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-db', required=True)
    args = parser.parse_args()
    engine = sa.create_engine(os.environ['DATABASE_URL'])
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                database = connection.exec_driver_sql('SELECT current_database()').scalar_one()
                if database != args.expected_db:
                    raise ValueError('Target database does not match expected environment')
                structure, fingerprint = snapshot(connection)
                counts = {}
                quote = connection.dialect.identifier_preparer.quote
                for name in structure['tables']:
                    counts[name] = connection.exec_driver_sql(f'SELECT count(*) FROM public.{quote(name)}').scalar_one()
                revision = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
                print(json.dumps(dict(database=database, postgres=connection.exec_driver_sql('SHOW server_version').scalar_one(),
                                      revision=revision, structure=structure, fingerprint=fingerprint, counts=counts),
                                 sort_keys=True, default=list, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
