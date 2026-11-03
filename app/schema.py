"""Verified adoption of an existing v1.1 database, without rewriting its tables."""
from importlib import import_module

import click
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask_migrate import stamp

from app import db


def setup_schema_cli(app):
    @app.cli.command('adopt-legacy')
    def adopt_legacy():
        """Validate the frozen v1.1 schema and stamp only its baseline revision."""
        # Build the historical schema in memory, independent of evolving models.
        baseline = import_module('migrations.versions.0001_v11_baseline')
        memory = sa.create_engine('sqlite:///:memory:')
        try:
            with memory.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    baseline.upgrade()
                expected = sa.MetaData()
                expected.reflect(connection)
            with db.engine.connect() as connection:
                actual = sa.inspect(connection)
                if set(actual.get_table_names()) != set(expected.tables):
                    raise click.ClickException('Ожидались только пять таблиц v1.1 без Alembic. База не изменена.')
                differences = compare_metadata(MigrationContext.configure(connection), expected)
                # Alembic does not compare primary keys and all CHECK constraints.
                # The legacy schema has no CHECK; validate PKs and reject extras.
                for name in expected.tables:
                    if actual.get_pk_constraint(name)['constrained_columns'] != ['id']:
                        differences.append(('primary_key', name))
                    if actual.get_check_constraints(name):
                        differences.append(('unexpected_check', name))
                if differences:
                    raise click.ClickException('Схема отличается от v1.1. Сначала проверьте её вручную; база не изменена.')
            stamp(revision='0001_v11_baseline')
            click.echo('Схема v1.1 проверена. Выполните flask db upgrade для добавления авторизации.')
        finally:
            memory.dispose()
